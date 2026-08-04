"""SAM → Label Studio 导入契约（手册§一.9 / §七）：

- SAM 结果只能成为 prediction，绝不能创建最终 annotation；
- manual_required 实例不生成 prediction 框（禁止比例框回退）；
- 每个实例必须留下完整证据（prompts/模型 SHA/候选/选择原因/规则版本）。"""
import numpy as np

from src.sam_assist.candidates import PhysicalLimits
from src.sam_assist.evidence import EvidenceStore
from src.sam_assist.ls_import import (ImageOutcome, import_to_ls,
                                      process_image, record_evidence)

SHA = "a" * 64
CKPT_SHA = "b" * 64
LIMITS = PhysicalLimits(min_area_px=10.0, max_area_px=10000.0,
                        min_aspect=0.1, max_aspect=10.0)


def _request_image():
    return {"image_sha": SHA, "width": 200, "height": 200,
            "photo_id": "p1",
            "instances": [{
                "instance_id": "i0", "positive": [50.0, 50.0],
                "negatives": [], "coarse_box": [30.0, 30.0, 70.0, 80.0],
                "prompt_config_version": "pc_v1:test",
            }]}


def _worker_result(mask):
    return {"image_sha": SHA, "instances": [{
        "instance_id": "i0", "decoder_sec": 0.01,
        "candidates": [{
            "candidate_id": "c0", "mask_path": None,
            "mask_sha256": "c" * 64, "iou_score": 0.9,
            "stability_score": 0.9, "area_px": int(mask.sum()),
            "bbox": None,
        }]}]}


def _good_mask():
    m = np.zeros((200, 200), np.uint8)
    m[35:75, 40:60] = 1   # 含正点(50,50)，在粗 ROI 内，单连通
    return m


def test_accepted_instance_becomes_prediction_not_annotation():
    req = _request_image()
    out = process_image(_worker_result(_good_mask()), req,
                        model_id="sam2.1_hiera_small",
                        checkpoint_sha256=CKPT_SHA, code_commit="deadbeef",
                        limits=LIMITS,
                        mask_loader=lambda c: _good_mask())
    assert isinstance(out, ImageOutcome)
    assert len(out.predictions) == 1
    pred = out.predictions[0]
    assert pred["metadata"]["source"] == "sam_prediction"
    assert pred["metadata"]["is_final_annotation"] is False
    assert out.manual_required == []
    # 证据完整
    ev = out.evidence[0]
    assert ev.image_sha256 == SHA
    assert ev.checkpoint_sha256 == CKPT_SHA
    assert ev.code_commit == "deadbeef"
    assert ev.auto_box is not None
    assert ev.selection_reason == "highest_valid_score"
    assert ev.prompts["positive"] == (50.0, 50.0)


def test_manual_required_instance_gets_no_prediction_box():
    bad = np.zeros((200, 200), np.uint8)
    bad[150:160, 150:160] = 1  # 不含正点 → 无合格候选
    req = _request_image()
    out = process_image(_worker_result(bad), req,
                        model_id="sam2.1_hiera_small",
                        checkpoint_sha256=CKPT_SHA, code_commit="deadbeef",
                        limits=LIMITS, mask_loader=lambda c: bad)
    assert out.predictions == []
    assert out.manual_required == ["i0"]
    assert out.evidence[0].auto_box is None
    assert out.evidence[0].selection_reason == "no_valid_candidate"


class FakeClient:
    def __init__(self):
        self.calls = []

    def create_prediction(self, task_id, result, score=0.5, model_version=""):
        self.calls.append(("create_prediction", task_id, len(result)))
        return {"id": 1}

    def __getattr__(self, name):
        # 任何 annotation 写入接口被调用即暴露
        def _boom(*a, **k):
            self.calls.append((name, a, k))
        return _boom


def test_import_only_touches_prediction_endpoint():
    req = _request_image()
    out = process_image(_worker_result(_good_mask()), req,
                        model_id="sam2.1_hiera_small",
                        checkpoint_sha256=CKPT_SHA, code_commit="deadbeef",
                        limits=LIMITS, mask_loader=lambda c: _good_mask())
    client = FakeClient()
    import_to_ls(client, task_id=7, outcome=out,
                 model_version="sam2.1_hiera_small@bbbbbbbbbbbb")
    assert client.calls and client.calls[0][0] == "create_prediction"
    forbidden = [c for c in client.calls
                 if "annotation" in c[0].lower()]
    assert not forbidden, f"禁止写 annotation: {forbidden}"


def test_record_evidence_append_only(tmp_path):
    req = _request_image()
    out = process_image(_worker_result(_good_mask()), req,
                        model_id="sam2.1_hiera_small",
                        checkpoint_sha256=CKPT_SHA, code_commit="deadbeef",
                        limits=LIMITS, mask_loader=lambda c: _good_mask())
    store = EvidenceStore(tmp_path / "ev.jsonl")
    record_evidence(store, out)
    record_evidence(store, out)  # 重跑只追加
    recs = store.read_all()
    assert len(recs) == 2
    assert not hasattr(store, "delete")
    assert not hasattr(store, "overwrite")
