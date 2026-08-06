"""VLM-011：受治理的 Qwen3-VL 4B QLoRA launcher（门禁 + 冻结命令，不执行）。

红线：
- 业务模型名固定 ``qwen3-vl:4b``；训练基础模型
  ``mlx-community/Qwen3-VL-4B-Instruct-4bit``，官方语义基线
  ``Qwen/Qwen3-VL-4B-Instruct``；Ollama Q4_K_M 推理制品不得作为
  LoRA 训练输入。
- 只生成 MLX-VLM 支持的真实参数；禁止 ``--use-mps``、``--num-epochs``
  与未经版本探针确认的参数。
- 第一轮上限：5,000–20,000 instance、1 epoch、rank16、alpha32、
  batch 不大于 benchmark 推荐值、vision frozen；提高 epoch/数据量/
  train_vision 需要新实验计划与独立批准。
- 本模块不加载权重、不下载模型、不发起训练，只做门禁校验与命令生成。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

VLM_TRAINER_VERSION = "vlm-qlora-launcher.v1"
BUSINESS_MODEL_ID = "qwen3-vl:4b"
DEFAULT_BASE_MODEL = "mlx-community/Qwen3-VL-4B-Instruct-4bit"
OFFICIAL_BASELINE = "Qwen/Qwen3-VL-4B-Instruct"

FIRST_ROUND_LIMITS = {
    "max_epochs": 1,
    "max_lora_rank": 16,
    "max_lora_alpha": 32,
    "min_instances": 5_000,
    "max_instances": 20_000,
}

# MLX-VLM 白名单（其余参数一律拒绝，禁止未经版本探针确认的参数）
ALLOWED_VALUE_ARGS = (
    "--model-path", "--dataset", "--batch-size", "--epochs", "--iters",
    "--learning-rate", "--gradient-accumulation-steps",
    "--lora-rank", "--lora-alpha", "--output-path",
)
ALLOWED_FLAGS = ("--grad-checkpoint", "--train-on-completions",
                 "--train-vision")
FORBIDDEN_ARGS = ("--use-mps", "--num-epochs")

# 需要按授权失败（AuthorizationRequired）而非普通治理失败处理的 blocker
AUTH_CODES = {"training_unauthorized", "train_vision_unauthorized"}


class VlmPlanError(ValueError):
    """VLM 训练计划门禁失败（携带全部 blocker 码，fail-closed）。"""

    def __init__(self, blockers: list[str]) -> None:
        self.blockers = sorted(set(blockers))
        super().__init__(
            "VLM 训练门禁未通过: " + ", ".join(self.blockers))


def check_vlm_gates(spec: dict[str, Any],
                    evidence: dict[str, Any]) -> list[str]:
    """逐项门禁校验，返回全部 blocker 码（fail-closed，不短路）。"""
    blockers: list[str] = []

    snap = evidence.get("snapshot")
    if not snap or not snap.get("manifest_sha256"):
        blockers.append("snapshot_missing")
    else:
        n = snap.get("train_instances")
        if (not isinstance(n, int)
                or not (FIRST_ROUND_LIMITS["min_instances"] <= n
                        <= FIRST_ROUND_LIMITS["max_instances"])):
            blockers.append("instances_out_of_range")

    pre = evidence.get("preflight_report")
    if not pre:
        blockers.append("preflight_missing")
    elif not pre.get("ok"):
        blockers.append("preflight_failed")

    zs = evidence.get("zero_shot_report")
    if not zs:
        blockers.append("zero_shot_missing")
    elif not (zs.get("coverage") and float(zs["coverage"]) > 0):
        blockers.append("zero_shot_insufficient")

    bm = evidence.get("benchmark_report")
    if not bm or "recommended_batch_size" not in bm:
        blockers.append("benchmark_missing")
    elif int(spec.get("batch_size", 0)) > int(bm["recommended_batch_size"]):
        blockers.append("batch_exceeds_benchmark")

    if Path(str(spec.get("output_dir", ""))).exists():
        blockers.append("output_dir_exists")
    if evidence.get("active_training"):
        blockers.append("active_training_conflict")
    if not evidence.get("authorized"):
        blockers.append("training_unauthorized")

    if int(spec.get("epochs", 0)) > FIRST_ROUND_LIMITS["max_epochs"]:
        blockers.append("epochs_exceed_first_round")
    if int(spec.get("lora_rank", 0)) > FIRST_ROUND_LIMITS["max_lora_rank"]:
        blockers.append("rank_exceed_first_round")
    if int(spec.get("lora_alpha", 0)) > FIRST_ROUND_LIMITS["max_lora_alpha"]:
        blockers.append("alpha_exceed_first_round")

    if spec.get("train_vision") and not evidence.get("vision_authorized"):
        blockers.append("train_vision_unauthorized")
    return blockers


def build_mlx_command(spec: dict[str, Any]) -> list[str]:
    """生成 MLX-VLM 真实参数命令；禁止参数 fail-closed。"""
    cmd = [
        "python3", "-m", "mlx_vlm.lora",
        "--model-path", str(spec["model_path"]),
        "--dataset", str(spec["dataset_path"]),
        "--batch-size", str(int(spec["batch_size"])),
        "--epochs", str(int(spec["epochs"])),
        "--learning-rate", str(spec["learning_rate"]),
        "--grad-checkpoint",
        "--gradient-accumulation-steps",
        str(int(spec["gradient_accumulation_steps"])),
        "--train-on-completions",
        "--lora-rank", str(int(spec["lora_rank"])),
        "--lora-alpha", str(int(spec["lora_alpha"])),
        "--output-path", str(spec["output_dir"]),
    ]
    if spec.get("train_vision"):
        cmd.append("--train-vision")
    hit = [a for a in cmd if a in FORBIDDEN_ARGS]
    if hit:
        raise VlmPlanError([f"forbidden_arg:{a}" for a in hit])
    return cmd


def plan_vlm(spec: dict[str, Any],
             evidence: dict[str, Any]) -> dict[str, Any]:
    """门禁全绿才产出冻结计划；任一 blocker 即抛 VlmPlanError。"""
    blockers = check_vlm_gates(spec, evidence)
    if blockers:
        raise VlmPlanError(blockers)
    command = build_mlx_command(spec)
    return {
        "trainer_version": VLM_TRAINER_VERSION,
        "model_id": BUSINESS_MODEL_ID,
        "base_model": str(spec["model_path"]),
        "official_baseline": OFFICIAL_BASELINE,
        "command": command,
        "limits": dict(FIRST_ROUND_LIMITS),
        "train_vision": bool(spec.get("train_vision")),
        "note": ("第一轮上限内执行；提高 epoch/数据量/train_vision "
                 "需新实验计划与独立批准"),
    }
