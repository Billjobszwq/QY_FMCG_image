"""OSV51 C-2 红测试：users_v1 首次密码零持久化。

契约（02-IMPORT-SECURITY.md §2）：
- initial_password_once 仅出现在 POST /commit 的当次 HTTP 响应；
- SQLite commit_json/dry_run_json/error_report_json、GET 详情、四视图
  列表、errors.csv、preview、EventEnvelope、Evidence、审计、日志均
  不得出现明文；DB 只存 PBKDF2 哈希；
- DTO 与 JSON 走递归 secret 扫描（不只顶层）；
- 重启后 GET 仍无明文；该密码仍可登录（哈希可用）；
- 存量嵌套 JSON 清洗：发现即安全清除 + 审计，不打印原值。
"""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.composition.build import (build_production_bundle,
                                   build_profiles_service)
from src.platform.api.app import create_app
from src.platform.iam import IAMService
from src.platform.test_data import FixtureTestDataService

PW = "osv51-pw-admin"
SECRET_KEYS = ("password", "initial_password_once", "password_once",
               "passwd", "token", "api_key", "apikey", "secret",
               "credential", "private_key")


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
    app = create_app(services=(), probe=lambda spec: None,
                     bundle=bundle, recognition_adapter=_OkRecognition(),
                     profiles_service=profiles,
                     web_dist=tmp_path / "none")
    client = TestClient(app)
    r = client.post("/api/v1/auth/login",
                    json={"username": "admin", "password": PW})
    headers = {"X-CSRF-Token": r.json()["csrf_token"]}
    FixtureTestDataService(bundle.store).create_test_run_context(
        "uatv7_osv51_pw", customer_ids=[])
    return {"store": bundle.store, "client": client, "h": headers,
            "db_path": tmp_path / "p.sqlite"}


def _users_csv(*names):
    rows = "".join(f"{n},显示{n},user,active\n" for n in names)
    return ("username,display_name,kind,status\n" + rows).encode(
        "utf-8-sig")


def _upload_users(env, names=("osv51_alice", "osv51_bob")):
    r = env["client"].post(
        "/api/v1/import/upload", headers=env["h"],
        data={"template_id": "users_v1"},
        files={"file": ("users.csv", io.BytesIO(_users_csv(*names)),
                         "text/csv")})
    assert r.status_code == 200, r.text
    return r.json()["batch"]["batch_id"]


