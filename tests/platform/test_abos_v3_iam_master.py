"""ABOSV3 T3 红测试：IAM 自定义与主数据运营（P1-008/P1-009）。

- 自定义角色创建（scope 白名单 fail-closed）；
- 权限模拟器回答"能否/为什么"；
- 客户/项目/SKU 停用（不删除）；
- 合并建议（规范化重名检测）。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.composition.build import (build_production_bundle,
                                   build_profiles_service)
from src.platform.api.app import create_app
from src.platform.iam import IAMService, MasterDataService

PW = "v3-iam-pw"


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
    h = {"X-CSRF-Token": r.json()["csrf_token"]}
    return c, h, bundle


class TestCustomRolesAndSimulator:
    def test_create_role_whitelist_and_simulate(self, client):
        c, h, bundle = client
        # 白名单外的 scope 必须 409（fail-closed）
        r = c.post("/api/v1/iam/roles", headers=h, json={
            "name": "危险角色", "scopes": ["not_real.scope"]})
        assert r.status_code == 409
        # 合法自定义角色
        r = c.post("/api/v1/iam/roles", headers=h, json={
            "name": "导入分析员", "scopes": ["survey.read",
                                             "analytics.read"]})
        assert r.status_code == 200, r.text
        roles = c.get("/api/v1/iam/roles").json()["roles"]
        hit = next(x for x in roles if x["name"] == "导入分析员")
        assert sorted(hit["scopes"]) == ["analytics.read", "survey.read"]
        assert hit["builtin"] is False
        # 建用户 + 授权 cust-a，模拟器回答能否
        c.post("/api/v1/iam/principals", headers=h, json={
            "kind": "user", "username": "simuser", "password": "pw-x-1"})
        iam = IAMService(bundle.store)
        md = MasterDataService(bundle.store, iam)
        md.create_customer(customer_id="cust-a", name="A",
                           created_by="admin")
        md.create_customer(customer_id="cust-b", name="B",
                           created_by="admin")
        c.post("/api/v1/iam/grants", headers=h, json={
            "username": "simuser", "role": "导入分析员",
            "customer_id": "cust-a"})
        ok = c.get("/api/v1/iam/simulate", params={
            "username": "simuser", "scope": "survey.read",
            "customer_id": "cust-a"}).json()
        assert ok["allowed"] is True and ok["reasons"]
        deny = c.get("/api/v1/iam/simulate", params={
            "username": "simuser", "scope": "survey.read",
            "customer_id": "cust-b"}).json()
        assert deny["allowed"] is False
        assert any("作用域不匹配" in x for x in deny["reasons"])
        # 未注册 scope 直接 fail-closed
        bad = c.get("/api/v1/iam/simulate", params={
            "username": "simuser", "scope": "x.y"}).json()
        assert bad["allowed"] is False and "未注册" in bad["reasons"][0]


class TestMasterOps:
    def test_deactivate_and_duplicates(self, client):
        c, h, bundle = client
        iam = IAMService(bundle.store)
        md = MasterDataService(bundle.store, iam)
        md.create_customer(customer_id="c1", name="同名客户",
                           created_by="admin")
        md.create_customer(customer_id="c2", name="同名客户",
                           created_by="admin")
        md.create_sku(sku_id="s1", canonical_name="同款商品",
                      created_by="admin")
        md.create_sku(sku_id="s2", canonical_name="同款 商品",
                      created_by="admin")
        # 合并建议：规范化重名被检出
        dup = c.get("/api/v1/master/duplicates").json()
        assert any(sorted(g["ids"]) == ["c1", "c2"]
                   for g in dup["customers"])
        assert any(sorted(g["ids"]) == ["s1", "s2"]
                   for g in dup["skus"])
        # 停用（不删除）
        r = c.post("/api/v1/master/customer/c1/status", headers=h,
                   json={"status": "inactive"})
        assert r.status_code == 200, r.text
        assert md.get_customer("c1")["status"] == "inactive"
        # 非法状态拒绝
        r = c.post("/api/v1/master/customer/c1/status", headers=h,
                   json={"status": "deleted"})
        assert r.status_code == 409
        # 审计留痕
        audits = [a for a in iam.list_audit()
                  if a["action"] == "master.customer.status_changed"]
        assert audits
