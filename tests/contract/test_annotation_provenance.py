"""审核来源状态机契约（手册§七）：
auto_proposed → annotator_accepted/corrected/manual → reviewer_accepted/rejected → adjudicated。
每次状态变更追加记录并保留前版；SAM prediction 永远不能直接成为最终 annotation。"""
import pytest

from src.sam_assist.provenance import (
    ALLOWED_TRANSITIONS,
    AnnotationEvent,
    ProvenanceLog,
)

BOX_A = (480.0, 700.0, 520.0, 900.0)
BOX_B = (475.0, 695.0, 525.0, 905.0)


def _log():
    return ProvenanceLog()


def test_all_documented_states_exist():
    assert set(ALLOWED_TRANSITIONS.keys()) >= {
        "auto_proposed", "annotator_accepted", "annotator_corrected",
        "annotator_manual", "reviewer_accepted", "reviewer_rejected",
        "adjudicated",
    }


def test_full_happy_path_accept():
    log = _log()
    log.append("i1", "auto_proposed", actor="sam_worker", box=BOX_A)
    log.append("i1", "annotator_accepted", actor="annotator_a", box=BOX_A)
    log.append("i1", "reviewer_accepted", actor="reviewer_b", box=BOX_A)
    assert log.current_state("i1") == "reviewer_accepted"
    assert log.final_box("i1") == BOX_A


def test_correction_path_keeps_previous_versions():
    log = _log()
    log.append("i1", "auto_proposed", actor="sam_worker", box=BOX_A)
    log.append("i1", "annotator_corrected", actor="annotator_a", box=BOX_B,
               reason="框偏大")
    events = log.events("i1")
    assert len(events) == 2
    assert events[0].box == BOX_A, "前版必须保留"
    assert events[1].box == BOX_B
    assert events[1].prev_event_id == events[0].event_id


def test_reject_then_fix_then_review():
    log = _log()
    log.append("i1", "auto_proposed", actor="sam_worker", box=BOX_A)
    log.append("i1", "annotator_accepted", actor="annotator_a", box=BOX_A)
    log.append("i1", "reviewer_rejected", actor="reviewer_b", reason="漏了半瓶")
    log.append("i1", "annotator_corrected", actor="annotator_a", box=BOX_B)
    log.append("i1", "reviewer_accepted", actor="reviewer_b", box=BOX_B)
    assert log.final_box("i1") == BOX_B


def test_invalid_transition_raises():
    log = _log()
    log.append("i1", "auto_proposed", actor="sam_worker", box=BOX_A)
    with pytest.raises(ValueError):
        log.append("i1", "reviewer_accepted", actor="reviewer_b")  # 跳过标注者


def test_first_event_must_be_auto_proposed_or_manual():
    log = _log()
    with pytest.raises(ValueError):
        log.append("i2", "reviewer_accepted", actor="reviewer_b", box=BOX_A)
    log.append("i3", "annotator_manual", actor="annotator_a", box=BOX_A)
    assert log.current_state("i3") == "annotator_manual"


def test_prediction_alone_never_yields_final_annotation():
    """手册§一.6：只有 auto_proposed（SAM prediction）时不得有最终框。"""
    log = _log()
    log.append("i1", "auto_proposed", actor="sam_worker", box=BOX_A)
    assert log.final_box("i1") is None
    assert log.is_finalized("i1") is False


def test_reviewer_accepted_or_adjudicated_only_finalizes():
    log = _log()
    log.append("i1", "annotator_manual", actor="annotator_a", box=BOX_A)
    assert log.is_finalized("i1") is False
    log.append("i1", "reviewer_accepted", actor="reviewer_b", box=BOX_A)
    assert log.is_finalized("i1") is True

    log.append("i2", "annotator_manual", actor="annotator_a", box=BOX_A)
    log.append("i2", "reviewer_rejected", actor="reviewer_b", reason="x")
    log.append("i2", "adjudicated", actor="judge_c", box=BOX_B, reason="仲裁")
    assert log.is_finalized("i2") is True
    assert log.final_box("i2") == BOX_B


def test_terminal_states_reject_further_changes():
    log = _log()
    log.append("i1", "annotator_manual", actor="a", box=BOX_A)
    log.append("i1", "reviewer_accepted", actor="b", box=BOX_A)
    with pytest.raises(ValueError):
        log.append("i1", "annotator_corrected", actor="a", box=BOX_B)


def test_events_require_actor_and_timestamp():
    log = _log()
    with pytest.raises(ValueError):
        log.append("i1", "auto_proposed", actor="", box=BOX_A)
    log.append("i1", "auto_proposed", actor="sam_worker", box=BOX_A)
    assert log.events("i1")[0].timestamp > 0
