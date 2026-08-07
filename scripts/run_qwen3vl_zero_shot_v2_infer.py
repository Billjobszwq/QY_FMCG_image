"""Qwen3-VL 零样本 V2 真实推理（方法修正版，隔离环境 .venv_mlx_vlm）。

对 V1 的修正（用户指令第十节，禁止 GT 泄漏）：
1. 采样：按门店/session/照片/SKU 分层轮转（src.eval.zeroshot_v2），
   不再"按文件名排序取前 N"（V1 的 48 crop 只来自 2 张照片）；
2. 候选：来自真实检索链路——crop → OCR 文本 → Qwen3-Embedding →
   KB 余弦检索 top-k；候选列表不含任何 GT/类别/真名注入；
3. top-k：记录真实 predicted ranking（检索排序），评估只取前 k；
   检索只返回 m<k 个候选时如实记录，不伪造 Top-5；
4. 逐实例错误账本（errors.jsonl）与采样分层报告一并落盘。

红线：
- 必须传入 ok=true 的 preflight 报告，否则拒绝执行（fail-closed）；
- 输出目录/文件已存在拒绝覆盖（不可变证据）；
- 只读数据集；本记录的 gt 仅用于事后对账，绝不进入候选构造；
- sam_refined 标签不是正式人工金标准：报告 evidence_level 明示。

用法（必须用隔离环境）：
  .venv_mlx_vlm/bin/python -m scripts.run_qwen3vl_zero_shot_v2_infer \
      --preflight-report .eval/vlm_preflight/<run_id>/preflight.json \
      --dataset-root .datasets/sam_refined_full_v1 \
      --output-root .eval/qwen3vl_zero_shot_v2/<run_id> \
      --limit 24 --candidates 8
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def _load_env_file(path: Path) -> None:
    """手动解析 .env（隔离环境不依赖 python-dotenv）。"""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _sep, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


_load_env_file(ROOT / ".env")

INFER_VERSION = "qwen3vl-zero-shot-infer.v2"
MODEL_ID = "mlx-community/Qwen3-VL-4B-Instruct-4bit"

_PROMPT_TMPL = (
    "你是一名货架商品识别助手。图像中是一件饮料商品的局部裁剪。\n"
    "候选商品列表：\n{candidates}\n"
    "请判断图像中的商品与哪个候选最匹配。只输出候选编号（如 3）；"
    "如果图像中商品不属于任何候选或无法判断，只输出 none。"
)
_OCR_PROMPT = "逐行输出图中所有可见文字，不要解释。"


def _omlx_headers() -> dict:
    key = os.environ.get("OMLX_API_KEY", "")
    if not key:
        raise RuntimeError("OMLX_API_KEY 未设置")
    return {"Authorization": f"Bearer {key}",
            "Content-Type": "application/json"}


def _omlx_post(path: str, payload: dict, timeout: int = 300) -> dict:
    base = os.environ.get("OMLX_BASE_URL", "http://127.0.0.1:8455/v1")
    req = urllib.request.Request(
        f"{base.rstrip('/')}/{path.lstrip('/')}",
        data=json.dumps(payload).encode("utf-8"),
        headers=_omlx_headers(), method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _embed_fn(texts: list[str]) -> list[list[float]]:
    model = os.environ.get("OMLX_EMBED_MODEL", "Qwen3-Embedding-0.6B-8bit")
    r = _omlx_post("embeddings", {"model": model, "input": texts})
    return [d["embedding"] for d in
            sorted(r["data"], key=lambda d: d["index"])]


def _data_uri(b: bytes) -> str:
    mime = "image/jpeg" if b[:3] == b"\xff\xd8\xff" else "image/png"
    return f"data:{mime};base64,{base64.b64encode(b).decode()}"


def _ocr_text(image_bytes: bytes) -> str:
    model = os.environ.get("OMLX_OCR_TEXT_MODEL", "DeepSeek-OCR-2-4bit")
    r = _omlx_post("chat/completions", {
        "model": model,
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": _data_uri(image_bytes)}},
            {"type": "text", "text": _OCR_PROMPT}]}],
        "max_tokens": 512, "temperature": 0})
    return (r["choices"][0]["message"]["content"] or "").strip()


def _parse_reply(text: str, candidates: list[str]) -> tuple[str, str | None]:
    t = (text or "").strip()
    if "none" in t.lower() or not t:
        return "abstain", None
    for i, name in enumerate(candidates, start=1):
        if t == str(i) or f"编号{i}" in t or f"{i}." == t[:2]:
            return "accepted", name
    for name in candidates:
        if name in t:
            return "accepted", name
    return "abstain", None


def _load_photo_meta(json_path: Path) -> dict:
    """读取主环境预生成的 photo_meta JSON（隔离环境无需 openpyxl）。

    生成：python3 -m scripts.export_photo_meta --xlsx 实景照片.xlsx --out ...
    """
    return json.loads(json_path.read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preflight-report", required=True)
    ap.add_argument("--dataset-root", default=".datasets/sam_refined_full_v1")
    ap.add_argument("--output-root", required=True)
    ap.add_argument("--kb-root", default=".kb")
    ap.add_argument("--photo-meta-json", required=True,
                    help="主环境预生成的门店/session 元数据 JSON")
    ap.add_argument("--limit", type=int, default=24)
    ap.add_argument("--candidates", type=int, default=8)
    ap.add_argument("--max-tokens", type=int, default=32)
    a = ap.parse_args()

    pf_path = Path(a.preflight_report)
    if not pf_path.is_file():
        print(f"preflight 报告不存在，fail-closed: {pf_path}", file=sys.stderr)
        return 2
    if not json.loads(pf_path.read_text("utf-8")).get("ok"):
        print("preflight 未通过，拒绝真实 zero-shot V2 推理", file=sys.stderr)
        return 3

    out_root = Path(a.output_root)
    if out_root.exists():
        print(f"输出目录已存在，拒绝覆盖（不可变证据）: {out_root}",
              file=sys.stderr)
        return 4

    # ---- 1. 分层采样（确定性） ----
    from src.eval.zeroshot_v2 import (enumerate_regions, retrieve_candidates,
                                      stratified_sample)
    from src.catalog.store import LocalStore
    regions, _names = enumerate_regions(a.dataset_root)
    photo_meta = _load_photo_meta(Path(a.photo_meta_json))
    picked, sample_report = stratified_sample(regions, photo_meta,
                                              limit=a.limit)
    if not picked:
        print("分层采样无可用区域（可能照片元数据缺失），fail-closed",
              file=sys.stderr)
        return 2

    # ---- 2. KB（真实检索目标；候选不含 GT） ----
    kb = LocalStore(Path(a.kb_root))
    kb_ids, kb_vec = kb.load_vectors()
    kb_id_set = set(kb_ids)

    # ---- 2b. canonical sku identity 映射链（任务书§十五）----
    # identity 判定禁止展示名字符串比较：dataset_class → canonical_sku_id
    # → package_version_id → KB vector_id（数据源：data/sku_registry.json、
    # data/sku_aliases.json、KB vector_ids）。
    from src.training.vlm.evaluate import build_default_identity_index
    identity_index = build_default_identity_index(ROOT, kb_root=a.kb_root)

    # ---- 3. Qwen 闭集重排（隔离环境 mlx-vlm） ----
    from PIL import Image
    from mlx_vlm import load, generate
    from mlx_vlm.utils import load_config
    from mlx_vlm.prompt_utils import apply_chat_template

    print(f"加载模型 {MODEL_ID} ...", flush=True)
    model, processor = load(MODEL_ID)
    config = load_config(MODEL_ID)

    out_root.mkdir(parents=True, exist_ok=True)
    img_dir = Path(a.dataset_root) / "images" / "val"
    records, errors = [], []
    t0 = time.time()
    for idx, reg in enumerate(picked):
        meta = photo_meta[reg["photo_id"]]
        source = f"{reg['photo_id']}#r{reg['region_index']}"
        err = None
        decision, pred, ranking, query = "error", None, [], ""
        latency_ms = 0.0
        try:
            img_path = img_dir / f"{reg['photo_id']}.jpg"
            if not img_path.is_file():
                raise FileNotFoundError(f"图片不存在: {img_path}")
            with Image.open(img_path) as im:
                im = im.convert("RGB")
                w, h = im.size
                cx, cy, bw, bh = reg["box_norm"]
                x1 = max(0, int((cx - bw / 2) * w))
                y1 = max(0, int((cy - bh / 2) * h))
                x2 = min(w, int((cx + bw / 2) * w))
                y2 = min(h, int((cy + bh / 2) * h))
                if x2 - x1 < 16 or y2 - y1 < 16:
                    raise ValueError("区域过小")
                crop = im.crop((x1, y1, x2, y2)).copy()
            import io
            buf = io.BytesIO()
            crop.save(buf, format="JPEG", quality=90)
            crop_bytes = buf.getvalue()

            # 真实检索链路：OCR 文本 -> embedding -> KB 检索
            query = _ocr_text(crop_bytes)
            hits = retrieve_candidates(query or "饮料",
                                       embed_fn=_embed_fn, kb_ids=kb_ids,
                                       kb_vectors=kb_vec,
                                       topk=a.candidates)
            ranking = [sku for sku, _sim in hits]
            candidates = ranking  # 真实 predicted ranking，无 GT 注入

            if candidates:
                cand_text = "\n".join(f"{i}. {n}" for i, n in
                                      enumerate(candidates, start=1))
                prompt = apply_chat_template(
                    processor, config,
                    _PROMPT_TMPL.format(candidates=cand_text), num_images=1)
                t_start = time.time()
                out = generate(model, processor, prompt, image=crop,
                               max_tokens=a.max_tokens, verbose=False)
                latency_ms = (time.time() - t_start) * 1000.0
                text = out if isinstance(out, str) else getattr(out, "text", "")
                decision, pred = _parse_reply(text, candidates)
            else:
                decision, pred = "abstain", None
        except Exception as e:  # fail-closed：错误进账本
            err = f"{type(e).__name__}: {e}"
            decision, pred = "error", None
        gt_ident = identity_index.resolve_sku_identity(reg["gt"])
        rec = {
            "gt": reg["gt"], "decision": decision, "pred": pred,
            "retrieval_ranking": ranking,
            "n_candidates": len(ranking),
            "gt_in_registry": gt_ident.kb_vector_id is not None,
            "gt_sku_id": gt_ident.sku_id,
            "gt_package_version_id": gt_ident.package_version_id,
            "target_type": "closed_set", "schema_ok": True,
            "candidate_escape": pred is not None and pred not in ranking,
            "attribute_correct": None,
            "latency_ms": round(latency_ms, 1),
            "prompt_tokens": 0, "completion_tokens": 0,
            "error": err, "source": source,
            "photo_id": reg["photo_id"],
            "store": meta["store"], "session": meta["session"],
            "query_text": query[:200],
        }
        records.append(rec)
        if err:
            errors.append({"source": source, "error": err})
        print(f"[{idx + 1}/{len(picked)}] gt={reg['gt'][:20]} "
              f"cand={len(ranking)} decision={decision} "
              f"pred={str(pred)[:20]} {latency_ms:.0f}ms"
              + (f" err={err}" if err else ""), flush=True)

    wall = time.time() - t0
    meta_out = {
        "infer_version": INFER_VERSION, "model_id": MODEL_ID,
        "preflight_report": str(pf_path), "kb_root": a.kb_root,
        "dataset_root": a.dataset_root, "limit": a.limit,
        "candidates": a.candidates, "wall_seconds": round(wall, 1),
        "count": len(records), "sampling_report": sample_report,
        "kb_sku_count": len(kb_ids),
        "evidence_level": "sam_refined_interim",
        "note": "候选来自真实 OCR+KB 文本检索，不含 GT 注入；"
                "sam_refined 标签不是正式人工金标准，正式报告须待 "
                "human_final/gold_verified 达成后重跑。",
    }
    with (out_root / "records.jsonl").open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    (out_root / "errors.jsonl").write_text(
        "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in errors),
        encoding="utf-8")
    (out_root / "meta.json").write_text(
        json.dumps(meta_out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"完成：{len(records)} 条记录（errors={len(errors)}），"
          f"wall={wall:.1f}s -> {out_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
