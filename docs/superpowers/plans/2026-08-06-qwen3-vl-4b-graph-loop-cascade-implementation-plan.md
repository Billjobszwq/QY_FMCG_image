# Qwen3-VL 4B + Graph+Loop FMCG Cascade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不替换现有生产 bundle 的前提下，把 YOLO、ResNet、SAM、OCR/检索、`qwen3-vl:4b` 和人工审核接入现有 Graph+Loop v2，形成可校准、可计费、可审计、适配 Apple Silicon 的四档客户智能级联。

**Architecture:** 复用现有 PlatformStore、CapabilityRegistry、LoopEngine、Job/Worker、CAS、UsageEvent 和统一 Web，不新建第二套 Orchestrator 或数据库。客户档位只定义预算、SLA 和最大阶段；内部 S0–S5 根据校准风险升级。Qwen 使用隔离 MLX-VLM 环境和 QLoRA，初期只做闭集候选裁决与 unknown/new-package 判断，作为 cold/sleeping capability 按需加载。

**Tech Stack:** Python 3.11–3.13、FastAPI、Pydantic、SQLite/PostgreSQL 兼容 PlatformStore、PyTorch/MPS、Ultralytics、SAM2.1、MLX、MLX-VLM、Hugging Face Datasets、React/TypeScript、pytest。

---

## 0. 执行前必须完整阅读

Agent 必须按顺序完整阅读，不能只读摘要：

1. `docs/superpowers/specs/2026-08-04-fmcg-vision-saas-platform-design.md`
2. `docs/superpowers/specs/2026-08-06-qwen3-vl-4b-graph-loop-cascade-design.md`
3. `docs/superpowers/plans/2026-08-05-unified-management-all-photo-training-execution-manual.md`
4. `docs/training-history-and-decisions.md`
5. `docs/tuning-methodology.md`
6. `docs/implementation/platform-v2/STATUS.md`
7. `docs/implementation/platform-v2/ISSUES.md`
8. `docs/implementation/platform-v2/DECISIONS.md`
9. `docs/implementation/platform-v2/IMPLEMENTATION-LIST.md`
10. `docs/implementation/platform-v2/EXECUTION-LOG.md`
11. `src/platform/registry.py`
12. `src/platform/contracts.py`
13. `src/platform/kernel/loop.py`
14. `src/platform/loops/pipeline_v2.py`
15. `src/platform/data/store.py`
16. `src/cascade/cascade_inference.py`
17. `src/pipeline/recognize.py`
18. `src/platform/quality/qpol_v2.py`
19. `src/training/quality_gate.py`
20. `src/training/sam_refine.py`

完成阅读后，先在 `docs/implementation/platform-v2/IMPLEMENTATION-LIST.md` 新增 `VLM-000` 至 `VLM-018`，状态全部为 `PENDING`；在 `EXECUTION-LOG.md` 追加本轮基线，不覆盖历史记录。

## 1. 不可突破的执行红线

- 不删除、移动、覆盖原图、SQLite/PostgreSQL、模型、数据集、审核、SAM、quality、eval、日志、备份、失败制品或临时制品。
- 不暂存 `.quality/`、`.sam_checkpoints/`、`.sam_runs/`、`.superpowers/`、`.models/`、`.datasets/`、`.eval/` 和任何密钥。
- 不使用 `git add .` 或 `git add -A`；每次只暂存任务明确列出的源码、测试和文档。
- 不自动 merge、push、deploy、force-push 或切换 production bundle。
- 不恢复 v6 lineage；不覆盖 `prod_20260804_v4_r2`。
- 当前 `sku_v7_sam` 训练进程存在时，不安装大型模型、不下载 Qwen 权重、不启动 MLX benchmark/微调、不启动第二个 MPS 重任务。
- 当前训练只标记为 `experimental`；训练自然停止后先评估，不自动发布。
- Qwen 训练和推理环境必须与主 YOLO/平台环境隔离。
- 所有模型输出缺少模型版本、输入哈希、策略版本或证据时 fail-closed。
- 任何 Qwen 输出的 `sku_id` 不在输入 CandidateSet 或 SKU Registry 中时，不得 accepted。
- 新包装和疑似新 SKU 只能创建待审核候选，不能自动修改商品主数据。

## 2. 目标文件结构

以下结构在 Task 1 冻结后不得随意把逻辑塞回 `cascade_inference.py` 或 `app.py`：

```text
src/modules/fmcg/cascade/
  __init__.py                 # 公开入口和版本
  contracts.py                # Region、Candidate、Prediction、Risk、Policy 契约
  policy.py                   # 客户档位与阶段预算策略
  risk.py                     # 特征提取、校准器加载、风险决策
  service.py                  # 单阶段能力组合，不负责 Graph 路由
  graph.py                    # S0–S5 GraphV2、handlers、routers
  manifest.py                 # FMCG 能力清单，由组合根注册
  billing.py                  # 级联计量明细和 RateCard 映射
  packaging.py                # 新包装候选和人工裁决状态机

src/modules/fmcg/adapters/
  __init__.py
  quality.py                  # qpol_v2 与统一四级质量结论适配
  scene.py                    # 场景/价签能力，未知时诚实转人工
  legacy_cascade.py           # 8091/现有 Cascade 兼容能力
  sam_refiner.py              # SAM 推理能力适配
  sku_retrieval.py            # OCR/属性/向量候选能力适配
  qwen3vl_mlx.py              # MLX-VLM HTTP 适配，严格结构化输出
  human_review.py             # 平台审核/Label Studio 适配

src/platform/model_runtime.py # 通用 hot/warm/cold 驻留状态和资源租约
src/platform/api/cascade.py   # 统一级联任务 API

src/training/vlm/
  __init__.py
  contracts.py                # CanonicalVlmSample 和快照清单
  builder.py                  # 资产/框/registry → canonical manifest
  hf_dataset.py               # canonical manifest → HF Dataset
  split_guard.py              # 客户/门店/session/近重复/协议隔离
  preflight.py                # Apple/MLX/内存/swap/服务门禁
  benchmark.py                # 200–500 step probe
  evaluate.py                 # zero-shot/adapter 同口径评估
  train.py                    # 受治理 QLoRA launcher

scripts/
  build_qwen3vl_dataset.py
  run_qwen3vl_preflight.py
  run_qwen3vl_zero_shot.py
  run_qwen3vl_benchmark.py
  run_qwen3vl_lora.py
  run_cascade_shadow_eval.py

tests/platform/
  test_vlm_contracts.py
  test_vlm_registry.py
  test_model_residency.py
  test_cascade_policy.py
  test_cascade_loop.py
  test_cascade_api.py
  test_cascade_billing.py
  test_vlm_training_gov.py
  test_new_packaging.py
  test_cascade_web_contract.py

tests/unit/
  test_cascade_adapters.py
  test_cascade_risk.py
  test_qwen3vl_adapter.py
  test_vlm_split_guard.py
  test_vlm_dataset_builder.py
  test_vlm_preflight.py
  test_vlm_evaluate.py
  test_cascade_shadow_eval.py

web/src/pages/
  CascadeTasks.tsx
  ModelRuntime.tsx
  NewPackaging.tsx
```

修改现有文件：

- `src/platform/registry.py`
- `src/platform/data/store.py`
- `src/platform/api/app.py`
- `src/platform/api/bundle.py`
- `src/composition/build.py`
- `src/cascade/cascade_inference.py`
- `src/pipeline/recognize.py`
- `src/training/quality_gate.py`
- `scripts/run_quality_screen.py`
- `src/modules/training_gov/service.py`
- `src/platform/api/training.py`
- `src/platform/jobs.py`
- `web/src/App.tsx`
- `web/src/api.ts`
- `web/src/pages/Recognition.tsx`
- `web/src/pages/GraphRuns.tsx`
- `web/src/pages/Training.tsx`
- `web/src/styles.css`
- `pyproject.toml`，只增加隔离可选依赖说明，不强迫主运行环境安装 MLX
- `docs/implementation/platform-v2/{STATUS,ISSUES,DECISIONS,IMPLEMENTATION-LIST,EXECUTION-LOG}.md`
- `docs/README.md`

