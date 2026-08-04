"""SAM 输出只能作为 Label Studio prediction 的契约（手册§一.6 / §七）。"""
import pytest

from src.sam_assist.prediction import to_ls_prediction


def _args(**overrides):
    d = dict(
        width=1500, height=2000,
        visible_tight_box=(480.0, 700.0, 520.0, 900.0),
        model_version="sam2.1_hiera_small@b" + "0" * 15,
        score=0.87,
    )
    d.update(overrides)
    return d


def test_prediction_structure_has_model_version_and_score():
    pred = to_ls_prediction(**_args())
    assert set(pred.keys()) >= {"score", "model_version", "result"}
    assert pred["model_version"].startswith("sam2.1_hiera_small@")
    assert 0 <= pred["score"] <= 1


def test_prediction_box_is_percentage_rectanglelabels_product():
    pred = to_ls_prediction(**_args())
    rects = [r for r in pred["result"] if r["type"] == "rectanglelabels"]
    assert len(rects) == 1
    v = rects[0]["value"]
    assert v["rectanglelabels"] == ["product"]
    # 像素框 → 百分比
    assert abs(v["x"] - 480 / 1500 * 100) < 1e-6
    assert abs(v["y"] - 700 / 2000 * 100) < 1e-6
    assert abs(v["width"] - 40 / 1500 * 100) < 1e-6
    assert abs(v["height"] - 200 / 2000 * 100) < 1e-6


def test_prediction_marks_source_and_prohibits_annotation_semantics():
    pred = to_ls_prediction(**_args())
    meta = pred.get("metadata", {})
    assert meta.get("source") == "sam_prediction"
    assert meta.get("coarse_only_fallback") is not True
    # 绝不允许声明为人工标注或最终标签
    assert "annotation" not in pred
    assert meta.get("is_final_annotation") is not True


def test_prediction_refuses_missing_box():
    with pytest.raises(ValueError):
        to_ls_prediction(**_args(visible_tight_box=None))


def test_prediction_refuses_invalid_score():
    with pytest.raises(ValueError):
        to_ls_prediction(**_args(score=1.5))
