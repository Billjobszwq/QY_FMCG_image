"""W6/M2：IAM 最小模型（本机单租户起步）。

红线：训练审批（training.approve）与模型发布审批（model.publish.approve）
必须是两个独立动作，不得合并；旧 /retrain 的 auto_switch=true 不进新平台。
"""

from __future__ import annotations

ROLES = ("viewer", "operator", "admin")
_ROLE_RANK = {"viewer": 1, "operator": 2, "admin": 3}

# action -> 所需最低角色
ACTION_MIN_ROLE: dict[str, str] = {
    "view": "viewer",
    "run.execute": "operator",
    "gate.approve": "operator",
    "training.request": "operator",
    "training.approve": "admin",        # 独立审批动作 1
    "model.publish.approve": "admin",   # 独立审批动作 2（不得与上者合并）
    "system.admin": "admin",
}


def can(role: str, action: str) -> bool:
    """fail-closed：未知角色或未知动作一律拒绝。"""
    if role not in _ROLE_RANK or action not in ACTION_MIN_ROLE:
        return False
    return _ROLE_RANK[role] >= _ROLE_RANK[ACTION_MIN_ROLE[action]]
