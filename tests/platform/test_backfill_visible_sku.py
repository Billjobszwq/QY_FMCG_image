"""历史 prediction 幂等回填契约（指令第七节）：

- dry-run 只扫描不写入；
- 追加 <原版本>@visible-sku-v2，不删除/覆盖旧 prediction、不动 annotation；
- 同一 task + model_version 重复执行必须跳过；
- blind 项目永不回填（守卫抛错）。
"""
from __future__ import annotations

import io

import pytest
from PIL import Image

from src.ls_platform.backfill import (
    BACKFILL_SUFFIX,
    BackfillGuardError,
    backfill_project,
    scan_project,
)

REGISTRY = {
    "可口可乐500ml": {"sku_id": "QY_KK_000001", "name": "可口可乐500ml",
                   "class_id": 1},
}

BOX = {"x": 5.0, "y": 5.0, "width": 20.0, "height": 30.0, "rotation": 0}
OLD_MV = "legacy.recognition.v2@cascade_v3"


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (320, 240), (200, 30, 30)).save(buf, format="PNG")
    return buf.getvalue()


def _box_only_result() -> list[dict]:
    return [{"id": "r0", "from_name": "box", "to_name": "image",
             "type": "rectanglelabels",
             "value": {**BOX, "rectanglelabels": ["product"]}}]


class FakeRecognition:
    def recognize(self, image_bytes: bytes, conf: float = 0.25) -> dict:
        return {"run_id": "fake", "count": 1, "products": [
            {"box": [16, 12, 80, 84], "sku_id": "QY_KK_000001",
             "name": "可口可乐500ml", "confidence": 0.9, "margin": 0.4,
             "source": "classifier", "status": "accepted"}],
            "elapsed_ms": 1, "model": "fake"}


class FakeLS:
    def __init__(self):
        self.projects: dict[int, dict] = {}
        self.tasks: dict[int, list[dict]] = {}
        self.predictions: dict[int, list[dict]] = {}
        self.annotations: dict[int, list[dict]] = {}
        self.files: dict[str, bytes] = {}
        self._pred_id = 0

    def add_project(self, pid, title):
        self.projects[pid] = {"id": pid, "title": title}
        self.tasks[pid] = []

    def add_task(self, pid, tid, image="/data/upload/x.jpg"):
        self.tasks[pid].append({"id": tid, "data": {"image": image},
                                "total_predictions": 0,
                                "total_annotations": 0})
        self.files[image] = _png()

    def add_prediction(self, tid, result, model_version):
        self.predictions.setdefault(tid, []).append(
            {"id": self._pid_next(), "result": result,
             "model_version": model_version, "score": 1.0})

    def _pid_next(self):
        self._pred_id += 1
        return self._pred_id

    # ---- LS client 接口 ----
    def get_project(self, pid):
        return self.projects[pid]

    def list_projects(self):
        return list(self.projects.values())

    def list_tasks(self, pid, page=1, page_size=100):
        return list(self.tasks[pid])

    def get_task(self, tid):
        for tasks in self.tasks.values():
            for t in tasks:
                if t["id"] == tid:
                    return {**t, "predictions": self.predictions.get(tid, []),
                            "annotations": self.annotations.get(tid, [])}
        raise KeyError(tid)

    def fetch_file(self, path):
        return self.files[path]

    def create_prediction(self, task_id, result, score=0.5,
                          model_version="yolo", meta=None):
        self._pred_id += 1
        self.predictions.setdefault(task_id, []).append(
            {"id": self._pred_id, "result": result, "score": score,
             "model_version": model_version, "meta": meta})
        return {"id": self._pred_id, "task": task_id}


@pytest.fixture()
def ls():
    fake = FakeLS()
    fake.add_project(10, "M4-trial10 [assisted]")
    fake.add_project(11, "M4-trial10 [blind]")
    # task 100：旧版 box-only prediction；task 101：无 prediction
    fake.add_task(10, 100, "/data/upload/10/a.jpg")
    fake.add_task(10, 101, "/data/upload/10/b.jpg")
    fake.add_prediction(100, _box_only_result(), OLD_MV)
    # blind 项目同样有 task，但永不能被回填
    fake.add_task(11, 200, "/data/upload/11/c.jpg")
    return fake


def test_dry_run_scan_classifies_and_writes_nothing(ls) -> None:
    report = scan_project(ls, 10, REGISTRY)
    assert report["stats"]["tasks"] == 2
    assert report["stats"]["box_only"] == 1
    assert report["stats"]["no_prediction"] == 1
    assert report["stats"]["will_add_predictions"] == 2
    # dry-run 不得写入任何 prediction
    assert len(ls.predictions.get(100, [])) == 1
    assert not ls.predictions.get(101)


def test_backfill_appends_visible_sku_without_touching_history(ls) -> None:
    old_pred = ls.predictions[100][0]
    old_result_snapshot = list(old_pred["result"])
    ls.annotations[100] = [{"id": 9, "result": _box_only_result()}]

    report = backfill_project(ls, FakeRecognition(), 10, registry=REGISTRY,
                              apply=True)
    assert report["added"] == 2  # 每 task 各 1 个区域
    assert report["errors"] == []

    # 新 prediction：原版本 + 后缀，含同 region id 的 taxonomy
    new100 = [p for p in ls.predictions[100]
              if p["model_version"] == OLD_MV + BACKFILL_SUFFIX]
    assert len(new100) == 1
    taxes = [r for r in new100[0]["result"] if r["type"] == "taxonomy"]
    assert taxes[0]["value"]["taxonomy"] == [["可口可乐500ml"]]
    rects = [r for r in new100[0]["result"]
             if r["type"] == "rectanglelabels"]
    assert taxes[0]["id"] == rects[0]["id"]  # 同 region id

    # 红线：旧 prediction 原样保留，annotation 未被触碰
    assert len(ls.predictions[100]) == 2
    assert ls.predictions[100][0]["result"] == old_result_snapshot
    assert ls.predictions[100][0]["model_version"] == OLD_MV
    assert len(ls.annotations[100]) == 1


def test_backfill_is_idempotent_per_task_and_version(ls) -> None:
    r1 = backfill_project(ls, FakeRecognition(), 10, registry=REGISTRY,
                          apply=True)
    n1 = {tid: len(ps) for tid, ps in ls.predictions.items()}
    r2 = backfill_project(ls, FakeRecognition(), 10, registry=REGISTRY,
                          apply=True)
    n2 = {tid: len(ps) for tid, ps in ls.predictions.items()}
    assert r1["added"] == 2
    assert r2["added"] == 0
    assert r2["skipped_idempotent"] == 2
    assert n1 == n2  # 重复执行零写入


def test_blind_project_never_backfilled(ls) -> None:
    with pytest.raises(BackfillGuardError):
        scan_project(ls, 11, REGISTRY)
    with pytest.raises(BackfillGuardError):
        backfill_project(ls, FakeRecognition(), 11, registry=REGISTRY,
                         apply=True)
    assert not ls.predictions.get(200)  # blind task 仍 0 prediction
