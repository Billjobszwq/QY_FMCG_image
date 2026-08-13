#!/usr/bin/env python3
"""SI4 T0：独立只读审计器（Operational Scope V4）。

复现独立 QA 报告的 P0/P1（不得直接相信旧 READY）：
- P0-001 IAM：active UAT principal/membership/登录面
- P0-002 BI：data-products 物理计数 vs effective operational
- P0-003 BI：UAT metric 注册表污染
- P1-001/002：BI/Finance 前端测试客户默认值（源码静态检查）
- P1-005：Gate stale（HEAD vs 记录）

只读连接（mode=ro）。输出 .eval/scope_v4/before_audit.json。
"""
from __future__ import annotations

import json
import re
import sqlite3
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / ".platform" / "platform.sqlite"
OUT = ROOT / ".eval" / "scope_v4" / "audit_latest.json"
UAT_GLOB = ("uatv2_%", "uatv3_%", "uatv4_%", "uatv5_%", "uat_%",
            "uat-%", "demo-%")


def _c(conn, sql) -> int:
    return conn.execute(sql).fetchone()[0]


def _uat_cond(col: str) -> str:
    """UAT/demo 前缀条件（一次性审计专用；运行时禁止名称判断）。"""
    return " OR ".join(f"lower({col}) LIKE '{g}'" for g in UAT_GLOB)


