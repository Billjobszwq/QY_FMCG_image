"""M4 TDD：Label Studio 闭环 —— assisted/blind 分离、webhook 去重、API 对账。"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from src.composition.build import build_labeling_router, build_production_bundle
from src.modules.labeling import LabelingService
from src.modules.labeling.service import box_px_to_ls_result, canonical_event_id
from src.platform.api.app import create_app
from src.platform.api.health import ServiceSpec, ServiceStatus
from src.platform.data.store import PlatformStore

LABEL_CONFIG = "<View><Image name='image' value='$image'/></View>"


class FakeLabelStudio:
    """内存版 LS：项目/任务/prediction/webhook。"""

    def __init__(self):
        self.projects: dict[int, dict] = {}
        self.tasks: dict[int, list[dict]] = {}
        self.predictions: dict[int, list[dict]] = {}
        self.webhooks: list[dict] = []
        self._pid = 0
        self._tid = 0
        self._wid = 0

    def create_project(self, title, label_config, description=""):
        self._pid += 1
        p = {"id": self._pid, "title": title, "label_config": label_config,
             "description": description}
        self.projects[self._pid] = p
        self.tasks[self._pid] = []
        return p

    def create_webhook(self, project_id, url, actions):
        self._wid += 1
        wh = {"id": self._wid, "project": project_id, "url": url, "actions": actions}
        self.webhooks.append(wh)
        return wh

    def import_files(self, project_id, files):
        ids = []
        for name, _data in files:
            self._tid += 1
            t = {"id": self._tid, "data": {"image": f"/data/upload/{project_id}/{name}"},
                 "total_annotations": 0, "total_predictions": 0}
            self.tasks[project_id].append(t)
            ids.append(self._tid)
        return {"task_count": len(ids), "task_ids": ids}

    def list_tasks(self, project_id, page_size=100):
        return [dict(t) for t in self.tasks[project_id]]

    def create_prediction(self, task_id, result, *, score, model_version):
        # 守卫：LS 真实校验拒绝非 dict 元素（嵌套 list 会 400）
        assert isinstance(result, list) and all(isinstance(r, dict) for r in result), \
            f"prediction result 含非法元素: {result!r}"
        for pid, tasks in self.tasks.items():
            for t in tasks:
                if t["id"] == task_id:
                    t["total_predictions"] += 1
                    self.predictions.setdefault(task_id, []).append(
                        {"result": result, "score": score, "model_version": model_version,
                         "project_id": pid})
                    return {"id": len(self.predictions[task_id]), "task": task_id}
        raise KeyError(task_id)

    # 测试辅助：模拟人工标注事件
    def annotate(self, task_id):
        for tasks in self.tasks.values():
            for t in tasks:
                if t["id"] == task_id:
                    t["total_annotations"] += 1
                    return t
        raise KeyError(task_id)


class FakeRecognition:
    def recognize(self, image_bytes: bytes, conf: float = 0.25) -> dict:
        return {"run_id": "fake", "count": 1, "products": [
            {"sku_id": "sku-1", "name": "测试SKU", "confidence": 0.9,
             "box": [10, 20, 110, 220]}], "elapsed_ms": 1, "model": "fake"}


class FakeMonitor:
    def live(self):
        return {"ok": True}

    def overview(self):
        return {"ok": True}


def _fake_probe(spec: ServiceSpec) -> ServiceStatus:
    return ServiceStatus(name=spec.name, status="healthy", latency_ms=1, detail="fake")


def _png(w=320, h=240, color=(200, 30, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture()
def store(tmp_path: Path):
    s = PlatformStore(tmp_path / "platform.sqlite")
    yield s
    s.close()


@pytest.fixture()
def service(store):
    return LabelingService(store, FakeLabelStudio())


# ---------- box 换算 ----------

def test_box_px_to_ls_result() -> None:
    r = box_px_to_ls_result((100, 50, 300, 250), 1000, 500)
    assert r["value"]["x"] == 10.0
    assert r["value"]["y"] == 10.0
    assert r["value"]["width"] == 20.0
    assert r["value"]["height"] == 40.0
    assert r["value"]["rectanglelabels"] == ["product"]


def test_box_invalid_raises() -> None:
    from src.modules.labeling import LabelingError

    with pytest.raises(LabelingError):
        box_px_to_ls_result((0, 0, 0, 0), 100, 100)
    with pytest.raises(LabelingError):
        box_px_to_ls_result((0, 0, 10, 10), 0, 100)


# ---------- assisted/blind 项目分离 ----------

def test_batch_creates_two_projects_and_webhooks(service) -> None:
    out = service.create_batch("trial10", LABEL_CONFIG)
    ls: FakeLabelStudio = service.ls
    titles = [p["title"] for p in ls.projects.values()]
    assert any("[assisted]" in t for t in titles)
    assert any("[blind]" in t for t in titles)
    assert len(ls.webhooks) == 2
    assert out["webhook_error"] is None
    batch = service.get_batch(out["batch"]["batch_id"])
    assert batch["status"] == "created"


def test_import_writes_predictions_only_to_assisted(service) -> None:
    out = service.create_batch("trial10", LABEL_CONFIG)
    bid = out["batch"]["batch_id"]
    photos = [("a.png", _png()), ("b.png", _png())]
    preds = {"a.png": [{"score": 0.9, "result": [
        box_px_to_ls_result((10, 20, 110, 220), 320, 240)]}]}
    report = service.import_photos(bid, photos, assisted_predictions=preds,
                                   model_version="fake@1")
    ls: FakeLabelStudio = service.ls

    assert report["predictions_written"] == 1
    assisted_tasks = ls.tasks[out["assisted_project_id"]]
    blind_tasks = ls.tasks[out["blind_project_id"]]
    assert len(assisted_tasks) == 2 and len(blind_tasks) == 2
    # 红线：blind 项目任何 task 都不得有 prediction
    assert all(t["total_predictions"] == 0 for t in blind_tasks)
    assert sum(t["total_predictions"] for t in assisted_tasks) == 1
    assert service.get_batch(bid)["status"] == "imported"


# ---------- webhook inbox 去重 ----------

def test_webhook_ingest_dedup(service) -> None:
    payload = {"action": "ANNOTATION_CREATED",
               "annotation": {"id": 7, "updated_at": "2026-08-05T00:00:00Z"},
               "project": {"id": 2}, "task": {"id": 5, "updated_at": "2026-08-05T00:00:01Z"}}
    r1 = service.ingest_webhook(payload)
    r2 = service.ingest_webhook(payload)  # 重放
    assert r1["accepted"] is True
    assert r2["accepted"] is False
    assert r1["event_id"] == r2["event_id"] == canonical_event_id("ANNOTATION_CREATED", payload)
    assert len(service.inbox(project_id=2)) == 1


def test_webhook_distinct_events_both_kept(service) -> None:
    base = {"action": "ANNOTATION_CREATED", "project": {"id": 2},
            "task": {"id": 5, "updated_at": "t1"}, "annotation": {"id": 7, "updated_at": "t1"}}
    service.ingest_webhook(base)
    other = dict(base, annotation={"id": 8, "updated_at": "t2"})
    assert service.ingest_webhook(other)["accepted"] is True
    assert len(service.inbox()) == 2


# ---------- 对账 ----------

def test_reconcile_consistent(service) -> None:
    out = service.create_batch("trial10", LABEL_CONFIG)
    bid = out["batch"]["batch_id"]
    service.import_photos(bid, [("a.png", _png())])
    ls: FakeLabelStudio = service.ls

    # 模拟 blind 项目一条人工标注 + webhook 事件
    blind_task = ls.tasks[out["blind_project_id"]][0]
    ls.annotate(blind_task["id"])
    service.ingest_webhook({"action": "ANNOTATION_CREATED",
                            "project": {"id": out["blind_project_id"]},
                            "task": {"id": blind_task["id"], "updated_at": "t"},
                            "annotation": {"id": 1, "updated_at": "t"}})

    report = service.reconcile(bid)
    assert report["projects"]["blind"]["annotations_api"] == 1
    assert report["projects"]["blind"]["consistent"] is True
    assert report["projects"]["assisted"]["annotations_api"] == 0
    assert report["blind_no_predictions"] is True
    assert report["consistent"] is True
    assert service.get_batch(bid)["status"] == "reconciled"


def test_reconcile_detects_missing_webhook(service) -> None:
    out = service.create_batch("trial10", LABEL_CONFIG)
    bid = out["batch"]["batch_id"]
    service.import_photos(bid, [("a.png", _png())])
    ls: FakeLabelStudio = service.ls
    t = ls.tasks[out["blind_project_id"]][0]
    ls.annotate(t["id"])  # API 有标注但 webhook 事件丢失
    report = service.reconcile(bid)
    assert report["projects"]["blind"]["annotations_api"] == 1
    assert report["projects"]["blind"]["inbox_annotation_events"] == 0
    assert report["projects"]["blind"]["consistent"] is False  # 显式标记，不谎报


# ---------- API E2E（TestClient + 组合根） ----------

def test_labeling_api_e2e(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    fake_ls = FakeLabelStudio()
    bundle = build_production_bundle(
        db_path=tmp_path / "p.sqlite", cas_root=tmp_path / "cas",
        recognition_adapter=FakeRecognition(), monitor_adapter=FakeMonitor(),
        label_studio_adapter=fake_ls, probe=_fake_probe)
    router = build_labeling_router(bundle)
    app = create_app(services=(), probe=_fake_probe, bundle=bundle,
                     labeling_router=router, web_dist=tmp_path / "none")
    client = TestClient(app)

    r = client.post("/api/v1/labeling/batches", json={"name": "trial10"})
    assert r.status_code == 200, r.text
    bid = r.json()["batch"]["batch_id"]

    files = [("files", ("p1.png", _png(), "image/png")),
             ("files", ("p2.png", _png(color=(30, 200, 30)), "image/png"))]
    r2 = client.post(f"/api/v1/labeling/batches/{bid}/import", files=files)
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["predictions_written"] == 2  # FakeRecognition 对每张图出 1 框
    assert body["prediction_failures"] == 0

    # blind 项目 0 prediction（红线）
    blind_pid = r.json()["blind_project_id"]
    assert all(t["total_predictions"] == 0 for t in fake_ls.tasks[blind_pid])

    # webhook：重复投递只收一次
    payload = {"action": "ANNOTATION_CREATED", "project": {"id": blind_pid},
               "task": {"id": fake_ls.tasks[blind_pid][0]["id"], "updated_at": "t"},
               "annotation": {"id": 1, "updated_at": "t"}}
    assert client.post("/api/v1/webhooks/label-studio", json=payload).json()["accepted"]
    assert not client.post("/api/v1/webhooks/label-studio", json=payload).json()["accepted"]
    assert client.get("/api/v1/labeling/inbox").json()["count"] == 1

    # 对账：API 无标注但 inbox 有 1 条 → 不一致显式标记
    r3 = client.get(f"/api/v1/labeling/batches/{bid}/reconcile")
    assert r3.status_code == 200, r3.text
    rep = r3.json()
    assert rep["projects"]["blind"]["inbox_annotation_events"] == 1
    assert rep["projects"]["blind"]["annotations_api"] == 0
    assert rep["projects"]["blind"]["consistent"] is False
    assert rep["blind_no_predictions"] is True
