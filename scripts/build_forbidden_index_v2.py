"""构建 Unified Forbidden Identity Index v2（全训练数据源）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data_governance.forbidden_identity_index import build_index


def main() -> int:
    src_dir = ROOT / ".datasets_nextgen"
    sources = {
        "m3_tvt": sorted(p for sp in ("train", "val", "test")
                         for p in (src_dir / "canonical38_train_val_test_v2"
                                   / sp).rglob("*.jpg")),
        "m3_old_d3": sorted(p for sp in ("train", "val")
                            for p in (src_dir / "d3_cropped_classifier_v1"
                                      / sp).rglob("*.jpg")),
        "qlora_v1": sorted((src_dir / "d4_cropped_vlm_v1" / "images")
                           .glob("*")),
        "qlora_v2": sorted((src_dir / "d4_real_candidate_v2" / "images")
                           .glob("*")),
        "scene_d1": sorted(p for sp in ("train", "val")
                           for p in (src_dir / "d1_detector_smoke_v1"
                                     / "images" / sp).glob("*")),
        "scene_d2": sorted(p for sp in ("train", "val")
                           for p in (src_dir / "d2_segmenter_smoke_v1"
                                     / "images" / sp).glob("*")),
    }
    # KB 参考图
    kb = json.loads((ROOT / ".kb/canonical38.json").read_text())
    kb_imgs = []
    for e in kb:
        kb_imgs += [Path(r) for r in e.get("ref_images", [])]
    sources["kb_refs"] = [p for p in kb_imgs if p.exists()]
    out = ROOT / "reports/nextgen_v2/forbidden_index_v2"
    idx = build_index(sources, out)
    print(json.dumps(idx["audit"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