def main() -> None:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    out: dict = {}

    # ---------- P0-001 IAM ----------
    out["iam_uat_principals_active"] = _c(conn, f"""
        SELECT count(*) FROM iam_principal_v1 WHERE status='active'
          AND ({_uat_cond('username')})""")
    out["iam_uat_principals_total"] = _c(conn, f"""
        SELECT count(*) FROM iam_principal_v1
          WHERE ({_uat_cond('username')})""")
    out["iam_uat_memberships"] = _c(conn, f"""
        SELECT count(*) FROM iam_membership_v1 m JOIN iam_principal_v1 p
          ON p.principal_id=m.principal_id
          WHERE COALESCE(m.visibility,'current')='current'
            AND ({_uat_cond('p.username')})""")
    out["iam_uat_memberships_with_customer_grant"] = _c(conn, f"""
        SELECT count(*) FROM iam_membership_v1 m JOIN iam_principal_v1 p
          ON p.principal_id=m.principal_id
          WHERE COALESCE(m.customer_id,'')!=''
            AND ({_uat_cond('p.username')})""")
    out["iam_uat_active_roles"] = [
        dict(r) for r in conn.execute(f"""
        SELECT m.role_id, count(*) n FROM iam_membership_v1 m
          JOIN iam_principal_v1 p ON p.principal_id=m.principal_id
          WHERE p.status='active' AND ({_uat_cond('p.username')})
          GROUP BY m.role_id ORDER BY n DESC""").fetchall()]
    out["iam_uat_active_sessions"] = _c(conn, f"""
        SELECT count(*) FROM auth_sessions s
          WHERE ({_uat_cond('s.actor')})""")
    # UAT V5 最新五个角色账号状态
    out["iam_uatv5_role_users"] = [
        dict(r) for r in conn.execute("""
        SELECT username, status FROM iam_principal_v1
          WHERE lower(username) LIKE 'uatv5_%'
          ORDER BY created_at DESC LIMIT 8""").fetchall()]

    # ---------- P0-002 BI data-products（物理 vs effective） ----------
    OP_CUST = ("COALESCE(data_scope,'operational')='operational'"
               " AND is_test_fixture=0")
    def _cols(t):
        return {r[1] for r in conn.execute(
            f"PRAGMA table_info({t})")}

    def op(t):
        cond = "COALESCE(data_scope,'operational')='operational'"
        if "test_run_id" in _cols(t):
            cond += " AND COALESCE(test_run_id,'')=''"
        return _c(conn, f"SELECT count(*) FROM {t} WHERE {cond}")
    out["bi_dp_physical_vs_effective"] = {
        "md_customer_v1": {
            "physical": _c(conn, "SELECT count(*) FROM md_customer_v1"),
            "effective_operational": _c(conn,
                                        f"SELECT count(*) FROM"
                                        f" md_customer_v1 WHERE {OP_CUST}")},
        "md_project_v1": {
            "physical": _c(conn, "SELECT count(*) FROM md_project_v1"),
            "effective_operational": op("md_project_v1")},
        "md_sku_v1": {
            "physical": _c(conn, "SELECT count(*) FROM md_sku_v1"),
            "effective_operational": op("md_sku_v1")},
        "survey_response_v1": {
            "physical": _c(conn,
                           "SELECT count(*) FROM survey_response_v1"),
            "effective_operational": op("survey_response_v1")},
        "recognition_task": {
            "physical": _c(conn, "SELECT count(*) FROM recognition_task"),
            "effective_operational": op("recognition_task")},
        "usage_event_v2": {
            "physical": _c(conn, "SELECT count(*) FROM usage_event_v2"),
            "effective_operational_note": "attribution+父链口径，见"
                                          " usage_api _EFFECTIVE_OP"},
        "geo_address_v1": {
            "physical": _c(conn, "SELECT count(*) FROM geo_address_v1"),
            "effective_operational": op("geo_address_v1")},
        "import_batch_v1": {
            "physical": _c(conn, "SELECT count(*) FROM import_batch_v1"),
            # OSV5-012 修正：迁移 058/059 后 import_batch_v1 已具备
            # data_scope/test_run_id/visibility 列；全链审计改用
            # scripts/scope_audit_v5.py（列/创建/scanner/archiver/
            # API/Gate/Registry 七维）。此处仅保留历史口径存档。
            "effective_operational_note": "见 scope_audit_v5.py"},
    }

    # ---------- P0-003 BI metric 污染 ----------
    out["bi_metrics_total"] = _c(conn, "SELECT count(*) FROM bi_metric_v1")
    out["bi_metric_has_scope_cols"] = (
        "data_scope" in _cols("bi_metric_v1"))
    rows = conn.execute("SELECT metric_id, name, scope FROM"
                        " bi_metric_v1 WHERE COALESCE(data_scope,"
                        "'operational')='operational' AND COALESCE("
                        "status,'active')!='archived'").fetchall()
    uat_names = re.compile(r"uat|测试|预演", re.I)
    out["bi_metrics_uat_suspect"] = [
        dict(r) for r in rows
        if uat_names.search((r["metric_id"] or "") + "|"
                            + (r["name"] or ""))]
    out["bi_dashboards_total"] = _c(conn,
                                    "SELECT count(*) FROM bi_dashboard_v1")
    dash_cols = _cols("bi_dashboard_v1")
    out["bi_dashboard_has_scope_cols"] = ("data_scope" in dash_cols
                                          and "test_run_id" in dash_cols)
    if out["bi_dashboard_has_scope_cols"]:
        out["bi_dashboards_effective_fixture"] = _c(conn, """
            SELECT count(*) FROM bi_dashboard_v1 WHERE data_scope IN
              ('uat_fixture','demo_fixture') OR COALESCE(test_run_id,'')
              !=''""")
    else:
        # 无 scope 列：无法结构性隔离（本身即缺陷，登记为发现）
        out["bi_dashboards_effective_fixture"] = "NO_SCOPE_COLS"
    out["bi_report_specs_operational_uat_name"] = _c(conn, """
        SELECT count(*) FROM bi_report_spec_v1 WHERE
          COALESCE(data_scope,'operational')='operational' AND
          (name LIKE '%uat%' OR name LIKE '%UAT%')""")

    # ---------- P1-001/002 前端测试默认值（静态源码） ----------
    fe_hits: list[dict] = []
    pat = re.compile(r"uat-cust-[ab]|demo-cust-[ab]|uat_cust|demo_cust")
    for p in (ROOT / "web" / "src").rglob("*"):
        if p.is_file() and p.suffix in (".tsx", ".ts", ".css"):
            try:
                txt = p.read_text(encoding="utf-8")
            except Exception:
                continue
            for i, line in enumerate(txt.splitlines(), 1):
                if pat.search(line):
                    fe_hits.append({"file": str(p.relative_to(ROOT)),
                                    "line": i,
                                    "text": line.strip()[:120]})
    out["frontend_fixture_defaults"] = fe_hits

    # ---------- P1-005 Gate stale ----------
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"],
                              cwd=str(ROOT), capture_output=True,
                              text=True, timeout=5).stdout.strip()
    except Exception:
        head = ""
    gate_src = ""
    gp = ROOT / ".eval" / "scope_v3" / "gate.json"
    if gp.exists():
        try:
            gate_src = json.loads(gp.read_text()).get(
                "source_commit", "")
        except Exception:
            pass
    out["head"] = head
    out["gate_recorded_commit"] = gate_src
    out["gate_stale"] = bool(gate_src) and gate_src != head

    # ---------- 其他：UAT 残留面 ----------
    out["anomalies_total"] = _c(conn, "SELECT count(*) FROM bi_anomaly_v1")
    out["anomalies_operational"] = _c(conn, """
        SELECT count(*) FROM bi_anomaly_v1 WHERE
          COALESCE(data_scope,'operational')='operational'""")
    out["integrity"] = conn.execute(
        "PRAGMA integrity_check").fetchone()[0]
    conn.close()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in out.items()
                      if k != "bi_dp_physical_vs_effective"},
                     ensure_ascii=False, indent=2)[:2500])
    print(json.dumps(out["bi_dp_physical_vs_effective"],
                     ensure_ascii=False, indent=2))
    print("\n[saved]", OUT)


if __name__ == "__main__":
    main()
