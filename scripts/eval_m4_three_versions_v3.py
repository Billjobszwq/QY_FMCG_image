"""M4 三版本真实评估 V3（只推理，不训练）。

读 m4_holdout_v3/holdout_samples.json（candidates+scores 已冻结）。
三版本同数据/候选/prompt/解析器；逐样本 raw/tokens/wall/adapter sha。
bounded smoke 12 条先行。
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PROMPT_TMPL = ("USER: <image>\n货架商品切图。候选 SKU：\n{cands}\n"
               "最匹配编号？都不匹配回答 none。\nASSISTANT:")


def parse_answer(raw: str, n: int):
    t = raw.strip()
    if t.lower() == "none":
        return "none", None
    m = re.search(r"\b(\d+)\b", t)
    if m and 1 <= int(m.group(1)) <= n:
        return "accepted", int(m.group(1))
    return "parse_error", None


def run_version(samples, adapter, vname, out_dir, limit=None):
    from mlx_vlm import generate, load
    from mlx_vlm.prompt_utils import apply_chat_template
    import cv2
    import mlx_vlm
    model, processor = load("mlx-community/Qwen3-VL-4B-Instruct-4bit",
                            adapter_path=adapter)
    config = model.config if hasattr(model, "config") else {}
    adapter_sha = ""
    if adapter:
        ap = Path(adapter) / "adapters.safetensors"
        adapter_sha = hashlib.sha256(ap.read_bytes()).hexdigest()
    rows = []
    for i, s in enumerate(samples if limit is None else samples[:limit]):
        x0, y0, x1, y1 = s["bbox"]
        img = cv2.imread(s["file"])
        crop = img[y0:y1, x0:x1]
        h, w = crop.shape[:2]
        if max(h, w) > 1024:
            sc = 1024 / max(h, w)
            crop = cv2.resize(crop, (int(w * sc), int(h * sc)))
        tmp = out_dir / f"_tmp_{vname}.jpg"
        cv2.imwrite(str(tmp), crop)
        cand_txt = "\n".join(f"{j+1}. {c}" for j, c in
                             enumerate(s["cands"]))
        prompt = apply_chat_template(processor, config,
                                     PROMPT_TMPL.format(cands=cand_txt),
                                     num_images=1)
        t0 = time.time()
        out = generate(model, processor, prompt, image=str(tmp),
                       max_tokens=8, verbose=False)
        dt = time.time() - t0
        kind, pos = parse_answer(out.text, len(s["cands"]))
        rows.append({"sample_id": s["sample_id"],
                     "image_sha": s["sha"], "group": s["group"],
                     "candidates": s["cands"],
                     "candidate_scores": s["scores"],
                     "prompt_hash": hashlib.sha256(
                         prompt.encode()).hexdigest()[:16],
                     "model_id": "mlx-community/Qwen3-VL-4B-Instruct-4bit",
                     "adapter": vname, "adapter_sha256": adapter_sha[:16],
                     "library_version": getattr(mlx_vlm, "__version__",
                                                "0.6.10"),
                     "raw_output": out.text, "parsed_kind": kind,
                     "parsed_pos": pos, "wall_time_s": round(dt, 3),
                     "generation_tokens": getattr(out, "generation_tokens",
                                                  "unsupported"),
                     "peak_memory_gb": (round(float(out.peak_memory), 2)
                                        if getattr(out, "peak_memory", 0)
                                        else "unsupported")})
    tmp = out_dir / f"_tmp_{vname}.jpg"
    if tmp.exists():
        tmp.unlink()
    (out_dir / f"per_sample_{vname}_v3.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows),
        encoding="utf-8")
    return rows


def score(rows, samples):
    hit = tot = acc = acc_ok = 0
    an = aok = fa = fr = pfa = 0
    for r, s in zip(rows, samples):
        tot += 1
        gt_pos = (s["cands"].index(s["gt"]) + 1
                  if s.get("gt") in s["cands"] else None)
        if r["parsed_kind"] == "none":
            an += 1
            if s["kind"] != "canonical":
                aok += 1
            else:
                fr += 1
        elif r["parsed_kind"] == "accepted":
            acc += 1
            if s["kind"] == "canonical" and r["parsed_pos"] == gt_pos:
                hit += 1
                acc_ok += 1
            elif s["kind"] == "canonical":
                fr += 1
            else:
                fa += 1
                if s["kind"] == "pending":
                    pfa += 1
        else:
            fr += 1
    lat = sorted(r["wall_time_s"] for r in rows)
    return {"n": tot, "top1": round(hit / max(tot, 1), 3),
            "accepted_precision": round(acc_ok / max(acc, 1), 3),
            "coverage": round(acc / max(tot, 1), 3),
            "abstain_n": an,
            "abstain_precision": round(aok / max(an, 1), 3),
            "false_accept": fa, "pending_false_accept": pfa,
            "false_reject": fr,
            "p50_s": round(lat[len(lat) // 2], 2),
            "p95_s": round(lat[int(0.95 * (len(lat) - 1))], 2)}


def main() -> int:
    out = ROOT / "reports/nextgen_v2/m4_evidence_v3"
    out.mkdir(parents=True, exist_ok=True)
    samples = json.loads((ROOT / "reports/nextgen_v2/m4_holdout_v3"
                          / "holdout_samples.json").read_text())
    versions = [("base", None),
                ("old_cropped_adapter",
                 str(ROOT / ".models/nextgen_vlm_cropped_v1/adapters")),
                ("new_real_adapter",
                 str(ROOT / ".models/nextgen_vlm_real_candidate_v1"
                     / "adapters"))]
    smoke = run_version(samples, None, "base_smoke", out, limit=12)
    sm = score(smoke, samples[:12])
    (out / "bounded_smoke_v3.json").write_text(
        json.dumps(sm, ensure_ascii=False, indent=1), encoding="utf-8")
    print("smoke:", sm)
    # 管线健康判据：解析率≥0.8 且 raw 非空（base 在独立集 top1=0 合法）
    parsed_ok = 1 - sum(1 for r in smoke
                        if r["parsed_kind"] == "parse_error") / len(smoke)
    if parsed_ok < 0.8 or not all(r["raw_output"].strip() for r in smoke):
        print("SMOKE FAILED (pipeline)")
        return 1
    results = {}
    for vname, adapter in versions:
        rows = run_version(samples, adapter, vname, out)
        results[vname] = score(rows, samples)
        print(vname, results[vname])
    rep = {"versions": results, "smoke": sm,
           "holdout_manifest": json.loads((ROOT / "reports/nextgen_v2"
                                           / "m4_holdout_v3"
                                           / "manifest.json").read_text()),
           "gt_policy": "GT 仅评估账本；候选冻结于 holdout",
           "report_hash": hashlib.sha256(json.dumps(
               results, sort_keys=True).encode()).hexdigest()}
    (ROOT / "reports/nextgen_v2/m4_three_version_eval_v3.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
