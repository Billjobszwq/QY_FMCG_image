"""Qwen3-VL benchmark 真实执行器（隔离环境 .venv_mlx_vlm）。

消费 src.training.vlm.benchmark.run_benchmark 的冻结矩阵，注入真实
executor：对确定性采样的 crop 做真实前向，实测 sample/region/token
数与耗时（estimation_basis=measured，禁止用照片数外推）。

诚实边界（写入报告 note，不伪造）：
- 本机仅有 4bit 推理权重；矩阵中 qlora/bf16 是训练配置标签，
  本探针均以同一 4bit 权重做推理测量，不声称区分两种训练模式；
- mlx-vlm generate 为逐样本推理，batch>1 以顺序推理等效测量。

用法（必须用隔离环境）：
  .venv_mlx_vlm/bin/python -m scripts.run_qwen3vl_benchmark_real \
      --preflight-report .eval/vlm_preflight/<run_id>/preflight.json \
      --dataset-root .datasets/sam_refined_full_v1 \
      --output-root .eval/qwen3vl_benchmark/<run_id>
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.training.vlm.benchmark import run_benchmark  # noqa: E402

MODEL_ID = "mlx-community/Qwen3-VL-4B-Instruct-4bit"
BENCH_VERSION = "qwen3vl-benchmark-real.v1"
# 视觉档位：low=小图少 token，high=大图多 token（像素上限）
TIER_MAX_PIXELS = {"low_tokens": 224 * 224, "high_tokens": 560 * 560}


def _collect_samples(dataset_root: Path, limit: int) -> list[dict]:
    """确定性采样：与 zero-shot 相同规则（排序后取前 limit 个 crop）。"""
    import yaml
    from PIL import Image
    data = yaml.safe_load((dataset_root / "data.yaml").read_text("utf-8"))
    names = list(data["names"])
    img_dir = dataset_root / "images" / "val"
    lbl_dir = dataset_root / "labels" / "val"
    samples: list[dict] = []
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
                cx, cy, bw, bh = map(float, parts[1:5])
                x1 = max(0, int((cx - bw / 2) * w))
                y1 = max(0, int((cy - bh / 2) * h))
                x2 = min(w, int((cx + bw / 2) * w))
                y2 = min(h, int((cy + bh / 2) * h))
                if x2 - x1 < 16 or y2 - y1 < 16:
                    continue
                samples.append({
                    "image": im.crop((x1, y1, x2, y2)).copy(),
                    "gt": names[int(parts[0])],
                })
                if len(samples) >= limit:
                    return samples
    return samples


def _fit_pixels(image, max_pixels: int):
    w, h = image.size
    if w * h <= max_pixels:
        return image
    scale = (max_pixels / (w * h)) ** 0.5
    return image.resize((max(32, int(w * scale)), max(32, int(h * scale))))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preflight-report", required=True)
    ap.add_argument("--dataset-root", default=".datasets/sam_refined_full_v1")
    ap.add_argument("--output-root", required=True)
    ap.add_argument("--samples", type=int, default=4,
                    help="每个 probe 的 crop 数（控制探针时长）")
    ap.add_argument("--max-tokens", type=int, default=16)
    a = ap.parse_args()

    pf_path = Path(a.preflight_report)
    if not pf_path.is_file():
        print(f"preflight 报告不存在，fail-closed: {pf_path}", file=sys.stderr)
        return 2
    pf = json.loads(pf_path.read_text("utf-8"))
    if not pf.get("ok"):
        print("preflight 未通过，拒绝真实 benchmark", file=sys.stderr)
        return 3

    out_root = Path(a.output_root)
    if out_root.exists():
        print(f"输出目录已存在，拒绝覆盖: {out_root}", file=sys.stderr)
        return 4

    samples = _collect_samples(Path(a.dataset_root), a.samples)
    if not samples:
        print("无可用样本，fail-closed", file=sys.stderr)
        return 2

    from mlx_vlm import load, generate
    from mlx_vlm.utils import load_config
    from mlx_vlm.prompt_utils import apply_chat_template

    print(f"加载模型 {MODEL_ID} ...", flush=True)
    model, processor = load(MODEL_ID)
    config = load_config(MODEL_ID)
    prompt_text = "请识别图中的饮料商品，只输出名称。"
    prompt = apply_chat_template(processor, config, prompt_text, num_images=1)

    def executor(probe, probe_samples):
        tier = probe["vision_tier"]
        max_pixels = TIER_MAX_PIXELS[tier]
        regions = 0
        tokens = 0
        t0 = time.time()
        for s in probe_samples:
            img = _fit_pixels(s["image"], max_pixels)
            regions += 1
            inputs = processor(images=img, text=prompt,
                               return_tensors="np") \
                if hasattr(processor, "image_processor") \
                else processor(img, prompt)
            ids = getattr(inputs, "input_ids", None)
            tokens += int(ids.shape[-1]) if ids is not None else 0
            generate(model, processor, prompt, image=img,
                     max_tokens=a.max_tokens, verbose=False)
        wall = time.time() - t0
        print(f"probe {probe['probe_id']}: regions={regions} "
              f"tokens={tokens} wall={wall:.2f}s", flush=True)
        return {"sample_count": len(probe_samples), "region_count": regions,
                "token_count": tokens, "wall_seconds": round(wall, 3)}

    t_start = time.time()
    report = run_benchmark(executor, output_root=out_root, samples=samples)
    report["note"] = (
        f"{BENCH_VERSION}: 真实前向测量；qlora/bf16 为矩阵标签，本机仅有 "
        f"4bit 推理权重，未声称区分训练模式；batch>1 以顺序推理等效测量。")
    report["model_id"] = MODEL_ID
    report["preflight_report"] = str(pf_path)
    report["wall_seconds_total"] = round(time.time() - t_start, 1)
    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1, default=str),
        encoding="utf-8")
    print(f"benchmark 完成 -> {out_root / 'report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
