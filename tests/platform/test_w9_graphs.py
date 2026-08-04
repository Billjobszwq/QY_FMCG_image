"""W9 TDD：fmcg_photo_inspection_v1 全链 + system_health_v1 非识别验证。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.composition.build import build_production_bundle
from src.modules.fmcg import GRAPH_NAME as FMCG
from src.modules.system_health import GRAPH_NAME as SYSHEALTH
from src.platform.api.app import create_app
from src.platform.api.health import ServiceSpec, ServiceStatus

FAKE_JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 4096


class FakeRecognition:
    def __init__(self, count: int = 2):
        self.calls = 0
        self._count = count

    def recognize(self, image_bytes: bytes, conf: float = 0.25) -> dict:
        self.calls += 1
        return {
            "run_id": "upstream-1",
            "products": [
                {"sku_id": "sku-1", "name": "测试SKU", "confidence": 0.9,
                 "box": [1, 2, 3, 4], "margin": None, "yolo_name": None,
                 "yolo_confidence": None, "source": "classifier", "needs_review": False}
            ] if self._count else [],
            "count": self._count,
            "elapsed_ms": 1,
            "model": "fake",
        }


class FakeMonitor:
    def live(self) -> dict:
        return {"ok": True}

    def overview(self) -> dict:
        return {"ok": True}


def _fake_probe(spec: ServiceSpec) -> ServiceStatus:
    status = "healthy" if spec.name != "label_studio" else "unavailable"
    return ServiceStatus(name=spec.name, status=status, latency_ms=1, detail="fake")


@pytest.fixture()
def bundle(tmp_path: Path):
    b = build_production_bundle(
        db_path=tmp_path / "platform.sqlite",
        cas_root=tmp_path / "cas",
        recognition_adapter=FakeRecognition(),
        monitor_adapter=FakeMonitor(),
        probe=_fake_probe,
    )
    yield b
    b.store.close()


# ---------- system_health_v1：非识别 Graph，证明 Kernel 无 FMCG 硬编码 ----------

def test_system_health_graph_runs(bundle) -> None:
    run = bundle.engine.start_run(SYSHEALTH, "1", {})
    out = bundle.engine.execute(run["run_id"], bundle.handlers_for(SYSHEALTH))
    assert out["status"] == "completed"
    summary = json.loads(out["output_json"])["summarize"]
    assert summary["total"] == 5
    assert "label_studio" in summary["unhealthy"]
    assert summary["overall"] == "degraded"


# ---------- fmcg 全链：upload→CAS→quality→recognize→人工门→Evidence→Result ----------

def test_fmcg_full_flow_with_human_gate(bundle) -> None:
    rec: FakeRecognition = bundle.capabilities.get("legacy.recognition.v2")
    ref = bundle.cas.put(FAKE_JPEG, kind="photo")
    run = bundle.engine.start_run(FMCG, "1", {"photo_sha256": ref.sha256})
    out = bundle.engine.execute(run["run_id"], bundle.handlers_for(FMCG))
    assert out["status"] == "waiting_human", "人工门必须真实暂停"
    assert rec.calls == 1

    bundle.engine.approve_human_gate(run["run_id"], approved=True, actor="tester")
    out2 = bundle.engine.execute(run["run_id"], bundle.handlers_for(FMCG))
    assert out2["status"] == "completed"
    assert rec.calls == 1, "恢复后不得重复识别（副作用幂等）"

    final = json.loads(out2["output_json"])["finalize"]
    assert final["recognition_result"]["count"] == 2
    assert final["evidence_id"]

    # Evidence / Usage / Audit 持久化
    ev = bundle.store.list_evidence(run["run_id"])
    assert len(ev) == 1
    manifest = json.loads(ev[0]["manifest_json"])
    roles = {i["role"] for i in manifest["items"]}
    assert roles == {"input_photo", "recognition_output"}
    assert len(bundle.store.list_usage(run_id=run["run_id"])) == 1
    actions = [a["action"] for a in bundle.store.list_audit(subject_id=run["run_id"])]
    assert "gate.approved" in actions and "run.completed" in actions


def test_fmcg_quality_fail_closed(bundle) -> None:
    ref = bundle.cas.put(b"tiny", kind="photo")  # 过小且非图像 magic
    run = bundle.engine.start_run(FMCG, "1", {"photo_sha256": ref.sha256})
    out = bundle.engine.execute(run["run_id"], bundle.handlers_for(FMCG))
    assert out["status"] == "failed"
    assert "quality_fail" in (out["error"] or "")


# ---------- API 层 E2E（TestClient） ----------

def test_runs_api_flow(bundle) -> None:
    from fastapi.testclient import TestClient

    app = create_app(services=(), probe=_fake_probe, bundle=bundle)
    client = TestClient(app)

    r = client.post(
        "/api/v1/assets/upload",
        files={"file": ("photo.jpg", FAKE_JPEG, "image/jpeg")},
    )
    assert r.status_code == 200
    sha = r.json()["sha256"]

    r2 = client.post(
        "/api/v1/runs",
        json={"graph_name": FMCG, "input": {"photo_sha256": sha}, "idempotency_key": f"k-{sha}"},
    )
    assert r2.status_code == 200
    body = r2.json()
    run_id = body["run"]["run_id"]
    assert body["run"]["status"] == "waiting_human"

    # 幂等：同 key 再发不产生新 run
    r3 = client.post(
        "/api/v1/runs",
        json={"graph_name": FMCG, "input": {"photo_sha256": sha}, "idempotency_key": f"k-{sha}"},
    )
    assert r3.json()["run"]["run_id"] == run_id

    r4 = client.post(f"/api/v1/runs/{run_id}/approve", json={"approved": True, "actor": "e2e"})
    assert r4.json()["run"]["status"] == "completed"
    nodes = [n["node_name"] for n in r4.json()["nodes"]]
    assert nodes[:3] == ["ingest", "quality", "recognize"]

    r5 = client.get("/api/v1/runs")
    assert r5.json()["count"] >= 1

    # system_health 经 API
    r6 = client.post("/api/v1/runs", json={"graph_name": SYSHEALTH, "input": {}})
    assert r6.json()["run"]["status"] == "completed"
