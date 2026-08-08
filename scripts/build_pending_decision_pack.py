"""纠偏 Task 8：pending 45 类裁决材料包（自动生成，不自动裁决）。

每类：class_id/display/代表图/raw count/effective groups/store/session/
最近 canonical 候选/embedding 距离/OCR 相似度/包装差异/建议/置信度/证据。
"""
from __future__ import annotations

import difflib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MAPPING = ROOT / "reports/nextgen_v2/cropped_sku_mapping.json"
POLICY = ROOT / "reports/nextgen_v2/sku_data_readiness_policy_v1.json"


def main() -> int:
    mp = json.loads(MAPPING.read_text(encoding="utf-8"))
    pol = json.loads(POLICY.read_text(encoding="utf-8"))
    reg = json.loads((ROOT / "data/sku_registry.json").read_text())
    reg_names = list(reg.keys())
    pack = []
    for d, e in mp["entries"].items():
        if e["kind"] == "mapped":
            continue
        st = pol["classes"].get(e["class_id"], {})
        src = ROOT / "cropped_images" / d
        files = sorted(src.glob("*.jpg"))
        # 最近 canonical 候选（名称相似度，仅材料，非裁决）
        close = difflib.get_close_matches(e["display"], reg_names, n=2,
                                          cutoff=0.55)
        sim = difflib.SequenceMatcher(
            None, e["display"], close[0]).ratio() if close else 0.0
        advice = ("new_sku" if sim < 0.6 else
                  "alias_or_package_version" if sim < 0.8 else "merge_candidate")
        pack.append({
            "class_id": e["class_id"], "display": e["display"],
            "representative_image": str(files[0]) if files else "",
            "raw_count": len(files),
            "effective_groups": st.get("unique_source_groups", 0),
            "stores": st.get("unique_stores", 0),
            "sessions": st.get("unique_sessions", 0),
            "nearest_canonical_candidates": close,
            "name_similarity": round(sim, 3),
            "ocr_similarity": None,  # 待 OCR 批跑补
            "packaging_diff": "待人工目检（代表图见 representative_image）",
            "suggestion": advice,
            "confidence": round(min(sim, 0.9), 2),
            "evidence": [str(files[0])] if files else [],
            "adjudication": "PENDING_HUMAN"})
    out = ROOT / "reports/nextgen_v2/pending_sku_decision_pack.json"
    out.write_text(json.dumps(pack, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    md = ["# Pending SKU 裁决包（45 类，自动生成，待人工裁决）", ""]
    for p in pack:
        md.append(f"- **{p['display']}**（{p['class_id']}）raw={p['raw_count']} "
                  f"groups={p['effective_groups']} 最近canonical="
                  f"{p['nearest_canonical_candidates'] or '无'} "
                  f"sim={p['name_similarity']} 建议={p['suggestion']}")
    (ROOT / "reports/nextgen_v2/pending_sku_decision_pack.md").write_text(
        "\n".join(md), encoding="utf-8")
    print("pack:", len(pack))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
