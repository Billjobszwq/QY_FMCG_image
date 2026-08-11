"""ABOSV3 T3 红测试：Import Center（14 套模板 round-trip + 幂等提交）。

要求（AGENT-EXECUTION-PROMPT §T3、03 文档 §1）：
- 14 套 CSV/XLSX 模板可下载，且下载后必须能被同一系统重新解析；
- 上传 → 映射 → dry-run（逐行新增/跳过/冲突/错误）→ 提交；
- 提交走 Domain Service（客户/项目/SKU/地址/员工/用户/角色/授权/
  问卷/路线约束/价目/知识文档），幂等、证据与审计；
- 故意错误必须被逐行报出并可修复后重提。
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
from src.platform.import_center import TEMPLATES

PW = "v3-import-pw"


class _OkRecognition:
    def recognize(self, data: bytes, conf: float = 0.25):
        return {"count": 0, "products": []}


@pytest.fixture()
def client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD", PW)
    adapter = _OkRecognition()
    bundle = build_production_bundle(
        db_path=tmp_path / "p.sqlite", cas_root=tmp_path / "cas",
        recognition_adapter=adapter, probe=lambda spec: None)
    build_profiles_service(bundle)
    app = create_app(services=(), probe=lambda spec: None,
                     bundle=bundle, recognition_adapter=adapter,
                     web_dist=Path("/nonexistent-dist"))
    c = TestClient(app)
    r = c.post("/api/v1/auth/login",
               json={"username": "admin", "password": PW})
    assert r.status_code == 200, r.text
    h = {"X-CSRF-Token": r.json()["csrf_token"]}
    return c, h, bundle


def _upload(c, h, tid: str, data: bytes, name="f.csv"):
    return c.post("/api/v1/import/upload", headers=h,
                  data={"template_id": tid},
                  files={"file": (name, io.BytesIO(data), "text/csv")})


class TestTemplatesRoundTrip:
    def test_all_14_templates_csv_round_trip(self, client):
        c, h, _b = client
        tps = c.get("/api/v1/import/templates").json()["templates"]
        assert len(tps) == 14
        for t in tps:
            tid = t["template_id"]
            r = c.get(f"/api/v1/import/templates/{tid}/download"
                      "?fmt=csv")
            assert r.status_code == 200, tid
            # 下载的模板必须能被同一系统重新解析（round-trip）
            up = _upload(c, h, tid, r.content)
            assert up.status_code == 200, f"{tid}: {up.text}"
            assert up.json()["batch"]["status"] == "parsed", tid

    def test_xlsx_round_trip(self, client):
        c, h, _b = client
        for tid in ("customers_v1", "stores_addresses_v1"):
            r = c.get(f"/api/v1/import/templates/{tid}/download"
                      "?fmt=xlsx")
            assert r.status_code == 200
            assert r.content[:2] == b"PK"  # 真 xlsx（zip 魔数）
            up = c.post("/api/v1/import/upload", headers=h,
                        data={"template_id": tid},
                        files={"file": ("f.xlsx", io.BytesIO(r.content),
                                        "application/octet-stream")})
            assert up.status_code == 200, up.text
            assert up.json()["batch"]["status"] == "parsed"


class TestCustomerImportE2E:
    CSV = ("customer_id,name,payment_terms,retention_policy,tags\n"
           "cust-imp,导入客户,月结30天,2年,快消\n").encode("utf-8-sig")

    def test_upload_dryrun_commit_and_idempotent_replay(self, client):
        c, h, bundle = client
        up = _upload(c, h, "customers_v1", self.CSV)
        bid = up.json()["batch"]["batch_id"]
        dr = c.post(f"/api/v1/import/batches/{bid}/dry-run", headers=h)
        assert dr.status_code == 200, dr.text
        b = dr.json()["batch"]
        assert b["status"] == "dry_run_passed", b["errors"]
        assert b["dry_run"]["plan"]["insert"] == 1
        cm = c.post(f"/api/v1/import/batches/{bid}/commit", headers=h)
        b = cm.json()["batch"]
        assert b["status"] == "committed", b["errors"]
        assert b["commit"]["stats"]["inserted"] == 1
        # 真实落库：走 MasterData 服务（不得绕过）
        row = bundle.store._conn.execute(
            "SELECT * FROM md_customer_v1 WHERE customer_id='cust-imp'"
            ).fetchone()
        assert row is not None and row["name"] == "导入客户"
        # 幂等重放：同一文件新批次 → 全部 skip，不重复插入
        up2 = _upload(c, h, "customers_v1", self.CSV)
        bid2 = up2.json()["batch"]["batch_id"]
        c.post(f"/api/v1/import/batches/{bid2}/dry-run", headers=h)
        cm2 = c.post(f"/api/v1/import/batches/{bid2}/commit", headers=h)
        st = cm2.json()["batch"]["commit"]["stats"]
        assert st["inserted"] == 0 and st["skipped"] == 1

    def test_row_errors_reported_and_fixable(self, client):
        c, h, _b = client
        # 故意错误：第 2 行缺必填 name；第 3 行与第 4 行 customer_id 重复
        bad = ("customer_id,name,payment_terms,retention_policy,tags\n"
               "cust-x,,月结,,\n"
               "cust-y,客户Y,,,\n"
               "cust-y,客户Y重复,,,\n").encode("utf-8-sig")
        up = _upload(c, h, "customers_v1", bad)
        bid = up.json()["batch"]["batch_id"]
        dr = c.post(f"/api/v1/import/batches/{bid}/dry-run", headers=h)
        b = dr.json()["batch"]
        assert b["status"] == "validation_failed"
        msgs = " ".join(e["error"] for e in b["errors"])
        assert "name" in msgs and "重复" in msgs
        # 未通过 dry-run 不得提交（诚实失败）
        cm = c.post(f"/api/v1/import/batches/{bid}/commit", headers=h)
        assert cm.status_code == 409
        # 错误报告可下载
        er = c.get(f"/api/v1/import/batches/{bid}/errors.csv")
        assert er.status_code == 200 and b"row" in er.content


class TestIamAndMasterImports:
    def test_users_roles_memberships_commit(self, client):
        c, h, bundle = client
        # 用户导入：一次性初始口令只在回执中出现
        up = _upload(c, h, "users_v1",
                     ("username,display_name,kind,status\n"
                      "impuser,导入用户,user,active\n"
                      ).encode("utf-8-sig"))
        bid = up.json()["batch"]["batch_id"]
        c.post(f"/api/v1/import/batches/{bid}/dry-run", headers=h)
        b = c.post(f"/api/v1/import/batches/{bid}/commit",
                   headers=h).json()["batch"]
        assert b["status"] == "committed", b["errors"]
        receipt = b["commit"]["receipts"][0]
        assert receipt["username"] == "impuser"
        pw_once = receipt["initial_password_once"]
        assert bundle.store._conn.execute(
            "SELECT 1 FROM iam_principal_v1 WHERE username='impuser'"
            ).fetchone() is not None
        # 初始口令可真实登录（走统一认证）；登录后切回 admin 会话
        lg = c.post("/api/v1/auth/login",
                    json={"username": "impuser", "password": pw_once})
        assert lg.status_code == 200, lg.text
        back = c.post("/api/v1/auth/login",
                      json={"username": "admin", "password": PW})
        h["X-CSRF-Token"] = back.json()["csrf_token"]
        # 角色导入：白名单外的 scope 必须 fail-closed
        up = _upload(c, h, "roles_permissions_v1",
                     ("role_name,description,scopes\n"
                      "危险角色,x,not_a_real_scope\n").encode("utf-8-sig"))
        bid = up.json()["batch"]["batch_id"]
        c.post(f"/api/v1/import/batches/{bid}/dry-run", headers=h)
        b = c.post(f"/api/v1/import/batches/{bid}/commit",
                   headers=h).json()["batch"]
        assert b["status"] == "partial_failed"
        assert "白名单" in b["errors"][0]["error"]
        # 合法角色 + 授权
        up = _upload(c, h, "roles_permissions_v1",
                     ("role_name,description,scopes\n"
                      "导入分析师,分析,survey.read;analytics.read\n"
                      ).encode("utf-8-sig"))
        bid = up.json()["batch"]["batch_id"]
        c.post(f"/api/v1/import/batches/{bid}/dry-run", headers=h)
        b = c.post(f"/api/v1/import/batches/{bid}/commit",
                   headers=h).json()["batch"]
        assert b["status"] == "committed", b["errors"]
        up = _upload(c, h, "memberships_v1",
                     ("username,role,customer_id,project_id\n"
                      "impuser,导入分析师,cust-imp,\n"
                      ).encode("utf-8-sig"))
        bid = up.json()["batch"]["batch_id"]
        c.post(f"/api/v1/import/batches/{bid}/dry-run", headers=h)
        b = c.post(f"/api/v1/import/batches/{bid}/commit",
                   headers=h).json()["batch"]
        assert b["status"] == "committed", b["errors"]

    def test_sku_and_address_import(self, client):
        c, h, bundle = client
        # 先有客户
        from src.platform.iam import IAMService, MasterDataService
        md = MasterDataService(bundle.store, IAMService(bundle.store))
        md.create_customer(customer_id="cust-geo", name="G",
                           created_by="admin")
        up = _upload(c, h, "skus_v1",
                     ("sku_id,canonical_name,brand,category,volume,"
                      "package_version,barcode,aliases,valid_from,valid_to\n"
                      "sku-t1,测试SKU,品A,饮料,500ml,v1,6901,别名1;别名2,,\n"
                      ).encode("utf-8-sig"))
        bid = up.json()["batch"]["batch_id"]
        c.post(f"/api/v1/import/batches/{bid}/dry-run", headers=h)
        b = c.post(f"/api/v1/import/batches/{bid}/commit",
                   headers=h).json()["batch"]
        assert b["status"] == "committed", b["errors"]
        assert md.get_sku("sku-t1") is not None
        assert len(md.aliases_of("sku-t1")) == 2
        # 地址导入：自带坐标 → status=confirmed（source=import）
        up = _upload(c, h, "stores_addresses_v1",
                     ("customer_id,store_name,raw_address,region,lat,lng,"
                      "coord_system,time_window\n"
                      "cust-geo,示例店,示例路1号,华东,31.2,121.4,wgs84,"
                      "09:00-18:00\n").encode("utf-8-sig"))
        bid = up.json()["batch"]["batch_id"]
        c.post(f"/api/v1/import/batches/{bid}/dry-run", headers=h)
        b = c.post(f"/api/v1/import/batches/{bid}/commit",
                   headers=h).json()["batch"]
        assert b["status"] == "committed", b["errors"]
        row = bundle.store._conn.execute(
            "SELECT * FROM geo_address_v1 WHERE customer_id='cust-geo'"
            ).fetchone()
        assert row is not None and row["status"] == "confirmed"
        assert "import" in row["chosen_json"]


class TestSurveyAndRateCardImports:
    def test_survey_questions_and_logic_into_draft(self, client):
        c, h, bundle = client
        up = _upload(c, h, "survey_definition_v1",
                     ("survey_name,description,pages\n"
                      "导入问卷,测试,1\n").encode("utf-8-sig"))
        bid = up.json()["batch"]["batch_id"]
        c.post(f"/api/v1/import/batches/{bid}/dry-run", headers=h)
        assert c.post(f"/api/v1/import/batches/{bid}/commit",
                      headers=h).json()["batch"]["status"] == "committed"
        up = _upload(c, h, "survey_questions_v1",
                     ("survey_name,question_id,qtype,title,options,"
                      "required,score,dimension\n"
                      "导入问卷,q1,single_choice,是否整洁,是;否,true,5,陈列\n"
                      "导入问卷,q2,rating,打分,1;2;3;4;5,false,3,服务\n"
                      ).encode("utf-8-sig"))
        bid = up.json()["batch"]["batch_id"]
        c.post(f"/api/v1/import/batches/{bid}/dry-run", headers=h)
        b = c.post(f"/api/v1/import/batches/{bid}/commit",
                   headers=h).json()["batch"]
        assert b["status"] == "committed", b["errors"]
        up = _upload(c, h, "survey_logic_v1",
                     ("survey_name,from_question,op,value,to_question\n"
                      "导入问卷,q1,eq,否,q2\n").encode("utf-8-sig"))
        bid = up.json()["batch"]["batch_id"]
        c.post(f"/api/v1/import/batches/{bid}/dry-run", headers=h)
        b = c.post(f"/api/v1/import/batches/{bid}/commit",
                   headers=h).json()["batch"]
        assert b["status"] == "committed", b["errors"]
        # draft 中真实存在题目与跳题
        row = bundle.store._conn.execute(
            "SELECT spec_json FROM survey_definition_v1 WHERE name="
            "'导入问卷' ORDER BY version DESC LIMIT 1").fetchone()
        spec = json.loads(row["spec_json"])
        assert len(spec["questions"]) == 2
        assert spec["skip_logic"][0]["to"] == "q2"

    def test_rate_card_new_version(self, client):
        c, h, bundle = client
        up = _upload(c, h, "usage_rate_cards_v1",
                     ("rate_card_id,name,unit,price,currency\n"
                      "rc-import,导入价目,recognition_photo,0.6,CNY\n"
                      "rc-import,导入价目,model_compute_ms,0.002,CNY\n"
                      ).encode("utf-8-sig"))
        bid = up.json()["batch"]["batch_id"]
        c.post(f"/api/v1/import/batches/{bid}/dry-run", headers=h)
        b = c.post(f"/api/v1/import/batches/{bid}/commit",
                   headers=h).json()["batch"]
        assert b["status"] == "committed", b["errors"]
        row = bundle.store._conn.execute(
            "SELECT lines_json FROM fin_rate_card_v1"
            " WHERE rate_card_id='rc-import'").fetchone()
        lines = json.loads(row["lines_json"])
        assert {l["unit"] for l in lines} == {
            "recognition_photo", "model_compute_ms"}
