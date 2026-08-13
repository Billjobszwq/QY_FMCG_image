"""OSV51 C-1 红测试：quarantine 批次写逃逸必须被服务层不可绕过地阻断。

对应 01-ROOT-CAUSES-AND-CONTRACTS.md C-1 与 02-IMPORT-SECURITY.md。
先于修复存在（红）：任何 data_scope=quarantine 批次不得执行 commit、
重放、dry-run（会覆写原证据），不得创建 operational 对象；API 必须
返回 409 与稳定错误码 IMPORT_BATCH_WRITE_BLOCKED；并发、直接调用
service、伪造参数、重启后重试均不得绕过。14 个模板参数化。
"""
from __future__ import annotations

import io
import json
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.composition.build import (build_production_bundle,
                                   build_profiles_service)
from src.platform.api.app import create_app
from src.platform.field_ops import FieldOpsService
from src.platform.finance import FinanceService
from src.platform.iam import IAMService, MasterDataService
from src.platform.import_center import (TEMPLATES, ImportCenter,
                                        ImportError_)
from src.platform.survey import SurveyService
from src.platform.test_data import FixtureTestDataService

ROOT = Path(__file__).resolve().parents[2]
PW = "osv51-admin-pw"
NS = "uatv7_osv51_guard"
CODE = "IMPORT_BATCH_WRITE_BLOCKED"
ALL_TEMPLATES = sorted(TEMPLATES.keys())
assert len(ALL_TEMPLATES) == 14, ALL_TEMPLATES


class _OkRecognition:
    def recognize(self, data, conf=0.25):
        return {"count": 0, "products": []}


@pytest.fixture()
def env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD", PW)
    bundle = build_production_bundle(
        db_path=tmp_path / "p.sqlite", cas_root=tmp_path / "cas",
        recognition_adapter=_OkRecognition(), probe=lambda spec: None)
    profiles = build_profiles_service(bundle)
    store = bundle.store
    app = create_app(services=(), probe=lambda spec: None,
                     bundle=bundle, recognition_adapter=_OkRecognition(),
                     profiles_service=profiles,
                     web_dist=tmp_path / "none")
    client = TestClient(app)
    r = client.post("/api/v1/auth/login",
                    json={"username": "admin", "password": PW})
    headers = {"X-CSRF-Token": r.json()["csrf_token"]}
    FixtureTestDataService(store).create_test_run_context(
        NS, customer_ids=[])
    return {"store": store, "bundle": bundle, "client": client,
            "h": headers, "iam": IAMService(store),
            "tds": FixtureTestDataService(store),
            "db_path": tmp_path / "p.sqlite",
            "cas_root": tmp_path / "cas"}


def _cust_csv(*cids):
    rows = "".join(f"{cid},客户{cid},月结30天,,\n" for cid in cids)
    return ("customer_id,name,payment_terms,retention_policy,tags\n"
            + rows).encode("utf-8-sig")


def _upload(c, h, tid: str, data: bytes, name="f.csv", **fields):
    form = {"template_id": tid, **fields}
    return c.post("/api/v1/import/upload", headers=h, data=form,
                  files={"file": (name, io.BytesIO(data), "text/csv")})


def _quarantine(env, batch_id: str) -> None:
    """复刻 scripts/scope_reconcile_imports_v5.py 的隔离方式。"""
    env["store"]._conn.execute(
        "UPDATE import_batch_v1 SET data_scope='quarantine',"
        " archived_at='2026-08-13T05:28:36+00:00' WHERE batch_id=?",
        (batch_id,))
    env["store"]._conn.commit()


def _mk_center(store) -> ImportCenter:
    """直接构造 Domain Service（绕过 API route 的调用路径）。"""
    iam = IAMService(store)
    return ImportCenter(store, iam=iam,
                        master=MasterDataService(store, iam),
                        survey=SurveyService(store),
                        field_ops=FieldOpsService(store),
                        finance=FinanceService(store))


def _seed_batch(env, batch_id: str, template_id: str) -> None:
    """直接落库一个 quarantine 批次（守卫必须在任何解析/校验前触发）。"""
    env["store"]._conn.execute(
        "INSERT INTO import_batch_v1 (batch_id, template_id, filename,"
        " file_format, file_hash, status, actor, row_count,"
        " mapping_json, dry_run_json, error_report_json, commit_json,"
        " created_at, updated_at, data_scope, visibility, archived_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (batch_id, template_id, f"{template_id}.csv", "csv",
         "h-" + batch_id, "dry_run_passed", "admin", 0,
         json.dumps({"rows": []}), "{}", "[]", "{}",
         "2026-08-13T00:00:00+00:00", "2026-08-13T00:00:00+00:00",
         "quarantine", "current",
         "2026-08-13T05:28:36+00:00"))
    env["store"]._conn.commit()


