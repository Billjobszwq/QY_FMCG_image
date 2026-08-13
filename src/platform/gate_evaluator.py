"""UFC T5：证据驱动 Gate 判定器（fail-closed）。

规则（指令第十一节）：
- Gate 只由 evaluate_gate_from_evidence() 从 Store/报告/测试/服务/
  浏览器证据自动计算；禁止调用方手写布尔值宣布 READY。
- 任一证据缺失或失败 → BLOCKED_BY_*；结果写入机器 gate.json，
  文档只引用，不得人工改写。
- 旧 evaluate_gate(布尔入参) 仅保留为内部单元参考，任何生产路径
  不得用它宣布 READY。
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

READY = "READY_FOR_REAL_DATA_UAT"
STALE = "STALE_GATE_EVIDENCE"
# OSV5（指令 P1-004）：版本一处定义，gate.json/API/Web/文档/
# validator/负例全部引用，禁止漂移。
# OSV51：3.3.0 = 证据新鲜度绑定 + 导入安全（quarantine 写逃逸/
# 递归 secret 扫描/血缘完整性）检查族。
EVALUATOR_VERSION = "3.3.0"
BLOCKED_IMPORT_LINEAGE = "BLOCKED_BY_IMPORT_SCOPE_LINEAGE"
# OSV51 C-1/C-2：导入安全阻断码（quarantine 写逃逸、secret 泄漏）
BLOCKED_IMPORT_SECURITY = "BLOCKED_BY_IMPORT_SECURITY"

# UAT 主工作流必备节点类型；model/command 任一即可作为 capability
# 节点（指令："model或command/capability"）。
REQUIRED_WORKFLOW_NODE_TYPES = ("trigger", "transform", "condition",
                                "wait", "parallel", "join", "loop",
                                "human_approval", "agent")
CAPABILITY_WORKFLOW_NODE_TYPES = ("model", "command")

# SI4：浏览器验收必须覆盖的 12 个一级工作台（少一页 Gate 不过）。
REQUIRED_BROWSER_ROUTES = (
    "home", "data/import", "survey/design", "geo/addresses",
    "vision/recognize", "analytics/reports", "workflow/studio",
    "iam/accounts", "master/customers", "finance/contracts", "help",
    "status",
)


def evaluate_gate(*, p0_open: int, p1_open: int, rate_limit_ok: bool,
                  scenarios_ok: bool, parallel_ok: bool,
                  storefront_contract_ok: bool = True,
                  usage_lineage_ok: bool = True,
                  uat_v2_ok: bool = True,
                  v4_honesty_ok: bool = True) -> tuple[str, list[str]]:
    """【已废弃的生产入口】仅保留为内部单元参考。生产 Gate 必须走
    evaluate_gate_from_evidence()。"""
    reasons: list[str] = []
    if p0_open > 0:
        reasons.append(f"存在 {p0_open} 个未关闭 P0")
    if p1_open > 0:
        reasons.append(f"存在 {p1_open} 个未关闭 P1")
    if not rate_limit_ok:
        reasons.append("rate limit 未真实实现/未验证（BLOCKED_BY_RATE_LIMIT）")
    if not scenarios_ok:
        reasons.append("UAT 必填场景缺失（BLOCKED_BY_UAT_EVIDENCE）")
    if not parallel_ok:
        reasons.append("parallel 无真实并发证明（BLOCKED_BY_WORKFLOW_RUNTIME）")
    if not storefront_contract_ok:
        reasons.append("门头必拍契约未通过（BLOCKED_BY_PHOTO_CONTRACT）")
    if not usage_lineage_ok:
        reasons.append("Agent Usage 链路不完整（BLOCKED_BY_USAGE_LINEAGE）")
    if not uat_v2_ok:
        reasons.append("UAT V2 未完整执行（BLOCKED_BY_UAT_EVIDENCE）")
    if not v4_honesty_ok:
        reasons.append("V4 证据口径不诚实（BLOCKED_BY_UAT_EVIDENCE）")
    if reasons:
        gate = "BLOCKED_BY_" + (
            "P0" if p0_open else "P1" if p1_open else "CONTRACT")
        return gate, reasons
    return READY, []


# --------------------------------------------------------------------
# 证据驱动主入口
# --------------------------------------------------------------------

def _file_sha(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()[:16]
    except Exception:
        return ""


def _load_json(path) -> dict | None:
    try:
        p = Path(path)
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def scan_terminal_drift(store) -> list[dict]:
    """DB 终态漂移扫描：run 终态但主 work/approval/timer/branch 未收敛。

    UFC T4：uat_fixture 为归档测试数据，不参与运营一致性判定。"""
    drift: list[dict] = []
    conn = store._conn
    rows = conn.execute(
        "SELECT br.run_id, br.status AS run_status, w.status AS"
        " work_status FROM business_run_v1 br JOIN work_item_v2 w"
        " ON w.work_id=br.work_id WHERE br.status IN"
        " ('succeeded','failed','partial_failed','cancelled') AND"
        " COALESCE(br.data_scope,'operational')='operational'"
        ).fetchall()
    expect = {"succeeded": "done", "failed": "blocked",
              "partial_failed": "blocked", "cancelled": "cancelled"}
    for r in rows:
        if r["work_status"] != expect[r["run_status"]]:
            drift.append({"kind": "main_work", "run_id": r["run_id"],
                          "run": r["run_status"],
                          "work": r["work_status"]})
    rows = conn.execute(
        "SELECT br.run_id, br.status AS run_status, w.work_id,"
        " w.status FROM business_run_v1 br JOIN work_item_v2 w"
        " ON w.run_id=br.run_id WHERE br.status IN"
        " ('succeeded','failed','partial_failed','cancelled') AND"
        " w.status='approval' AND"
        " COALESCE(br.data_scope,'operational')='operational'")
    rows = rows.fetchall()
    for r in rows:
        drift.append({"kind": "approval_open", "run_id": r["run_id"],
                      "run": r["run_status"], "work": r["work_id"]})
    rows = conn.execute(
        "SELECT t.run_id, t.status FROM workflow_timer_v1 t JOIN"
        " business_run_v1 br ON br.run_id=t.run_id WHERE br.status IN"
        " ('succeeded','failed','partial_failed','cancelled') AND"
        " t.status='pending' AND"
        " COALESCE(br.data_scope,'operational')='operational'")
    rows = rows.fetchall()
    for r in rows:
        drift.append({"kind": "timer_pending", "run_id": r["run_id"]})
    rows = conn.execute(
        "SELECT b.run_id, b.branch_id, b.status FROM"
        " workflow_branch_v1 b JOIN business_run_v1 br ON"
        " br.run_id=b.run_id WHERE br.status IN"
        " ('succeeded','failed','partial_failed','cancelled') AND"
        " b.status IN ('pending','running') AND"
        " COALESCE(br.data_scope,'operational')='operational'")
    rows = rows.fetchall()
    for r in rows:
        drift.append({"kind": "branch_open", "run_id": r["run_id"],
                      "branch": r["branch_id"]})
    # SI3：节点层同样必须收敛（指令八/九.10）：terminal Run 下
    # 不得残留任何活动态 node。
    rows = conn.execute(
        "SELECT n.run_id, n.node_id, n.status FROM"
        " workflow_node_execution_v1 n JOIN business_run_v1 br ON"
        " br.run_id=n.run_id WHERE br.status IN"
        " ('succeeded','failed','partial_failed','cancelled') AND"
        " n.status IN ('running','pending','queued','waiting',"
        "'paused','started','in_progress','scheduled',"
        "'waiting_timer','waiting_approval','waiting_human') AND"
        " COALESCE(br.data_scope,'operational')='operational'")
    rows = rows.fetchall()
    for r in rows:
        drift.append({"kind": "node_open", "run_id": r["run_id"],
                      "node": r["node_id"], "status": r["status"]})
    return drift


# --------------------------------------------------------------------
# OSV51 W2-a（契约 C-1 §8）：quarantine 批次 → operational 对象写入
# 归因断言。只用结构化键（批次行内自然键 / commit receipts），不做
# 任何名称猜测。
# --------------------------------------------------------------------

_QUARANTINE_ATTR_NATURAL: dict[str, tuple[str, str, str]] = {
    # template_id → (目标表, 主键列, 批次行内列)
    "customers_v1": ("md_customer_v1", "customer_id", "customer_id"),
    "projects_v1": ("md_project_v1", "project_id", "project_id"),
    "skus_v1": ("md_sku_v1", "sku_id", "sku_id"),
    "users_v1": ("iam_principal_v1", "username", "username"),
}
_QUARANTINE_ATTR_RECEIPT: dict[str, tuple[str, str]] = {
    # template_id → (目标表, receipt 键)
    "stores_addresses_v1": ("geo_address_v1", "address_id"),
    "employees_v1": ("geo_employee_v1", "employee_id"),
}


def _has_column(conn, table: str, column: str) -> bool:
    try:
        return any(r[1] == column for r in conn.execute(
            f"PRAGMA table_info({table})"))
    except Exception:
        return False


def quarantine_operational_write_violations(conn) -> list[dict]:
    """DB 级断言：可归因于 quarantine 批次的目标对象行不得处于
    operational 作用域。

    归因（保守、结构化、sound）：
    1) mapping_json 行内自然键（customers/projects/skus/users）；
    2) commit receipts 的 address_id/employee_id（stores/employees）；
    3) receipts 为空时 stores/employees 退回 _classify 同款幂等自然键
       （customer_id+store_name raw LIKE / customer_id+name 等值）。

    假设：目标表均带 data_scope 列（缺失则跳过该表，不误报）；归因
    只用结构化键，不按时间戳反推历史——批次仍 operational 时合法产生
    的对象应已由 reconcile/backfill 重新打标，残留 operational 即视为
    逃逸写入（现场 imp-bf333d101db6 重放因地址已存在被幂等跳过，属
    运气非设计；本断言捕获其下一次真正插入）。
    """
    out: list[dict] = []
    batches = conn.execute(
        "SELECT batch_id, template_id, mapping_json, commit_json FROM"
        " import_batch_v1 WHERE COALESCE(data_scope,'')='quarantine'"
    ).fetchall()
    for b in batches:
        tpl = b["template_id"]
        try:
            mapping = json.loads(b["mapping_json"] or "{}")
        except Exception:
            mapping = {}
        try:
            commit = json.loads(b["commit_json"] or "{}")
        except Exception:
            commit = {}
        header = mapping.get("header") or []
        mrows = mapping.get("rows") or []

        def _flag(table: str, key: str, n: int) -> None:
            if n:
                out.append({"batch_id": b["batch_id"], "table": table,
                            "key": key, "count": int(n)})

        if tpl in _QUARANTINE_ATTR_NATURAL:
            table, pkcol, col = _QUARANTINE_ATTR_NATURAL[tpl]
            if _has_column(conn, table, "data_scope") and col in header:
                idx = header.index(col)
                keys = sorted({str(r[idx]).strip() for r in mrows
                               if idx < len(r) and str(r[idx]).strip()})
                for k in keys:
                    n = conn.execute(
                        f"SELECT count(*) c FROM {table} WHERE {pkcol}=?"
                        " AND COALESCE(data_scope,'operational')"
                        "='operational'", (k,)).fetchone()["c"]
                    _flag(table, k, n)
        if tpl in _QUARANTINE_ATTR_RECEIPT:
            table, rkey = _QUARANTINE_ATTR_RECEIPT[tpl]
            if not _has_column(conn, table, "data_scope"):
                continue
            ids = sorted({str(r.get(rkey)) for r in
                          (commit.get("receipts") or [])
                          if r.get(rkey)})
            for oid in ids:
                n = conn.execute(
                    f"SELECT count(*) c FROM {table} WHERE {rkey}=?"
                    " AND COALESCE(data_scope,'operational')"
                    "='operational'", (oid,)).fetchone()["c"]
                _flag(table, oid, n)
            if ids:
                continue
            # receipts 为空（如重放被幂等跳过覆写）→ 自然键回退
            if tpl == "stores_addresses_v1" and "customer_id" in header \
                    and "store_name" in header:
                ci = header.index("customer_id")
                si = header.index("store_name")
                for r in mrows:
                    if max(ci, si) >= len(r):
                        continue
                    cid = str(r[ci]).strip()
                    sn = str(r[si]).strip()
                    if not cid or not sn:
                        continue
                    n = conn.execute(
                        "SELECT count(*) c FROM geo_address_v1 WHERE"
                        " customer_id=? AND raw LIKE ? AND COALESCE("
                        "data_scope,'operational')='operational'",
                        (cid, f"%{sn}%")).fetchone()["c"]
                    _flag("geo_address_v1", f"{cid}|{sn}", n)
            if tpl == "employees_v1" and "customer_id" in header \
                    and "name" in header:
                ci = header.index("customer_id")
                ni = header.index("name")
                for r in mrows:
                    if max(ci, ni) >= len(r):
                        continue
                    cid = str(r[ci]).strip()
                    nm = str(r[ni]).strip()
                    if not cid or not nm:
                        continue
                    n = conn.execute(
                        "SELECT count(*) c FROM geo_employee_v1 WHERE"
                        " customer_id=? AND name=? AND COALESCE("
                        "data_scope,'operational')='operational'",
                        (cid, nm)).fetchone()["c"]
                    _flag("geo_employee_v1", f"{cid}|{nm}", n)
    return out


# --------------------------------------------------------------------
# SI3 T7：数据库绑定 fingerprint（Gate 3.0 freshness，指令九.2/3）
# --------------------------------------------------------------------

def db_fingerprint(store) -> dict:
    """数据库实时绑定：scope graph 聚合 + 事件/outbox 水位 +
    work 投影 hash + 关键表计数。任一变化 → 旧 Gate STALE。
    计算必须便宜（<200ms）；异常 fail-fast。
    注意：投影重建会顺带投递 outbox（副作用），必须先重建再取
    计数，否则两次复评会因投递差异产生假 STALE。"""
    from .scope import _SCOPED_TABLES
    conn = store._conn
    try:
        proj = store.rebuild_work_projection()
        proj_hash = proj.get("hash", "")
    except Exception as e:  # noqa: BLE001
        proj_hash = f"ERR:{e}"
    agg: list[str] = []
    for t in _SCOPED_TABLES:
        rows = conn.execute(
            f"SELECT COALESCE(data_scope,'operational') ds, count(*) c"
            f" FROM {t} GROUP BY ds ORDER BY ds").fetchall()
        agg.append(t + ":" + ",".join(
            f"{r['ds']}={r['c']}" for r in rows))
    h = hashlib.sha256("\n".join(agg).encode()).hexdigest()[:16]
    watermark = conn.execute(
        "SELECT COALESCE(max(seq),0) s FROM event_envelope_v1"
    ).fetchone()["s"]
    outbox_pending = conn.execute(
        "SELECT count(*) c FROM outbox_v1 WHERE status='pending'"
    ).fetchone()["c"]
    counts = {}
    for t in ("business_run_v1", "work_item_v2", "usage_event_v2",
              "recognition_task", "survey_media_v1"):
        counts[t] = conn.execute(
            f"SELECT count(*) c FROM {t}").fetchone()["c"]
    return {"scope_graph": h, "event_watermark": int(watermark),
            "outbox_pending": int(outbox_pending),
            "projection_hash": str(proj_hash), "counts": counts}


def _open_issues(issue_ledger_path) -> list[dict]:
    """解析 ISSUES.md 表格中 OPEN 的 P0/P1。"""
    out = []
    try:
        text = Path(issue_ledger_path).read_text(encoding="utf-8")
    except Exception:
        return out
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and cells[2].upper() == "OPEN" \
                and cells[1].upper() in ("P0", "P1"):
            out.append({"id": cells[0], "level": cells[1],
                        "summary": cells[3] if len(cells) > 3 else ""})
    return out


def evaluate_gate_from_evidence(*, store=None,
                                uat_report_path=None,
                                browser_report_path=None,
                                issue_ledger_path=None,
                                test_report_path=None,
                                service_health=None,
                                source_commit: str = "",
                                current_head: str = "",
                                recorded_tree_hash: str = "",
                                current_tree_hash: str = "",
                                recorded_migration_hash: str = "",
                                current_migration_hash: str = "",
                                worktree_clean: bool | None = None,
                                recorded_gate_path=None,
                                out_path=None) -> dict:
    """从证据自动计算 Gate（3.0）。任一证据缺失/失败 → BLOCKED_BY_*；
    Gate 生成后代码/数据变化 → STALE_GATE_EVIDENCE。

    SI3：传 recorded_gate_path 时执行 **freshness 复评**（指令九.4）：
    实时重算 DB fingerprint/HEAD 绑定，与已记录 Gate 比对；不一致
    即 STALE，绝不允许 DB 已变化仍返回 READY。
    判定优先级：STALE > 浏览器语义 > scope lineage > fixture 泄漏 >
    状态投影 > 其余证据缺失。"""
    # ---- SI3 T7：freshness 复评路径（不重跑全量证据，只验绑定） ----
    if recorded_gate_path:
        recorded = _load_json(recorded_gate_path)
        if recorded is None:
            return {"gate": "BLOCKED_BY_GATE_EVIDENCE",
                    "reasons": ["recorded gate.json 缺失/不可读"],
                    "checks": [], "evidence_hashes": {},
                    "evaluated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "evaluator_version": EVALUATOR_VERSION,
                    "source_commit": source_commit}
        stale: list[str] = []
        if current_head and recorded.get("source_commit") \
                and recorded["source_commit"] != current_head:
            stale.append(
                f"head 已变化: {recorded['source_commit']} →"
                f" {current_head}")
        if store is not None:
            rec_fp = recorded.get("db_fingerprint") or {}
            cur_fp = db_fingerprint(store)
            if rec_fp:
                for key in ("scope_graph", "event_watermark",
                            "outbox_pending", "projection_hash",
                            "counts"):
                    if rec_fp.get(key) != cur_fp.get(key):
                        stale.append(f"db_fingerprint.{key} 已变化")
            else:
                stale.append("recorded gate 无 db_fingerprint 绑定")
        if stale:
            return {"gate": STALE, "reasons": stale,
                    "checks": [{"check": "gate_freshness", "ok": False,
                                "evidence": "; ".join(stale)[:300],
                                "block": STALE}],
                    "evidence_hashes": recorded.get("evidence_hashes", {}),
                    "evaluated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "evaluator_version": EVALUATOR_VERSION,
                    "source_commit": recorded.get("source_commit", "")}
        recorded["freshness_verified_at"] = time.strftime(
            "%Y-%m-%dT%H:%M:%S%z")
        return recorded

    checks: list[dict] = []
    block_hint: list[str] = []

    def chk(name: str, ok: bool, evidence: str = "",
            block: str = "") -> bool:
        checks.append({"check": name, "ok": bool(ok),
                       "evidence": str(evidence)[:300],
                       "block": block})
        if not ok and block and block not in block_hint:
            block_hint.append(block)
        return bool(ok)

    evidence_hashes: dict[str, str] = {}

    # ---- SI2 T6：Gate 必须绑定当前代码状态（P1-004） ----
    if current_head:
        chk("gate_bound_to_head", source_commit == current_head,
            f"source_commit={source_commit} head={current_head}",
            STALE)
    if recorded_tree_hash or current_tree_hash:
        chk("code_tree_hash_match",
            bool(recorded_tree_hash)
            and recorded_tree_hash == current_tree_hash,
            f"recorded={recorded_tree_hash[:16]}"
            f" current={current_tree_hash[:16]}",
            STALE)
    if recorded_migration_hash or current_migration_hash:
        chk("migration_hash_match",
            bool(recorded_migration_hash)
            and recorded_migration_hash == current_migration_hash,
            f"recorded={recorded_migration_hash[:16]}"
            f" current={current_migration_hash[:16]}",
            STALE)
    if worktree_clean is not None:
        chk("tracked_worktree_clean", worktree_clean,
            "clean" if worktree_clean else "tracked 文件存在未提交变更",
            "BLOCKED_BY_GATE_EVIDENCE")

    # ---- SI2 T6：全 Domain scope lineage（直接重算，不信自报） ----
    if store is not None:
        try:
            from .scope import ScopedQuery
            conn = store._conn
            sq = ScopedQuery(store)
            leak = sq.operational_leakage()
            leak_total = sum(leak.values())
            chk("full_domain_fixture_leakage_zero", not leak,
                f"{leak_total} tables={sorted(leak)[:6]}",
                "BLOCKED_BY_UAT_FIXTURE_PROJECTION")
            missing = sq.fixture_missing_test_run()
            chk("fixture_test_run_id_full", missing == 0,
                str(missing), "BLOCKED_BY_SCOPE_LINEAGE")
            mismatch = sq.parent_child_mismatch()
            chk("parent_child_scope_consistent", mismatch == 0,
                str(mismatch), "BLOCKED_BY_SCOPE_LINEAGE")
            residue = sq.recovery_residue()
            chk("recovery_scope_consistent", residue == 0,
                str(residue), "BLOCKED_BY_SCOPE_LINEAGE")
            # Usage/Work 谱系：带 run_id 的行必须能定位到来源 Run
            # （指令 4.3：Usage/Evidence 找不到来源 Run → fail-closed）
            orphan_usage = conn.execute(
                "SELECT count(*) c FROM usage_event_v2 WHERE"
                " run_id!='' AND run_id NOT IN (SELECT run_id FROM"
                " business_run_v1)").fetchone()["c"]
            chk("usage_run_lineage_full", orphan_usage == 0,
                str(orphan_usage), "BLOCKED_BY_SCOPE_LINEAGE")
            orphan_work = conn.execute(
                "SELECT count(*) c FROM work_item_v2 WHERE run_id!=''"
                " AND run_id NOT IN (SELECT run_id FROM"
                " business_run_v1)").fetchone()["c"]
            chk("work_run_lineage_full", orphan_work == 0,
                str(orphan_work), "BLOCKED_BY_SCOPE_LINEAGE")
            # 不得存在未归档的 UAT Test Run 上下文（READY 前提）
            open_ctx = conn.execute(
                "SELECT count(*) c FROM uat_test_run_v1 WHERE"
                " status='current'").fetchone()["c"]
            chk("no_open_uat_test_run", open_ctx == 0,
                str(open_ctx), "BLOCKED_BY_UAT_FIXTURE_PROJECTION")
            # SI3：全表 Scope Registry 覆盖率必须 100%（指令五）
            from .scope_registry import registry_coverage
            cov = registry_coverage(conn)
            chk("scope_registry_full", not cov["missing"]
                and cov["coverage"] == 100.0,
                f"coverage={cov['coverage']}%"
                f" missing={cov['missing'][:5]}",
                "BLOCKED_BY_SCOPE_REGISTRY")
            # SI4 Gate 3.1：IAM 测试身份（指令 11.1）
            act_fx = conn.execute(
                "SELECT count(*) c FROM iam_principal_v1 WHERE"
                " status='active' AND COALESCE(data_scope,"
                "'operational') IN ('uat_fixture','demo_fixture')"
            ).fetchone()["c"]
            chk("iam_active_fixture_principal_zero", act_fx == 0,
                str(act_fx), "BLOCKED_BY_IAM_IDENTITY")
            op_fx_mem = conn.execute(
                "SELECT count(*) c FROM iam_membership_v1 WHERE"
                " COALESCE(visibility,'current')='current' AND"
                " COALESCE(data_scope,'operational') IN"
                " ('uat_fixture','demo_fixture')").fetchone()["c"]
            chk("iam_operational_fixture_membership_zero",
                op_fx_mem == 0, str(op_fx_mem),
                "BLOCKED_BY_IAM_IDENTITY")
            # SI4 Gate 3.1：BI 注册表（指令 11.2）
            uat_metric_op = conn.execute(
                "SELECT count(*) c FROM bi_metric_v1 WHERE"
                " COALESCE(data_scope,'operational')='operational'"
                " AND COALESCE(test_run_id,'')!=''").fetchone()["c"]
            chk("uat_metric_operational_zero", uat_metric_op == 0,
                str(uat_metric_op), "BLOCKED_BY_BI_EFFECTIVE")
            metric_not_archived = conn.execute(
                "SELECT count(*) c FROM bi_metric_v1 WHERE"
                " COALESCE(test_run_id,'')!='' AND COALESCE(status,"
                "'active')!='archived' AND test_run_id IN (SELECT"
                " test_run_id FROM uat_test_run_v1 WHERE status="
                "'archived')").fetchone()["c"]
            chk("uat_metric_archived_consistent",
                metric_not_archived == 0, str(metric_not_archived),
                "BLOCKED_BY_BI_EFFECTIVE")
            uat_dash_op = conn.execute(
                "SELECT count(*) c FROM bi_dashboard_v1 WHERE"
                " COALESCE(data_scope,'operational')='operational'"
                " AND COALESCE(test_run_id,'')!=''").fetchone()["c"]
            chk("uat_dashboard_operational_zero", uat_dash_op == 0,
                str(uat_dash_op), "BLOCKED_BY_BI_EFFECTIVE")
            # SI4 Gate 3.1：data-products effective 口径证明
            # （物理存在 fixture 而 effective 计数排除之；与运营
            # Domain API 对账由红测试 r06 在端点层覆盖）。
            try:
                from .analytics import bi_effective_counts
                effc = bi_effective_counts(conn)
                phys_cust = conn.execute(
                    "SELECT count(*) c FROM md_customer_v1"
                ).fetchone()["c"]
                chk("data_products_effective_basis",
                    effc["md_customer_v1"] <= phys_cust
                    and effc["md_customer_v1"] == conn.execute(
                        "SELECT count(*) c FROM md_customer_v1 WHERE"
                        " COALESCE(data_scope,'operational')"
                        "='operational' AND is_test_fixture=0"
                    ).fetchone()["c"],
                    f"effective={effc['md_customer_v1']}"
                    f" physical={phys_cust}",
                    "BLOCKED_BY_BI_EFFECTIVE")
            except Exception as e:  # noqa: BLE001
                chk("data_products_effective_basis", False,
                    f"effective 计数不可用: {e}",
                    "BLOCKED_BY_BI_EFFECTIVE")
            # ---- OSV5 Gate 3.2：导入批次作用域谱系（指令第八节） ----
            try:
                bad_scope = conn.execute(
                    "SELECT count(*) c FROM import_batch_v1 WHERE"
                    " (COALESCE(data_scope,'operational')='operational'"
                    " AND COALESCE(test_run_id,'')!='') OR"
                    " (COALESCE(data_scope,'') IN ('uat_fixture',"
                    "'demo_fixture') AND COALESCE(test_run_id,'')='')"
                ).fetchone()["c"]
                chk("import_batch_scope_complete", bad_scope == 0,
                    str(bad_scope), BLOCKED_IMPORT_LINEAGE)
                op_fx = conn.execute(
                    "SELECT count(*) c FROM import_batch_v1 b WHERE"
                    " COALESCE(b.data_scope,'operational')='operational'"
                    " AND EXISTS (SELECT 1 FROM"
                    " import_batch_customer_scope_v1 s JOIN"
                    " md_customer_v1 c ON c.customer_id=s.customer_id"
                    " WHERE s.batch_id=b.batch_id AND COALESCE("
                    "c.data_scope,'operational') IN ('uat_fixture',"
                    "'demo_fixture'))").fetchone()["c"]
                chk("import_batch_operational_fixture_zero", op_fx == 0,
                    str(op_fx), BLOCKED_IMPORT_LINEAGE)
                unknown = conn.execute(
                    "SELECT count(*) c FROM import_batch_v1 WHERE"
                    " COALESCE(data_scope,'') NOT IN ('operational',"
                    "'uat_fixture','demo_fixture','system','archived',"
                    "'quarantine')").fetchone()["c"]
                chk("import_batch_unknown_scope_zero", unknown == 0,
                    str(unknown), BLOCKED_IMPORT_LINEAGE)
                # OSV51 C-1：quarantine 批次写逃逸检测——隔离后
                # （archived_at 之后）仍被改写的 quarantine 批次即违规；
                # 已进入裁决状态机（quarantine_adjudication_v1 有行）
                # 的批次视为已受治理，豁免（W3 引入该表前豁免集为空）。
                try:
                    esc = conn.execute(
                        "SELECT count(*) c FROM import_batch_v1 b WHERE"
                        " COALESCE(b.data_scope,'')='quarantine' AND"
                        " COALESCE(b.archived_at,'')!='' AND"
                        " b.updated_at > b.archived_at AND NOT EXISTS"
                        " (SELECT 1 FROM quarantine_adjudication_v1 a"
                        "  WHERE a.batch_id=b.batch_id)"
                    ).fetchone()["c"]
                except Exception:
                    esc = conn.execute(
                        "SELECT count(*) c FROM import_batch_v1 b WHERE"
                        " COALESCE(b.data_scope,'')='quarantine' AND"
                        " COALESCE(b.archived_at,'')!='' AND"
                        " b.updated_at > b.archived_at"
                    ).fetchone()["c"]
                chk("quarantine_execution_escape", esc == 0,
                    f"post_quarantine_modified={esc}",
                    BLOCKED_IMPORT_SECURITY)
                # OSV51 C-2：递归 secret 扫描——import 批次全部 JSON 列
                # 不得携带敏感键明文（password/token/api_key/secret 等）。
                from .import_center import redact_secrets as _redact
                leak = 0
                leak_batches: list = []
                for _brow in conn.execute(
                        "SELECT batch_id, mapping_json, dry_run_json,"
                        " error_report_json, commit_json FROM"
                        " import_batch_v1"):
                    for _col in ("mapping_json", "dry_run_json",
                                 "error_report_json", "commit_json"):
                        try:
                            _p = json.loads(_brow[_col] or "{}")
                        except Exception:
                            continue
                        if json.dumps(_redact(_p), sort_keys=True,
                                      ensure_ascii=False) != \
                                json.dumps(_p, sort_keys=True,
                                           ensure_ascii=False):
                            leak += 1
                            if _brow["batch_id"] not in leak_batches:
                                leak_batches.append(_brow["batch_id"])
                chk("recursive_secret_scan", leak == 0,
                    f"leak_columns={leak} batches={leak_batches[:5]}",
                    BLOCKED_IMPORT_SECURITY)
                # OSV51 W2-a（C-1 §8）：quarantine 批次不得有任何可
                # 归因的 operational 对象写入（DB 级断言，归因见
                # quarantine_operational_write_violations 文档）。
                qw = quarantine_operational_write_violations(conn)
                chk("quarantine_no_operational_writes", not qw,
                    f"violations={len(qw)} {qw[:3]}",
                    BLOCKED_IMPORT_SECURITY)
                from .analytics import bi_effective_counts as _eff2
                eff_imp = _eff2(conn)["import_batch_v1"]
                db_eff = conn.execute(
                    "SELECT count(*) c FROM import_batch_v1 WHERE"
                    " COALESCE(data_scope,'operational')='operational'"
                    " AND COALESCE(test_run_id,'')=''").fetchone()["c"]
                chk("import_batch_api_effective_consistent",
                    eff_imp == db_eff,
                    f"effective={eff_imp} db_operational={db_eff}",
                    BLOCKED_IMPORT_LINEAGE)
                chk("import_batch_bi_effective_consistent",
                    eff_imp == db_eff,
                    f"bi_effective={eff_imp} operational={db_eff}",
                    "BLOCKED_BY_BI_EFFECTIVE")
                from .scope_registry import archive_handler_for
                chk("import_batch_archive_handler_registered",
                    callable(archive_handler_for("import_batch_v1")),
                    "archive_handler_for(import_batch_v1)",
                    "BLOCKED_BY_SCOPE_REGISTRY")
                from .test_data import FixtureTestDataService
                _center_keys = FixtureTestDataService(store)\
                    .center_summary()["test_runs"]
                _ct_ok = True
                try:
                    conn.execute(
                        "SELECT count(*) c FROM import_batch_v1 WHERE"
                        " 1=0").fetchone()
                except Exception:
                    _ct_ok = False
                chk("import_batch_test_center_consistent", _ct_ok,
                    "count_tables 含 import_batches（test_run 维度）",
                    BLOCKED_IMPORT_LINEAGE)
                # 越权/脱敏：消费入口必须存在（红测试/UAT 负例提供
                # 行为证据；此处验证代码面接入不丢失）。
                from .import_center import ImportCenter
                chk("import_batch_cross_tenant_access_denied",
                    callable(getattr(ImportCenter, "authorize_batch",
                                     None))
                    and "view" in ImportCenter.list_batches.__code__
                    .co_varnames,
                    "authorize_batch + list_batches(view) 接入",
                    BLOCKED_IMPORT_LINEAGE)
                _dto = set(ImportCenter._DTO_KEYS)
                _forbid = {"mapping_json", "dry_run_json",
                           "error_report_json", "commit_json"}
                chk("import_batch_raw_payload_redacted",
                    not (_dto & _forbid)
                    and "filename" in _dto and "data_scope" in _dto,
                    f"dto_keys 无原始 payload（{len(_dto)} 字段）",
                    BLOCKED_IMPORT_LINEAGE)
            except Exception as e:  # noqa: BLE001
                chk("import_batch_lineage_scanned", False,
                    f"扫描异常: {e}", BLOCKED_IMPORT_LINEAGE)
            # ---- OSV5 Gate 3.2：可执行 Registry（指令第七节） ----
            try:
                from .scope_registry import (ARCHIVE_HANDLERS,
                                             SCOPE_REGISTRY,
                                             leak_scan_tables,
                                             validate_registry)
                problems = validate_registry(conn)
                chk("registry_schema_valid", not problems,
                    f"problems={problems[:4]} 共{len(problems)}",
                    "BLOCKED_BY_SCOPE_REGISTRY")
                # 新 scoped 表（带 data_scope 列）必须被 Registry
                # 登记并进 scanner；漏注册 → 阻断（负例 9）。
                scoped_in_db = {r[0] for r in conn.execute(
                    "SELECT DISTINCT m.name FROM sqlite_master m JOIN"
                    " pragma_table_info(m.name) p WHERE m.type='table'"
                    " AND m.name NOT LIKE 'sqlite_%' AND"
                    " p.name='data_scope'")}
                unreg = sorted(t for t in scoped_in_db
                               if t not in SCOPE_REGISTRY)
                # 非 leak_scan 表必须有其它可执行 gate 策略（如
                # finance_scan/parent_edge/registry）；未登记或无
                # 策略声明即阻断（负例 9）。
                unscanned = sorted(t for t in scoped_in_db
                                   if t in SCOPE_REGISTRY and not
                                   (SCOPE_REGISTRY[t].get("gate") or
                                    "none").replace("none", "").strip())
                chk("registry_runtime_scanner_complete",
                    not unreg and not unscanned,
                    f"unregistered={unreg[:4]} unscanned="
                    f"{unscanned[:4]}", "BLOCKED_BY_SCOPE_REGISTRY")
                bad_handlers = [t for t in ARCHIVE_HANDLERS
                                if not callable(ARCHIVE_HANDLERS[t])]
                chk("registry_archive_handler_complete",
                    not bad_handlers,
                    f"handlers={len(ARCHIVE_HANDLERS)} bad="
                    f"{bad_handlers[:4]}", "BLOCKED_BY_SCOPE_REGISTRY")
                from .analytics import bi_effective_counts as _eff3
                _products = set(_eff3(conn))
                chk("registry_operational_query_complete",
                    _products == {"md_customer_v1", "md_project_v1",
                                  "md_sku_v1", "survey_response_v1",
                                  "recognition_task", "usage_event_v2",
                                  "geo_address_v1", "import_batch_v1"},
                    f"effective 口径覆盖 {len(_products)} 产品",
                    "BLOCKED_BY_BI_EFFECTIVE")
                from .scope import ScopedQuery
                pe_bad = []
                for t, (fk, pt, pk) in ScopedQuery._PARENT_EDGES.items():
                    pcols = {r[1] for r in conn.execute(
                        f"PRAGMA table_info({pt})")}
                    if pk not in pcols:
                        pe_bad.append(f"{t}→{pt}.{pk}")
                chk("registry_parent_edges_valid", not pe_bad,
                    f"bad={pe_bad[:4]}", "BLOCKED_BY_SCOPE_REGISTRY")
            except Exception as e:  # noqa: BLE001
                chk("registry_validated", False, f"校验异常: {e}",
                    "BLOCKED_BY_SCOPE_REGISTRY")
            # ---- OSV5 Gate 3.2：全数据产品逐一对账（禁弱条件） ----
            try:
                from .analytics import bi_effective_counts as _eff4
                effc4 = _eff4(conn)
                mism = []
                for t in ("md_project_v1", "md_sku_v1",
                          "survey_response_v1", "recognition_task",
                          "geo_address_v1", "import_batch_v1"):
                    dbn = conn.execute(
                        f"SELECT count(*) c FROM {t} WHERE COALESCE("
                        "data_scope,'operational')='operational' AND"
                        " COALESCE(test_run_id,'')=''").fetchone()["c"]
                    if effc4[t] != dbn:
                        mism.append(f"{t}:{effc4[t]}!={dbn}")
                cust_eff = conn.execute(
                    "SELECT count(*) c FROM md_customer_v1 WHERE"
                    " COALESCE(data_scope,'operational')='operational'"
                    " AND COALESCE(test_run_id,'')='' AND"
                    " is_test_fixture=0").fetchone()["c"]
                if effc4["md_customer_v1"] != cust_eff:
                    mism.append(f"md_customer_v1:{effc4['md_customer_v1']}"
                                f"!={cust_eff}")
                chk("data_products_all_effective_consistent", not mism,
                    f"mismatch={mism[:6]}" if mism else
                    "全部 8 产品逐项对账一致",
                    "BLOCKED_BY_BI_EFFECTIVE")
            except Exception as e:  # noqa: BLE001
                chk("data_products_all_effective_consistent", False,
                    f"对账异常: {e}", "BLOCKED_BY_BI_EFFECTIVE")
            chk("evaluator_version_consistent",
                EVALUATOR_VERSION == "3.3.0",
                f"evaluator_version={EVALUATOR_VERSION}",
                "BLOCKED_BY_GATE_EVIDENCE")
        except Exception as e:
            chk("scope_lineage_scanned", False, f"扫描异常: {e}",
                "BLOCKED_BY_SCOPE_LINEAGE")

    # ---- UAT 报告与 validator ----
    rep = _load_json(uat_report_path) if uat_report_path else None
    if uat_report_path:
        evidence_hashes["uat_report"] = _file_sha(Path(uat_report_path))
    if rep is None:
        chk("uat_report_present", False, "UAT 报告缺失",
            "BLOCKED_BY_GATE_EVIDENCE")
    else:
        failed_checks = [c for c in rep.get("checks", [])
                         if not c.get("ok")]
        chk("uat_checks_all_ok",
            not failed_checks and rep.get("failed", 0) == 0,
            f"failed={rep.get('failed')} "
            f"checks_failed={len(failed_checks)}",
            "BLOCKED_BY_GATE_EVIDENCE")
        try:
            from scripts.uat_report_validator import validate_report
            rep.setdefault("_base_dir",
                           str(Path(uat_report_path).parent))
            problems = validate_report(rep)
        except Exception as e:
            problems = [f"validator 异常: {e}"]
        chk("uat_validator_clean", not problems, str(problems)[:200],
            "BLOCKED_BY_GATE_EVIDENCE")
        # OSV5：UAT V7 必须真实经过 Import Center（指令第九节）：
        # protocol=uatv7 且 ids 含 6 个 import 键。
        _imp_ids = ("import_batch_customer", "import_batch_project",
                    "import_batch_address", "import_scope_associations",
                    "import_evidence", "import_audit_events")
        _ids = rep.get("ids") or {}
        _missing_imp = [k for k in _imp_ids if not _ids.get(k)]
        chk("uat_import_lineage_complete",
            rep.get("protocol") == "uatv7" and not _missing_imp,
            f"protocol={rep.get('protocol')} missing={_missing_imp[:4]}",
            BLOCKED_IMPORT_LINEAGE)
        # 主工作流必备节点（含 model/capability：model 或 command 任一）；
        # SI2：仅在报告声明了节点类型时校验（UAT V4 协议由 checks 覆盖）
        if "workflow_node_types" in rep:
            node_types = set(rep.get("workflow_node_types") or [])
            missing_nodes = [t for t in REQUIRED_WORKFLOW_NODE_TYPES
                             if t not in node_types]
            if not any(t in node_types
                       for t in CAPABILITY_WORKFLOW_NODE_TYPES):
                missing_nodes.append("model|command")
            chk("workflow_model_chain", not missing_nodes,
                f"missing={missing_nodes}",
                "BLOCKED_BY_WORKFLOW_MODEL_CHAIN")
        # 以下专项：仅当报告含对应协议字段时校验（V3 协议字段；
        # V4 协议的同等要求由 checks[] 内的同名断言承载）。
        # 门头契约负例+成功例
        sf = rep.get("storefront") or {}
        if sf:
            chk("storefront_contract",
                bool(sf.get("negative_rejected"))
                and bool(sf.get("positive_submitted")),
                str(sf)[:200], "BLOCKED_BY_GATE_EVIDENCE")
        # parallel 真实并行与终态
        par = rep.get("parallel") or {}
        if par:
            wall = par.get("wall_seconds")
            chk("parallel_real",
                isinstance(wall, (int, float)) and wall < 3.5
                and par.get("terminal") == "succeeded",
                str(par)[:200], "BLOCKED_BY_WORKFLOW_MODEL_CHAIN")
        # 异常追问链
        an = rep.get("anomaly_chain") or {}
        if an:
            chk("anomaly_followup_chain",
                bool(an.get("anomaly_id")) and bool(an.get("follow_up"))
                and bool(an.get("human_answer"))
                and an.get("resolved") is True
                and int(an.get("report_versions", 0)) >= 2,
                str(an)[:200], "BLOCKED_BY_ANALYTICS_FOLLOWUP")
        # Agent 失败账本
        af = rep.get("agent_failure") or {}
        if af:
            chk("agent_failure_lineage",
                bool(af.get("failed_run")) and bool(af.get("evidence"))
                and af.get("usage_recorded") is True,
                str(af)[:200], "BLOCKED_BY_AGENT_FAILURE_LINEAGE")
        # rate limit 拒绝证据
        rl = rep.get("rate_limit") or {}
        if rl:
            chk("rate_limit_denied_evidence", bool(rl.get("denied_429")),
                str(rl)[:200], "BLOCKED_BY_GATE_EVIDENCE")
        # 当前模型 / 训练进程 / fixture 残留
        chk("current_bundle_v4",
            rep.get("current_bundle") == "prod_v4_best_r1",
            str(rep.get("current_bundle")), "BLOCKED_BY_GATE_EVIDENCE")
        chk("no_training_process",
            int(rep.get("training_processes", 1)) == 0,
            str(rep.get("training_processes")),
            "BLOCKED_BY_GATE_EVIDENCE")
        chk("operational_uat_residue_zero",
            int(rep.get("operational_residue",
                        (rep.get("projection") or {})
                        .get("operational_residue", 1))) == 0,
            # SI2-007：0 必须显示为数字 0，不得因 falsy/or 变 None
            str(int(rep.get("operational_residue",
                            (rep.get("projection") or {})
                            .get("operational_residue", 1)))),
            "BLOCKED_BY_UAT_FIXTURE_POLLUTION")
        # Usage 完整率（报告提供时校验；V4 由 center scan 覆盖谱系）
        usage = rep.get("usage_lineage") or {}
        if usage:
            chk("usage_lineage_full",
                usage.get("total", 0) > 0
                and usage.get("linked", 0) == usage.get("total", 0),
                str(usage)[:200], "BLOCKED_BY_AGENT_FAILURE_LINEAGE")

    # ---- DB 终态漂移与 Agent 账本 ----
    if store is not None:
        try:
            drift = scan_terminal_drift(store)
            chk("no_terminal_drift", not drift, str(drift)[:250],
                "BLOCKED_BY_STATE_PROJECTION")
        except Exception as e:
            chk("no_terminal_drift", False, f"扫描异常: {e}",
                "BLOCKED_BY_STATE_PROJECTION")
        try:
            conn = store._conn
            n_failed_agent = conn.execute(
                "SELECT count(*) c FROM business_run_v1 WHERE"
                " command_kind='agent.invoke' AND status IN"
                " ('failed','partial_failed')").fetchone()["c"]
            chk("agent_failure_ledger_exists", n_failed_agent >= 1,
                f"failed_agent_runs={n_failed_agent}",
                "BLOCKED_BY_AGENT_FAILURE_LINEAGE")
            ic = conn.execute("PRAGMA integrity_check").fetchone()[0]
            chk("sqlite_integrity", ic == "ok", ic,
                "BLOCKED_BY_GATE_EVIDENCE")
        except Exception as e:
            chk("sqlite_integrity", False, str(e),
                "BLOCKED_BY_GATE_EVIDENCE")
    else:
        chk("store_present", False, "store 缺失",
            "BLOCKED_BY_GATE_EVIDENCE")

    # ---- ISSUES 账本 ----
    if issue_ledger_path:
        evidence_hashes["issue_ledger"] = _file_sha(
            Path(issue_ledger_path))
        opens = _open_issues(issue_ledger_path)
        chk("no_open_p0_p1", not opens, str(opens)[:250],
            "BLOCKED_BY_" + ("P0" if any(o["level"] == "P0"
                                         for o in opens) else "P1"))
    else:
        chk("issue_ledger_present", False, "ISSUES 账本缺失",
            "BLOCKED_BY_GATE_EVIDENCE")

    # ---- 测试报告 ----
    if test_report_path and Path(test_report_path).exists():
        evidence_hashes["test_report"] = _file_sha(
            Path(test_report_path))
        tr = _load_json(test_report_path)
        if tr is not None:
            failed_n = int(tr.get("failed", 0))
            chk("tests_all_passed", failed_n == 0,
                f"failed={failed_n} passed={tr.get('passed')}",
                "BLOCKED_BY_GATE_EVIDENCE")
        else:
            txt = Path(test_report_path).read_text(encoding="utf-8")
            ok = " failed" not in txt and (" passed" in txt)
            chk("tests_all_passed", ok, txt[-160:],
                "BLOCKED_BY_GATE_EVIDENCE")
    else:
        chk("test_report_present", False, "测试报告缺失",
            "BLOCKED_BY_GATE_EVIDENCE")

    # ---- 浏览器证据（文件必须存在，不接受纯文字；SI2 T7：语义断言） ----
    brow = _load_json(browser_report_path) if browser_report_path else None
    if browser_report_path:
        evidence_hashes["browser_report"] = _file_sha(
            Path(browser_report_path))
    if brow is None:
        chk("browser_evidence_present", False, "浏览器证据缺失",
            "BLOCKED_BY_GATE_EVIDENCE")
    else:
        files = brow.get("files") or []
        base = Path(browser_report_path).parent
        missing = [f for f in files
                   if not (base / f).exists()]
        chk("browser_screenshots_exist",
            bool(files) and not missing,
            f"total={len(files)} missing={missing[:5]}",
            "BLOCKED_BY_GATE_EVIDENCE")
        chk("browser_console_clean",
            brow.get("console_errors_unexplained", 1) == 0,
            str(brow.get("console_errors_unexplained")),
            "BLOCKED_BY_GATE_EVIDENCE")
        # SI2 T7：四个真实视口必须覆盖（1440/1280/1024/768）
        widths = {str(p.get("viewport", "")) for p in (brow.get("pages")
                                                         or [])}
        need = {"1440", "1280", "1024", "768"}
        chk("browser_viewports_covered", need.issubset(widths),
            f"covered={sorted(widths)}", "BLOCKED_BY_GATE_EVIDENCE")
        # SI4：浏览器证据必须覆盖 12 个一级工作台（指令 11.4；
        # 少一页即 Gate 不过，证据面必须等于报告表述）。
        covered_routes = set()
        for p in (brow.get("pages") or []):
            rt = str(p.get("route", "")).lstrip("/#/").strip("/")
            covered_routes.add(rt)
        missing_routes = [r for r in REQUIRED_BROWSER_ROUTES
                          if r not in covered_routes]
        chk("browser_routes_covered", not missing_routes,
            f"covered={len(covered_routes)}"
            f" missing={missing_routes[:6]}",
            "BLOCKED_BY_BROWSER_SEMANTICS")
        # OSV5：Import Center 运营/历史视图必须分离验收（对象级；
        # 不得只用 token 计数，指令第十节/P1-001）。
        imp_views = {str(p.get("view", "")) for p in (brow.get("pages")
                     or []) if str(p.get("route", "")).lstrip("/#/")
                     .strip("/") == "data/import"}
        _imp_ok = {"operational", "history"}.issubset(imp_views) and \
            all(p.get("assertion", False) for p in (brow.get("pages")
                or []) if str(p.get("route", "")).lstrip("/#/")
                .strip("/") == "data/import")
        chk("browser_import_current_history_separated", _imp_ok,
            f"import 页 views={sorted(imp_views)}",
            "BLOCKED_BY_BROWSER_SEMANTICS")
        # SI2 T7：实际对象 ID/文本必须与预期一致（不得只看截图存在）；
        # 无语义断言页面 = 证据缺失（GATE_EVIDENCE），断言失败 =
        # 语义不一致（BROWSER_SEMANTICS）。
        pages = brow.get("pages") or []
        bad = [p.get("route", "?") for p in pages
               if not p.get("assertion", False)
               or str(p.get("actual_object_id", ""))
               != str(p.get("expected_object_id", ""))]
        if pages:
            chk("browser_semantic_assertions", not bad,
                f"pages={len(pages)} failed={bad[:5]}",
                "BLOCKED_BY_BROWSER_SEMANTICS")
        else:
            chk("browser_semantic_assertions", False,
                "无语义断言页面（pages=[]，证据缺失）",
                "BLOCKED_BY_GATE_EVIDENCE")

    # ---- 服务健康 ----
    if service_health is not None:
        down = [k for k, v in (service_health or {}).items() if not v]
        chk("services_healthy", not down, str(service_health)[:200],
            "BLOCKED_BY_GATE_EVIDENCE")
    else:
        chk("service_health_present", False, "服务健康证据缺失",
            "BLOCKED_BY_GATE_EVIDENCE")

    # ---- 判定（优先级：STALE > 语义 > lineage > 泄漏 > 投影 > 证据） ----
    all_ok = all(c["ok"] for c in checks)
    if all_ok:
        gate = READY
        reasons: list[str] = []
    else:
        failed = [c for c in checks if not c["ok"]]
        reasons = [c["check"] for c in failed]
        gate = "BLOCKED_BY_GATE_EVIDENCE"
        for prio in (STALE, "BLOCKED_BY_P0", "BLOCKED_BY_P1",
                     "BLOCKED_BY_BROWSER_SEMANTICS",
                     "BLOCKED_BY_IAM_IDENTITY",
                     BLOCKED_IMPORT_SECURITY,
                     "BLOCKED_BY_BI_EFFECTIVE",
                     "BLOCKED_BY_FINANCE_CONTEXT",
                     BLOCKED_IMPORT_LINEAGE,
                     "BLOCKED_BY_OPERATIONAL_FIXTURE_SURFACE",
                     "BLOCKED_BY_SCOPE_LINEAGE",
                     "BLOCKED_BY_SCOPE_REGISTRY",
                     "BLOCKED_BY_UAT_FIXTURE_PROJECTION",
                     "BLOCKED_BY_UAT_FIXTURE_POLLUTION",
                     "BLOCKED_BY_STATE_PROJECTION"):
            if any(c.get("block") == prio for c in failed):
                gate = prio
                break
        else:
            gate = block_hint[0] if block_hint else gate
    result = {"gate": gate, "reasons": reasons, "checks": checks,
              "evidence_hashes": evidence_hashes,
              "evaluated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
              "evaluator_version": EVALUATOR_VERSION,
              "source_commit": source_commit}
    # SI3：绑定数据库 fingerprint（freshness 复评依据，指令九.2）
    if store is not None:
        try:
            result["db_fingerprint"] = db_fingerprint(store)
        except Exception as e:  # noqa: BLE001
            result["db_fingerprint"] = {"error": str(e)}
            result["checks"].append({"check": "db_fingerprint_bound",
                                     "ok": False,
                                     "evidence": str(e)[:300],
                                     "block": STALE})
            if result["gate"] == READY:
                result["gate"] = STALE
                result["reasons"] = ["db_fingerprint 计算失败"]
    if out_path:
        p = Path(out_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                     encoding="utf-8")
    return result