## Task 0: 运行事实对账和当前训练封存

**Files:**
- Modify: `docs/implementation/platform-v2/STATUS.md`
- Modify: `docs/implementation/platform-v2/ISSUES.md`
- Modify: `docs/implementation/platform-v2/IMPLEMENTATION-LIST.md`
- Modify: `docs/implementation/platform-v2/EXECUTION-LOG.md`
- Create after training ends: `docs/experiments/sku-v7-sam-final-evaluation.md`

- [ ] **Step 1: 只读确认训练进程和 Git 状态**

Run:

```bash
git status --short --branch
git rev-parse HEAD
ps aux
```

Expected: 精确记录当前分支、HEAD、未跟踪制品和 `src.training.train_v1 ... sku_v7_sam` 是否存在。不得因为进程存在而改写训练状态为成功。

- [ ] **Step 2: 解析训练结果而不读取 ANSI 巨型日志全文**

Run:

```bash
python3 - <<'PY'
import csv
from pathlib import Path
p = Path('.models/sku_v7_sam/results.csv')
rows = list(csv.DictReader(p.open()))
print({'epochs_completed': len(rows), 'last': rows[-1] if rows else None})
PY
```

Expected: 输出已完成 epoch 和最后一轮指标；如果训练仍在运行，状态写 `RUNNING_EXPERIMENTAL`。

- [ ] **Step 3: 把治理偏差写入 ISSUE**

至少新增：

```text
VLM-ISSUE-001 STATUS.md 与实际训练进程不一致
VLM-ISSUE-002 optimizer=auto 忽略 lr0=0.0005，实际 MuSGD lr=0.01
VLM-ISSUE-003 934/944 reject 由未有人工金标准的 tilt 启发式产生
VLM-ISSUE-004 SAM 96.5% 只代表几何通过，不代表 truebox/SKU 正确
VLM-ISSUE-005 Qwen/MLX 环境尚未安装，旧训练耗时估算无证据
```

- [ ] **Step 4: 训练结束后运行严格评估**

复用 `src/eval/truebox_eval.py` 和现有 frozen protocol；如果人工 truebox 不完整，报告必须同时列出“可计算指标”和“因人工未完成不可计算指标”。不得用 Ultralytics val mAP 替代业务级 accepted precision。

- [ ] **Step 5: Commit 文档对账**

```bash
git add docs/implementation/platform-v2/STATUS.md docs/implementation/platform-v2/ISSUES.md docs/implementation/platform-v2/IMPLEMENTATION-LIST.md docs/implementation/platform-v2/EXECUTION-LOG.md docs/experiments/sku-v7-sam-final-evaluation.md
git commit -m "docs: reconcile active training and cascade baseline"
```

只在训练已经结束且评估文档实际存在时暂存最后一个文件；否则从命令中移除该路径。

## Task 1: 冻结统一级联契约

**Files:**
- Create: `src/modules/fmcg/cascade/__init__.py`
- Create: `src/modules/fmcg/cascade/contracts.py`
- Test: `tests/platform/test_vlm_contracts.py`

- [ ] **Step 1: 写失败测试**

```python
import pytest
from pydantic import ValidationError

from src.modules.fmcg.cascade.contracts import Candidate, PredictionEnvelope


def test_prediction_rejects_unknown_extra_fields():
    with pytest.raises(ValidationError):
        PredictionEnvelope(
            prediction_id="p1", run_id="r1", asset_id="a1", region_id="g1",
            stage="S1", model_id="resnet18", model_version="sha",
            registry_version="reg1", policy_version="pol1",
            topk=[Candidate(sku_id="SKU-1", score=0.7)],
            signals={}, calibrated_risk=0.1, decision="accepted",
            latency_ms=2.0, evidence_ids=[], unexpected=True,
        )


def test_accepted_requires_sku_and_evidence():
    with pytest.raises(ValidationError):
        PredictionEnvelope(
            prediction_id="p1", run_id="r1", asset_id="a1", region_id="g1",
            stage="S1", model_id="resnet18", model_version="sha",
            registry_version="reg1", policy_version="pol1", topk=[], signals={},
            calibrated_risk=0.1, decision="accepted", latency_ms=2.0,
            evidence_ids=[],
        )
```

- [ ] **Step 2: 验证测试为红**

Run: `python -m pytest tests/platform/test_vlm_contracts.py -q -p no:cacheprovider`

Expected: FAIL，模块不存在。

- [ ] **Step 3: 实现最小冻结契约**

必须使用 `ConfigDict(extra="forbid", frozen=True)`，并定义：

```python
class Candidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    sku_id: str
    score: float
    source: str = "model"


class PredictionEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    prediction_id: str
    run_id: str
    asset_id: str
    region_id: str
    stage: Literal["S1", "S2", "S3", "S4", "S5"]
    model_id: str
    model_version: str
    registry_version: str
    policy_version: str
    topk: list[Candidate]
    signals: dict[str, Any]
    calibrated_risk: float = Field(ge=0.0, le=1.0)
    decision: Literal["accepted", "needs_review", "unknown", "new_package"]
    sku_id: str | None = None
    package_version_id: str | None = None
    abstain_reason: str | None = None
    latency_ms: float = Field(ge=0.0)
    evidence_ids: list[str]

    @model_validator(mode="after")
    def accepted_has_identity_and_evidence(self):
        if self.decision == "accepted" and (not self.sku_id or not self.evidence_ids):
            raise ValueError("accepted requires sku_id and evidence")
        return self
```

同文件定义 `RegionRef`、`CandidateSet`、`RiskDecision`、`CascadePolicy` 和 `QwenSkuDecision`，字段严格对应规格文档。

- [ ] **Step 4: 运行测试**

Run: `python -m pytest tests/platform/test_vlm_contracts.py -q -p no:cacheprovider`

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/modules/fmcg/cascade/__init__.py src/modules/fmcg/cascade/contracts.py tests/platform/test_vlm_contracts.py
git commit -m "feat: freeze FMCG cascade contracts"
```

## Task 2: 扩展 Capability Registry，不破坏依赖方向

**Files:**
- Create: `src/modules/fmcg/adapters/__init__.py`
- Create: `src/modules/fmcg/cascade/manifest.py`
- Modify: `src/platform/registry.py`
- Modify: `src/composition/build.py`
- Test: `tests/platform/test_vlm_registry.py`

- [ ] **Step 1: 写注册失败和重复能力测试**

测试必须断言以下 ID 全部存在且 adapter 缺失时拒绝注册：

```python
EXPECTED = {
    "vision.quality.assess.v2",
    "vision.scene.classify.v1",
    "vision.detect.product.v1",
    "vision.classify.sku.fast.v1",
    "vision.segment.refine.sam.v1",
    "vision.retrieve.sku.v1",
    "vision.vlm.qwen3vl4b.rerank.v1",
    "vision.human.review.v1",
}
```

- [ ] **Step 2: 运行红测试**

Run: `python -m pytest tests/platform/test_vlm_registry.py -q -p no:cacheprovider`

Expected: FAIL，新 manifest 不存在。

- [ ] **Step 3: 扩展通用 Capability 元数据**

在 `CapabilitySpec` 增加有默认值的通用字段，旧 manifest 不需要修改即可继续工作；同时在 `src/platform/registry.py` 补充 `from typing import Literal`：

```python
resource_class: str = "cpu"
residency: Literal["hot", "warm", "cold"] = "hot"
meter_units: tuple[str, ...] = ("call",)
```

`CapabilityRegistry.capabilities()` 返回这些字段。字段只描述运行特征，不在 platform 内出现 YOLO、SAM、Qwen 或 FMCG 名称。

- [ ] **Step 4: 在 Domain Pack 定义 manifest 并由组合根注入**

`src/modules/fmcg/cascade/manifest.py` 只返回 `ModuleManifest` 和 adapter mapping。平台组合根负责注入，`src/platform` 不得 import `src.modules`。

```python
CAP_QUALITY = "vision.quality.assess.v2"
CAP_SCENE = "vision.scene.classify.v1"
CAP_DETECT = "vision.detect.product.v1"
CAP_FAST_SKU = "vision.classify.sku.fast.v1"
CAP_SAM = "vision.segment.refine.sam.v1"
CAP_RETRIEVE = "vision.retrieve.sku.v1"
CAP_QWEN = "vision.vlm.qwen3vl4b.rerank.v1"
CAP_HUMAN = "vision.human.review.v1"


