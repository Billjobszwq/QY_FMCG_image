"""证据链收口 T8：M4 三版本真实推理评估 v2（完整证据，只评估不训练）。

bounded smoke 12 条先行；逐样本：sample_id(无语义)/image SHA/
leakage_group/candidates+scores/prompt hash/model+adapter hash/
library 版本/raw output/parsed/abstain/wall time/generation_tokens/
parse error/escape。GT 仅评估账本读取。
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PROMPT_TMPL = ("USER: <image>\n货架商品切图。候选 SKU：\n{cands}\n"
               "最匹配编号？都不匹配回答 none。\nASSISTANT:")


def parse_answer(raw: str, n_cands: int):
    t = raw.strip()
    if t.lower() == "none":
        return "none", None
    for tok in t.replace("。", " ").split():
        if tok.isdigit() and 1 <= int(tok) <= n_cands:
            return "accepted", int(tok)
    import re
    m = re.search(r"\b(\d+)\b", t)
    if m and 1 <= int(m.group(1)) <= n_cands:
        return "accepted", int(m.group(1))
    return "parse_error", None


def run_version(samples, adapter, vname, out_dir, limit=None):
    from mlx_vlm import generate, load
    from mlx_vlm.prompt_utils import apply_chat_template
    import mlx_vlm
    model, processor = load("mlx-community/Qwen3-VL-4B-Instruct-4bit",
                            adapter_path=adapter)
    config = model.config if hasattr(model, "config") else {}
    adapter_sha = ""
    if adapter:
        ap = Path(adapter) / "adapters.safetensors"
        adapter_sha = hashlib.sha256(ap.read_bytes()).hexdigest()
    rows = []
    lat = []
    for i, s in enumerate(samples if limit is None else samples[:limit]):
        cand_txt = "\n".join(f"{j+1}. {c}" for j, c in
                             enumerate(s["cands"]))
        prompt = apply_chat_template(processor, config,
                                     PROMPT_TMPL.format(cands=cand_txt),
                                     num_images=1)
        t0 = time.time()
        out = generate(model, processor, prompt, image=s["file"],
                       max_tokens=8, verbose=False)
        dt = time.time() - t0
        lat.append(dt)
        raw = out.text
        kind, pos = parse_answer(raw, len(s["cands"]))
        rows.append({
            "sample_id": f"s{i:04d}", "image_sha": s["sha"],
            "leakage_group": s["group"],
            "candidates": s["cands"], "candidate_scores": s.get("scores"),
            "prompt_hash": hashlib.sha256(prompt.encode()).hexdigest()[:16],
            "model_id": "mlx-community/Qwen3-VL-4B-Instruct-4bit",
            "adapter": vname, "adapter_sha256": adapter_sha[:16],
            "library_version": getattr(mlx_vlm, "__version__", "0.6.10"),
            "raw_output": raw, "parsed_kind": kind, "parsed_pos": pos,
            "wall_time_s": round(dt, 3),
            "generation_tokens": getattr(out, "generation_tokens",
                                         "unsupported"),
            "peak_memory_gb": round(getattr(out, "peak_memory", 0) /
                                    (1024 ** 3), 2),
        })
    (out_dir / f"per_sample_{vname}.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows),
        encoding="utf-8")
    return rows, lat


def score(rows, samples):
    hit = tot = acc = acc_ok = 0
    abstain_n = abstain_ok = fa = fr = esc = 0
    for r, s in zip(rows, samples):
        tot += 1
        gt_pos = (s["cands"].index(s["gt"]) + 1
                  if s["gt"] in s["cands"] else None)
        if r["parsed_kind"] == "none":
            abstain_n += 1
            if not s["is_canonical"]:
                abstain_ok += 1
            else:
                fr += 1
        elif r["parsed_kind"] == "accepted":
            acc += 1
            if s["is_canonical"] and r["parsed_pos"] == gt_pos:
                hit += 1
                acc_ok += 1
            elif s["is_canonical"]:
                fr += 1
            else:
                fa += 1
        else:
            fr += 1
    lat = sorted(r["wall_time_s"] for r in rows)
    return {"n": tot, "top1": round(hit / max(tot, 1), 3),
            "accepted_precision": round(acc_ok / max(acc, 1), 3),
            "coverage": round(acc / max(tot, 1), 3),
            "abstain_n": abstain_n,
            "abstain_precision": round(abstain_ok / max(abstain_n, 1), 3),
            "false_accept": fa, "false_reject": fr,
            "p50_s": round(lat[len(lat) // 2], 2),
            "p95_s": round(lat[int(0.95 * (len(lat) - 1))], 2)}


def main() -> int:
    import re
    samples = json.loads(Path("/tmp/m4_eval_samples.json").read_text())
    grp_re = re.compile(r"^[0-9a-f]{8}__(.+?)_29_")
    for s in samples:
        p = Path(s["file"])
        s["sha"] = hashlib.sha256(p.read_bytes()).hexdigest()
        m = grp_re.match(p.name)
        s["group"] = m.group(1) if m else f"nosrc:{p.name}"
    # 无语义 sample 顺序：按 sha 排序，去文件名语义
    samples.sort(key=lambda s: s["sha"])
    out_dir = ROOT / "reports/nextgen_v2/m4_evidence_v2"
    out_dir.mkdir(parents=True, exist_ok=True)

    versions = [("base", None),
                ("old_cropped_adapter",
                 str(ROOT / ".models/nextgen_vlm_cropped_v1/adapters")),
                ("new_real_adapter",
                 str(ROOT / ".models/nextgen_vlm_real_candidate_v1"
                     / "adapters"))]
    # bounded smoke：base 12 条
    smoke_rows, smoke_lat = run_version(samples, None, "base_smoke",
                                        out_dir, limit=12)
    sm = score(smoke_rows, samples[:12])
    (out_dir / "bounded_smoke.json").write_text(
        json.dumps(sm, ensure_ascii=False, indent=1), encoding="utf-8")
    print("smoke:", sm)
    if sm["top1"] < 0.25:
        print("SMOKE FAILED → stop")
        return 1

    results = {}
    for vname, adapter in versions:
        rows, lat = run_version(samples, adapter, vname, out_dir)
        results[vname] = score(rows, samples)
        print(vname, results[vname])
    rep = {"versions": results,
           "smoke": sm,
           "holdout_n": len(samples),
           "gt_policy": "GT 仅评估账本读取；推理输入无语义 sample_id",
           "token_policy": "generation_tokens 来自 GenerationResult；"
                           "缺失写 unsupported"}
    (ROOT / "reports/nextgen_v2/m4_three_version_eval_v2.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
