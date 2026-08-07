"""GLTC 词汇表：lane、状态机、事件、Hook、租约资源、blocker 代码。

所有集合冻结；新增必须走文档修订 + 契约测试更新。
"""
from __future__ import annotations

# ---- 四条训练 lane（训练能力，不是客户档位）----
TRAINING_LANES: tuple[str, ...] = (
    "detector", "classifier", "segmenter", "vlm")

# ---- Run 状态机（01 §7；无 CANCELLED 捷径：安全停止必须有证据链）----
RUN_STATES: tuple[str, ...] = (
    "DRAFT", "BLOCKED", "READY_FOR_APPROVAL", "APPROVED", "QUEUED",
    "STARTING", "RUNNING", "STOPPING", "STOPPED", "FAILED", "COMPLETED",
    "EVALUATING", "CANDIDATE_REJECTED", "CANDIDATE_READY", "SHADOW",
    "PUBLISH_REQUESTED", "PUBLISHED", "PUBLISH_REJECTED",
)

RUN_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "DRAFT": ("BLOCKED", "READY_FOR_APPROVAL"),
    "BLOCKED": ("DRAFT", "READY_FOR_APPROVAL"),
    "READY_FOR_APPROVAL": ("APPROVED", "BLOCKED", "DRAFT"),
    "APPROVED": ("QUEUED", "BLOCKED"),
    "QUEUED": ("STARTING", "FAILED"),
    "STARTING": ("RUNNING", "FAILED"),
    "RUNNING": ("STOPPING", "FAILED", "COMPLETED"),
    "STOPPING": ("STOPPED", "FAILED"),
    "STOPPED": ("READY_FOR_APPROVAL",),  # 恢复需重新审批入队
    "FAILED": ("READY_FOR_APPROVAL",),
    "COMPLETED": ("EVALUATING",),
    "EVALUATING": ("CANDIDATE_READY", "CANDIDATE_REJECTED", "FAILED"),
    "CANDIDATE_REJECTED": (),
    "CANDIDATE_READY": ("SHADOW",),
    "SHADOW": ("PUBLISH_REQUESTED", "CANDIDATE_REJECTED"),
    "PUBLISH_REQUESTED": ("PUBLISHED", "PUBLISH_REJECTED"),
    "PUBLISHED": (),
    "PUBLISH_REJECTED": (),
}


def can_transition(current: str, target: str) -> bool:
    """状态机合法跃迁判定；未声明的一律拒绝。"""
    return target in RUN_TRANSITIONS.get(current, ())


# ---- 结构化事件（append-only，禁 stdout 文本解析）----
EVENT_KINDS: tuple[str, ...] = (
    "started", "progress", "stop_requested", "stopped", "failed",
    "completed", "checkpoint_saved", "lease_acquired", "lease_released",
    "evaluation_ready", "gate_blocked",
)

# ---- Hook（01 §6.1 全集）----
HOOK_NAMES: tuple[str, ...] = (
    "HOOK_DATASET_READY", "HOOK_LABEL_GOLD_READY",
    "HOOK_APPLE_RESOURCE_READY", "HOOK_TRAINING_APPROVAL_REQUIRED",
    "HOOK_RUN_STARTED", "HOOK_RUN_PROGRESS", "HOOK_STOP_LINE_TRIGGERED",
    "HOOK_RUN_FAILED", "HOOK_EVALUATION_READY", "HOOK_REGRESSION_BLOCKED",
    "HOOK_SHADOW_READY", "HOOK_PUBLISH_APPROVAL_REQUIRED",
    "HOOK_HUMAN_REVIEW_REQUIRED",
)

# ---- 资源租约（01 §8）----
RESOURCES: tuple[str, ...] = ("mps", "mlx", "cpu", "io", "model_server")
HEAVY_RESOURCES: tuple[str, ...] = ("mps", "mlx")
HEAVY_MAX_CONCURRENCY = 1  # 本机初期只允许一个 heavy accelerator lease

# ---- Readiness blocker 代码 ----
BLOCKER_CODES: tuple[str, ...] = (
    "BLOCKED_BY_MASK_GOLD",        # T3 无真实 mask gold，不得伪称微调
    "CALIBRATION_ONLY",            # T3 仅允许 prompt/阈值/裁剪校准
    "BLOCKED_BY_GOLD",             # 无 human_final/gold_verified 真值
    "BLOCKED_BY_DATASET",          # DatasetSnapshot 未冻结/未发布
    "BLOCKED_BY_HARDWARE_GATE",    # G0 未通过
    "BLOCKED_BY_AUTHORIZATION",    # 无显式训练授权
    "BLOCKED_BY_RESOURCE_LEASE",   # heavy lease 冲突
    "BLOCKED_BY_BASE_MODEL",       # base/parent 校验失败
    "BLOCKED_BY_ENVIRONMENT",      # 隔离环境（如 .venv_mlx_vlm）缺失
)

# ---- 旧模型登记状态（01 §2.1）----
LEGACY_MODEL_STATUSES: tuple[str, ...] = (
    "production_legacy", "historical", "experimental_ended", "quarantined")

LINEAGE_FAMILY = "fmcg_nextgen_v1"
