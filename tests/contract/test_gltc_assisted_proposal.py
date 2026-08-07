"""GLTC-004 契约测试：assisted proposal 接线与 blind 隔离（任务书 Task 4）。

- 项目 19（diag_v2_assisted）允许回填；项目 20（diag_v2_blind）永不；
- proposal append-only/幂等；零检出标 no_proposal 且保留人工入口；
- proposal 永不写 gold_region（predictions_from_recognition 状态恒 unreviewed）。
"""
from __future__ import annotations

import io

import pytest
from PIL import Image

from src.ls_platform import backfill as B


def _real_png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (16, 16)).save(buf, "PNG")
    return buf.getvalue()


_REAL_PNG = _real_png()


class FakeLS:
    """最小 LS 桩：只支持回填链路所需方法。"""

    def __init__(self, project: dict, tasks: list[dict],
                 predictions: dict[int, list[dict]] | None = None):
        self.project = project
        self.tasks = tasks
        self.predictions = predictions or {}
        self.created: list[tuple[int, str]] = []
        self.meta_updates: list[tuple[int, dict]] = []

    def get_project(self, pid):
        return self.project

    def list_tasks(self, pid, page=1, page_size=100):
        return list(self.tasks)

    def get_task(self, tid):
        t = next(x for x in self.tasks if x["id"] == tid)
        return {**t, "predictions": self.predictions.get(tid, [])}

    def fetch_file(self, path):
        return _REAL_PNG

    def create_prediction(self, tid, result, score=0.5, model_version=""):
        self.created.append((tid, model_version))

    def update_task_meta(self, tid, patch: dict):
        self.meta_updates.append((tid, patch))


class FakeRecognitionEmpty:
    """零检出识别桩（真实 recognize 返回 {'products': [...]}）。"""

    def recognize(self, data):
        return {"products": []}


def _assisted_project():
    return {"id": 19, "title": "diag_v2_assisted"}


def _tasks(n=2):
    return [{"id": 100 + i, "data": {"image": f"/data/upload/{i}.jpg"}}
            for i in range(n)]


class TestAssistedSelection:
    def test_diag_v2_assisted_is_assisted(self):
        assert B._is_assisted({"title": "diag_v2_assisted"})
        assert B._is_assisted({"title": "M4-trial10 [assisted]"})

    def test_blind_projects_never_assisted(self):
        for title in ("diag_v2_blind", "M4-trial10 [blind]",
                      "SKU 检测标注与审核"):
            assert not B._is_assisted({"title": title})

    def test_scan_blind_project_raises(self):
        ls = FakeLS({"id": 20, "title": "diag_v2_blind"}, _tasks())
        with pytest.raises(B.BackfillGuardError):
            B.scan_project(ls, 20, registry={})


class TestNoProposalMarking:
    def test_zero_detection_marked_no_proposal(self):
        ls = FakeLS(_assisted_project(), _tasks(2))
        rep = B.backfill_project(ls, FakeRecognitionEmpty(), 19,
                                 registry={}, apply=True)
        # 零检出：不新增 prediction，但逐任务标 no_proposal
        assert rep["added"] == 0
        assert sorted(rep["no_proposal_tasks"]) == [100, 101]
        metas = dict(ls.meta_updates)
        assert metas[100]["no_proposal"] is True
        assert "人工检查漏标" in metas[100]["no_proposal_note"]

    def test_idempotent_no_proposal_not_duplicated(self):
        ls = FakeLS(_assisted_project(), _tasks(1),
                    predictions={})
        # 第一次标记
        B.backfill_project(ls, FakeRecognitionEmpty(), 19,
                           registry={}, apply=True)
        # 模拟已标记：meta 已含 no_proposal
        ls.tasks[0]["meta"] = {"no_proposal": True}
        ls.meta_updates.clear()
        rep = B.backfill_project(ls, FakeRecognitionEmpty(), 19,
                                 registry={}, apply=True)
        assert ls.meta_updates == [], "已标记任务不得重复写 meta"
        assert rep["skipped_idempotent"] >= 1
