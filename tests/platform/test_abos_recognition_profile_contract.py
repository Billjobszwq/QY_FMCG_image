"""ABOS T7：Recognition Profile 契约（fail-closed + 回显 + 同源）。"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.composition.build import (build_production_bundle,
                                   build_profiles_service,
                                   build_training_router)
from src.platform.api.app import create_app
from src.platform.api.health import ServiceSpec, ServiceStatus
from src.platform.api.recognition_tasks import (
    ProfileResolveError, resolve_profile, validate_profile_input)


def _fake_probe(spec: ServiceSpec) -> ServiceStatus:
    return ServiceStatus(name=spec.name, status="healthy", latency_ms=1,
                         detail="fake")


class FakeProfiles:
    def __init__(self, profiles):
        self._p = profiles

    def list_profiles(self):
        return self._p


@pytest.fixture()
def client(tmp_path: Path, monkeypatch):
    from tests.platform.test_m5_training_gov import (
        FakeLS, FakeMonitor, FakeRecognition)

    monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD", "abos-t7-pw")
    fake_rec = FakeRecognition()
    bundle = build_production_bundle(
        db_path=tmp_path / "p.sqlite", cas_root=tmp_path / "cas",
        recognition_adapter=fake_rec, monitor_adapter=FakeMonitor(),
        label_studio_adapter=FakeLS(), probe=_fake_probe)
    app = create_app(services=(), probe=_fake_probe, bundle=bundle,
                     recognition_adapter=fake_rec,
                     training_router=build_training_router(bundle),
                     profiles_service=build_profiles_service(bundle),
                     web_dist=tmp_path / "none")
    return TestClient(app), bundle


def _login(c: TestClient) -> dict:
    r = c.post("/api/v1/auth/login",
               json={"username": "admin", "password": "abos-t7-pw"})
    return {"X-CSRF-Token": r.json()["csrf_token"]}


# ---------------- resolve 单元契约 ----------------


def test_weight_path_input_rejected():
    for bad in ("../../.models/x.pt", ".models/sku_v5/best.pt",
                "a/b", "a\\b", ""):
        with pytest.raises(ProfileResolveError):
            validate_profile_input(bad)


def test_unknown_profile_fail_closed():
    svc = FakeProfiles([{"profile_id": "production_legacy",
                         "status": "enabled", "blockers": []}])
    with pytest.raises(ProfileResolveError):
        resolve_profile("not_registered_x", svc)


def test_disabled_profile_fail_closed():
    svc = FakeProfiles([{"profile_id": "exp_x", "status": "disabled",
                         "blockers": ["m: PENDING"]}])
    with pytest.raises(ProfileResolveError) as ei:
        resolve_profile("exp_x", svc)
    assert ei.value.blockers


def test_no_profiles_service_fail_closed():
    with pytest.raises(ProfileResolveError):
        resolve_profile("production_legacy", None)


# ---------------- API 行为契约 ----------------


def test_upload_with_profile_echoes_frozen_contract(client, tmp_path):
    c, bundle = client
    h = _login(c)
    img = tmp_path / "shelf.jpg"
    img.write_bytes(b"\xff\xd8fakejpeg")
    r = c.post("/api/v1/recognition/tasks/upload",
               files=[("files", ("shelf.jpg", img.read_bytes(),
                                 "image/jpeg"))],
               data={"recognition_profile_id": "production_legacy",
                     "service_tier": "standard", "source": "web",
                     "project_id": "proj-demo"},
               headers=h)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["recognition_profile_id"] == "production_legacy"
    assert d["service_tier"] == "standard"
    assert d["source"] == "web"
    assert d["trace_id"].startswith("tr-")
    task = d["task"]
    assert task["recognition_profile_id"] == "production_legacy"
    assert task["project_id"] == "proj-demo"
    assert task["trace_id"] == d["trace_id"]


def test_upload_unknown_profile_rejected(client, tmp_path):
    c, _ = client
    h = _login(c)
    r = c.post("/api/v1/recognition/tasks/upload",
               files=[("files", ("a.jpg", b"\xff\xd8x", "image/jpeg"))],
               data={"recognition_profile_id": "not_a_profile"},
               headers=h)
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "profile_rejected"


def test_upload_weight_path_rejected(client):
    c, _ = client
    h = _login(c)
    r = c.post("/api/v1/recognition/tasks/upload",
               files=[("files", ("a.jpg", b"\xff\xd8x", "image/jpeg"))],
               data={"recognition_profile_id": ".models/sku_v5/best.pt"},
               headers=h)
    assert r.status_code == 400


def test_disabled_profile_rejected_with_blockers(client):
    """research83_* 组件未达 CANDIDATE → disabled → 拒绝并给 blockers。"""
    c, _ = client
    h = _login(c)
    profs = c.get("/api/v1/recognition/profiles").json()["profiles"]
    disabled = next((p for p in profs if p["status"] == "disabled"), None)
    if disabled is None:
        pytest.skip("当前无 disabled profile")
    r = c.post("/api/v1/recognition/tasks/upload",
               files=[("files", ("a.jpg", b"\xff\xd8x", "image/jpeg"))],
               data={"recognition_profile_id": disabled["profile_id"]},
               headers=h)
    assert r.status_code == 400
    assert r.json()["detail"]["blockers"]


def test_url_entry_same_profile_contract(client, monkeypatch):
    c, _ = client
    h = _login(c)
    import src.platform.api.recognition_tasks as rt
    monkeypatch.setattr(rt, "fetch_url_bytes",
                        lambda url, timeout=10.0: b"\xff\xd8urlbytes")
    r = c.post("/api/v1/recognition/tasks/url", headers=h,
               json={"url": "https://example.com/x.jpg",
                     "recognition_profile_id": "production_legacy",
                     "service_tier": "standard", "source": "web"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["recognition_profile_id"] == "production_legacy"
    assert d["task"]["entry"] == "url"


def test_profiles_endpoint_live(client):
    c, _ = client
    d = c.get("/api/v1/recognition/profiles").json()
    assert d["count"] >= 1
    ids = {p["profile_id"] for p in d["profiles"]}
    assert "production_legacy" in ids
    prod = next(p for p in d["profiles"]
                if p["profile_id"] == "production_legacy")
    assert prod["status"] == "enabled"


def test_invalid_tier_rejected(client):
    c, _ = client
    h = _login(c)
    r = c.post("/api/v1/recognition/tasks/upload",
               files=[("files", ("a.jpg", b"\xff\xd8x", "image/jpeg"))],
               data={"recognition_profile_id": "production_legacy",
                     "service_tier": "turbo"},
               headers=h)
    assert r.status_code == 400
