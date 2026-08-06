"""Task 15（VLM-015）：受审 FMCG 包装演进状态机（新包装工作流）。

红线（规格 2026-08-06 §10）：
- 状态：candidate → reviewing → same_sku_new_package / new_sku / unknown / rejected；
- Qwen 只能创建 candidate：不得直接产出终态、不得自动写商品主数据；
- 只有 human / customer_policy 可以终结决定；
- 已终结决定不可更新、不可删除（应用层 + DB 触发器双保险）；
- 历史修正只追加 supersede 关系，绝不改写旧行；
- 显示名与 package_version 分离：名称变化绝不自动改变 sku_id。
"""

from __future__ import annotations

import secrets
from typing import Any

from src.platform.data.store import StoreError

STATUSES = ("candidate", "reviewing", "same_sku_new_package",
            "new_sku", "unknown", "rejected")
NON_FINAL_STATUSES = ("candidate", "reviewing")
FINAL_STATUSES = ("same_sku_new_package", "new_sku", "unknown", "rejected")
SOURCES = ("qwen", "human", "customer_policy")
TERMINATING_SOURCES = ("human", "customer_policy")
NAME_CHOICES = ("keep_old_name", "adopt_new_name", "create_new_sku")


class PackagingError(Exception):
    """新包装工作流域错误（非法状态转移、越权终结、不可变违反等）。"""


def _get(store, decision_id: str) -> dict[str, Any]:
    try:
        return store.get_package_decision(decision_id)
    except StoreError as e:
        raise PackagingError(str(e)) from e


def _infer_source(created_by: str, source: str | None) -> str:
    if source is None:
        return "qwen" if "qwen" in created_by.lower() else "human"
    return source


def create_candidate(
    store,
    *,
    sku_id: str = "",
    display_name: str,
    package_version_id: str,
    created_by: str,
    source: str | None = None,
    run_id: str | None = None,
    evidence: list[Any] | None = None,
    status: str = "candidate",
) -> dict[str, Any]:
    """创建包装候选。任何来源（含 Qwen）只能创建 candidate。"""
    if status != "candidate":
        raise PackagingError(
            f"只能创建 candidate（收到 {status!r}）：终态必须由人工/客户策略"
            "经审核后产生，Qwen 不得直接产出终态或写商品主数据")
    src = _infer_source(created_by, source)
    if src not in SOURCES:
        raise PackagingError(f"未知来源: {src!r}（合法 {SOURCES}）")
    decision_id = "pkg-" + secrets.token_hex(8)
    try:
        return store.create_package_decision(
            decision_id=decision_id, sku_id=sku_id,
            display_name=display_name,
            package_version_id=package_version_id,
            status="candidate", source=src, run_id=run_id,
            evidence=evidence, created_by=created_by)
    except StoreError as e:
        raise PackagingError(str(e)) from e


def move_to_reviewing(store, decision_id: str, *, actor: str) -> dict[str, Any]:
    d = _get(store, decision_id)
    if d["status"] != "candidate":
        raise PackagingError(
            f"只有 candidate 可进入 reviewing（当前 {d['status']!r}）")
    try:
        return store.update_package_decision(
            decision_id, fields={"status": "reviewing"})
    except StoreError as e:
        raise PackagingError(str(e)) from e


def _new_package_version_id(sku_id: str) -> str:
    return f"pv-{(sku_id or 'anon')}-{secrets.token_hex(4)}"


def finalize_decision(
    store,
    decision_id: str,
    *,
    status: str,
    actor: str,
    source: str,
    name_choice: str | None = None,
    new_sku_id: str | None = None,
    display_name: str | None = None,
) -> dict[str, Any]:
    """终结决定（仅 human/customer_policy）。终态后不可再变更。"""
    if source not in TERMINATING_SOURCES:
        raise PackagingError(
            f"只有 {TERMINATING_SOURCES} 可终结包装决定（收到 {source!r}）；"
            "Qwen 仅可创建 candidate")
    if status not in FINAL_STATUSES:
        raise PackagingError(f"非法终态: {status!r}（合法 {FINAL_STATUSES}）")
    d = _get(store, decision_id)
    if d["status"] not in NON_FINAL_STATUSES:
        raise PackagingError(
            f"决定已终结（{d['status']!r}），不可再变更；"
            "如需修正请使用 supersede 追加新决定")

    sku_id = d["sku_id"]
    name = d["display_name"]
    pv = d["package_version_id"]
    if status == "same_sku_new_package":
        if name_choice not in ("keep_old_name", "adopt_new_name"):
            raise PackagingError(
                "same_sku_new_package 需要 name_choice ∈ "
                "(keep_old_name, adopt_new_name)")
        if name_choice == "adopt_new_name":
            if not display_name:
                raise PackagingError("adopt_new_name 需要提供新显示名")
            name = display_name  # 名称变化绝不改变 sku_id
        pv = _new_package_version_id(sku_id)  # 新包装 = 新 package_version
    elif status == "new_sku":
        if name_choice != "create_new_sku" or not new_sku_id:
            raise PackagingError("new_sku 需要 name_choice=create_new_sku"
                                 " 且提供 new_sku_id")
        sku_id = new_sku_id
        pv = _new_package_version_id(sku_id)
    # unknown/rejected：不涉及名称与 SKU 变更

    try:
        out = store.update_package_decision(
            decision_id,
            fields={"status": status, "sku_id": sku_id,
                    "display_name": name, "package_version_id": pv,
                    "name_choice": name_choice})
    except StoreError as e:
        raise PackagingError(str(e)) from e
    store.append_audit(
        actor=actor, action="packaging.finalized",
        subject_type="package_decision", subject_id=decision_id,
        detail={"status": status, "source": source,
                "name_choice": name_choice, "sku_id": sku_id})
    return out


def supersede(
    store, *, older_id: str, newer_id: str,
    reason: str = "", actor: str,
) -> None:
    """追加 supersede 关系（只增不改：旧决定行保持逐字段不变）。"""
    older = _get(store, older_id)
    newer = _get(store, newer_id)
    for d in (older, newer):
        if d["status"] not in FINAL_STATUSES:
            raise PackagingError(
                f"supersede 双方必须均已终结（{d['decision_id']} 当前"
                f" {d['status']!r}）")
    try:
        store.add_package_supersede(
            older_decision_id=older_id, newer_decision_id=newer_id,
            reason=reason, created_by=actor)
    except StoreError as e:
        raise PackagingError(str(e)) from e
    store.append_audit(
        actor=actor, action="packaging.superseded",
        subject_type="package_decision", subject_id=older_id,
        detail={"newer_decision_id": newer_id, "reason": reason})


def supersede_history(store, decision_id: str) -> list[dict[str, Any]]:
    _get(store, decision_id)
    return store.list_package_supersedes(decision_id)


def get_decision(store, decision_id: str) -> dict[str, Any]:
    return _get(store, decision_id)


def list_decisions(
    store, *, sku_id: str | None = None, status: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    return store.list_package_decisions(sku_id=sku_id, status=status,
                                        limit=limit)
