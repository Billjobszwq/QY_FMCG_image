"""U3-5 红测试：qpol_v2 质量策略（十一维 + 全字段证据 + waiting_human）。

手册 §5/U4 指令：qpol_v2 覆盖斜拍、反光、翻拍、屏摄、摩尔纹、模糊、
商品大头照误导、裁切、遮挡、场景和价签；所有质量结论保留原图 SHA、
策略版本、分数、阈值、自动结论、人工结论、模型版本和证据；
人工尚未完成时必须显示 waiting_human，不得伪造通过。

当前平台没有 qpol_v2（仅 qpol_v1），本测试必须 RED。
"""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def store(tmp_path: Path):
    from src.platform.data.store import PlatformStore

    s = PlatformStore(tmp_path / "p.sqlite")
    yield s
    s.close()


def _img(kind: str, path: Path) -> Path:
    import numpy as np
    from PIL import Image, ImageFilter

    rng = np.random.default_rng(3)
    arr = rng.integers(60, 200, (160, 160, 3), dtype=np.uint8)
    img = Image.fromarray(arr)
    if kind == "blur":
        img = img.filter(ImageFilter.GaussianBlur(6))
    elif kind == "bright":
        img = Image.fromarray(np.full((160, 160, 3), 254, dtype=np.uint8))
    if kind == "bright":
        path = path.with_suffix(".png")  # 无损，避免 JPEG 伪影压低反光分
    img.save(path)
    return path


class TestQpolV2Dimensions:
    def test_eleven_dimensions_defined(self):
        from src.platform.quality.qpol_v2 import DIMENSIONS

        assert len(DIMENSIONS) == 11
        names = {d["name"] for d in DIMENSIONS}
        for need in ("tilt", "reflection", "rephoto", "screen_capture",
                     "moire", "blur", "product_closeup_mislead", "cropped",
                     "occlusion", "scene", "price_tag"):
            assert need in names, f"缺少维度 {need}"
        assert all(d["label"] for d in DIMENSIONS), "每维必须有中文标签"


class TestQpolV2EvidenceFields:
    def test_decision_records_all_fields(self, store, tmp_path):
        from src.platform.quality.qpol_v2 import evaluate_image

        p = _img("normal", tmp_path / "n.jpg")
        import hashlib
        sha = hashlib.sha256(p.read_bytes()).hexdigest()
        d = evaluate_image(store, sha256=sha, path=p)
        for k in ("sha256", "policy_version", "score", "threshold",
                  "auto_decision", "human_decision", "model_version",
                  "evidence"):
            assert k in d, f"缺少字段 {k}"
        assert d["policy_version"] == "qpol_v2"
        assert d["sha256"] == sha
        assert d["human_decision"] is None, "人工结论未完成必须为 None"
        assert d["score"], "必须带各维度分数"
        assert d["threshold"], "必须带各维度阈值"

    def test_decision_table_immutable(self, store, tmp_path):
        import sqlite3

        from src.platform.quality.qpol_v2 import evaluate_image

        p = _img("normal", tmp_path / "n.jpg")
        import hashlib
        sha = hashlib.sha256(p.read_bytes()).hexdigest()
        evaluate_image(store, sha256=sha, path=p)
        with pytest.raises(sqlite3.IntegrityError):
            store._conn.execute("DELETE FROM quality_decision_v1")


class TestWaitingHumanFailClosed:
    def test_auto_pass_forbidden_without_human(self, store, tmp_path):
        """人工未完成：自动结论不得是 pass 的整体判定。"""
        from src.platform.quality.qpol_v2 import evaluate_image

        p = _img("normal", tmp_path / "n.jpg")
        import hashlib
        sha = hashlib.sha256(p.read_bytes()).hexdigest()
        d = evaluate_image(store, sha256=sha, path=p)
        assert d["auto_decision"] in ("pass", "fail", "waiting_human")
        # 各维度自动结论：没有人工结论时，模糊/不确定维度必须 waiting_human
        for dim, v in d["score"].items():
            per = d["evidence"][dim]
            assert per["auto"] in ("pass", "fail", "waiting_human")
            if per["auto"] == "pass":
                assert per["confidence"] == "high", (
                    "只有高置信才允许自动 pass，否则 waiting_human")

    def test_blur_image_flagged(self, store, tmp_path):
        from src.platform.quality.qpol_v2 import evaluate_image

        p = _img("blur", tmp_path / "b.jpg")
        import hashlib
        sha = hashlib.sha256(p.read_bytes()).hexdigest()
        d = evaluate_image(store, sha256=sha, path=p)
        assert d["score"]["blur"] > d["threshold"]["blur"], "模糊分必须超阈"
        assert d["evidence"]["blur"]["auto"] in ("fail", "waiting_human")
        assert d["auto_decision"] != "pass"

    def test_overexposed_reflection_flagged(self, store, tmp_path):
        from src.platform.quality.qpol_v2 import evaluate_image

        p = _img("bright", tmp_path / "r.jpg")
        import hashlib
        sha = hashlib.sha256(p.read_bytes()).hexdigest()
        d = evaluate_image(store, sha256=sha, path=p)
        assert d["score"]["reflection"] > d["threshold"]["reflection"]
        assert d["auto_decision"] != "pass"

    def test_record_persisted_and_queryable(self, store, tmp_path):
        from src.platform.quality.qpol_v2 import evaluate_image

        p = _img("normal", tmp_path / "n.jpg")
        import hashlib
        sha = hashlib.sha256(p.read_bytes()).hexdigest()
        evaluate_image(store, sha256=sha, path=p)
        rows = store.list_quality_decisions(sha256=sha)
        assert len(rows) == 1
        assert rows[0]["policy_version"] == "qpol_v2"
