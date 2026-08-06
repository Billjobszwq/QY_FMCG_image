"""Task 15（VLM-015）：新包装工作流状态机（受审 FMCG 包装演进）。

红线：
- 状态：candidate/reviewing/same_sku_new_package/new_sku/unknown/rejected；
- Qwen 只能创建 candidate，绝不能直接产出终态或写商品主数据；
- 只有 human/customer_policy 可终结；终结后决定不可更新、不可删除；
- 历史修正只追加 supersede 关系，不改写旧行；
- 显示名与 package_version 分离：名称变化绝不自动改变 sku_id。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.modules.fmcg.cascade.packaging import (
    FINAL_STATUSES,
    STATUSES,
    PackagingError,
    create_candidate,
    finalize_decision,
    get_decision,
    list_decisions,
    move_to_reviewing,
    supersede,
    supersede_history,
)
from src.platform.data.store import PlatformStore, StoreError


@pytest.fixture()
def store(tmp_path: Path):
    s = PlatformStore(tmp_path / "p.sqlite")
    yield s
    s.close()


def _cand(store, **kw):
    base = dict(sku_id="sku-001", display_name="500ml茉莉乌龙（无糖）",
                package_version_id="pv-001", created_by="qwen3-vl:4b",
                run_id="run-1", evidence=["ev-1"])
    base.update(kw)
    return create_candidate(store, **base)


# ---------- Qwen 只能创建 candidate ----------

def test_qwen_creates_only_candidate(store) -> None:
    d = _cand(store)
    assert d["status"] == "candidate"
    assert d["source"] == "qwen"
    assert set(STATUSES) == {"candidate", "reviewing",
                             "same_sku_new_package", "new_sku",
                             "unknown", "rejected"}


def test_qwen_cannot_create_terminal_state(store) -> None:
    with pytest.raises(PackagingError):
        create_candidate(store, sku_id="sku-001", display_name="x",
                         package_version_id="pv-2", created_by="qwen3-vl:4b",
                         status="new_sku")


def test_qwen_cannot_finalize(store) -> None:
    d = _cand(store)
    with pytest.raises(PackagingError):
        finalize_decision(store, d["decision_id"], status="new_sku",
                          actor="qwen3-vl:4b", source="qwen",
                          name_choice="create_new_sku",
                          new_sku_id="sku-999")


# ---------- 状态流转 ----------

def test_candidate_to_reviewing(store) -> None:
    d = _cand(store)
    d2 = move_to_reviewing(store, d["decision_id"], actor="reviewer-a")
    assert d2["status"] == "reviewing"
    with pytest.raises(PackagingError):
        move_to_reviewing(store, d["decision_id"], actor="reviewer-a")


@pytest.mark.parametrize("final_status", FINAL_STATUSES)
def test_human_can_finalize_all_terminal_states(store, final_status) -> None:
    d = _cand(store)
    move_to_reviewing(store, d["decision_id"], actor="reviewer-a")
    kw = {}
    if final_status == "new_sku":
        kw = dict(name_choice="create_new_sku", new_sku_id="sku-100")
    elif final_status == "same_sku_new_package":
        kw = dict(name_choice="keep_old_name")
    out = finalize_decision(store, d["decision_id"], status=final_status,
                            actor="reviewer-a", source="human", **kw)
    assert out["status"] == final_status


def test_customer_policy_source_allowed(store) -> None:
    d = _cand(store)
    out = finalize_decision(store, d["decision_id"],
                            status="same_sku_new_package",
                            actor="policy-engine", source="customer_policy",
                            name_choice="keep_old_name")
    assert out["status"] == "same_sku_new_package"


def test_unknown_source_rejected(store) -> None:
    d = _cand(store)
    with pytest.raises(PackagingError):
        finalize_decision(store, d["decision_id"], status="rejected",
                          actor="x", source="api")


# ---------- 名称选择：sku_id 不随名称变化 ----------

def test_keep_old_name_keeps_sku_and_name(store) -> None:
    d = _cand(store)
    out = finalize_decision(store, d["decision_id"],
                            status="same_sku_new_package", actor="r",
                            source="human", name_choice="keep_old_name")
    assert out["sku_id"] == "sku-001"
    assert out["display_name"] == "500ml茉莉乌龙（无糖）"
    assert out["package_version_id"] != "pv-001"  # 新包装=新 version


def test_adopt_new_name_keeps_sku_id(store) -> None:
    d = _cand(store)
    out = finalize_decision(store, d["decision_id"],
                            status="same_sku_new_package", actor="r",
                            source="human", name_choice="adopt_new_name",
                            display_name="茉莉乌龙 焕新装")
    assert out["sku_id"] == "sku-001"  # 名称变化绝不改变 sku_id
    assert out["display_name"] == "茉莉乌龙 焕新装"


def test_create_new_sku_requires_new_sku_id(store) -> None:
    d = _cand(store)
    with pytest.raises(PackagingError):
        finalize_decision(store, d["decision_id"], status="new_sku",
                          actor="r", source="human",
                          name_choice="create_new_sku")  # 缺 new_sku_id
    out = finalize_decision(store, d["decision_id"], status="new_sku",
                            actor="r", source="human",
                            name_choice="create_new_sku", new_sku_id="sku-200")
    assert out["sku_id"] == "sku-200"
    assert out["display_name"] == "500ml茉莉乌龙（无糖）"


# ---------- 终态不可变：不更新、不删除 ----------

def test_terminal_decision_immutable(store) -> None:
    d = _cand(store)
    out = finalize_decision(store, d["decision_id"], status="rejected",
                            actor="r", source="human")
    with pytest.raises(PackagingError):
        finalize_decision(store, d["decision_id"], status="new_sku",
                          actor="r", source="human",
                          name_choice="create_new_sku", new_sku_id="sku-x")
    with pytest.raises(PackagingError):
        move_to_reviewing(store, d["decision_id"], actor="r")
    # DB 层也拒绝 UPDATE/DELETE 终态行（双保险）
    with pytest.raises(Exception):
        store._conn.execute(
            "DELETE FROM package_decision WHERE decision_id=?",
            (d["decision_id"],))
    assert get_decision(store, d["decision_id"])["status"] == "rejected"
    _ = out


# ---------- supersede：只追加，不改写旧行 ----------

def test_supersede_appends_without_rewriting(store) -> None:
    old = _cand(store)
    finalize_decision(store, old["decision_id"],
                      status="same_sku_new_package", actor="r",
                      source="human", name_choice="keep_old_name")
    before = get_decision(store, old["decision_id"])
    new = _cand(store, package_version_id="pv-002")
    finalize_decision(store, new["decision_id"], status="rejected",
                      actor="r", source="human")
    supersede(store, older_id=old["decision_id"], newer_id=new["decision_id"],
              reason="复核后改判", actor="admin")
    after = get_decision(store, old["decision_id"])
    # 旧决定逐字段不变（除 supersede 链为外挂表）
    assert after == before
    chain = supersede_history(store, old["decision_id"])
    assert [c["newer_decision_id"] for c in chain] == [new["decision_id"]]
    # 重复 supersede 拒绝（幂等防重）
    with pytest.raises(PackagingError):
        supersede(store, older_id=old["decision_id"],
                  newer_id=new["decision_id"], reason="again", actor="admin")


def test_supersede_requires_terminal_both(store) -> None:
    old = _cand(store)
    new = _cand(store, package_version_id="pv-003")
    with pytest.raises(PackagingError):  # 双方均未终结
        supersede(store, older_id=old["decision_id"],
                  newer_id=new["decision_id"], reason="x", actor="admin")


def test_list_and_get(store) -> None:
    d1 = _cand(store)
    _cand(store, sku_id="sku-002", package_version_id="pv-010")
    assert len(list_decisions(store)) == 2
    assert len(list_decisions(store, sku_id="sku-002")) == 1
    assert get_decision(store, d1["decision_id"])["sku_id"] == "sku-001"
    with pytest.raises(PackagingError):
        get_decision(store, "missing")


def test_audit_written_on_finalize(store) -> None:
    d = _cand(store)
    finalize_decision(store, d["decision_id"], status="rejected",
                      actor="reviewer-a", source="human")
    audit = [a for a in store.list_audit(subject_id=d["decision_id"])
             if a["action"] == "packaging.finalized"]
    assert len(audit) == 1