def build_fmcg_manifest() -> ModuleManifest:
    return ModuleManifest(
        module_id="fmcg.vision.cascade",
        name="FMCG Vision Cascade",
        version="1.0.0",
        capabilities=[
            CapabilitySpec(
                capability_id=CAP_QUALITY,
                kind="quality_assessment",
                description="Versioned quality and evidence assessment",
                resource_class="cpu",
                residency="hot",
                meter_units=("photo",),
            ),
            CapabilitySpec(
                capability_id=CAP_SCENE,
                kind="scene_classification",
                description="Scene and price-tag presence classification",
                resource_class="mps_light",
                residency="warm",
                meter_units=("photo",),
            ),
            CapabilitySpec(
                capability_id=CAP_DETECT,
                kind="product_detection",
                description="YOLO product localization",
                resource_class="mps_medium",
                residency="hot",
                meter_units=("photo", "region"),
            ),
            CapabilitySpec(
                capability_id=CAP_FAST_SKU,
                kind="sku_classification",
                description="Fast closed-set SKU classification",
                resource_class="mps_light",
                residency="hot",
                meter_units=("region",),
            ),
            CapabilitySpec(
                capability_id=CAP_SAM,
                kind="mask_refinement",
                description="SAM mask and crop refinement",
                resource_class="mps_medium",
                residency="warm",
                meter_units=("region", "mask"),
            ),
            CapabilitySpec(
                capability_id=CAP_RETRIEVE,
                kind="sku_retrieval",
                description="OCR, attributes and vector candidate retrieval",
                resource_class="mixed",
                residency="warm",
                meter_units=("region", "candidate"),
            ),
            CapabilitySpec(
                capability_id=CAP_QWEN,
                kind="vlm_rerank",
                description="Qwen3-VL 4B closed-set SKU reranker",
                resource_class="mlx_vlm",
                residency="cold",
                meter_units=("request", "input_token", "output_token"),
            ),
            CapabilitySpec(
                capability_id=CAP_HUMAN,
                kind="human_review",
                description="Auditable human review handoff",
                resource_class="human",
                residency="hot",
                meter_units=("task",),
            ),
        ],
    )
```

上述八项必须逐项注册，不在 platform registry 中硬编码 FMCG。

`src/composition/build.py` 是唯一允许同时 import platform 和 Domain Pack 的组合根；它调用 `build_fmcg_manifest()` 并传入实际 adapters。现有 `bootstrap_default_registry()` 保留 legacy 能力，测试注入 fake adapters 时不得连接真实服务。

- [ ] **Step 5: 运行依赖方向守卫**

Run:

```bash
python -m pytest tests/platform/test_vlm_registry.py tests/platform/test_m2_registry.py::test_platform_does_not_import_domain_modules -q -p no:cacheprovider
```

Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add src/modules/fmcg/adapters/__init__.py src/modules/fmcg/cascade/manifest.py src/platform/registry.py src/composition/build.py tests/platform/test_vlm_registry.py
git commit -m "feat: register FMCG cascade capabilities"
```

## Task 3: 模型驻留管理器

**Files:**
- Create: `src/platform/model_runtime.py`
- Modify: `src/platform/data/store.py`
- Test: `tests/platform/test_model_residency.py`

- [ ] **Step 1: 写失败测试**

覆盖：cold→loading→hot、TTL unload、并发租约、加载失败、进程重启后状态恢复、Qwen 初期 max_concurrency=1。

```python
def test_qwen_single_lease_and_idle_unload(store, clock):
    mgr = ModelResidencyManager(store, now=clock.now)
    mgr.register("qwen3-vl:4b", residency="cold", max_concurrency=1, idle_ttl_s=300)
    lease = mgr.acquire("qwen3-vl:4b", run_id="r1")
    assert mgr.state("qwen3-vl:4b")["active_leases"] == 1
    with pytest.raises(ModelBusy):
        mgr.acquire("qwen3-vl:4b", run_id="r2")
    mgr.release(lease.lease_id)
    clock.advance(301)
    assert mgr.unload_idle() == ["qwen3-vl:4b"]
```

- [ ] **Step 2: 运行红测试**

Run: `python -m pytest tests/platform/test_model_residency.py -q -p no:cacheprovider`

- [ ] **Step 3: 实现通用状态机**

允许状态：`cold/loading/hot/unloading/failed`。所有 acquire/release/load/unload 写 audit；租约带 `run_id`、`attempt_id`、deadline。进程崩溃后的过期租约由显式 reap 恢复，不能永久占用。

- [ ] **Step 4: 运行测试**

Run: `python -m pytest tests/platform/test_model_residency.py tests/platform/test_platform_store.py -q -p no:cacheprovider`

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/platform/model_runtime.py src/platform/data/store.py tests/platform/test_model_residency.py
git commit -m "feat: add hot warm cold model residency control"
```

## Task 4: 客户四档策略和预算

**Files:**
- Create: `src/modules/fmcg/cascade/policy.py`
- Test: `tests/platform/test_cascade_policy.py`

- [ ] **Step 1: 写策略测试**

```python
def test_customer_tiers_limit_stage_without_bypassing_safety():
    fast = policy_for("fast")
    expert = policy_for("expert")
    assert fast.max_stage == "S1"
    assert expert.max_stage == "S4"
    assert fast.require_quality_gate is True
    assert expert.require_quality_gate is True
    assert expert.vlm_concurrency == 1
```

同时覆盖 SLA、最大区域数、最大 VLM token、人工策略、预算耗尽结果和未知商品必须转人工。

- [ ] **Step 2: 实现版本化策略**

定义 `fast/standard/deep/expert`，禁止用客户档位名称代替内部 S1–S4。策略值从受控配置加载并落入 run checkpoint；运行中配置变化不能改变已启动 run。

- [ ] **Step 3: 验证和提交**

Run: `python -m pytest tests/platform/test_cascade_policy.py -q -p no:cacheprovider`

```bash
git add src/modules/fmcg/cascade/policy.py tests/platform/test_cascade_policy.py
git commit -m "feat: define versioned cascade service tiers"
```

## Task 5: 风险校准器，禁止跨模型原始置信度直连

**Files:**
- Create: `src/modules/fmcg/cascade/risk.py`
- Test: `tests/unit/test_cascade_risk.py`

- [ ] **Step 1: 写失败测试**

```python
def test_raw_confidence_cannot_route_without_calibrator():
    with pytest.raises(CalibrationUnavailable):
        decide_risk(stage="S1", signals={"top1": 0.99}, calibrator=None,
                    policy=policy_for("expert"))


def test_hard_attribute_conflict_forces_escalation(calibrator):
    d = decide_risk(
        stage="S3",
        signals={"top1": 0.96, "margin": 0.7,
                 "ocr_conflicts": ["volume_ml:500!=600"]},
        calibrator=calibrator,
        policy=policy_for("expert"),
    )
    assert d.action == "escalate"
    assert d.next_stage == "S4"
