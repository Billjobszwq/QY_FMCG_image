"""GLTC V2 契约：Plan/Run/Event/Artifact/Lease/Readiness/Snapshot。

红线固化在构造函数校验中（fail-closed）：
- parent_artifact_id 只允许 `public:` 前缀的 foundation base；
- 旧业务 checkpoint（.models/sku_*、classifier、E2、prod bundle）
  禁作 parent/resume/EMA/optimizer/distillation teacher；
- proposal_teacher_bundle 是独立字段（仅产 provisional proposal），
  与 parent 结构上不可互换。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import vocabulary as V


class ContractError(ValueError):
    """契约违例（fail-closed）。"""


LINEAGE_FAMILY = V.LINEAGE_FAMILY

# 四快照各自独立 schema（共享身份/泄漏/原子发布基础库，
# 不共享错误标签语义，01 §3.4）
SNAPSHOT_SCHEMA_BY_LANE: dict[str, str] = {
    "detector": "detector-snapshot.v1",
    "classifier": "classifier-snapshot.v1",
    "segmenter": "segmenter-snapshot.v1",
    "vlm": "vlm-snapshot.v1",
}

# proposal teacher 白名单：当前生产 bundle 只允许生成 provisional proposal
ALLOWED_PROPOSAL_TEACHERS: tuple[str, ...] = ("prod_20260805_v5_r1",)


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise ContractError(msg)


def _is_legacy_business_ref(ref: str) -> bool:
    """旧业务制品引用识别：禁入 nextgen 训练血缘。"""
    if not ref:
        return False
    low = ref.lower()
    return (low.startswith(".models/") or low.startswith("prod_")
            or "sku_v" in low or "e2_" in low
            or "classifier/best" in low or "crop_dataset" in low)


def validate_parent_ref(ref: str, *, field_name: str) -> None:
    """parent/resume/EMA/optimizer 引用校验：只允许 public base。"""
    if not ref:
        return
    if _is_legacy_business_ref(ref):
        raise ContractError(
            f"{field_name} 指向旧业务制品（禁止作为 nextgen 血缘）: {ref}")
    _require(ref.startswith("public:"),
             f"{field_name} 只允许 public/foundation base（public: 前缀）: {ref}")


@dataclass(frozen=True)
class TrainingPlanV2:
    """训练计划 V2（01 §7）。lineage 固定 fmcg_nextgen_v1。"""

    lane: str
    dataset_snapshot_id: str
    base_model_source: str
    base_model_revision: str
    config_hash: str
    code_commit: str
    parent_artifact_id: str = ""
    proposal_teacher_bundle: str = ""
    resume_from: str = ""
    ema_from: str = ""
    optimizer_state_from: str = ""
    budget: dict[str, Any] = field(default_factory=dict)
    stop_lines: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require(self.lane in V.TRAINING_LANES,
                 f"非法 lane: {self.lane}（冻结四通道）")
        validate_parent_ref(self.parent_artifact_id,
                            field_name="parent_artifact_id")
        validate_parent_ref(self.resume_from, field_name="resume_from")
        validate_parent_ref(self.ema_from, field_name="ema_from")
        validate_parent_ref(self.optimizer_state_from,
                            field_name="optimizer_state_from")
        if self.proposal_teacher_bundle:
            _require(self.proposal_teacher_bundle in
                     ALLOWED_PROPOSAL_TEACHERS,
                     "proposal_teacher_bundle 只允许当前生产 bundle"
                     f"（只产 provisional proposal）: "
                     f"{self.proposal_teacher_bundle}")
            # teacher 与 parent 结构不可互换：teacher 不得同时充当 parent
            _require(self.parent_artifact_id != self.proposal_teacher_bundle,
                     "proposal_teacher_bundle 不得充当 parent_artifact_id")
        _require(bool(self.dataset_snapshot_id), "dataset_snapshot_id 必填")
        _require(bool(self.config_hash), "config_hash 必填")
        _require(bool(self.code_commit), "code_commit 必填")

    @property
    def lineage_family(self) -> str:
        return LINEAGE_FAMILY

    def lineage(self) -> dict[str, Any]:
        return {
            "lineage_family": LINEAGE_FAMILY,
            "training_lane": self.lane,
            "base_model_source": self.base_model_source,
            "base_model_revision": self.base_model_revision,
            "parent_artifact_id": self.parent_artifact_id,
            "proposal_teacher_bundle": self.proposal_teacher_bundle,
            "dataset_snapshot_id": self.dataset_snapshot_id,
            "code_commit": self.code_commit,
            "config_hash": self.config_hash,
        }


@dataclass(frozen=True)
class TrainingRunV2:
    run_id: str
    plan_id: str
    lane: str
    status: str = "DRAFT"
    worker: str = ""
    pid: int | None = None
    attempt: int = 0

    def __post_init__(self) -> None:
        _require(self.lane in V.TRAINING_LANES, f"非法 lane: {self.lane}")
        _require(self.status in V.RUN_STATES, f"非法状态: {self.status}")


@dataclass(frozen=True)
class TrainingEventV1:
    """append-only 结构化进度事件（禁 stdout 文本解析）。"""

    run_id: str
    seq: int
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    schema_version: str = "training-event.v1"

    def __post_init__(self) -> None:
        _require(self.kind in V.EVENT_KINDS,
                 f"非法事件类型: {self.kind}")
        _require(self.seq >= 1, "seq 必须从 1 递增")


@dataclass(frozen=True)
class TrainingArtifactV1:
    """checkpoint/config/metrics/curves/env 制品登记（必须带哈希）。"""

    run_id: str
    lane: str
    artifact_type: str
    path: str
    sha256: str
    lineage: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require(self.lane in V.TRAINING_LANES, f"非法 lane: {self.lane}")
        _require(bool(self.sha256), "artifact 必须带 sha256")
        _require(bool(self.path), "artifact 必须带 path")


@dataclass(frozen=True)
class ResourceLeaseV1:
    """资源租约：mps/mlx/cpu/io/model_server 排他或共享。"""

    run_id: str
    resource: str
    mode: str = "exclusive"  # exclusive / shared

    def __post_init__(self) -> None:
        _require(self.resource in V.RESOURCES,
                 f"非法资源: {self.resource}")
        _require(self.mode in ("exclusive", "shared"),
                 f"非法租约模式: {self.mode}")


def validate_lease_set(leases: list[ResourceLeaseV1]) -> None:
    """单 run 租约集校验：MPS 与 MLX 互斥（01 §8）。"""
    held = {l.resource for l in leases}
    if "mps" in held and "mlx" in held:
        raise ContractError("同一 run 不得同时持有 mps 与 mlx（互斥）")


def lease_conflicts(leases: list[ResourceLeaseV1]
                    ) -> list[dict[str, str]]:
    """跨 run 冲突检测：heavy 资源并发上限 1；shared 资源不冲突。"""
    conflicts: list[dict[str, str]] = []
    for res in V.HEAVY_RESOURCES:
        holders = [l for l in leases if l.resource == res]
        if len(holders) > V.HEAVY_MAX_CONCURRENCY:
            conflicts.append({
                "resource": res,
                "run_ids": ",".join(sorted({h.run_id for h in holders})),
                "reason": f"heavy 并发上限 {V.HEAVY_MAX_CONCURRENCY}"})
    return conflicts


@dataclass(frozen=True)
class Blocker:
    code: str
    detail: str = ""

    def __post_init__(self) -> None:
        _require(self.code in V.BLOCKER_CODES,
                 f"非法 blocker 代码: {self.code}")


@dataclass(frozen=True)
class LaneReadiness:
    """单 lane 就绪度投影（统一 Web/API 消费）。"""

    lane: str
    ready: bool
    blockers: list[Blocker] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require(self.lane in V.TRAINING_LANES, f"非法 lane: {self.lane}")


@dataclass(frozen=True)
class DatasetSnapshotV2:
    """四通道数据集快照契约（01 §3.3/§3.4）。"""

    lane: str
    snapshot_id: str
    manifest_hash: str
    builder_version: str
    schema_version: str
    split_report: dict[str, Any] = field(default_factory=dict)
    exclusion_ledger: list[dict[str, Any]] = field(default_factory=list)
    quality_histogram: dict[str, Any] = field(default_factory=dict)
    source_hashes: dict[str, str] = field(default_factory=dict)
    trainable: bool = True

    def __post_init__(self) -> None:
        _require(self.lane in V.TRAINING_LANES, f"非法 lane: {self.lane}")
        _require(bool(self.manifest_hash), "manifest_hash 必填")
        _require(self.schema_version == SNAPSHOT_SCHEMA_BY_LANE[self.lane],
                 f"{self.lane} 快照必须使用 schema "
                 f"{SNAPSHOT_SCHEMA_BY_LANE[self.lane]}")
