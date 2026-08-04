"""M5 训练治理域模块：DatasetSnapshot / split guard / dry-run / 授权门 / 发布分离。"""

from .service import (
    AuthorizationRequired,
    TrainingGovError,
    TrainingGovernanceService,
    export_inference_manifest,
    promotion_gate,
    split_guard,
    unified_eval,
)

__all__ = [
    "AuthorizationRequired",
    "TrainingGovError",
    "TrainingGovernanceService",
    "export_inference_manifest",
    "promotion_gate",
    "split_guard",
    "unified_eval",
]
