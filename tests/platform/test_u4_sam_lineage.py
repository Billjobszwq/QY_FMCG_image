"""U4-1 红测试：点坐标引导 SAM 管线 + 完整 point→prompt→mask→box lineage。

手册 §六/U4 指令：
- 点坐标引导 SAM2.1 Hiera Small 自动框；疑难样本才升级 Base+；
- 保留 point→prompt→mask→box 的完整 lineage（不可变落库）；
- 无合格候选 → manual_required，绝不回退固定比例框（不得伪造 box）。

当前平台无 sam lineage 表与管线，本测试必须 RED。
SAM 权重推理经隔离 venv worker（本测试用确定性 stub 替代，
真实冒烟在提交前以 .venv_sam 实跑留档）。
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest


@pytest.fixture()
def store(tmp_path: Path):
    from src.platform.data.store import PlatformStore

    s = PlatformStore(tmp_path / "p.sqlite")
    yield s
    s.close()


class StubSamWorker:
    """确定性 SAM worker：画以 positive 为中心的方块 mask。

    fail_models：这些模型一律返回无合格候选（模拟疑难样本），
    用于验证 Small→Base+ 升级逻辑。
    """

    def __init__(self, *, side: int = 60, fail_models=()):
        self.side = side
        self.fail_models = set(fail_models)
        self.calls: list[str] = []

    def invoke(self, request: dict) -> dict:
        self.calls.append(request["model"])
        results = []
        for img in request["images"]:
            w, h = img["width"], img["height"]
            mask = np.zeros((h, w), dtype=np.uint8)
            insts = []
            for inst in img["instances"]:
                px, py = int(inst["positive"][0]), int(inst["positive"][1])
                m = mask.copy()
                if request["model"] not in self.fail_models:
                    x1, x2 = max(0, px - self.side // 2), min(w, px + self.side // 2)
                    y1, y2 = max(0, py - self.side // 2), min(h, py + self.side // 2)
                    m[y1:y2, x1:x2] = 255
                out_dir = Path(request["out_dir"]) / "masks"
                out_dir.mkdir(parents=True, exist_ok=True)
                mp = out_dir / f"{inst['instance_id']}_{request['model']}.png"
                from PIL import Image
                Image.fromarray(m).save(mp)
                import hashlib
                ys, xs = np.nonzero(m)
                insts.append({
                    "instance_id": inst["instance_id"],
                    "decoder_sec": 0.01,
                    "candidates": [{
                        "candidate_id": "c0",
                        "mask_path": str(mp),
                        "mask_sha256": hashlib.sha256(
                            mp.read_bytes()).hexdigest(),
                        "iou_score": 0.95,
                        "stability_score": 0.95,
                        "area_px": int(len(xs)),
                        "bbox": ([int(xs.min()), int(ys.min()),
                                  int(xs.max() + 1), int(ys.max() + 1)]
                                 if len(xs) else None),
                    }],
                })
            results.append({"image_sha": img["image_sha"],
                            "encoder_sec": 0.05,
                            "mps_peak_mem_bytes": 0,
                            "instances": insts})
        return {"ok": True,
                "env": {"device": "mps", "torch": "stub"},
                "results": results, "wall_time_sec": 0.1}


def _images(tmp_path: Path):
    """一张合成图，两个实例点（相距 > 负提示半径内）。"""
    return [{
        "photo_id": "p1", "image_sha": "a" * 64,
        "width": 640, "height": 480,
        "image_path": str(tmp_path / "p1.jpg"),
        "instances": [
            {"instance_id": "p1_000", "x": 200.0, "y": 200.0,
             "sku_raw_name": "乌龙茶"},
            {"instance_id": "p1_001", "x": 420.0, "y": 210.0,
             "sku_raw_name": "茉莉乌龙"},
        ],
    }]


class TestSamLineage:
    def test_lineage_full_chain_persisted(self, store, tmp_path):
        from src.platform.annotate.sam_pipeline import run_sam_assist

        worker = StubSamWorker()
        rep = run_sam_assist(store, images=_images(tmp_path),
                             worker=worker, out_root=tmp_path / "out")
        assert rep["n_instances"] == 2
        assert rep["accepted"] == 2 and rep["manual_required"] == 0
        rows = store.list_sam_lineage(image_sha="a" * 64)
        assert len(rows) == 2
        r = rows[0]
        # point→prompt→mask→box 全链路字段都必须在
        for k in ("point_x", "point_y", "prompt_config_version",
                  "positive_point_json", "negative_points_json",
                  "coarse_box_json", "model", "checkpoint_sha256",
                  "mask_sha256", "decision", "tight_box_json",
                  "selection_reason", "rules_version", "escalated_to",
                  "reject_reasons_json"):
            assert k in r, f"lineage 缺字段 {k}"
        box = json.loads(r["tight_box_json"])
        assert len(box) == 4 and box[2] > box[0] and box[3] > box[1]
        assert r["model"] == "sam2.1_hiera_small", "默认必须先用 Hiera Small"
        assert worker.calls == ["sam2.1_hiera_small"], \
            "无疑难时不得调用 Base+"

    def test_no_valid_candidate_is_manual_required_not_fake_box(
            self, store, tmp_path):
        from src.platform.annotate.sam_pipeline import run_sam_assist

        worker = StubSamWorker(fail_models={"sam2.1_hiera_small",
                                            "sam2.1_hiera_base_plus"})
        rep = run_sam_assist(store, images=_images(tmp_path),
                             worker=worker, out_root=tmp_path / "out")
        assert rep["manual_required"] == 2 and rep["accepted"] == 0
        for r in store.list_sam_lineage():
            assert r["decision"] == "manual_required"
            assert r["tight_box_json"] is None, "禁止伪造/回退比例框"
            assert r["escalated_to"] == "sam2.1_hiera_base_plus", \
                "Small 失败必须升级 Base+ 仍失败才 manual_required"

    def test_escalation_only_for_difficult(self, store, tmp_path):
        from src.platform.annotate.sam_pipeline import run_sam_assist

        worker = StubSamWorker(
            fail_models={"sam2.1_hiera_small"})  # Small 全疑难
        rep = run_sam_assist(store, images=_images(tmp_path),
                             worker=worker, out_root=tmp_path / "out")
        assert rep["accepted"] == 2
        assert set(worker.calls) == {"sam2.1_hiera_small",
                                     "sam2.1_hiera_base_plus"}
        for r in store.list_sam_lineage():
            assert r["model"] == "sam2.1_hiera_base_plus"
            assert r["escalated_to"] == "sam2.1_hiera_base_plus"

    def test_lineage_immutable(self, store, tmp_path):
        import sqlite3

        from src.platform.annotate.sam_pipeline import run_sam_assist

        run_sam_assist(store, images=_images(tmp_path),
                       worker=StubSamWorker(), out_root=tmp_path / "out")
        with pytest.raises(sqlite3.IntegrityError):
            store._conn.execute(
                "UPDATE sam_lineage_v1 SET decision='accepted'")
