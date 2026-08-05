"""U5-2 红测试：第一条真实 Loop（照片→质量→识别→人工→数据集→评估→误差回流）。

口径（手册 §七/U5）：
- 图结构必须是完整链路，且 quality 失败走 feedback 回跳（误差回流）；
- quality 节点必须调用真实 qpol_v2（合成图仅作输入，不得 mock 结论逻辑）；
- 条件分支（has_fails/clean）、人工门暂停+跨实例恢复、预算停止
  必须各自真实发生；
- 每次质量 fail 必须落审计账本（append_audit），不得伪造。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest


@pytest.fixture()
def store(tmp_path: Path):
    from src.platform.data.store import PlatformStore

    s = PlatformStore(tmp_path / "p.sqlite")
    yield s
    s.close()


def _save(tmp_path: Path, name: str, arr) -> str:
    from PIL import Image

    p = tmp_path / name
    Image.fromarray(arr).save(p)
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _register(store, tmp_path: Path, name: str, sha: str) -> None:
    store.register_inventory_asset(
        source_id="testsrc", source_type="directory",
        source_uri=name, photo_id=name, sha256=sha)


def _images(tmp_path: Path):
    import numpy as np

    rng = np.random.default_rng(7)
    clean = rng.integers(0, 255, size=(64, 64), dtype=np.uint8)  # 噪声→不模糊
    bad = np.full((64, 64), 128, dtype=np.uint8)                 # 均匀→模糊 fail
    sha_c1 = _save(tmp_path, "1_clean.png", clean)
    sha_bad = _save(tmp_path, "2_bad.png", bad)
    sha_c2 = _save(tmp_path, "3_clean.png",
                   rng.integers(0, 255, size=(64, 64), dtype=np.uint8))
    return sha_c1, sha_bad, sha_c2


class TestRealLoopGraph:
    def test_graph_shape(self):
        from src.platform.loops.pipeline_v2 import build_graph

        g = build_graph()
        assert g.entry == "select"
        for n in ("select", "quality", "review", "assemble",
                  "recognize"):
            assert n in g.nodes
        fb = [e for e in g.edges
              if e.src == "quality" and e.edge_type == "feedback"]
        assert fb and fb[0].dst == "select" and fb[0].when == "has_fails"
        clean = [e for e in g.edges
                 if e.src == "quality" and e.when == "clean"]
        assert clean and clean[0].dst == "review"


class TestRealLoopE2E:
    def test_feedback_human_resume_complete(self, store, tmp_path):
        from src.platform.kernel.loop import LoopEngine
        from src.platform.loops.pipeline_v2 import (build_graph,
                                                    build_handlers,
                                                    build_routers)

        sha_c1, sha_bad, sha_c2 = _images(tmp_path)
        for name, sha in (("1_clean.png", sha_c1), ("2_bad.png", sha_bad),
                          ("3_clean.png", sha_c2)):
            _register(store, tmp_path, name, sha)

        calls: list[str] = []

        def fake_recognize(path: Path):
            calls.append(str(path))
            return {"boxes": 1}

        handlers = build_handlers(store, root=tmp_path, source_id="testsrc",
                                  batch_size=2, recognize_fn=fake_recognize)
        eng = LoopEngine(store)
        run = eng.start_run(build_graph(), {"origin": "u52-test"})
        out = eng.execute(run["run_id"], handlers, build_routers())
        # 第 1 轮 2_bad.png 质量 fail → feedback 回跳 → 第 2 轮 clean → 人工门
        assert out["status"] == "waiting_human"
        trail = eng.decision_trail(run["run_id"])
        assert any(d["decision"] == "feedback" for d in trail), \
            "质量失败必须真实回流一次"
        assert any(d["decision"] == "human_gate" for d in trail)

        # 误差回流账本：fail 的 SHA 必须有审计记录
        audits = [a for a in store.list_audit(limit=500)
                  if a["action"] == "quality.fail"]
        assert audits and audits[0]["subject_id"] == sha_bad

        # 模拟进程重启：新实例批准人工门后续跑
        eng2 = LoopEngine(store)
        eng2.approve_human_gate(run["run_id"], approved=True, actor="admin")
        out2 = eng2.execute(run["run_id"], handlers, build_routers())
        assert out2["status"] == "completed"

        outputs = json.loads(out2["output_json"])
        asm = outputs["assemble"]
        assert asm["n_items"] == 2, "数据集只含非 fail 照片"
        rec = outputs["recognize"]
        assert rec["n_recognized"] == 2 and len(calls) == 2

    def test_budget_stop_real(self, store, tmp_path):
        from src.platform.kernel.loop import LoopEngine
        from src.platform.loops.pipeline_v2 import (build_graph,
                                                    build_handlers,
                                                    build_routers)

        import numpy as np

        bad = np.full((32, 32), 128, dtype=np.uint8)
        for i in range(3):
            sha = _save(tmp_path, f"bad_{i}.png", bad + i)
            _register(store, tmp_path, f"bad_{i}.png", sha)

        handlers = build_handlers(store, root=tmp_path, source_id="testsrc",
                                  batch_size=1,
                                  recognize_fn=lambda p: {"boxes": 0})
        eng = LoopEngine(store)
        run = eng.start_run(build_graph(max_rounds=2), {})
        out = eng.execute(run["run_id"], handlers, build_routers())
        assert out["status"] == "failed"
        assert out["stop_reason"] == "budget_rounds"
        assert "max_rounds=2" in (out.get("error") or "")

    def test_reject_terminal_real(self, store, tmp_path):
        from src.platform.kernel.loop import LoopEngine
        from src.platform.loops.pipeline_v2 import (build_graph,
                                                    build_handlers,
                                                    build_routers)

        sha_c1, sha_bad, sha_c2 = _images(tmp_path)
        # 只登记干净照片：一轮即 clean → 人工门
        _register(store, tmp_path, "1_clean.png", sha_c1)
        handlers = build_handlers(store, root=tmp_path, source_id="testsrc",
                                  batch_size=4,
                                  recognize_fn=lambda p: {"boxes": 0})
        eng = LoopEngine(store)
        run = eng.start_run(build_graph(), {})
        out = eng.execute(run["run_id"], handlers, build_routers())
        assert out["status"] == "waiting_human"
        eng.approve_human_gate(run["run_id"], approved=False, actor="admin")
        out2 = eng.execute(run["run_id"], handlers, build_routers())
        assert out2["status"] == "failed", "人工拒绝为终态"