# --------------------------------------------------------------------
# 服务层守卫：14 模板参数化（直接调用 service，绕过 API）
# --------------------------------------------------------------------

class TestServiceGuard:
    @pytest.mark.parametrize("tid", ALL_TEMPLATES)
    def test_quarantine_commit_blocked_service_level(self, env, tid):
        bid = f"imp-q-{tid.replace('_', '-')[:24]}"
        _seed_batch(env, bid, tid)
        center = _mk_center(env["store"])
        with pytest.raises(ImportError_) as ei:
            center.commit(bid, actor="admin", session_role="admin")
        assert CODE in str(ei.value)
        # 无任何写入：commit_json 保持 {}
        row = env["store"]._conn.execute(
            "SELECT commit_json, status FROM import_batch_v1"
            " WHERE batch_id=?", (bid,)).fetchone()
        assert row["commit_json"] == "{}"
        assert row["status"] == "dry_run_passed"

    @pytest.mark.parametrize("tid", ALL_TEMPLATES)
    def test_quarantine_dry_run_blocked_service_level(self, env, tid):
        bid = f"imp-qd-{tid.replace('_', '-')[:23]}"
        _seed_batch(env, bid, tid)
        center = _mk_center(env["store"])
        with pytest.raises(ImportError_) as ei:
            center.dry_run(bid, actor="admin", session_role="admin")
        assert CODE in str(ei.value)
        row = env["store"]._conn.execute(
            "SELECT dry_run_json, status FROM import_batch_v1"
            " WHERE batch_id=?", (bid,)).fetchone()
        assert row["dry_run_json"] == "{}"  # 原证据不得被覆写


# --------------------------------------------------------------------
# API 层：真实 upload → 隔离 → 409 + 稳定码
# --------------------------------------------------------------------

class TestApiGuard:
    def _mk_quarantined(self, env):
        r = _upload(env["client"], env["h"], "customers_v1",
                    _cust_csv(f"{NS}_qc1"))
        assert r.status_code == 200, r.text
        bid = r.json()["batch"]["batch_id"]
        _quarantine(env, bid)
        return bid

    def test_commit_returns_409_with_stable_code(self, env):
        bid = self._mk_quarantined(env)
        r = env["client"].post(
            f"/api/v1/import/batches/{bid}/commit", headers=env["h"])
        assert r.status_code == 409
        assert CODE in r.json()["detail"]

    def test_dry_run_returns_409_with_stable_code(self, env):
        bid = self._mk_quarantined(env)
        r = env["client"].post(
            f"/api/v1/import/batches/{bid}/dry-run", headers=env["h"])
        assert r.status_code == 409
        assert CODE in r.json()["detail"]

    def test_forged_params_cannot_override_scope(self, env):
        bid = self._mk_quarantined(env)
        r = env["client"].post(
            f"/api/v1/import/batches/{bid}/commit?data_scope=operational",
            headers=env["h"], json={"data_scope": "operational"})
        assert r.status_code == 409
        assert CODE in r.json()["detail"]

    def test_concurrent_commits_all_blocked_zero_writes(self, env):
        bid = self._mk_quarantined(env)
        before = env["store"]._conn.execute(
            "SELECT COUNT(*) c FROM md_customer_v1").fetchone()["c"]
        results: list[int] = []
        lock = threading.Lock()

        def hit():
            rr = env["client"].post(
                f"/api/v1/import/batches/{bid}/commit",
                headers=env["h"])
            with lock:
                results.append(rr.status_code)

        ths = [threading.Thread(target=hit) for _ in range(4)]
        [t.start() for t in ths]
        [t.join() for t in ths]
        assert results == [409] * 4, results
        after = env["store"]._conn.execute(
            "SELECT COUNT(*) c FROM md_customer_v1").fetchone()["c"]
        assert after == before  # 零 operational 写入
        row = env["store"]._conn.execute(
            "SELECT commit_json FROM import_batch_v1"
            " WHERE batch_id=?", (bid,)).fetchone()
        assert row["commit_json"] in ("{}", "")

    def test_restart_does_not_unblock(self, env):
        """重启（新 PlatformStore + 新 ImportCenter）后仍 409。"""
        from src.platform.data.store import PlatformStore
        bid = self._mk_quarantined(env)
        store2 = PlatformStore(env["db_path"])
        with pytest.raises(ImportError_) as ei:
            _mk_center(store2).commit(bid, actor="admin",
                                      session_role="admin")
        assert CODE in str(ei.value)

    def test_operational_batch_still_commits(self, env):
        """回归：operational 路径不受影响。"""
        r = _upload(env["client"], env["h"], "customers_v1",
                    _cust_csv(f"{NS}_ok1"))
        bid = r.json()["batch"]["batch_id"]
        rd = env["client"].post(
            f"/api/v1/import/batches/{bid}/dry-run", headers=env["h"])
        assert rd.status_code == 200, rd.text
        rc = env["client"].post(
            f"/api/v1/import/batches/{bid}/commit", headers=env["h"])
        assert rc.status_code == 200, rc.text
        assert rc.json()["batch"]["status"] == "committed"

    def test_detail_still_readable_for_audit(self, env):
        """只读详情不受守卫影响（隔离区仍需可查看）。"""
        bid = self._mk_quarantined(env)
        r = env["client"].get(f"/api/v1/import/batches/{bid}",
                              headers=env["h"])
        assert r.status_code == 200
        assert r.json()["batch"]["data_scope"] == "quarantine"