```

- [ ] **Step 2: 实现特征和校准版本**

输入包含 detection stability、top1/margin/entropy、SAM stability/area delta、OCR conflict、retrieval margin、quality、OOD 和 package novelty。校准器只读取冻结 JSON 制品并验证 SHA；初期可以使用明确标记为 `bootstrap_rule_v1` 的规则，但不能称为概率校准。

- [ ] **Step 3: 测试覆盖 NaN/Inf/缺字段**

NaN、Inf、缺校准版本和未识别 stage 一律 `needs_review` 或抛受控错误，不能 accepted。

- [ ] **Step 4: 验证和提交**

Run: `python -m pytest tests/unit/test_cascade_risk.py -q -p no:cacheprovider`

```bash
git add src/modules/fmcg/cascade/risk.py tests/unit/test_cascade_risk.py
git commit -m "feat: add calibrated cascade risk decisions"
```

## Task 6: 现有 YOLO/ResNet、SAM 和检索适配器

**Files:**
- Create: `src/modules/fmcg/adapters/quality.py`
- Create: `src/modules/fmcg/adapters/scene.py`
- Create: `src/modules/fmcg/adapters/legacy_cascade.py`
- Create: `src/modules/fmcg/adapters/sam_refiner.py`
- Create: `src/modules/fmcg/adapters/sku_retrieval.py`
- Modify: `src/cascade/cascade_inference.py`
- Modify: `src/pipeline/recognize.py`
- Test: `tests/unit/test_cascade_adapters.py`

- [ ] **Step 1: 写适配器契约测试**

断言：

- detector 只输出 region，不输出 final SKU；
- ResNet 输出 Top-K、margin、entropy 和模型版本；
- SAM 只输出 mask/crop/evidence，不输出 SKU；
- retrieval 返回 registry 内 CandidateSet；
- quality 返回 pass/warn/manual_review/reject 和不可变证据引用；
- scene 返回货架/冰柜/冷风柜/地堆/堆箱/小货架/unknown 及 price_tag present/absent/unknown；
- legacy 异常映射为受控 capability error。

- [ ] **Step 2: 小步提取，不重写现有生产入口**

给 `CascadeRecognizer` 增加只读的 `detect_regions()` 和 `classify_region()` 方法，`recognize()` 保持现有兼容行为。适配器调用新方法；8091 原 API 测试必须继续通过。

- [ ] **Step 3: 生成多视角输入**

SAM adapter 输出三种引用：原粗框 crop、mask crop、带 10%–20% 上下文 crop。任何 mask 失败保留原框证据并返回 `needs_review`，不伪造 mask。

scene 没有足够模型或人工证据时必须输出 unknown 并进入人工/后续能力，不能用文件名、目录名或默认值伪造具体场景和价签结论。

- [ ] **Step 4: 验证**

Run:

```bash
python -m pytest tests/unit/test_cascade_adapters.py tests/unit/test_cascade_gate.py tests/platform/test_sam_refine.py -q -p no:cacheprovider
```

Expected: PASS，旧 gate 行为不变。

- [ ] **Step 5: Commit**

```bash
git add src/modules/fmcg/adapters/quality.py src/modules/fmcg/adapters/scene.py src/modules/fmcg/adapters/legacy_cascade.py src/modules/fmcg/adapters/sam_refiner.py src/modules/fmcg/adapters/sku_retrieval.py src/cascade/cascade_inference.py src/pipeline/recognize.py tests/unit/test_cascade_adapters.py
git commit -m "feat: expose staged FMCG vision adapters"
```

## Task 7: Qwen3-VL MLX 适配器和结构化输出

**Files:**
- Create: `src/modules/fmcg/adapters/qwen3vl_mlx.py`
- Test: `tests/unit/test_qwen3vl_adapter.py`

- [ ] **Step 1: 写失败测试**

覆盖合法结果、非法 JSON、candidate 外 SKU、registry 缺失、新包装、超时、429、503 和空响应。

```python
def test_candidate_outside_set_never_accepted(fake_http):
    fake_http.reply({"decision": "accepted", "sku_id": "SKU-X",
                     "package_version_id": None, "attributes": {},
                     "conflicts": [], "evidence": [], "abstain_reason": None})
    out = adapter(fake_http).rerank(context(), candidates=[candidate("SKU-A")])
    assert out.decision == "needs_review"
    assert out.abstain_reason == "sku_outside_candidate_set"
```

- [ ] **Step 2: 实现 HTTP adapter**

adapter 只接受受控 `base_url`、模型 ID 和 adapter revision；请求使用 MLX-VLM OpenAI-compatible endpoint。prompt 由固定模板构建，用户不能提交任意 system prompt。输出经 `QwenSkuDecision` 校验。

- [ ] **Step 3: 加入资源租约**

调用前 acquire `qwen3-vl:4b`，finally release；单次 timeout 与 queue SLA 分离。网络重试只对可重试错误执行，使用稳定 idempotency key，最多重试策略由 JobPolicy 注入。

- [ ] **Step 4: 验证和提交**

Run: `python -m pytest tests/unit/test_qwen3vl_adapter.py tests/platform/test_model_residency.py -q -p no:cacheprovider`

```bash
git add src/modules/fmcg/adapters/qwen3vl_mlx.py tests/unit/test_qwen3vl_adapter.py
git commit -m "feat: add guarded Qwen3-VL MLX reranker adapter"
```

## Task 8: Canonical VLM 数据集构建和防泄漏

**Files:**
- Create: `src/training/vlm/__init__.py`
- Create: `src/training/vlm/contracts.py`
- Create: `src/training/vlm/builder.py`
- Create: `src/training/vlm/split_guard.py`
- Create: `src/training/vlm/hf_dataset.py`
- Create: `scripts/build_qwen3vl_dataset.py`
- Modify: `src/training/quality_gate.py`
- Modify: `scripts/run_quality_screen.py`
- Test: `tests/platform/test_quality_gate.py`
- Test: `tests/unit/test_vlm_dataset_builder.py`
- Test: `tests/unit/test_vlm_split_guard.py`

- [ ] **Step 1: 先统一质量门禁红测试**

增加并确认以下行为：

```python
def test_missing_horizontal_lines_requires_review_not_auto_reject():
    out = assess_quality(np.zeros((64, 64), dtype=np.uint8))
    assert out.disposition == "manual_review"
    assert "tilt_unobservable" in out.reason_codes


def test_single_weak_heuristic_cannot_auto_reject():
    out = decide_quality({"blur": 0.46, "reflection": 0.0, "tilt": None})
    assert out.disposition in {"warn", "manual_review"}
```

修改训练质量门，使“无法检测水平线”返回 unobservable/manual_review，不再返回 tilt=1.0 自动 reject。未经人工金标准验证的单项弱启发式不得自动 reject；自动 reject 需要版本化策略规定的多强信号，或人工 final verdict。原 934 张 tilt reject 保留历史证据并进入复核队列，不改写旧 JSON。

- [ ] **Step 2: 运行质量门测试**

Run: `python -m pytest tests/platform/test_quality_gate.py tests/platform/test_u3_qpol_v2.py -q -p no:cacheprovider`

Expected: 新测试先 FAIL，最小实现后 PASS；qpol_v2 历史不可变规则继续通过。

- [ ] **Step 3: 写防泄漏红测试**

必须覆盖 SHA、near_dup_group、customer、store、session、package_version、active protocol 和 frozen role。

```python
@pytest.mark.parametrize("key", [
    "sha256", "near_dup_group", "customer", "store", "session",
    "package_version",
])
def test_group_overlap_rejected(key):
    manifest = manifest_with_overlap(key)
    with pytest.raises(SplitLeakageError):
        validate_splits(manifest)
