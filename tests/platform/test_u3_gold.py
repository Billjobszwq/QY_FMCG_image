"""U3-6 红测试：500–1,000 张分层人工质量金标准入口 + 混淆矩阵。

手册 §5/U4 指令：建立分层人工质量金标准入口和混淆矩阵；
人工尚未完成时必须显示 waiting_human，不得伪造通过；
人工结论必须来自真实登录身份（服务端 session），追加式不可变。

当前平台没有 gold 入口 API，本测试必须 RED。
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


def _seed(store, tmp_path: Path, n: int = 6):
    """n 张本地照片登记台账，其中一半有 fail 质量结论、一半无结论。"""
    import hashlib

    import numpy as np
    from PIL import Image

    d = tmp_path / "照片Q"
    d.mkdir(exist_ok=True)
    rng = np.random.default_rng(11)
    shas = []
    for i in range(n):
        p = d / f"{i}.jpg"
        Image.fromarray(rng.integers(0, 256, (64, 64, 3),
                                     dtype=np.uint8)).save(p)
        sha = hashlib.sha256(p.read_bytes()).hexdigest()
        shas.append(sha)
        store.register_inventory_asset(
            source_id="photoQ", source_type="directory",
            source_uri=f"照片Q/{i}.jpg", photo_id=f"{i}.jpg",
            sha256=sha)
        if i % 2 == 0:
            store.record_quality_decision(
                sha256=sha, policy_version="qpol_v2",
                score={"blur": 0.9}, threshold={"blur": 0.5},
                auto_decision="fail", human_decision=None,
                model_version="heuristic_v1")
    return shas


class TestGoldBuild:
    def test_build_stratified_queue(self, store, tmp_path):
        from src.platform.quality.gold import build_gold_queue

        shas = _seed(store, tmp_path, n=6)
        out = build_gold_queue(store, size=4, root=tmp_path)
        assert out["added"] == 4
        assert out["total_queue"] == 4
        # 分层：fail 层与 waiting_human 层都必须有代表
        strata = {q["stratum"] for q in out["items"]}
        assert len(strata) >= 2
        # 幂等：重跑不重复入队
        out2 = build_gold_queue(store, size=4, root=tmp_path)
        assert out2["added"] == 0

    def test_only_local_files_enter_gold(self, store, tmp_path):
        """manifest-only（无本地文件）照片不得进人工金标准队列。"""
        from src.platform.quality.gold import build_gold_queue

        store.register_inventory_asset(
            source_id="batch3_clean", source_type="manifest_sha_dict",
            source_uri="m.json#x", photo_id="x", sha256="f" * 64)
        out = build_gold_queue(store, size=10, root=tmp_path)
        assert out["total_queue"] == 0


class TestGoldStatusWaitingHuman:
    def test_status_waiting_human_until_real_human(self, store, tmp_path):
        from src.platform.quality.gold import (build_gold_queue,
                                               gold_status)

        _seed(store, tmp_path, n=4)
        build_gold_queue(store, size=4, root=tmp_path)
        st = gold_status(store)
        assert st["waiting_human"] == 4
        assert st["done"] == 0
        assert st["items"][0]["status"] == "waiting_human", (
            "人工未完成必须显示 waiting_human，不得伪造通过")

    def test_human_verdict_flips_status(self, store, tmp_path):
        from src.platform.quality.gold import (build_gold_queue,
                                               gold_status,
                                               submit_human_verdict)

        shas = _seed(store, tmp_path, n=2)
        build_gold_queue(store, size=2, root=tmp_path)
        submit_human_verdict(store, sha256=shas[0], verdict="fail",
                             reviewer="admin", dims={"blur": "fail"})
        st = gold_status(store)
        assert st["done"] == 1 and st["waiting_human"] == 1

    def test_human_verdict_immutable(self, store, tmp_path):
        import sqlite3

        from src.platform.quality.gold import submit_human_verdict

        shas = _seed(store, tmp_path, n=1)
        submit_human_verdict(store, sha256=shas[0], verdict="pass",
                             reviewer="admin")
        with pytest.raises(sqlite3.IntegrityError):
            store._conn.execute("UPDATE quality_human_v1 SET verdict='fail'")


class TestConfusionMatrix:
    def test_confusion_only_on_done_pairs(self, store, tmp_path):
        from src.platform.quality.gold import (build_gold_queue,
                                               confusion_matrix,
                                               submit_human_verdict)

        shas = _seed(store, tmp_path, n=4)
        build_gold_queue(store, size=4, root=tmp_path)
        # 只完成 2 张人工：一张与 auto=fail 一致，一张翻为 pass
        submit_human_verdict(store, sha256=shas[0], verdict="fail",
                             reviewer="admin")
        submit_human_verdict(store, sha256=shas[1], verdict="pass",
                             reviewer="admin")
        m = confusion_matrix(store)
        assert m["pairs"] == 2, "只对有人工结论的对计算"
        assert m["auto_fail_human_fail"] >= 1
        assert m["auto_none_human_pass"] >= 1, (
            "无自动结论（waiting_human）被人工判 pass 必须计入")