# --------------------------------------------------------------------
# 14 模板参数化 HTTP 表面：真实 upload → 隔离 → 409 + 稳定码（C-1 §7）
# --------------------------------------------------------------------

# 每个模板的最小合法行（仅必填列；守卫先于任何分类/写入触发）
_MIN_ROWS: dict[str, str] = {
    "customers_v1": "customer_id,name\nosv51-cust,隔离客户\n",
    "projects_v1":
        "project_id,customer_id,name\nosv51-prj,osv51-cust,隔离项目\n",
    "skus_v1": "sku_id,canonical_name\nosv51-sku,隔离SKU\n",
    "stores_addresses_v1":
        "customer_id,store_name,raw_address\n"
        "osv51-cust,隔离门店,隔离路1号\n",
    "employees_v1": "customer_id,name\nosv51-cust,隔离员工\n",
    "users_v1": "username\nosv51_user\n",
    "roles_permissions_v1": "role_name,scopes\n隔离角色,survey.read\n",
    "memberships_v1": "username,role\nosv51_user,隔离角色\n",
    "survey_definition_v1": "survey_name\n隔离问卷\n",
    "survey_questions_v1":
        "survey_name,question_id,qtype,title\n隔离问卷,q1,text,隔离题目\n",
    "survey_logic_v1":
        "survey_name,from_question,op,value,to_question\n"
        "隔离问卷,q1,eq,是,q2\n",
    "route_constraints_v1":
        "customer_id,preset_name\nosv51-cust,隔离预设\n",
    "usage_rate_cards_v1":
        "rate_card_id,unit,price\nosv51-rc,recognition_photo,0.1\n",
    "knowledge_documents_v1": "kb_name,title\n隔离kb,隔离文档\n",
}


class TestAllTemplatesHttpGuard:
    """真实上传路径（multipart upload）+ reconcile 式隔离 → HTTP 双
    端点 409 + 稳定码 + 零批次行写入；全部 14 模板参数化。"""

    @pytest.mark.parametrize("tid", ALL_TEMPLATES)
    def test_uploaded_then_quarantined_http_blocked(self, env, tid):
        r = _upload(env["client"], env["h"], tid,
                    _MIN_ROWS[tid].encode("utf-8-sig"))
        assert r.status_code == 200, f"{tid}: {r.text[:300]}"
        bid = r.json()["batch"]["batch_id"]
        _quarantine(env, bid)
        row = env["store"]._conn.execute(
            "SELECT data_scope, visibility, status, mapping_json,"
            " dry_run_json, error_report_json, commit_json, updated_at"
            " FROM import_batch_v1 WHERE batch_id=?", (bid,)).fetchone()
        assert row["data_scope"] == "quarantine"
        assert row["visibility"] == "current"  # 现场形态：未设 history

        for ep in ("dry-run", "commit"):
            resp = env["client"].post(
                f"/api/v1/import/batches/{bid}/{ep}", headers=env["h"])
            assert resp.status_code == 409, \
                f"{tid} {ep}: quarantine 批次必须 409，实际 " \
                f"{resp.status_code}: {resp.text[:200]}"
            assert CODE in str(resp.json().get("detail")), \
                f"{tid} {ep}: 409 detail 必须原样携带 {CODE}"

        # 零写入：批次 JSON 列与状态逐字节不变（dry-run 也不得覆写证据）
        after = env["store"]._conn.execute(
            "SELECT status, mapping_json, dry_run_json,"
            " error_report_json, commit_json, updated_at"
            " FROM import_batch_v1 WHERE batch_id=?", (bid,)).fetchone()
        for col in ("status", "mapping_json", "dry_run_json",
                    "error_report_json", "commit_json", "updated_at"):
            assert after[col] == row[col], \
                f"{tid}: quarantine 后尝试不得写批次行 {col}"