```

- [ ] **Step 4: 写 builder 红测试**

断言 manual_pending/reject/frozen/model_provisional 无裁决不得进入正式 train；SAM geometry accepted 不自动等于 human_final；每条 sample 有 asset、原图尺寸、pixel bbox、bbox_1000、registry version、label source、weight 和 evidence。

- [ ] **Step 5: 实现 immutable staging builder**

输出目录已存在即拒绝；先写 staging，完成 manifest hash、builder hash、registry hash、split report、sample histogram 和磁盘核对后原子发布。禁止覆盖旧数据集。

- [ ] **Step 6: 转换 MLX-VLM 数据格式**

Hugging Face Dataset 必须为 `images`、`messages`；Qwen 消息使用结构化 content：

```python
messages = [
    {
        "role": "user",
        "content": [
            {"type": "image", "image": image},
            {"type": "text", "text": question},
        ],
    },
    {
        "role": "assistant",
        "content": [{"type": "text", "text": answer_json}],
    },
]
```

不得手工插入 `<|vision_start|>`。

- [ ] **Step 7: 生成四类样本报告**

builder 输出 region crop、full-image bbox、hard-negative、unknown/new-package 数量和比例；同一大图重复视觉 token 估算必须写 audit。

- [ ] **Step 8: 验证**

Run:

```bash
python -m pytest tests/platform/test_quality_gate.py tests/unit/test_vlm_dataset_builder.py tests/unit/test_vlm_split_guard.py tests/contract/test_protocol_isolation.py -q -p no:cacheprovider
```

- [ ] **Step 9: Commit**

```bash
git add src/training/vlm/__init__.py src/training/vlm/contracts.py src/training/vlm/builder.py src/training/vlm/split_guard.py src/training/vlm/hf_dataset.py scripts/build_qwen3vl_dataset.py src/training/quality_gate.py scripts/run_quality_screen.py tests/platform/test_quality_gate.py tests/unit/test_vlm_dataset_builder.py tests/unit/test_vlm_split_guard.py
git commit -m "feat: build guarded Qwen3-VL FMCG datasets"
```

## Task 9: Apple MLX 隔离环境和硬预检

**Files:**
- Create: `src/training/vlm/preflight.py`
- Create: `scripts/run_qwen3vl_preflight.py`
- Modify: `pyproject.toml`
- Test: `tests/unit/test_vlm_preflight.py`

- [ ] **Step 1: 写预检测试**

门禁包含 arm64、Apple Silicon、MLX Metal device、模型可加载、processor 可处理图像、有限前向、AC 电源、磁盘、内存、swap、热状态、当前 YOLO 训练冲突、服务健康和输出目录防覆盖。

- [ ] **Step 2: 实现隔离环境说明**

主项目只增加 `vlm-train` 可选依赖说明；实际安装使用独立环境，例如 `.venv_mlx_vlm`，并锁定：

```text
mlx-vlm[train]
datasets
Pillow
```

版本以安装当日 lock 和官方兼容性探针为准，必须把 `pip freeze`、Python、MLX 和模型 revision 写证据，不能在文档中假装尚未安装的版本已验证。

- [ ] **Step 3: 拒绝并发重训练**

如果进程表存在 `src.training.train_v1`、`mlx_vlm.lora` 或另一个 active training lease，preflight 返回 `ok=false` 和 `active_training_conflict`，不得继续。

- [ ] **Step 4: 运行纯测试**

Run: `python -m pytest tests/unit/test_vlm_preflight.py -q -p no:cacheprovider`

Expected: PASS；测试使用 fake probes，不下载模型。

- [ ] **Step 5: 获得依赖下载授权后才执行真实 preflight**

真实命令必须先获得用户对下载模型和安装依赖的明确授权。证据写入新目录 `.eval/vlm_preflight/<run_id>/`，不得覆盖。

- [ ] **Step 6: Commit**

```bash
git add src/training/vlm/preflight.py scripts/run_qwen3vl_preflight.py pyproject.toml tests/unit/test_vlm_preflight.py
git commit -m "feat: add Apple MLX VLM hard preflight"
```

## Task 10: 零样本评估和 200–500 step 吞吐探针

**Files:**
- Create: `src/training/vlm/evaluate.py`
- Create: `src/training/vlm/benchmark.py`
- Create: `scripts/run_qwen3vl_zero_shot.py`
- Create: `scripts/run_qwen3vl_benchmark.py`
- Test: `tests/unit/test_vlm_evaluate.py`

- [ ] **Step 1: 冻结评估契约**

输出必须包含：Top-1/Top-5、accepted precision、coverage、unknown/new-package precision/recall、schema compliance、candidate escape、属性准确率、p50/p95、tokens/s、峰值内存、swap 和逐实例错误账本。

- [ ] **Step 2: 写确定性评估测试**

```python
def test_high_precision_cannot_hide_zero_coverage():
    report = evaluate_records([
        record(gt="SKU-A", decision="needs_review", pred=None),
        record(gt="SKU-B", decision="needs_review", pred=None),
    ])
    assert report["coverage"] == 0.0
    assert report["accepted_precision"] is None
    assert report["gate_pass"] is False
