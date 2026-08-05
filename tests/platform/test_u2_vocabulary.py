"""U2-4 红测试：统一任务状态词汇；业务语言默认、技术字段折叠。

手册 §4：标注、审核、训练、识别、Graph Run 使用统一任务状态；
默认使用业务语言，M4/M5、hash 和 raw JSON 放到高级详情。

当前 workitems 状态列直接回显 dry_run/queued/pending 等英文技术
状态，技术字段散落在顶层，本测试必须 RED。
"""
from __future__ import annotations

from pathlib import Path

import pytest


def test_unified_vocabulary_covers_all_kinds():
    """五类任务（标注/审核/训练/识别/Graph Run）全部有业务语言映射。"""
    from src.platform.vocabulary import UNIFIED_STATUS, status_text

    graph_statuses = ["pending", "running", "waiting_human",
                      "completed", "failed", "cancelled"]
    for st in graph_statuses:
        assert status_text("graph_run", st) in UNIFIED_STATUS, st
        assert status_text("graph_run", st) != st, (
            f"Graph Run 状态 {st} 必须翻译为业务语言")
    for kind, st in [("training", "dry_run"), ("training", "approved"),
                     ("training", "queued"), ("job", "running"),
                     ("human_review", "pending"),
                     ("recognition", "completed"),
                     ("labeling", "pending")]:
        out = status_text(kind, st)
        assert out in UNIFIED_STATUS, (kind, st, out)


def test_status_text_is_business_language():
    from src.platform.vocabulary import status_text

    cases = [
        ("training", "dry_run", "待批准"),
        ("training", "approved", "已批准"),
        ("training", "queued", "等待执行"),
        ("training", "running", "执行中"),
        ("training", "completed", "已完成"),
        ("job", "failed", "失败"),
        ("human_review", "pending", "待人工审核"),
        ("recognition", "completed", "已完成"),
        ("graph_run", "waiting_human", "等待人工"),
    ]
    for kind, st, want in cases:
        got = status_text(kind, st)
        assert want in got, f"{kind}/{st} -> {got!r}，应包含 {want!r}"
        assert got.isascii() is False, f"{kind}/{st} 必须是中文业务语言"


def test_workitems_items_carry_status_text(tmp_path: Path, monkeypatch):
    """workitems 每条必须带业务语言 status_text；技术字段只在 detail。"""
    import json
    from fastapi.testclient import TestClient

    from src.composition.build import build_production_bundle
    from src.platform.api.app import create_app

    rq = tmp_path / "rq.json"
    rq.write_text(json.dumps({
        "protocol": "diagnostic_v1",
        "items": [{"photo_id": "p1", "status": "pending"}]},
        ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("PLATFORM_REVIEW_QUEUE", str(rq))

    bundle = build_production_bundle(
        db_path=tmp_path / "p.sqlite", cas_root=tmp_path / "cas",
        recognition_adapter=None, monitor_adapter=None,
        label_studio_adapter=None,
        probe=lambda spec: None)
    app = create_app(services=(), probe=lambda spec: None, bundle=bundle,
                     web_dist=tmp_path / "none")
    c = TestClient(app)
    d = c.get("/api/v1/workitems").json()
    assert d["count"] >= 1
    for w in d["items"]:
        assert "status_text" in w and w["status_text"], w
        assert w["status_text"].isascii() is False, w
        # 技术字段不得散落在顶层：hash/run_id/job_id/photo_id 只进 detail
        for tech in ("sha256", "run_id", "job_id", "photo_id"):
            assert tech not in w, (tech, w)
