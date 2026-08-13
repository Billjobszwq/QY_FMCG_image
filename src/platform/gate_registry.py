"""OSV52：Active Gate 显式 Registry（gate_run_v1）。

废除 `.eval/*/gate.json` mtime 选择：实时 Gate 只读 Registry 中
**唯一 active** 的 gate run。规则：

- 每次 gate 全量评估落盘 gate.json 时登记一条 `candidate`（append-only，
  禁 DELETE 触发器；状态迁移走 CAS 条件 UPDATE）。
- 激活（activate）需平台角色 + 显式人工批准（approved=True）；
  CAS：candidate→active 且同一 protocol 至多一个 active——激活新 run
  时旧 active 以条件 UPDATE 置 superseded 并记录 supersedes 链。
- 旧 scope 重跑只能产生 candidate；`expected_protocol` 不匹配时激活
  fail-closed——旧 scope Gate 不得接管系统状态。
- active 缺失/文件缺失/文件哈希不一致/registry 不一致 → 调用方必须
  fail-closed（BLOCKED_BY_GATE_EVIDENCE）。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone


class GateRegistryError(Exception):
    """OSV52：Gate Registry 错误（稳定语义，API 映射 409/403）。"""


PLATFORM_ROLES = ("admin", "owner", "platform_admin")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_gate_run_id() -> str:
    return "grun-" + uuid.uuid4().hex[:12]


def record_gate_run(store, *, protocol: str, gate_path,
                    source_commit: str, evaluator_version: str,
                    evidence_manifest_hash: str,
                    gate_file_sha256: str,
                    requested_by: str = "", note: str = "") -> str:
    """登记一次 gate 生成为 candidate；返回 gate_run_id。"""
    gid = _new_gate_run_id()
    now = _now()
    store._conn.execute(
        "INSERT INTO gate_run_v1 (gate_run_id, protocol, gate_path,"
        " gate_file_sha256, source_commit, evaluator_version,"
        " evidence_manifest_hash, status, requested_by, created_at,"
        " updated_at, note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (gid, protocol, str(gate_path), gate_file_sha256,
         source_commit, evaluator_version, evidence_manifest_hash,
         "candidate", requested_by, now, now, note))
    store._conn.commit()
    return gid


def get_gate_run(store, gate_run_id: str):
    row = store._conn.execute(
        "SELECT * FROM gate_run_v1 WHERE gate_run_id=?",
        (gate_run_id,)).fetchone()
    return dict(row) if row else None


def get_active_gate_run(store, *, protocol: str = ""):
    if protocol:
        row = store._conn.execute(
            "SELECT * FROM gate_run_v1 WHERE status='active' AND"
            " protocol=? ORDER BY activated_at DESC LIMIT 1",
            (protocol,)).fetchone()
    else:
        row = store._conn.execute(
            "SELECT * FROM gate_run_v1 WHERE status='active'"
            " ORDER BY activated_at DESC LIMIT 1").fetchone()
    return dict(row) if row else None


def activate_gate_run(store, *, gate_run_id: str, actor: str,
                      approved: bool, session_role: str = "admin",
                      expected_protocol: str = "") -> dict:
    """CAS 激活：candidate→active；旧 active→superseded。

    - 需平台角色 + approved=True（人工批准）；
    - expected_protocol 给定且不匹配 → GateRegistryError（旧 scope
      不得接管）；
    - 同 run 重复激活幂等返回当前行。
    """
    if not approved:
        raise GateRegistryError(
            "GATE_ACTIVATION_NOT_APPROVED: 激活需人工批准"
            "（approved=true）")
    if session_role not in PLATFORM_ROLES:
        raise GateRegistryError(
            "GATE_ACTIVATION_PERMISSION_DENIED: 激活需平台角色"
            f"（当前 {session_role}）")
    row = get_gate_run(store, gate_run_id)
    if row is None:
        raise GateRegistryError(
            f"GATE_RUN_NOT_FOUND: {gate_run_id}")
    if expected_protocol and row["protocol"] != expected_protocol:
        raise GateRegistryError(
            "GATE_PROTOCOL_MISMATCH: 试图激活 protocol="
            f"{row['protocol']}，当前系统 protocol="
            f"{expected_protocol}（旧 scope 不得接管）")
    if row["status"] == "active":
        return row  # 幂等
    if row["status"] != "candidate":
        raise GateRegistryError(
            f"GATE_ACTIVATION_INVALID_STATE: {row['status']} 不可激活")
    now = _now()
    conn = store._conn
    prev = get_active_gate_run(store, protocol=row["protocol"])
    rc = conn.execute(
        "UPDATE gate_run_v1 SET status='active', activated_by=?,"
        " activated_at=?, updated_at=?, supersedes=? WHERE"
        " gate_run_id=? AND status='candidate'",
        (actor, now, now, prev["gate_run_id"] if prev else "",
         gate_run_id)).rowcount
    if rc == 0:
        cur = get_gate_run(store, gate_run_id)
        if cur and cur["status"] == "active":
            return cur  # 并发下他人已激活同一 run → 幂等
        raise GateRegistryError(
            "GATE_ACTIVATION_VERSION_CONFLICT: CAS 失败，请刷新重试")
    if prev:
        conn.execute(
            "UPDATE gate_run_v1 SET status='superseded',"
            " updated_at=? WHERE gate_run_id=? AND status='active'",
            (now, prev["gate_run_id"]))
    conn.commit()
    try:
        from .iam import IAMService
        IAMService(store).audit(
            actor, "gate.activated", f"gate_run:{gate_run_id}",
            {"protocol": row["protocol"],
             "supersedes": prev["gate_run_id"] if prev else ""},
            customer_id="")
    except Exception:  # noqa: BLE001
        pass
    return get_gate_run(store, gate_run_id)