```

- [ ] **Step 3: 实现 benchmark matrix**

比较 batch 1/2/4、两档视觉 token/分辨率和 QLoRA/BF16 可用配置。每个 probe 使用独立 run 目录，记录实际 sample/region/token 数；不得用照片数代替训练实例数估时。

- [ ] **Step 4: 运行测试和真实探针门**

Run: `python -m pytest tests/unit/test_vlm_evaluate.py tests/unit/test_vlm_preflight.py -q -p no:cacheprovider`

真实 zero-shot/benchmark 只有 Task 9 真门通过后才运行。

- [ ] **Step 5: Commit**

```bash
git add src/training/vlm/evaluate.py src/training/vlm/benchmark.py scripts/run_qwen3vl_zero_shot.py scripts/run_qwen3vl_benchmark.py tests/unit/test_vlm_evaluate.py
git commit -m "feat: benchmark and evaluate Qwen3-VL on Apple"
```

## Task 11: 受治理 QLoRA launcher

**Files:**
- Create: `src/training/vlm/train.py`
- Create: `scripts/run_qwen3vl_lora.py`
- Modify: `src/modules/training_gov/service.py`
- Modify: `src/platform/api/training.py`
- Test: `tests/platform/test_vlm_training_gov.py`

- [ ] **Step 1: 写禁止越权和覆盖测试**

覆盖：无 snapshot、无 preflight、无 zero-shot、无 benchmark、目录存在、训练冲突、未授权、batch 超 benchmark、epochs 超批准值、`train_vision=true` 未单独授权。

- [ ] **Step 2: launcher 生成真实 MLX-VLM 参数**

使用 MLX-VLM 支持的参数：

```text
--model-path
--dataset
--batch-size
--epochs 或 --iters
--learning-rate
--grad-checkpoint
--gradient-accumulation-steps
--train-on-completions
--lora-rank
--lora-alpha
--output-path
```

禁止 `--use-mps`、`--num-epochs` 和未经版本探针确认的参数。

- [ ] **Step 3: 第一轮参数上限**

第一轮只允许：5,000–20,000 instance、1 epoch、rank16、alpha32、batch 不大于 benchmark 推荐值、vision frozen。提高 epoch、数据量或 train_vision 需要创建新实验计划和独立批准。

- [ ] **Step 4: 训练后不自动发布**

完成状态为 `completed_candidate`；adapter、config、loss、tokens/s、环境 lock、数据 hash、模型 revision 和错误样本账本全部注册。发布 API 仍需独立 admin 审批且生产切换默认 false。

- [ ] **Step 5: 验证和提交**

Run:

```bash
python -m pytest tests/platform/test_vlm_training_gov.py tests/platform/test_m5_training_gov.py -q -p no:cacheprovider
```

```bash
git add src/training/vlm/train.py scripts/run_qwen3vl_lora.py src/modules/training_gov/service.py src/platform/api/training.py tests/platform/test_vlm_training_gov.py
git commit -m "feat: govern Qwen3-VL QLoRA pilots"
```

## Task 12: S0–S5 Graph+Loop

**Files:**
- Create: `src/modules/fmcg/cascade/service.py`
- Create: `src/modules/fmcg/cascade/graph.py`
- Create: `src/modules/fmcg/adapters/human_review.py`
- Test: `tests/platform/test_cascade_loop.py`

- [ ] **Step 1: 写完整路由红测试**

测试四条路径：

1. fast：S0→S1→accepted；
2. standard：S1 high risk→S2→accepted；
3. expert：S2/S3 冲突→S4→accepted；
4. unknown/new package：S4→S5 waiting_human→跨进程恢复。

同时覆盖预算耗尽、VLM 不可用、SLA 过期和 retry 不重复计费。

- [ ] **Step 2: 定义 GraphV2**

节点必须明确：`quality`、`scene`、`detect`、`classify_fast`、`risk_s1`、`segment`、`reclassify`、`risk_s2`、`retrieve`、`risk_s3`、`vlm_rerank`、`risk_s4`、`human_review`、`finalize`。

每个多条件节点有 router；没有匹配 edge 时 fail-closed。feedback 只能用于明确的数据补充/重裁剪循环并受 max_rounds 限制。

- [ ] **Step 3: 输出完整决策轨迹**

trail reason 不只写 route label，还要包含 policy version、risk、budget before/after、SLA、模型和证据 ID；不得记录密钥或完整 prompt 内的客户敏感数据。

- [ ] **Step 4: 验证和提交**

Run:

```bash
python -m pytest tests/platform/test_cascade_loop.py tests/platform/test_u5_loop_kernel.py tests/platform/test_u5_real_loop.py -q -p no:cacheprovider
```

```bash
git add src/modules/fmcg/cascade/service.py src/modules/fmcg/cascade/graph.py src/modules/fmcg/adapters/human_review.py tests/platform/test_cascade_loop.py
git commit -m "feat: orchestrate S0 to S5 recognition loop"
```

## Task 13: 队列 SLA、计费和证据

**Files:**
- Modify: `src/platform/data/store.py`
- Modify: `src/platform/jobs.py`
- Create: `src/modules/fmcg/cascade/billing.py`
- Test: `tests/platform/test_cascade_billing.py`

- [ ] **Step 1: 写账本测试**

断言每个 node attempt 记录 capability、model/version、photo/region/token/compute_ms、customer tier、cold_start、cache_hit、rate_card_version、resource_cost 和 billed_cost。相同 idempotency key 重试不得重复 bill。

- [ ] **Step 2: 分离 attempt timeout 和 queue deadline**

Job 增加 `attempt_timeout_at` 和 `queue_deadline_at`。单次 VLM timeout 不等于任务过期；到 queue deadline 必须转人工、降级或 expired，并写审计。

- [ ] **Step 3: 追加式迁移**

只增加新表/列/索引，保留旧 usage_event。迁移必须可重复执行，旧库备份后演练；禁止 drop/rename 历史表。

- [ ] **Step 4: 验证和提交**

Run: `python -m pytest tests/platform/test_cascade_billing.py tests/platform/test_m6_worker.py tests/platform/test_platform_store.py -q -p no:cacheprovider`

```bash
git add src/platform/data/store.py src/platform/jobs.py src/modules/fmcg/cascade/billing.py tests/platform/test_cascade_billing.py
git commit -m "feat: meter cascade stages and queue SLA"
```

## Task 14: 统一 API

**Files:**
- Create: `src/platform/api/cascade.py`
- Modify: `src/platform/api/app.py`
- Modify: `src/platform/api/bundle.py`
- Test: `tests/platform/test_cascade_api.py`

- [ ] **Step 1: 写 API 安全测试**

覆盖单文件、批量、URL、API 和内部 Agent 启动同一种 RecognitionTask；未登录状态变更拒绝；URL SSRF 防护沿用现有规则；任意 file path/model/prompt 拒绝；idempotency 生效。

- [ ] **Step 2: 定义端点**

```text
POST /api/v1/cascade/tasks
GET  /api/v1/cascade/tasks
GET  /api/v1/cascade/tasks/{task_id}
GET  /api/v1/cascade/tasks/{task_id}/regions
GET  /api/v1/cascade/tasks/{task_id}/trail
POST /api/v1/cascade/tasks/{task_id}/cancel
GET  /api/v1/models/runtime
```

请求只接受 customer tier、source、项目和已批准选项，不接受任意 Graph 定义。

- [ ] **Step 3: 兼容旧 API**

`/api/v1/recognition/recognize` 和 8091 保持不变；新 API 默认 shadow，不改变旧响应。

- [ ] **Step 4: 验证和提交**

Run: `python -m pytest tests/platform/test_cascade_api.py tests/platform/test_u2_recognition_tasks.py tests/platform/test_umt006_auth.py -q -p no:cacheprovider`

```bash
git add src/platform/api/cascade.py src/platform/api/app.py src/platform/api/bundle.py tests/platform/test_cascade_api.py
git commit -m "feat: expose unified cascade task API"
```

## Task 15: 新包装工作流

**Files:**
- Create: `src/modules/fmcg/cascade/packaging.py`
- Modify: `src/platform/data/store.py`
- Test: `tests/platform/test_new_packaging.py`

- [ ] **Step 1: 写状态机测试**

状态：`candidate/reviewing/same_sku_new_package/new_sku/unknown/rejected`。Qwen 只能创建 candidate；只有人工或客户批准策略可以终结。历史决定不可更新或删除，只追加 supersede 关系。

- [ ] **Step 2: 实现名称选择**

支持客户选择沿用旧名称、采用新名称或创建新 SKU。显示名和 package_version 分离，不能因名称变化自动改变 sku_id。

- [ ] **Step 3: 验证和提交**

Run: `python -m pytest tests/platform/test_new_packaging.py -q -p no:cacheprovider`

```bash
git add src/modules/fmcg/cascade/packaging.py src/platform/data/store.py tests/platform/test_new_packaging.py
git commit -m "feat: add reviewed FMCG packaging evolution"
```

## Task 16: 统一 Web 管理界面

**Files:**
- Create: `web/src/pages/CascadeTasks.tsx`
- Create: `web/src/pages/ModelRuntime.tsx`
- Create: `web/src/pages/NewPackaging.tsx`
- Modify: `web/src/App.tsx`
- Modify: `web/src/api.ts`
- Modify: `web/src/pages/Recognition.tsx`
- Modify: `web/src/pages/GraphRuns.tsx`
- Modify: `web/src/pages/Training.tsx`
- Modify: `web/src/styles.css`
- Test: `tests/platform/test_cascade_web_contract.py`

- [ ] **Step 1: 写 API/UI 合约测试**

页面必须显示业务语言：客户档位、当前阶段、为何升级、自动/待人工、剩余 SLA、成本、证据。技术字段折叠显示模型哈希、策略版本、risk 和 token。

- [ ] **Step 2: 实现三个页面**

- CascadeTasks：任务、区域、阶段 trail、结果、人工状态。
- ModelRuntime：hot/warm/cold、队列、内存、冷启动、错误。
- NewPackaging：候选对比、沿用旧名/新名/新 SKU 裁决入口。

- [ ] **Step 3: 不复制已有页面**

识别、Graph、训练页面增加跳转和摘要；Label Studio 仍作为能力嵌入/链接，不重新实现其全部 UI。

- [ ] **Step 4: 构建和浏览器验证**

Run:

```bash
cd web
npm test --if-present
npm run build
```

Expected: build 成功。再用真实浏览器验证 8400：无白屏、无 console error、空队列和不可用模型有诚实状态。

- [ ] **Step 5: Commit**

```bash
git add web/src/pages/CascadeTasks.tsx web/src/pages/ModelRuntime.tsx web/src/pages/NewPackaging.tsx web/src/App.tsx web/src/api.ts web/src/pages/Recognition.tsx web/src/pages/GraphRuns.tsx web/src/pages/Training.tsx web/src/styles.css tests/platform/test_cascade_web_contract.py
git commit -m "feat: add cascade operations workbench"
```

## Task 17: 全链路 shadow 评估和晋级门

**Files:**
- Create: `scripts/run_cascade_shadow_eval.py`
- Create: `src/eval/cascade_shadow.py`
- Test: `tests/unit/test_cascade_shadow_eval.py`
- Create after run: `docs/experiments/qwen3vl-cascade-shadow-report.md`

- [ ] **Step 1: 写评估计算测试**

必须同时报告 accepted precision 和 coverage；检测使用 truebox one-to-one；重复框、背景误检、拒识、错分、新包装、unknown、人工率、延迟和成本都进入逐实例账本。

- [ ] **Step 2: 建四套对照**

```text
E0: 当前生产 bundle
E1: 当前 sku_v7_sam experimental，不发布
C1: S1–S3 级联，无 Qwen
C2: S1–S4 级联，Qwen3-VL adapter
```

全部使用相同 frozen data、相同 region matching 和相同 SKU Registry。

- [ ] **Step 3: 晋级条件**

专家档 accepted precision 目标 ≥95%，但必须同时报告 coverage；false accept、unknown/new-package、FP/photo、p95、成本和人工率不能恶化超过批准线。没有足够人工真值时报告 `not_evaluable`，不得造 pass。

- [ ] **Step 4: 运行全量测试**

Run:

```bash
python -m pytest tests -q -p no:cacheprovider
```

Expected: 全绿；如有跳过，逐项解释原因和是否影响门禁。

- [ ] **Step 5: Commit**

```bash
git add scripts/run_cascade_shadow_eval.py src/eval/cascade_shadow.py tests/unit/test_cascade_shadow_eval.py docs/experiments/qwen3vl-cascade-shadow-report.md
git commit -m "eval: compare staged and Qwen cascade in shadow"
```

## Task 18: 文档、状态和最终交付

**Files:**
- Modify: `docs/README.md`
- Modify: `docs/implementation/platform-v2/STATUS.md`
- Modify: `docs/implementation/platform-v2/ISSUES.md`
- Modify: `docs/implementation/platform-v2/DECISIONS.md`
- Modify: `docs/implementation/platform-v2/IMPLEMENTATION-LIST.md`
- Modify: `docs/implementation/platform-v2/EXECUTION-LOG.md`
- Create: `docs/runbooks/qwen3vl-cascade-local-runbook.md`

- [ ] **Step 1: 状态只写事实**

区分 `implemented/tested/benchmarked/trained/shadow_passed/publish_approved/production_active`。不能用“代码已实现”代替“模型已训练”，不能用“adapter 文件存在”代替“shadow 通过”。

- [ ] **Step 2: Runbook 写真实命令**

列出环境、preflight、zero-shot、dataset build、benchmark、pilot、shadow、服务加载/卸载和故障排查。所有命令先用 `--help` 或 parse-only 测试验证参数真实存在。

- [ ] **Step 3: 保留未关闭项**

人工 truebox、质量金标准、934 tilt reject、Qwen 新包装金标准和生产发布未完成时继续 OPEN，不为结项勾掉。

- [ ] **Step 4: 最终回归和 Git 审计**

Run:

```bash
python -m pytest tests -q -p no:cacheprovider
git status --short
git diff --check
git log --oneline -20
```

Expected: 测试全绿、无 whitespace error、只出现本计划明确文件和必须保留的未跟踪制品。

- [ ] **Step 5: Commit 文档**

```bash
git add docs/README.md docs/implementation/platform-v2/STATUS.md docs/implementation/platform-v2/ISSUES.md docs/implementation/platform-v2/DECISIONS.md docs/implementation/platform-v2/IMPLEMENTATION-LIST.md docs/implementation/platform-v2/EXECUTION-LOG.md docs/runbooks/qwen3vl-cascade-local-runbook.md
git commit -m "docs: publish Qwen cascade operations runbook"
```

不得自动 push、merge、deploy 或切换生产。

## 3. 阶段门禁总表

| Gate | 必须满足 | 失败动作 |
|---|---|---|
| G-CURRENT | 当前 YOLO 训练结束；状态和制品对账 | 不启动任何 MLX 重任务 |
| G-DATA | 快照 hash、registry、label source、全维泄漏为 0 | 拒绝构建/训练 |
| G-APPLE | MLX Metal、内存、swap、热、电源、服务和模型前向通过 | fail-closed，不回 CPU |
| G-ZERO | 零样本评估和逐实例账本完整 | 不进入微调 |
| G-SMOKE | 32 overfit、128 smoke、schema 100% | 修数据/模板，不扩大 |
| G-BENCH | 200–500 step 吞吐稳定，得出 batch/token 上限 | 不采用 batch16 假设 |
| G-PILOT | 5k–20k、1ep、vision frozen 有冻结集收益 | 停止，不扩大 |
| G-SHADOW | 准确率、覆盖率、FP、unknown、延迟、成本同时通过 | 不申请发布 |
| G-PUBLISH | 独立发布审批和 rollback 策略完成 | 保持 production_switch=false |

## 4. Agent 最终交付格式

每个阶段都更新 Implementation List 和 Execution Log。最终报告必须包含：

1. Git 分支、HEAD、精确 commits、工作树状态。
2. 未删除/未覆盖声明和未跟踪制品清单。
3. 训练前后进程、MPS、内存、swap、热状态和服务健康。
4. 数据快照：图片数、区域数、类别、label source、四类样本、split 和全部 hash。
5. Qwen 模型、MLX-VLM、Python、revision、adapter hash 和环境 lock。
6. zero-shot、smoke、benchmark、pilot、shadow 的逐项结果。
7. accepted precision + coverage，不得只写 Top-1。
8. unknown、新包装、错标、漏标、重复框、背景 FP 和人工回退账本。
9. 客户四档 p50/p95、算力、token、成本和 SLA。
10. production bundle 未切换，或若未来获得独立授权则提供审批与 rollback 证据。

## 5. 可直接交给实施 Agent 的完整提示词

```text
你现在是本项目的主实施 Agent。你的任务不是新建第二套识别系统，而是在现有统一 Graph+Loop 智能业务操作系统内，实现 Qwen3-VL 4B + YOLO + ResNet + SAM + OCR/检索 + 人工审核的 FMCG 多模型智能级联。