# --------------------------------------------------------------------
# 现场复现：已 committed 批次被隔离后重放（状态门接受 'committed'）
# --------------------------------------------------------------------

class TestReplayProductionVector:
    """imp-bf333d101db6 复现：operational 提交成功 → reconcile 隔离 →
    status='committed' 绕过状态门的重放必须被稳定码拦截，且不得覆写
    commit_json 证据（现场 inserted:1 → skipped:1 覆写）。"""

    def test_replay_of_committed_quarantine_batch_blocked(self, env):
        r = _upload(env["client"], env["h"], "stores_addresses_v1",
                    ("customer_id,store_name,raw_address\n"
                     "osv51-rp-cust,重放门店,重放路1号\n")
                    .encode("utf-8-sig"))
        assert r.status_code == 200, r.text
        bid = r.json()["batch"]["batch_id"]
        # 先建客户使地址提交可真正插入（复刻运营面真实提交）
        env["client"].post("/api/v1/master/customers", headers=env["h"],
                           json={"customer_id": "osv51-rp-cust",
                                 "name": "重放客户"})
        rd = env["client"].post(f"/api/v1/import/batches/{bid}/dry-run",
                                headers=env["h"])
        assert rd.status_code == 200, rd.text
        rc = env["client"].post(f"/api/v1/import/batches/{bid}/commit",
                                headers=env["h"])
        assert rc.status_code == 200, rc.text
        assert rc.json()["batch"]["commit"]["stats"]["inserted"] == 1
        orig = env["store"]._conn.execute(
            "SELECT status, commit_json, dry_run_json FROM"
            " import_batch_v1 WHERE batch_id=?", (bid,)).fetchone()
        assert orig["status"] == "committed"
        addr_n = env["store"]._conn.execute(
            "SELECT count(*) c FROM geo_address_v1").fetchone()["c"]
        assert addr_n == 1

        _quarantine(env, bid)

        # 重放：HTTP 表面 409 + 稳定码
        rr = env["client"].post(f"/api/v1/import/batches/{bid}/commit",
                                headers=env["h"])
        assert rr.status_code == 409, \
            f"隔离后重放必须 409，实际 {rr.status_code}: {rr.text[:200]}"
        assert CODE in str(rr.json().get("detail"))
        # 重放：直接 service 调用同样被拦（绕过 API 无效）
        with pytest.raises(ImportError_) as ei:
            _mk_center(env["store"]).commit(
                bid, actor="admin", session_role="admin")
        assert CODE in str(ei.value)

        # 证据冻结：commit_json/status 不变；运营表零新增
        after = env["store"]._conn.execute(
            "SELECT status, commit_json, dry_run_json FROM"
            " import_batch_v1 WHERE batch_id=?", (bid,)).fetchone()
        assert after["commit_json"] == orig["commit_json"], \
            "quarantine 重放不得覆写 commit_json 证据"
        assert after["status"] == "committed"
        assert env["store"]._conn.execute(
            "SELECT count(*) c FROM geo_address_v1").fetchone()["c"] \
            == addr_n


class TestArchivedHistorySameCode:
    """C-1 §2：archived/history 已终态批次与 quarantine 同一稳定码。"""

    @pytest.mark.parametrize("mutate", (
        "visibility='history'",
        "data_scope='archived'",
    ))
    def test_archived_or_history_same_stable_code(self, env, mutate):
        r = _upload(env["client"], env["h"], "customers_v1",
                    _cust_csv(f"{NS}_ah1"))
        bid = r.json()["batch"]["batch_id"]
        env["store"]._conn.execute(
            f"UPDATE import_batch_v1 SET {mutate} WHERE batch_id=?",
            (bid,))
        env["store"]._conn.commit()
        rc = env["client"].post(f"/api/v1/import/batches/{bid}/commit",
                                headers=env["h"])
        assert rc.status_code == 409
        assert CODE in str(rc.json().get("detail"))
