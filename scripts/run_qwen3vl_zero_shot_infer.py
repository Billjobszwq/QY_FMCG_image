"""Qwen3-VL 零样本真实推理（G-ZERO 证据生成，隔离环境 .venv_mlx_vlm）。

职责边界：本脚本产出评估记录 JSONL（evaluate.record schema），
确定性汇总仍由 scripts/run_qwen3vl_zero_shot.py 完成。

闭集重排协议（与级联中 Qwen 的"闭集重排/相似 SKU 裁决"职责一致）：
- 每个真值 crop 给模型 K 个候选 SKU 名（gt + 注册表确定序的 K-1 个干扰项，
  按 hash 确定性打乱位置，避免位置偏置）；
- 模型只能回答候选编号/名称或 "none"（abstain）；
- 不加载任何微调权重，纯 zero-shot。

红线：
- 必须传入 ok=true 的 preflight 报告，否则拒绝执行（fail-closed）；
- 确定性采样（按文件名排序后取前 N），禁止随机；
- 只读数据集，不修改 .datasets/。

用法（必须用隔离环境）：
  .venv_mlx_vlm/bin/python -m scripts.run_qwen3vl_zero_shot_infer \
      --preflight-report .eval/vlm_preflight/<run_id>/preflight.json \
      --dataset-root .datasets/sam_refined_full_v1 \
      --output .eval/qwen3vl_zero_shot/<run_id>/records.jsonl \
      --limit 48 --candidates 8
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

INFER_VERSION = "qwen3vl-zero-shot-infer.v1"
MODEL_ID = "mlx-community/Qwen3-VL-4B-Instruct-4bit"

_PROMPT_TMPL = (
    "你是一名货架商品识别助手。图像中是一件饮料商品的局部裁剪。\n"
    "候选商品列表：\n{candidates}\n"
    "请判断图像中的商品与哪个候选最匹配。只输出候选编号（如 3）；"
    "如果图像中商品不属于任何候选或无法判断，只输出 none。"
)


def _load_dataset(dataset_root: Path) -> tuple[list[str], dict[int, str]]:
    import yaml
    data = yaml.safe_load((dataset_root / "data.yaml").read_text("utf-8"))
    names = list(data["names"])
    return names, {i: n for i, n in enumerate(names)}


def _collect_crops(dataset_root: Path, class_names: dict[int, str],
                   limit: int) -> list[dict]:
    """确定性采样：val 图片按文件名排序，逐框裁剪，取前 limit 个。"""
    from PIL import Image
    img_dir = dataset_root / "images" / "val"
    lbl_dir = dataset_root / "labels" / "val"
    crops: list[dict] = []
    for img_path in sorted(img_dir.iterdir()):
        if img_path.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            continue
        lbl_path = lbl_dir / (img_path.stem + ".txt")
        if not lbl_path.is_file():
            continue
        with Image.open(img_path) as im:
            im = im.convert("RGB")
            w, h = im.size
            for line in lbl_path.read_text("utf-8").splitlines():
                parts = line.split()
                if len(parts) < 5:
                    continue
                cls = int(parts[0])
                cx, cy, bw, bh = map(float, parts[1:5])
                x1 = max(0, int((cx - bw / 2) * w))
                y1 = max(0, int((cy - bh / 2) * h))
                x2 = min(w, int((cx + bw / 2) * w))
                y2 = min(h, int((cy + bh / 2) * h))
                if x2 - x1 < 16 or y2 - y1 < 16:
                    continue
                crops.append({
                    "image": im.crop((x1, y1, x2, y2)).copy(),
                    "gt": class_names.get(cls, f"class_{cls}"),
                    "gt_class": cls,
                    "source": f"{img_path.name}#{len(crops)}",
                })
                if len(crops) >= limit:
                    return crops
    return crops


def _candidate_set(gt_class: int, names: list[str], k: int) -> list[str]:
    """gt + 注册表确定序干扰项，按 hash 确定性打乱。"""
    n = len(names)
    distractors = [names[(gt_class + i) % n] for i in range(1, n)
                   if names[(gt_class + i) % n] != names[gt_class]]
    cand = [names[gt_class]] + distractors[: k - 1]
    seed = hashlib.sha256(f"{INFER_VERSION}:{gt_class}".encode()).digest()
    order = sorted(range(len(cand)), key=lambda i: (seed[i % len(seed)], i))
    return [cand[i] for i in order]


def _parse_reply(text: str, candidates: list[str]) -> tuple[str, str | None]:
    """返回 (decision, pred)。解析失败一律 abstain（fail-closed）。"""
    t = (text or "").strip()
    low = t.lower()
    if "none" in low or not t:
        return "abstain", None
    for i, name in enumerate(candidates, start=1):
        if t == str(i) or f"编号{i}" in t or f"{i}." == t[:2]:
            return "accepted", name
    for name in candidates:
        if name in t:
            return "accepted", name
    return "abstain", None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preflight-report", required=True)
    ap.add_argument("--dataset-root", default=".datasets/sam_refined_full_v1")
    ap.add_argument("--output", required=True, help="records.jsonl 输出路径")
    ap.add_argument("--limit", type=int, default=48, help="最多推理 crop 数")
    ap.add_argument("--candidates", type=int, default=8, help="闭集候选数 K")
    ap.add_argument("--max-tokens", type=int, default=32)
    a = ap.parse_args()

    pf_path = Path(a.preflight_report)
    if not pf_path.is_file():
        print(f"preflight 报告不存在，fail-closed: {pf_path}", file=sys.stderr)
        return 2
    pf = json.loads(pf_path.read_text("utf-8"))
    if not pf.get("ok"):
        print("preflight 未通过，拒绝真实 zero-shot 推理", file=sys.stderr)
        return 3

    dataset_root = Path(a.dataset_root)
    names, class_names = _load_dataset(dataset_root)
    crops = _collect_crops(dataset_root, class_names, a.limit)
    if not crops:
        print("无可用 crop，fail-closed", file=sys.stderr)
        return 2

    out_path = Path(a.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        print(f"输出已存在，拒绝覆盖（不可变证据）: {out_path}", file=sys.stderr)
        return 4

    from PIL import Image  # noqa: F401（隔离环境依赖检查）
    from mlx_vlm import load, generate
    from mlx_vlm.utils import load_config
    from mlx_vlm.prompt_utils import apply_chat_template

    print(f"加载模型 {MODEL_ID} ...", flush=True)
    model, processor = load(MODEL_ID)
    config = load_config(MODEL_ID)

    records = []
    t0 = time.time()
    for idx, crop in enumerate(crops):
        candidates = _candidate_set(crop["gt_class"], names, a.candidates)
        cand_text = "\n".join(f"{i}. {n}" for i, n in
                              enumerate(candidates, start=1))
        prompt = apply_chat_template(processor, config,
                                     _PROMPT_TMPL.format(candidates=cand_text),
                                     num_images=1)
        err = None
        decision, pred = "abstain", None
        latency_ms = 0.0
        try:
            t_start = time.time()
            out = generate(model, processor, prompt, image=crop["image"],
                           max_tokens=a.max_tokens, verbose=False)
            latency_ms = (time.time() - t_start) * 1000.0
            # mlx-vlm 0.6.10：generate 返回 GenerationResult 对象（.text）
            text = out if isinstance(out, str) else getattr(out, "text", "")
            decision, pred = _parse_reply(text, candidates)
        except Exception as e:  # fail-closed：错误进 error_ledger
            err = f"{type(e).__name__}: {e}"
            decision, pred = "error", None
        rec = {
            "gt": crop["gt"], "decision": decision, "pred": pred,
            "topk": candidates, "target_type": "closed_set",
            "schema_ok": True,
            "candidate_escape": pred is not None and pred not in candidates,
            "attribute_correct": None,
            "latency_ms": round(latency_ms, 1),
            "prompt_tokens": 0, "completion_tokens": 0, "error": err,
            "source": crop["source"],
        }
        records.append(rec)
        print(f"[{idx + 1}/{len(crops)}] gt={crop['gt'][:24]} "
              f"decision={decision} pred={str(pred)[:24]} "
              f"{latency_ms:.0f}ms" + (f" err={err}" if err else ""),
              flush=True)

    wall = time.time() - t0
    meta = {
        "infer_version": INFER_VERSION, "model_id": MODEL_ID,
        "preflight_report": str(pf_path), "dataset_root": str(dataset_root),
        "limit": a.limit, "candidates": a.candidates,
        "wall_seconds": round(wall, 1), "count": len(records),
    }
    with out_path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    meta_path = out_path.with_suffix(".meta.json")
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1),
                         encoding="utf-8")
    print(f"完成：{len(records)} 条记录，wall={wall:.1f}s -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
