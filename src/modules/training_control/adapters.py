"""GLTC Task 5：四训练 Lane Adapter。

统一接口：validate_plan / build_command_or_callable / start /
stream_progress / request_safe_stop / collect_artifacts / evaluate。
四条 lane 共享同一控制图（Task 6），差异只经 adapter 与 policy 注入。

红线：
- 参数白名单：未知 CLI 参数 fail-closed；
- 目标输出目录已存在拒绝（防覆盖）；
- 旧业务 checkpoint 禁入（contracts 层结构性拒绝）；
- VLM base 只允许 mlx-community HF 权重，禁 Ollama 量化推理制品；
- adapter 只产结构化 TrainingEventV1，不依赖 stdout 文本解析；
- safe-stop 只发 stop_requested 事件，终态由 Worker 证据链确认。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import contracts as C
from . import vocabulary as V


class AdapterError(RuntimeError):
    """Lane adapter 错误（fail-closed）。"""


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class BaseLaneAdapter:
    lane: str = ""
    # CLI 参数白名单（不含值）
    allowed_flags: tuple[str, ...] = ()
    # base_model_source 允许前缀
    allowed_base_prefixes: tuple[str, ...] = ("public:",)

    # ---- 校验 ----

    def validate_plan(self, plan: C.TrainingPlanV2, *,
                      snapshot: dict[str, Any],
                      mode: str = "train",
                      env_probe: Any = None) -> list[C.Blocker]:
        """返回 blocker 列表（空 = 就绪）。plan 构造时已做 lineage 校验。"""
        blockers: list[C.Blocker] = []
        if not any(plan.base_model_source.startswith(p)
                   for p in self.allowed_base_prefixes):
            blockers.append(C.Blocker(
                "BLOCKED_BY_BASE_MODEL",
                f"base_model_source 非法: {plan.base_model_source}"))
        if mode == "train" and not snapshot.get("trainable", False):
            blockers.append(C.Blocker(
                "BLOCKED_BY_DATASET",
                "DatasetSnapshot 非 trainable（缺真值或未发布）"))
        if env_probe is not None and not env_probe():
            blockers.append(C.Blocker(
                "BLOCKED_BY_ENVIRONMENT",
                f"{self.lane} 隔离环境探针失败"))
        return blockers

    # ---- 命令构建 ----

    def build_command_or_callable(self, plan: C.TrainingPlanV2, *,
                                  args: list[str],
                                  output_dir: str) -> dict[str, Any]:
        """构建训练命令（白名单校验 + 目标目录防覆盖）。"""
        for a in args:
            if a.startswith("--") and a not in self.allowed_flags:
                raise AdapterError(
                    f"{self.lane} 参数白名单拒绝: {a}")
        out = Path(output_dir)
        if out.exists():
            raise AdapterError(
                f"目标输出目录已存在，拒绝覆盖: {out}")
        return {
            "lane": self.lane,
            "lineage": plan.lineage(),
            "args": list(args),
            "output_dir": str(out),
            "config_hash": plan.config_hash,
            "code_commit": plan.code_commit,
        }

    # ---- 运行期（结构化事件） ----

    def start(self, command: dict[str, Any]) -> C.TrainingEventV1:
        return C.TrainingEventV1(
            run_id=command.get("run_id", ""), seq=1, kind="started",
            payload={"lane": self.lane,
                     "config_hash": command.get("config_hash")})

    def stream_progress(self, raw_events: list[dict[str, Any]],
                        *, run_id: str = "") -> list[C.TrainingEventV1]:
        """把 worker 上报的结构化 dict 转成 typed 事件；
        非法 kind 直接丢弃（不做 stdout 文本猜测）。"""
        out: list[C.TrainingEventV1] = []
        seq = 0
        for raw in raw_events:
            kind = raw.get("kind")
            if kind not in V.EVENT_KINDS:
                continue
            seq += 1
            out.append(C.TrainingEventV1(
                run_id=run_id, seq=seq, kind=kind,
                payload=dict(raw.get("payload") or {})))
        return out

    def request_safe_stop(self, *, run_id: str,
                          reason: str) -> C.TrainingEventV1:
        """只发停止请求；确认 checkpoint/退出/lease 释放是 Worker 职责，
        不得在此伪写终态（cancelled 不等于已杀死进程）。"""
        return C.TrainingEventV1(
            run_id=run_id, seq=1, kind="stop_requested",
            payload={"reason": reason, "lane": self.lane,
                     "confirmed": False})

    def collect_artifacts(self, *, run_id: str,
                          entries: list[dict[str, Any]]
                          ) -> list[C.TrainingArtifactV1]:
        return [C.TrainingArtifactV1(
            run_id=run_id, lane=self.lane,
            artifact_type=e["artifact_type"], path=e["path"],
            sha256=e["sha256"], lineage=e.get("lineage", {}))
            for e in entries]

    def evaluate(self, *, run_id: str,
                 eval_report: dict[str, Any]) -> dict[str, Any]:
        """评估钩子：由 Task 10 的 lane 口径实现；此处只做透传投影。"""
        return {"lane": self.lane, "run_id": run_id,
                "report": eval_report,
                "candidate": bool(eval_report.get("pass"))}


class DetectorAdapter(BaseLaneAdapter):
    lane = "detector"
    allowed_flags = ("--data-yaml", "--run-name", "--epochs", "--imgsz",
                     "--device", "--batch", "--parse-check")


class ClassifierAdapter(BaseLaneAdapter):
    lane = "classifier"
    allowed_flags = ("--data-dir", "--classes", "--epochs", "--batch",
                     "--lr", "--device", "--output-dir", "--unknown-class")


class SegmenterAdapter(BaseLaneAdapter):
    """T3：无真实 mask gold 只允许 calibration，禁止权重微调。"""

    lane = "segmenter"
    allowed_flags = ("--mode", "--data-dir", "--prompt-source",
                     "--threshold", "--output-dir")

    def validate_plan(self, plan, *, snapshot, mode="train",
                      env_probe=None) -> list[C.Blocker]:
        blockers = super().validate_plan(
            plan, snapshot=snapshot, mode=mode, env_probe=env_probe)
        if mode == "train" and snapshot.get("mode") == "calibration_only":
            blockers.append(C.Blocker(
                "BLOCKED_BY_MASK_GOLD",
                "无真实 mask gold：SAM 只允许 prompt/阈值/裁剪校准"))
        elif mode == "calibration":
            # calibration 不消耗训练算力：清除数据集可训练性 blocker，
            # 并给出信息性 CALIBRATION_ONLY 标记
            blockers = [b for b in blockers
                        if b.code != "BLOCKED_BY_DATASET"]
            blockers.append(C.Blocker(
                "CALIBRATION_ONLY",
                "segmenter 当前仅校准模式（信息性 blocker）"))
        return blockers


class VlmAdapter(BaseLaneAdapter):
    """T4：MLX QLoRA；禁 Ollama 量化制品作 base；隔离 venv 探针。"""

    lane = "vlm"
    allowed_flags = ("--model", "--data", "--train", "--iters",
                     "--batch-size", "--grad-checkpoint", "--lora-rank",
                     "--lora-alpha", "--learning-rate", "--adapter-path",
                     "--steps-per-report", "--steps-per-eval",
                     "--max-seq-length")
    allowed_base_prefixes = ("public:mlx-community/", "public:Qwen/")

    def build_command_or_callable(self, plan, *, args, output_dir):
        if plan.base_model_source.startswith("ollama:"):
            raise AdapterError(
                "Ollama 量化推理制品不能作为 QLoRA 基础权重")
        return super().build_command_or_callable(
            plan, args=args, output_dir=output_dir)

    def validate_plan(self, plan, *, snapshot, mode="train",
                      env_probe=None) -> list[C.Blocker]:
        if env_probe is None:
            def env_probe() -> bool:  # 默认探针：隔离 venv 是否存在
                return (PROJECT_ROOT / ".venv_mlx_vlm").is_dir()
        return super().validate_plan(
            plan, snapshot=snapshot, mode=mode, env_probe=env_probe)


_ADAPTERS: dict[str, BaseLaneAdapter] = {
    "detector": DetectorAdapter(),
    "classifier": ClassifierAdapter(),
    "segmenter": SegmenterAdapter(),
    "vlm": VlmAdapter(),
}


def get_adapter(lane: str) -> BaseLaneAdapter:
    if lane not in _ADAPTERS:
        raise AdapterError(f"未注册 lane: {lane}（冻结四通道）")
    return _ADAPTERS[lane]
