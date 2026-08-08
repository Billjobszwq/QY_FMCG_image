"""纠偏 Task 1/2：制品状态纠正 + 追加式 reconciliation + 四方对账。

磁盘 Artifact = 数据库 = API = Web；hash 不一致 fail-closed。
不覆盖历史行：同 artifact_id 已存在且 sha 相同 → duplicate（幂等）；
sha 不同 → ReconciliationError（fail-closed）。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Task 1：纠正后的制品状态（冻结）
CORRECT_STATUS = {
    "m1": "SMOKE_ONLY_NOT_CANDIDATE",
    "m2": "SMOKE_ONLY_NOT_CANDIDATE",
    "m3_random": "INVALID_FOR_BUSINESS_EVAL_LEAKED_SPLIT",
    "m3_grouped": "GROUPED_BASELINE_NOT_CANDIDATE",
    "m4_old": "PILOT_NOT_EVALUABLE_KB_COVERAGE_ZERO",
    "sam_v1": "EXPERIMENTAL_SELF_CONSISTENCY_NOT_CANDIDATE",
    "sam_v2": "EXPERIMENTAL_SELF_CONSISTENCY_NOT_CANDIDATE",
}

CORRECTED_GATE = "PIPELINE_SMOKES_READY_PLATFORM_NOT_CONNECTED"


class ReconciliationError(RuntimeError):
    """对账冲突（fail-closed）。"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ReconciliationService:
    def __init__(self, store: Any) -> None:
        self.store = store

    # ---- model artifact ----

    def register_artifact(self, *, artifact_id: str, kind: str, path: str,
                          sha256: str, dataset_manifest_sha: str,
                          source_commit: str, dirty_diff_hash: str,
                          model_base: str, label_source: str,
                          evidence_level: str, candidate_status: str,
                          blocker: str, actor: str,
                          run_id: str) -> dict[str, Any]:
        row = self.store._conn.execute(
            "SELECT sha256 FROM model_artifact_registry_v1"
            " WHERE artifact_id=?", (artifact_id,)).fetchone()
        if row is not None:
            if row["sha256"] != sha256:
                raise ReconciliationError(
                    f"artifact {artifact_id} hash 冲突："
                    f"DB={row['sha256'][:12]} new={sha256[:12]}（fail-closed）")
            return {"duplicate": True, "artifact_id": artifact_id}
        self.store._conn.execute(
            "INSERT INTO model_artifact_registry_v1 (artifact_id, kind,"
            " path, sha256, dataset_manifest_sha, source_commit,"
            " dirty_diff_hash, model_base, label_source, evidence_level,"
            " candidate_status, blocker, created_at, reconciled_by,"
            " reconciliation_run_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (artifact_id, kind, path, sha256, dataset_manifest_sha,
             source_commit, dirty_diff_hash, model_base, label_source,
             evidence_level, candidate_status, blocker, _now(), actor,
             run_id))
        self.store._conn.commit()
        return {"duplicate": False, "artifact_id": artifact_id}

    def reconcile_artifact(self, artifact_id: str) -> dict[str, Any]:
        """磁盘 sha == DB sha？不一致 fail-closed。"""
        row = self.store._conn.execute(
            "SELECT * FROM model_artifact_registry_v1 WHERE artifact_id=?",
            (artifact_id,)).fetchone()
        if row is None:
            return {"consistent": False, "reason": "not_registered"}
        p = Path(row["path"])
        if not p.exists():
            return {"consistent": False, "reason": "file_missing"}
        disk = _sha_file(p)
        return {"consistent": disk == row["sha256"],
                "disk_sha": disk[:12], "db_sha": row["sha256"][:12]}

    # ---- dataset snapshot ----

    def register_snapshot(self, *, snapshot_id: str, path: str,
                          manifest_sha: str, label_source: str,
                          evidence_level: str, leakage_policy: str,
                          actor: str, run_id: str) -> dict[str, Any]:
        row = self.store._conn.execute(
            "SELECT manifest_sha FROM dataset_snapshot_registry_v1"
            " WHERE snapshot_id=?", (snapshot_id,)).fetchone()
        if row is not None:
            if row["manifest_sha"] != manifest_sha:
                raise ReconciliationError(
                    f"snapshot {snapshot_id} manifest hash 冲突")
            return {"duplicate": True, "snapshot_id": snapshot_id}
        self.store._conn.execute(
            "INSERT INTO dataset_snapshot_registry_v1 (snapshot_id, path,"
            " manifest_sha, label_source, evidence_level, leakage_policy,"
            " created_at, reconciled_by, reconciliation_run_id)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (snapshot_id, path, manifest_sha, label_source, evidence_level,
             leakage_policy, _now(), actor, run_id))
        self.store._conn.commit()
        return {"duplicate": False, "snapshot_id": snapshot_id}

    # ---- evaluation ----

    def register_evaluation(self, *, eval_id: str, kind: str,
                            report_path: str, summary: dict[str, Any],
                            evidence_level: str, actor: str,
                            run_id: str) -> dict[str, Any]:
        p = Path(report_path)
        rsha = _sha_file(p) if p.exists() else ""
        row = self.store._conn.execute(
            "SELECT report_sha FROM evaluation_registry_v1 WHERE eval_id=?",
            (eval_id,)).fetchone()
        if row is not None:
            if row["report_sha"] and rsha and row["report_sha"] != rsha:
                raise ReconciliationError(f"eval {eval_id} report hash 冲突")
            return {"duplicate": True, "eval_id": eval_id}
        self.store._conn.execute(
            "INSERT INTO evaluation_registry_v1 (eval_id, kind, report_path,"
            " report_sha, summary_json, evidence_level, created_at,"
            " reconciled_by, reconciliation_run_id)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (eval_id, kind, report_path, rsha,
             json.dumps(summary, ensure_ascii=False), evidence_level,
             _now(), actor, run_id))
        self.store._conn.commit()
        return {"duplicate": False, "eval_id": eval_id}
