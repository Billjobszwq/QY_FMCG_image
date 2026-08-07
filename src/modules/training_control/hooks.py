"""GLTC Task 6：13 个 Hook（01 §6.1）。

Hook 只能推进合法状态（经 TrainingControlGraph.advance 校验），
不能绕过状态机；人工 Hook 只写 checkpoint，不代替人工决定。
"""
from __future__ import annotations

from typing import Any

from . import vocabulary as V
from .graph import GraphError

# hook -> (要求的当前状态, 推进目标状态)；None 表示不做状态推进
_HOOK_EFFECTS: dict[str, tuple[str | None, str | None]] = {
    "HOOK_DATASET_READY": (None, None),
    "HOOK_LABEL_GOLD_READY": (None, None),
    "HOOK_APPLE_RESOURCE_READY": (None, None),
    "HOOK_TRAINING_APPROVAL_REQUIRED": (None, None),  # 写 checkpoint
    "HOOK_RUN_STARTED": ("STARTING", "RUNNING"),
    "HOOK_RUN_PROGRESS": ("RUNNING", None),
    "HOOK_STOP_LINE_TRIGGERED": ("RUNNING", "STOPPING"),
    "HOOK_RUN_FAILED": (None, "FAILED"),
    "HOOK_EVALUATION_READY": ("COMPLETED", "EVALUATING"),
    "HOOK_REGRESSION_BLOCKED": (None, None),
    "HOOK_SHADOW_READY": ("CANDIDATE_READY", "SHADOW"),
    "HOOK_PUBLISH_APPROVAL_REQUIRED": (None, None),  # 写 checkpoint
    "HOOK_HUMAN_REVIEW_REQUIRED": (None, None),
}

_CHECKPOINT_HOOKS = {
    "HOOK_TRAINING_APPROVAL_REQUIRED": "human_approval",
    "HOOK_PUBLISH_APPROVAL_REQUIRED": "publish_approval",
    "HOOK_HUMAN_REVIEW_REQUIRED": "human_review",
}


class HookRegistry:
    def __init__(self) -> None:
        self._names = tuple(V.HOOK_NAMES)
        missing = set(V.HOOK_NAMES) - set(_HOOK_EFFECTS)
        if missing:
            raise GraphError(f"Hook 效果未定义: {sorted(missing)}")

    def names(self) -> tuple[str, ...]:
        return self._names

    def emit(self, name: str, graph: Any, run_id: str, *,
             actor: str, evidence: dict[str, Any] | None = None) -> None:
        if name not in _HOOK_EFFECTS:
            raise GraphError(f"未注册 hook: {name}")
        required, target = _HOOK_EFFECTS[name]
        if required is not None and graph.status(run_id) != required:
            raise GraphError(
                f"hook {name} 仅适用于状态 {required}"
                f"（当前 {graph.status(run_id)}）")
        if name in _CHECKPOINT_HOOKS:
            graph.mark_waiting(run_id, _CHECKPOINT_HOOKS[name])
        if target is not None:
            graph.advance(run_id, target, actor=actor,
                          evidence=evidence, via_hook=name)