项目根目录：
<legacy-workspace>

本地 VLM 逻辑模型固定为：
qwen3-vl:4b

训练框架固定优先使用 Apple Silicon 原生 MLX/MLX-VLM。第一轮训练基础权重优先使用 mlx-community/Qwen3-VL-4B-Instruct-4bit 做 QLoRA；官方语义基线是 Qwen/Qwen3-VL-4B-Instruct。不得直接把 Ollama 的 Q4_K_M 推理制品当成 MLX LoRA 训练输入。

开始任何实现前，必须完整阅读以下文件，不得只读摘要：
1. docs/superpowers/specs/2026-08-04-fmcg-vision-saas-platform-design.md
2. docs/superpowers/specs/2026-08-06-qwen3-vl-4b-graph-loop-cascade-design.md
3. docs/superpowers/plans/2026-08-06-qwen3-vl-4b-graph-loop-cascade-implementation-plan.md
4. docs/superpowers/plans/2026-08-05-unified-management-all-photo-training-execution-manual.md
5. docs/training-history-and-decisions.md
6. docs/tuning-methodology.md
7. docs/implementation/platform-v2/STATUS.md
8. docs/implementation/platform-v2/ISSUES.md
9. docs/implementation/platform-v2/DECISIONS.md
10. docs/implementation/platform-v2/IMPLEMENTATION-LIST.md
11. docs/implementation/platform-v2/EXECUTION-LOG.md
12. src/platform/registry.py
13. src/platform/contracts.py
14. src/platform/kernel/loop.py
15. src/platform/loops/pipeline_v2.py
16. src/platform/data/store.py
17. src/cascade/cascade_inference.py
18. src/pipeline/recognize.py
19. src/platform/quality/qpol_v2.py
20. src/training/quality_gate.py
21. src/training/sam_refine.py

