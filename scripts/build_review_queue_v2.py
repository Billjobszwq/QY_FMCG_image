"""构建并发布 review_queue_diag_v2（PLC3-003，取代 rq_v1）。

- SHA 按 photo_id 从 clean_manifest.json 查询（禁止位置 zip，P0 根因修复）；
- 发布门禁任一失败即不发布：500/500 映射、250/250 配对、
  226/226 原图存在、226/226 现场 SHA 一致；
- 输出 `.review_queue/review_queue_diag_v2.json`（含 audit，已存在拒绝覆盖）
  与 `.review_queue/review_queue_diag_v2_audit.json`（独立审计副本）。

用法：
  python -m scripts.build_review_queue_v2
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

from src.review import review_queue_v2 as RQ2

DIAG = PROJECT_ROOT / ".data_protocol" / "diagnostic_v1.json"
MANIFEST = PROJECT_ROOT / ".batch3_clean" / "clean_manifest.json"
BLOBS = PROJECT_ROOT / ".batch3_clean" / "blobs"
OUT = PROJECT_ROOT / ".review_queue" / "review_queue_diag_v2.json"
AUDIT = PROJECT_ROOT / ".review_queue" / "review_queue_diag_v2_audit.json"


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT,
            text=True).strip()
    except Exception:
        return ""


def main() -> None:
    proto = json.loads(DIAG.read_text(encoding="utf-8"))
    assert proto.get("frozen") is True and proto["role"] == "diagnostic_v1"
    seed = int(proto.get("seed", 20260804))

    q, audit, gates = RQ2.build_v2(
        protocol_path=DIAG, manifest_path=MANIFEST, blobs_dir=BLOBS,
        seed=seed, n_double=200, n_blind=50, verify_blobs=True,
        git_commit=_git_commit())

    print(json.dumps({"gates": gates,
                      "audit": {k: audit[k] for k in
                                ("n_tasks", "n_unique_photos",
                                 "n_overlap_photos", "pairing_correct",
                                 "distribution", "errors", "supersedes")}},
                     ensure_ascii=False, indent=2))
    if not gates["ok"]:
        raise SystemExit("[rq2] 发布门禁未通过，fail-closed：不发布")
    if audit["pairing_correct"] != audit["n_tasks"]:
        raise SystemExit("[rq2] 配对未全对，fail-closed：不发布")

    RQ2.write_v2(q, audit, OUT)
    if not AUDIT.exists():
        tmp = AUDIT.with_suffix(".tmp")
        tmp.write_text(json.dumps(audit, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(AUDIT)
    print(f"[rq2] queue → {OUT}")
    print(f"[rq2] audit → {AUDIT}")
    print(f"[rq2] 门禁通过：{gates['mapping_recovered']}/{gates['mapping_total']} 映射，"
          f"{audit['pairing_correct']}/{audit['n_tasks']} 配对，"
          f"{gates['files_present']}/{gates['n_unique_photos']} 原图，"
          f"{gates['sha_verified']}/{gates['n_unique_photos']} 现场SHA")


if __name__ == "__main__":
    main()