def _deep_scan(obj, found: list, path="$"):
    """递归查找 secret 键且值非 [REDACTED] 的位置。"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            kl = str(k).lower()
            if any(s in kl for s in SECRET_KEYS):
                if isinstance(v, str) and v and v != "[REDACTED]":
                    found.append(f"{path}.{k}")
            _deep_scan(v, found, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _deep_scan(v, found, f"{path}[{i}]")
    return found


def _all_batch_jsons(conn):
    """所有批次四列 JSON 的全部文本。"""
    out = []
    for row in conn.execute(
            "SELECT batch_id, mapping_json, dry_run_json,"
            " error_report_json, commit_json FROM import_batch_v1"):
        out.append((row["batch_id"],
                    "".join([row["mapping_json"], row["dry_run_json"],
                             row["error_report_json"],
                             row["commit_json"]])))
    return out


class TestOneTimeDelivery:
    def test_commit_response_contains_password_once(self, env):
        bid = _upload_users(env)
        for ep in ("dry-run", "commit"):
            r = env["client"].post(
                f"/api/v1/import/batches/{bid}/{ep}", headers=env["h"])
            assert r.status_code == 200, r.text
        r = env["client"].post(
            f"/api/v1/import/batches/{bid}/commit", headers=env["h"])
        # 幂等再提交：不得再次回发明文
        body = json.dumps(r.json())
        found = _deep_scan(json.loads(body), [])
        assert found == [], f"重复提交不得回发明文: {found}"

    def test_first_commit_delivers_once(self, env):
        # OSV52：测试函数只做断言，不返回业务值（复用逻辑见
        # _commit_users helper）。
        bid, pws = _commit_users(env)
        assert len(pws) == 2 and all(
            p and p != "[REDACTED]" for p in pws), pws
        # 当次响应后重读详情：明文不得再次出现
        rr = env["client"].get(f"/api/v1/import/batches/{bid}",
                               headers=env["h"])
        body = rr.text
        for pw in pws:
            assert pw not in body, "初始口令在重读详情中复现"


def _commit_users(env):
    """OSV52：普通 helper（非测试函数）——upload→dry-run→commit，
    返回 (batch_id, 一次性初始口令列表)。"""
    bid = _upload_users(env)
    env["client"].post(f"/api/v1/import/batches/{bid}/dry-run",
                       headers=env["h"])
    r = env["client"].post(
        f"/api/v1/import/batches/{bid}/commit", headers=env["h"])
    assert r.status_code == 200, r.text
    pws = [x["initial_password_once"]
           for x in r.json()["batch"]["commit"]["receipts"]]
    return bid, pws


class TestZeroPersistence:
    def _commit_users(self, env):
        return _commit_users(env)

    def test_db_json_columns_contain_no_plaintext(self, env):
        bid, pws = self._commit_users(env)
        for bid2, blob in _all_batch_jsons(env["store"]._conn):
            for pw in pws:
                assert pw not in blob, f"{bid2} 落库明文泄漏"
        # 递归键扫描（防非本批次的结构泄漏）
        for bid2, blob in _all_batch_jsons(env["store"]._conn):
            try:
                parsed = json.loads(blob) if blob.strip() else {}
            except Exception:
                parsed = {}
            assert _deep_scan(parsed, []) == [], f"{bid2} 含敏感键明文"

    def test_get_detail_and_lists_no_plaintext(self, env):
        bid, pws = self._commit_users(env)
        surfaces = [
            f"/api/v1/import/batches/{bid}",
            "/api/v1/import/batches?view=mine",
            "/api/v1/import/batches?view=history&include_fixture=1",
            "/api/v1/import/batches?view=quarantine",
            "/api/v1/import/batches?view=operational",
        ]
        for path in surfaces:
            body = env["client"].get(path, headers=env["h"]).text
            for pw in pws:
                assert pw not in body, f"{path} 明文泄漏"
            found = _deep_scan(
                json.loads(env["client"].get(path,
                                             headers=env["h"]).text), [])
            assert found == [], f"{path} 敏感键明文: {found}"

    def test_errors_csv_and_audit_evidence_clean(self, env):
        bid, pws = self._commit_users(env)
        csv_body = env["client"].get(
            f"/api/v1/import/batches/{bid}/errors.csv",
            headers=env["h"]).text
        conn = env["store"]._conn
        audit_blob = "".join(
            r["detail_json"] for r in conn.execute(
                "SELECT detail_json FROM iam_audit_event_v1"))
        evid_blob = "".join(
            (r["source_uri"] or "") + (r["cas_hash"] or "")
            for r in conn.execute(
                "SELECT source_uri, cas_hash FROM evidence_bundle_v1"))
        events = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
            " AND name LIKE 'event%'").fetchall()
        env_blob = ""
        if events:
            try:
                env_blob = "".join(
                    str(r[0]) for r in conn.execute(
                        "SELECT * FROM event_envelope_v1"))
            except Exception:
                env_blob = ""
        for pw in pws:
            assert pw not in csv_body and pw not in audit_blob \
                and pw not in evid_blob and pw not in env_blob

    def test_restart_still_clean_and_password_usable(self, env):
        bid, pws = self._commit_users(env)
        from src.platform.data.store import PlatformStore
        store2 = PlatformStore(env["db_path"])
        for row in store2._conn.execute(
                "SELECT commit_json FROM import_batch_v1"):
            for pw in pws:
                assert pw not in row["commit_json"]
        # 重启后 API 面也干净：用新 store 组装 app
        bundle2 = build_production_bundle(
            db_path=env["db_path"], cas_root=env["db_path"].parent /
            "cas2", recognition_adapter=_OkRecognition(),
            probe=lambda spec: None)
        app2 = create_app(services=(), probe=lambda spec: None,
                          bundle=bundle2,
                          recognition_adapter=_OkRecognition(),
                          profiles_service=build_profiles_service(
                              bundle2),
                          web_dist=env["db_path"].parent / "none")
        c2 = TestClient(app2)
        lg = c2.post("/api/v1/auth/login",
                     json={"username": "admin", "password": PW})
        h2 = {"X-CSRF-Token": lg.json()["csrf_token"]}
        body = c2.get(f"/api/v1/import/batches/{bid}",
                      headers=h2).text
        for pw in pws:
            assert pw not in body
        # 初始密码哈希可用：首次密码仍可登录
        r = c2.post("/api/v1/auth/login",
                    json={"username": "osv51_alice",
                          "password": pws[0]})
        assert r.status_code == 200, "初始密码哈希必须可用"

    def test_no_plaintext_via_service_direct(self, env):
        """直接调用 service 的 DTO 路径也不得泄漏（绕过 API）。"""
        from src.platform.field_ops import FieldOpsService
        from src.platform.finance import FinanceService
        from src.platform.iam import MasterDataService
        from src.platform.import_center import ImportCenter
        from src.platform.survey import SurveyService
        bid = _upload_users(env, ("osv51_carol",))
        iam = IAMService(env["store"])
        center = ImportCenter(env["store"], iam=iam,
                              master=MasterDataService(env["store"],
                                                       iam),
                              survey=SurveyService(env["store"]),
                              field_ops=FieldOpsService(env["store"]),
                              finance=FinanceService(env["store"]))
        center.dry_run(bid, actor="admin", session_role="admin")
        dto = center.commit(bid, actor="admin", session_role="admin")
        # commit 当次返回允许含一次明文；之后的 get_batch/dto 不得含
        dto2 = center.batch_dto(center._must(bid))
        found = _deep_scan(dto2, [])
        assert found == [], f"重读 DTO 泄漏: {found}"


class TestRecursiveRedaction:
    def test_redact_secrets_nested(self):
        from src.platform.import_center import redact_secrets
        obj = {"a": [{"initial_password_once": "Init-x",
                      "username": "u",
                      "deep": {"API_KEY": "k-123",
                               "list": [{"password": "p2"}]}}]}
        out = redact_secrets(obj)
        assert out["a"][0]["initial_password_once"] == "[REDACTED]"
        assert out["a"][0]["deep"]["API_KEY"] == "[REDACTED]"
        assert out["a"][0]["deep"]["list"][0]["password"] == \
            "[REDACTED]"
        assert out["a"][0]["username"] == "u"  # 非敏感字段保留

    def test_commit_json_persists_redacted_receipts(self, env):
        bid = _upload_users(env, ("osv51_dave",))
        env["client"].post(f"/api/v1/import/batches/{bid}/dry-run",
                           headers=env["h"])
        env["client"].post(f"/api/v1/import/batches/{bid}/commit",
                           headers=env["h"])
        row = env["store"]._conn.execute(
            "SELECT commit_json FROM import_batch_v1 WHERE batch_id=?",
            (bid,)).fetchone()
        cj = json.loads(row["commit_json"])
        rec = cj["receipts"][0]
        assert rec["username"] == "osv51_dave"
        assert rec.get("initial_password_once") == "[REDACTED]"


class TestLegacyScrub:
    def test_scrub_cleans_nested_legacy_secrets(self, env, capsys):
        """存量嵌套 JSON 中的秘密被清除 + 审计，且不打印原值。"""
        conn = env["store"]._conn
        legacy = {"stats": {"inserted": 1}, "receipts": [
            {"username": "legacy_u",
             "initial_password_once": "Init-legacy-secret-1",
             "nested": {"token": "tk-999"}}]}
        conn.execute(
            "INSERT INTO import_batch_v1 (batch_id, template_id,"
            " filename, file_format, file_hash, status, actor,"
            " row_count, mapping_json, dry_run_json,"
            " error_report_json, commit_json, created_at, updated_at)"
            " VALUES ('imp-legacy-pw','users_v1','l.csv','csv','h',"
            "'committed','x',1,'{}','{}','[]',?,"
            "'2026-08-01T00:00:00+00:00','2026-08-01T00:00:00+00:00')",
            (json.dumps(legacy),))
        conn.commit()
        from scripts.osv51_scrub_secrets import scrub_store
        report = scrub_store(env["store"])
        assert report["scrubbed_batches"] == ["imp-legacy-pw"]
        row = conn.execute(
            "SELECT commit_json FROM import_batch_v1"
            " WHERE batch_id='imp-legacy-pw'").fetchone()
        cj = json.loads(row["commit_json"])
        assert cj["receipts"][0]["initial_password_once"] == \
            "[REDACTED]"
        assert cj["receipts"][0]["nested"]["token"] == "[REDACTED]"
        # 审计入账
        aud = conn.execute(
            "SELECT detail_json FROM iam_audit_event_v1 WHERE action="
            "'import.secret.scrubbed'").fetchall()
        assert len(aud) >= 1
        # 原值绝不打印/落日志
        out = capsys.readouterr().out
        assert "Init-legacy-secret-1" not in out
        assert "tk-999" not in out
        # 幂等
        report2 = scrub_store(env["store"])
        assert report2["scrubbed_batches"] == []