阅读后先做以下工作：
- 执行 git status、git rev-parse HEAD、git log；
- 只读检查当前训练进程、.models/sku_v7_sam/results.csv 和 /tmp/train_sku_v7_sam.log；
- 在 IMPLEMENTATION-LIST.md 建立 VLM-000 至 VLM-018 清单；
- 在 EXECUTION-LOG.md 记录基线；
- 在 ISSUES.md 登记状态文档冲突、optimizer=auto 忽略 lr0、934 张 tilt 未经人工金标准、SAM 96.5% 仅为几何通过、Qwen/MLX 未安装等问题；
- 不得把这些问题伪装为已关闭。

硬红线：
1. 不删除、移动或覆盖任何原图、数据库、模型、数据集、审核、SAM、quality、eval、日志、备份、失败制品或临时制品。
2. 不暂存 .quality/、.sam_checkpoints/、.sam_runs/、.superpowers/、.models/、.datasets/、.eval/ 和密钥。
3. 不使用 git add . 或 git add -A；只暂存当前任务明确文件。
4. 不自动 merge、push、deploy、force-push 或切换 production bundle。
5. 不恢复 v6；保持 prod_20260804_v4_r2 和 production_switch=false。
6. 当前 sku_v7_sam 训练进程存在时，不下载 Qwen 权重、不安装大型模型、不启动 MLX benchmark/微调、不启动第二个 MPS 重任务，也不要中断当前训练。让其依据 patience 自然停止并保留证据。
7. 当前 sku_v7_sam 只能标记 experimental。训练日志显示 optimizer=auto 忽略 lr0=0.0005，实际 MuSGD lr=0.01；必须严格评估后再判断，不得自动发布。
8. Qwen/MLX 使用隔离环境，不污染现有 YOLO/平台环境。
9. Qwen 输出不在 CandidateSet 或 SKU Registry 时不得 accepted。
10. 新包装和疑似新 SKU 只能进入人工/客户裁决，不能自动写商品主数据。
11. 训练完成不等于发布；发布必须独立审批。

架构原则：
- 复用现有 Graph+Loop v2，禁止另建 Orchestrator、数据库、计费或审核系统。
- 客户 fast/standard/deep/expert 四档与内部 S0–S5 模型阶段分离。
- YOLO 只定位，ResNet 快速分类，SAM 只精修 mask/crop，OCR/检索产生闭集候选，Qwen3-VL 只做候选裁决和 unknown/new-package 判断。
- Qwen 是 sleeping guardian，采用 hot/warm/cold 驻留；初期并发为 1，空闲 TTL 后卸载。
- 不能用统一的 0.85/0.65/0.4 原始置信度跨模型路由。必须有版本化 calibrated risk 或明确标注 bootstrap_rule_v1。
- 12/48 小时是 queue SLA，不是单次模型推理 timeout。
- API、Web 和内部 Agent 使用同一个 RecognitionTask/GraphRun。
- 所有节点写模型版本、输入 SHA、策略版本、风险、延迟、用量、成本和证据。

实施方法：
- 严格按 docs/superpowers/plans/2026-08-06-qwen3-vl-4b-graph-loop-cascade-implementation-plan.md 的 Task 0–18 顺序执行。
- 使用 TDD：每个任务先写失败测试并确认红，再写最小实现并确认绿，再运行相关回归。
- 每个任务单独 commit，commit 前更新 IMPLEMENTATION-LIST 和 EXECUTION-LOG。
- 不要把所有逻辑塞入 cascade_inference.py、app.py 或 store.py。
- 平台内核不得反向 import Domain Pack；FMCG 能力通过 ModuleManifest + CapabilityRegistry 注入。
- 所有数据集使用 staging + 原子发布 + 已存在拒绝覆盖。
- 所有 active protocol、SHA、近重复、客户、门店、session、时间和包装版本泄漏守卫 fail-closed。

Qwen 数据要求：
- 全部照片进入资产台账和用途判定，但 frozen/reject/manual_pending/未裁决 prediction 不得进入正式训练。
- JSONL 作为不可变审计清单；MLX-VLM 训练制品转换为 Hugging Face Dataset 的 images + messages。
- 使用 processor/chat template，不手工插入 <|vision_start|>。
- 保存原像素 bbox、原图宽高和 Qwen3-VL 0–1000 bbox。
- 样本包含 region crop、带上下文 crop、full-image bbox、hard negative、unknown 和 new packaging。
- 输出必须是结构化 JSON，包含 sku_id、package_version_id、attributes、conflicts、decision 和 abstain_reason。

训练阶梯：
1. 当前 YOLO 训练结束和事实对账；
2. 隔离 MLX 环境 + Apple 硬预检；
3. zero-shot 冻结基线；
4. 32 条 overfit + 128 条 dataset smoke；
5. 200–500 step batch/token/内存/swap benchmark；
6. 5,000–20,000 region、1 epoch、rank16、alpha32、batch 从 2 起、gradient accumulation 4–8、train_on_completions、vision frozen 的 QLoRA pilot；
7. 只有冻结集收益和风险门同时通过才扩大；
8. 只有语言层会重排但视觉仍看不清时，才单变量实验 train_vision；
9. shadow 对比 E0/E1/C1/C2；
10. 未获独立发布授权保持生产不变。

禁止直接使用 batch16、10 epoch、3–5 小时完成等未经本机 benchmark 证明的假设。不要使用 --use-mps、--num-epochs 等 MLX-VLM 不支持的参数。实际命令必须先通过 --help 或 parse-only 测试。

验收必须同时报告：
- accepted precision 和 auto coverage；
- Top-1/Top-5；
- detector recall@固定 FP/photo、IoU0.50/0.75；
- duplicate/background FP、FN、错分、拒识；
- unknown/new packaging precision/recall 和 false accept；
- 属性准确率；
- 客户四档 p50/p95、tokens/s、冷启动、人工率、超 SLA 和每千实例成本；
- 逐实例错误账本和证据链。

专家档 accepted precision 目标为冻结客户验收集上的 95% 或以上，但必须同时报告 coverage，禁止靠大量拒识制造 95%。200 张只能作为 smoke，不能单独支持商业准确率承诺。

完成后交付：
- 精确分支、HEAD、commit 清单和工作树；
- 文件变更清单；
- 测试命令与完整结果；
- 数据/模型/adapter/环境 hash；
- Apple MPS/MLX、内存、swap、热状态、吞吐证据；
- zero-shot、smoke、benchmark、pilot、shadow 报告；
- Web 真实浏览器截图和 console 结果；
- 未关闭问题、阻断项和下一步；
- 明确说明 production bundle 是否保持不变。

遇到人工审核、下载授权、生产发布授权、数据泄漏、MPS/内存停止线或不确定的商品命名规则时立即 fail-closed，记录证据并向用户请求决定，禁止猜测或伪造通过。
```

## 6. 执行建议

实现时优先使用 `superpowers:subagent-driven-development` 逐任务执行并进行两阶段审查；若由单一 Agent 连续实施，则使用 `superpowers:executing-plans`，每完成一组任务暂停并提交测试、状态和差异供复核。

无论采用哪种方式，Task 0、G-CURRENT 和 G-APPLE 都不能并行绕过。Qwen 下载、安装和真实训练属于会消耗大量本机资源的外部动作，必须在当前训练结束并获得明确授权后进行。
