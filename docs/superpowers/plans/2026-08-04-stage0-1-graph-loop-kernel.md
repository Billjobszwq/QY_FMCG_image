# Stage 0–1 Unified Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Use superpowers:test-driven-development for every behavior change and superpowers:verification-before-completion before claiming a gate. Steps use `- [ ]` checkboxes for tracking.

**Goal:** 在不重写现有识别链路的前提下，建立本机可运行、可恢复、可审计的统一平台底座。Graph+Loop 是底座的智能执行主干；Module SDK、统一 IAM、数据与证据、任务与 Worker、用量计费、审计和 Web Shell 是所有 Domain Pack 的共同契约。最终必须用 Reference Echo Pack 和 FMCG Vision Bridge 两个可独立启停的薄模块证明底座通用性与模块隔离。

**Architecture:** 采用本地优先的模块化单体与隔离 Worker，并以绞杀式迁移承接旧系统。统一 Foundation 只依赖稳定契约，不反向 import 业务模块；Domain Pack 通过 `ModuleManifest`、Capability、DomainCommand、事件、DataProduct 和 ResourceRef 接入。新增 FastAPI 控制面、PostgreSQL 事实库、CAS 证据层、持久 Worker、Policy/Usage 契约和 React Web Shell；现有识别服务继续运行在 8091，由 FMCG Vision Bridge 调用。Graph、IAM、模块、任务、用量和审计事实只进入 PostgreSQL；原始文件进入内容寻址存储；旧 SQLite 只作为兼容审计与历史导入源。

**Tech Stack:** Python 3.11–3.13（本机执行使用 3.13.2）、FastAPI、Pydantic v2、SQLAlchemy 2、psycopg 3、Alembic、PostgreSQL 16、httpx、pytest、React、TypeScript、Vite、Vitest。

---

## 0. 执行边界与当前基线

本计划只覆盖总体设计中的 Stage 0 和 Stage 1，即完整 Foundation Milestone：

- Stage 0：平台边界、Module SDK、Graph、Capability、Policy、Run、Checkpoint、HumanTask、Job、Asset、Evidence、Usage、Audit、DataProduct 和 ResourceRef 契约冻结。
- Stage 1：本机统一底座、Reference Echo Pack、FMCG Vision Bridge、统一 API 和 Web Shell；完成恢复、隔离、升级、禁用、备份与性能验收。

本计划不实现完整照片接入、质量检测、Label Studio 闭环、生产级多模型路由、训练中心、正式客户结算、地理外勤、问卷或 BI。它们分别进入后续 Stage 2–9。Stage 0–1 只建立可承载它们的真实底座，禁止以占位接口冒充业务模块完成。

编写本计划时的只读基线：

- Git HEAD：94a6e718ed26faeb78237c8d19fe34eb2410ff52。
- 测试基线：74 passed。
- Python：保持项目允许的 3.11–3.13；本机基线使用 3.13.2，不能使用 Python 3.14。
- 当前在线识别：src/recognize/service.py，端口 8091，v2 API。
- 当前平台编排：src/ls_platform/orchestrator.py，端口 8304。
- 当前事实冲突：业务代码仍大量使用 src/data/warehouse.py 的 SQLite；Graph 新事实必须从第一天只写 PostgreSQL。
- 当前 Postgres/Redis/MinIO/Label Studio 已在 compose.yaml 中定义。

执行红线：

1. 不删除或覆盖原图、SQLite 历史、模型、训练产物、审核文件、临时产物和失败证据。
2. 不把旧 SQLite 数据自动改写为 PostgreSQL；迁移另建只读导入任务和核对报告。
3. 不修改旧服务端口或切走现有识别入口，直到新内核验收通过。
4. 不允许从数据库读取任意 Python import path 并执行；Capability handler 必须来自代码白名单。
5. 不允许使用 eval 执行 Graph 条件；条件只支持受控 JSON 路径和操作符。
6. 不允许 Graph/Agent 直接写客户源数据；领域写入只走 DomainCommand。
7. 不允许无界 Loop；每个 Run 必须有步骤、时间、费用和人工边界。
8. 不运行 git add .；每个提交只暂存任务明确列出的文件。
9. Foundation 不得 import `src/modules/*`；模块只能实现 Foundation 定义的契约，并由注册表装配。
10. 禁止建立跨模块共享业务表或万能 JSON 大表；每个模块拥有独立 schema 和 forward-only migration。
11. 禁止把 URL、本机绝对路径或对象存储 key 当长期资源身份；跨模块只传 `ResourceRef`。
12. 禁止把计费金额从 float 推导；原始用量、内部成本与客户价格必须分层且全部可重放。

## 1. 文件结构锁定

### 1.1 新增后端文件

| 路径 | 单一职责 |
|---|---|
| src/platform/kernel/contracts.py | Graph、Capability、Run、Budget、Policy 的 Pydantic 类型 |
| src/platform/kernel/validation.py | Graph 静态校验、环路和可达终态检查 |
| src/platform/kernel/conditions.py | 安全 JSON 路径读取和条件判断 |
| src/platform/modules/capability_registry.py | 代码白名单 Capability Registry |
| src/platform/kernel/policy.py | 权限、副作用等级和预算判断 |
| src/platform/kernel/runtime.py | 纯状态转换和下一节点决定 |
| src/platform/kernel/worker.py | claim → execute → checkpoint 的持久 Worker |
| src/platform/data/repositories.py | Repository Protocol 与记录类型 |
| src/platform/modules/capability.py | Capability Handler Protocol |
| src/platform/modules/manifest.py | ModuleManifest、兼容版本和声明式贡献点 |
| src/platform/modules/registry.py | 模块发现、依赖排序、启停与健康状态 |
| src/platform/modules/lifecycle.py | install/enable/disable/upgrade 的事务化生命周期 |
| src/modules/reference_echo/capability.py | 非识别示例能力 |
| src/modules/fmcg_vision/adapters/legacy_recognition.py | 8091 v2 识别适配器 |
| src/platform/iam/service.py | principal、tenant、project、scope 与数据域授权 |
| src/platform/assets/cas.py | 内容哈希、不可变对象与引用计数，不删除原件 |
| src/platform/assets/evidence.py | EvidenceBundle、来源链和保留策略 |
| src/platform/jobs/contracts.py | Job、Attempt、lease、retry、dead-letter 契约 |
| src/platform/jobs/worker.py | 通用持久任务 Worker，与 Graph Node Worker 分离 |
| src/platform/data/resources.py | ResourceRef、DataProduct、Lineage 契约 |
| src/platform/data/work_items.py | 跨模块只读 WorkItemProjection |
| src/platform/billing/metering.py | Meter、UsageEvent、RateCard 与幂等计量 |
| src/platform/audit/service.py | 审计、决策、导出和管理操作证据 |
| src/platform/data/database.py | SQLAlchemy engine、session 和事务边界 |
| src/platform/data/graph_repository.py | Graph、Run、Node、Checkpoint、HumanTask 持久化 |
| src/platform/billing/ledger_repository.py | UsageEvent、AuditEvent 只追加持久化 |
| src/platform/api/settings.py | 新控制面的环境配置 |
| src/platform/api/auth.py | Bearer principal 与租户/项目上下文 |
| src/platform/api/dependencies.py | FastAPI 依赖装配 |
| src/platform/api/main.py | FastAPI app 和路由装配 |
| src/platform/api/routes/health.py | live/ready |
| src/platform/api/routes/graphs.py | Graph 创建、版本和发布 |
| src/platform/api/routes/capabilities.py | 能力目录 |
| src/platform/api/routes/runs.py | Run 创建、查询、暂停、恢复、取消 |
| src/platform/api/routes/human_tasks.py | 人工任务领取与完成 |

所有新 package 同时创建空的 __init__.py。禁止把上述职责重新合并进一个 app.py 或 orchestrator.py 大文件。

### 1.2 新增契约、迁移和配置

| 路径 | 职责 |
|---|---|
| alembic.ini | Alembic 配置 |
| migrations/platform/env.py | 从 APP_DATABASE_URL 获取连接 |
| migrations/platform/versions/20260804_0001_foundation.py | 仅创建新智能内核 schema/table |
| migrations/platform/versions/20260804_0002_platform_services.py | module/asset/job/projection/metering 平台表 |
| migrations/modules/reference_echo/versions/20260804_0001_echo.py | Reference Echo 独立 schema |
| migrations/modules/fmcg_vision/versions/20260804_0001_bridge.py | FMCG Bridge 独立 schema |
| contracts/graph/v1/graph-definition.schema.json | GraphDefinition JSON Schema |
| contracts/graph/v1/capability-definition.schema.json | CapabilityDefinition JSON Schema |
| contracts/openapi/control-plane-v1.json | FastAPI OpenAPI 冻结产物 |
| src/modules/reference_echo/graphs/echo-v1.json | 非识别示例 Graph |
| src/modules/fmcg_vision/graphs/minimal-recognition-v1.json | 最小识别 + 人工检查点 Graph |
| src/modules/reference_echo/manifest.json | Reference Echo 模块声明 |
| src/modules/fmcg_vision/manifest.json | FMCG Vision Bridge 模块声明 |
| scripts/export_contracts.py | 从 Pydantic/FastAPI 生成契约 |
| scripts/run_control_plane.sh | 本机控制面启动 |
| scripts/run_graph_worker.sh | 本机 Worker 启动 |

旧 migrations/postgres/001_schema.sql 继续拥有 public legacy 表。平台 Alembic 拥有 `iam`、`module_registry`、`graph`、`capability`、`policy`、`asset`、`job`、`projection`、`billing`、`audit` schema；每个 Domain Pack 只拥有自己的 schema 和迁移目录，避免一开始重写旧业务表。

### 1.3 新增前端文件

| 路径 | 职责 |
|---|---|
| web/package.json | React/Vite/Vitest 依赖与脚本 |
| web/vite.config.ts | 开发代理和测试环境 |
| web/src/platform/api/client.ts | 唯一 API client |
| web/src/platform/types.ts | 与控制面响应一致的前端类型 |
| web/src/platform/App.tsx | 智能工作台壳 |
| web/src/platform/features/runs/RunLauncher.tsx | 选择 Graph、输入目标、启动 Run |
| web/src/platform/features/runs/RunTimeline.tsx | 节点、循环、费用和终态时间线 |
| web/src/platform/features/tasks/HumanTaskPanel.tsx | 人工检查点完成 |
| web/src/platform/features/capabilities/CapabilityCatalog.tsx | 能力目录 |
| web/src/platform/features/modules/ModuleAdmin.tsx | 模块状态、依赖、健康和启停入口 |
| web/src/platform/features/work/WorkInbox.tsx | 统一工作项投影，不直接写领域表 |
| web/src/platform/styles.css | 最小布局；不做最终品牌 UI |

### 1.4 测试文件

| 路径 | 覆盖 |
|---|---|
| tests/unit/platform/kernel/test_contracts.py | 类型、枚举、schema |
| tests/unit/platform/kernel/test_validation.py | 图引用、环路、终态 |
| tests/unit/platform/kernel/test_conditions.py | 安全条件 |
| tests/unit/platform/kernel/test_policy.py | 权限、副作用和预算 |
| tests/unit/platform/kernel/test_runtime.py | 状态转换、停滞和下一节点 |
| tests/unit/platform/modules/test_capability_registry.py | handler 白名单 |
| tests/unit/platform/modules/test_manifest.py | manifest schema、依赖和兼容范围 |
| tests/integration/test_module_lifecycle.py | 安装、升级、禁用、失败隔离 |
| tests/integration/test_asset_evidence.py | CAS、证据链、引用和保留策略 |
| tests/integration/test_job_worker.py | lease、重试、死信和恢复 |
| tests/integration/test_metering.py | 幂等计量、成本与售价分离 |
| tests/architecture/test_module_boundaries.py | Foundation 不依赖 Domain Pack、模块无跨表写入 |
| tests/integration/test_graph_repository.py | PostgreSQL 不可变、claim 和幂等 |
| tests/integration/test_worker_recovery.py | Worker 崩溃和检查点恢复 |
| tests/integration/test_control_plane_api.py | auth、跨租户、API |
| tests/integration/test_recognition_capability.py | 8091 适配与请求幂等 |
| tests/e2e/test_minimal_graphs.py | 识别与非识别两条 Graph |
| web/src/platform/features/runs/RunLauncher.test.tsx | 启动表单 |
| web/src/platform/features/runs/RunTimeline.test.tsx | 时间线 |

## 2. 固定领域契约

以下名字和语义在 Stage 0-1 内冻结，后续任务不得自行改名：

- Graph 状态：draft、published、retired。
- Run 状态：created、ready、running、waiting_human、paused、completed、failed、cancelled、budget_exhausted、policy_blocked。
- Node 状态：queued、leased、running、waiting_human、succeeded、failed、cancelled。
- Node kind：capability、decision、human、end。
- Capability effect：read_only、system_write、domain_command。
- Usage 金额/额度：整数 micros，禁止 float 金额。
- max_tokens=0 表示禁止任何生成式 token 消耗，不表示无限额度。
- max_wall_seconds 只累计自动执行时间；显式 paused 和 waiting_human 通过 suspended_at 冻结 deadline，恢复时顺延。
- Graph 条件操作符：eq、ne、gt、gte、lt、lte、exists、in。
- 幂等键：tenant_id + operation + Idempotency-Key。
- 节点外部调用幂等键：SHA256(run_id:node_id:iteration)。
- 每个发布 GraphVersion 不可原地修改。
- 每次节点完成后必须在同一事务写 NodeExecution、RunEvent、Checkpoint、UsageEvent 和下一节点。

## Task 1: 创建隔离执行分支并锁定基线

**Files:**
- Inspect: git status
- Inspect: docs/superpowers/specs/2026-08-04-fmcg-vision-saas-platform-design.md
- Create during execution: isolated worktree only

- [ ] **Step 1: 确认执行起点没有用户未提交文件**

~~~bash
git status --short
git rev-parse HEAD
~~~

Expected: 计划基线 HEAD 为 94a6e718ed26faeb78237c8d19fe34eb2410ff52。若执行时 main 已前进，记录真实 HEAD 并重新跑基线；若有未提交文件，停止并区分用户改动，不得暂存或覆盖。

- [ ] **Step 2: 使用 worktree 创建实施分支**

执行 Agent 必须先使用 superpowers:using-git-worktrees，然后创建分支：

~~~bash
git worktree add ../LLM-Image-unified-foundation -b feat/unified-foundation
~~~

Expected: 新 worktree 位于同级目录，原工作区保持不变。若目录已存在，不删除，改用新的明确目录名。

- [ ] **Step 3: 在 worktree 跑基线**

~~~bash
cd ../LLM-Image-unified-foundation
XONSH_HISTORY_BACKEND=dummy PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider -q
~~~

Expected: 74 passed。若基线变化，以最新 main 的真实结果记录到计划执行日志；红色基线必须先诊断。

- [ ] **Step 4: 建立执行证据文件**

Create: docs/experiments/GK0-stage0-1-execution-evidence.md

~~~markdown
# GK0 Stage 0-1 Execution Evidence

- plan_base_commit: 94a6e718ed26faeb78237c8d19fe34eb2410ff52
- plan_python: 3.13.2
- execution_base_commit: 执行前将本行更新为 worktree 内 `git rev-parse HEAD` 的真实输出
- execution_python: 执行前将本行更新为 `$PROJECT_PYTHON_PATH --version` 的真实输出
- baseline_tests: 74 passed
- production_switch: forbidden
- legacy_ports_changed: false
- source_or_history_deleted: false
~~~

填写真实值后提交：

~~~bash
git add docs/experiments/GK0-stage0-1-execution-evidence.md
git commit -m "docs(kernel): record stage0-1 execution baseline"
~~~

## Task 2: 增加依赖与控制面配置

**Files:**
- Modify: pyproject.toml
- Modify: .env.example
- Create: src/platform/api/__init__.py
- Create: src/platform/api/settings.py
- Test: tests/unit/platform/api/test_settings.py

- [ ] **Step 1: 写配置失败测试**

~~~python
from pydantic import ValidationError
import pytest

from src.platform.api.settings import ControlPlaneSettings


def test_database_and_bootstrap_token_are_required():
    with pytest.raises(ValidationError):
        ControlPlaneSettings(
            app_database_url="",
            app_bootstrap_token="short",
        )


def test_local_settings_accept_explicit_values():
    settings = ControlPlaneSettings(
        app_database_url="postgresql+psycopg://<user>:<password>@127.0.0.1:55432/sku_graph_test",
        app_bootstrap_token="x" * 32,
        app_default_tenant_id="tenant_local",
        app_default_project_id="project_local",
    )
    assert settings.app_control_port == 8400
    assert settings.recognize_v2_url == "http://127.0.0.1:8091"
~~~

- [ ] **Step 2: 运行并确认失败**

~~~bash
XONSH_HISTORY_BACKEND=dummy PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/unit/platform/api/test_settings.py -q
~~~

Expected: FAIL，原因是 src.platform.api.settings 尚不存在。

- [ ] **Step 3: 更新依赖**

保持 `requires-python = ">=3.11,<3.14"`，并在 runtime dependencies 加入：

~~~toml
"fastapi>=0.116,<1",
"uvicorn[standard]>=0.35,<1",
"pydantic>=2.11,<3",
"pydantic-settings>=2.10,<3",
"SQLAlchemy>=2.0.41,<3",
"psycopg[binary]>=3.2.9,<4",
"alembic>=1.16,<2",
"httpx>=0.28,<1",
"jsonschema>=4.24,<5",
"packaging>=24,<26",
~~~

在 dev extras 加入：

~~~toml
"pytest-cov>=6.2,<7",
~~~

- [ ] **Step 4: 创建 ControlPlaneSettings**

~~~python
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ControlPlaneSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "dev"
    app_database_url: str
    app_bootstrap_token: str
    app_default_tenant_id: str = "tenant_local"
    app_default_customer_id: str = "customer_local"
    app_default_project_id: str = "project_local"
    app_control_host: str = "127.0.0.1"
    app_control_port: int = 8400
    graph_worker_id: str = "worker_local_1"
    graph_poll_interval_ms: int = Field(default=250, ge=50, le=10_000)
    graph_lease_seconds: int = Field(default=60, ge=10, le=3600)
    recognize_v2_url: str = "http://127.0.0.1:8091"
    recognize_timeout_seconds: float = Field(default=30.0, ge=1, le=300)
    graph_kernel_enabled: bool = False

    @field_validator("app_database_url")
    @classmethod
    def require_postgres(cls, value: str) -> str:
        if not value.startswith("postgresql+psycopg://"):
            raise ValueError("APP_DATABASE_URL must use postgresql+psycopg")
        return value

    @field_validator("app_bootstrap_token")
    @classmethod
    def strong_bootstrap_token(cls, value: str) -> str:
        if len(value) < 32:
            raise ValueError("APP_BOOTSTRAP_TOKEN must be at least 32 characters")
        return value
~~~

- [ ] **Step 5: 扩展 .env.example**

~~~dotenv
# ===== Graph+Loop control plane =====
APP_DATABASE_URL=postgresql+psycopg://<user>:<password>@127.0.0.1:5432/sku_kb
APP_BOOTSTRAP_TOKEN=replace-with-at-least-32-random-characters
APP_DEFAULT_TENANT_ID=tenant_local
APP_DEFAULT_CUSTOMER_ID=customer_local
APP_DEFAULT_PROJECT_ID=project_local
APP_CONTROL_HOST=127.0.0.1
APP_CONTROL_PORT=8400
GRAPH_WORKER_ID=worker_local_1
GRAPH_POLL_INTERVAL_MS=250
GRAPH_LEASE_SECONDS=60
GRAPH_KERNEL_ENABLED=false
RECOGNIZE_V2_URL=http://127.0.0.1:8091
RECOGNIZE_TIMEOUT_SECONDS=30
~~~

- [ ] **Step 6: 运行测试并提交**

~~~bash
XONSH_HISTORY_BACKEND=dummy PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/unit/platform/api/test_settings.py -q
git add pyproject.toml .env.example src/platform/api tests/unit/platform/api/test_settings.py
git commit -m "feat(kernel): add control plane settings and dependencies"
~~~

Expected: 2 passed；暂存区不包含 .env。

## Task 3: 冻结 Graph 与 Capability 类型契约

**Files:**
- Create: src/platform/kernel/__init__.py
- Create: src/platform/kernel/contracts.py
- Create: scripts/export_contracts.py
- Create: tests/unit/platform/kernel/test_contracts.py
- Create generated: contracts/graph/v1/graph-definition.schema.json
- Create generated: contracts/graph/v1/capability-definition.schema.json

- [ ] **Step 1: 写契约测试**

~~~python
from src.platform.kernel.contracts import (
    BudgetLimits,
    CapabilityDefinition,
    CapabilityEffect,
    CapabilityRef,
    Condition,
    GraphDefinition,
    GraphNode,
    NodeKind,
)


def test_minimal_graph_contract_is_stable():
    graph = GraphDefinition(
        graph_id="echo",
        name="Echo",
        start_node="echo",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        budget=BudgetLimits(
            max_steps=4,
            max_wall_seconds=30,
            max_cost_micros=10_000,
            max_tokens=0,
        ),
        nodes=[
            GraphNode(
                node_id="echo",
                kind=NodeKind.CAPABILITY,
                capability=CapabilityRef(capability_id="core.echo", version="1.0.0"),
                next_node="done",
            ),
            GraphNode(node_id="done", kind=NodeKind.END),
        ],
    )
    assert graph.schema_version == "1.0"
    assert graph.nodes[0].capability.capability_id == "core.echo"


def test_capability_effect_is_explicit():
    capability = CapabilityDefinition(
        capability_id="core.echo",
        version="1.0.0",
        name="Echo",
        effect=CapabilityEffect.READ_ONLY,
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        required_scopes=["capability:echo"],
        timeout_seconds=5,
        max_attempts=1,
        fixed_cost_micros=10,
        handler_key="core.echo",
    )
    assert capability.effect.value == "read_only"


def test_condition_has_no_expression_string():
    condition = Condition(path="$.nodes.echo.output.ok", operator="eq", value=True)
    assert not hasattr(condition, "expression")
~~~

- [ ] **Step 2: 运行并确认失败**

~~~bash
XONSH_HISTORY_BACKEND=dummy PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/unit/platform/kernel/test_contracts.py -q
~~~

Expected: FAIL，原因是 src.platform.kernel.contracts 尚不存在。

- [ ] **Step 3: 创建固定契约**

~~~python
from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GraphVersionStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    RETIRED = "retired"


class RunStatus(StrEnum):
    CREATED = "created"
    READY = "ready"
    RUNNING = "running"
    WAITING_HUMAN = "waiting_human"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BUDGET_EXHAUSTED = "budget_exhausted"
    POLICY_BLOCKED = "policy_blocked"


class NodeStatus(StrEnum):
    QUEUED = "queued"
    LEASED = "leased"
    RUNNING = "running"
    WAITING_HUMAN = "waiting_human"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class NodeKind(StrEnum):
    CAPABILITY = "capability"
    DECISION = "decision"
    HUMAN = "human"
    END = "end"


class CapabilityEffect(StrEnum):
    READ_ONLY = "read_only"
    SYSTEM_WRITE = "system_write"
    DOMAIN_COMMAND = "domain_command"


class ConditionOperator(StrEnum):
    EQ = "eq"
    NE = "ne"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    EXISTS = "exists"
    IN = "in"


class BudgetLimits(FrozenModel):
    max_steps: int = Field(ge=1, le=10_000)
    max_wall_seconds: int = Field(ge=1, le=604_800)
    max_cost_micros: int = Field(ge=0)
    max_tokens: int = Field(ge=0)


class CapabilityRef(FrozenModel):
    capability_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,127}$")
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")


class Condition(FrozenModel):
    path: str = Field(pattern=r"^\$\.(input|nodes|human)(\.[A-Za-z0-9_-]+)+$")
    operator: ConditionOperator
    value: Any = None


class GraphNode(FrozenModel):
    node_id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
    kind: NodeKind
    capability: CapabilityRef | None = None
    condition: Condition | None = None
    next_node: str | None = None
    true_node: str | None = None
    false_node: str | None = None
    task_type: str | None = None
    max_iterations: int | None = Field(default=None, ge=1, le=1000)
    input_mapping: dict[str, str] = Field(default_factory=dict)
    output_mapping: dict[str, str] = Field(default_factory=dict)


class GraphDefinition(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    graph_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,127}$")
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    start_node: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    budget: BudgetLimits
    required_scopes: list[str] = Field(default_factory=list)
    nodes: list[GraphNode] = Field(min_length=1, max_length=1000)


class CapabilityDefinition(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    capability_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,127}$")
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    name: str = Field(min_length=1, max_length=200)
    effect: CapabilityEffect
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    required_scopes: list[str]
    timeout_seconds: int = Field(ge=1, le=3600)
    max_attempts: int = Field(ge=1, le=10)
    fixed_cost_micros: int = Field(ge=0)
    handler_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,127}$")


class RequestContext(FrozenModel):
    principal_id: str
    tenant_id: str
    customer_id: str
    project_id: str
    scopes: frozenset[str]
    correlation_id: str


class CapabilityExecutionContext(FrozenModel):
    request: RequestContext
    run_id: str
    node_execution_id: str
    idempotency_key: str
    timeout_seconds: int


class CapabilityResult(FrozenModel):
    output: dict[str, Any]
    actual_cost_micros: int = Field(ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    evidence_refs: list[str] = Field(default_factory=list)
~~~

- [ ] **Step 4: 创建契约导出脚本**

~~~python
from __future__ import annotations

import json
from pathlib import Path

from src.platform.kernel.contracts import CapabilityDefinition, GraphDefinition


ROOT = Path(__file__).resolve().parents[1]


def write_schema(path: Path, model) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    write_schema(
        ROOT / "contracts/graph/v1/graph-definition.schema.json",
        GraphDefinition,
    )
    write_schema(
        ROOT / "contracts/graph/v1/capability-definition.schema.json",
        CapabilityDefinition,
    )


if __name__ == "__main__":
    main()
~~~

- [ ] **Step 5: 生成、验证并提交**

~~~bash
python3 scripts/export_contracts.py
XONSH_HISTORY_BACKEND=dummy PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/unit/platform/kernel/test_contracts.py -q
git diff --check
git add src/platform/kernel scripts/export_contracts.py tests/unit/platform/kernel/test_contracts.py contracts/graph
git commit -m "feat(kernel): freeze graph and capability contracts"
~~~

Expected: 3 passed；生成文件再次运行无 diff。

## Task 4: 实现安全条件与 Graph 静态校验

**Files:**
- Create: src/platform/kernel/conditions.py
- Create: src/platform/kernel/validation.py
- Create: tests/unit/platform/kernel/test_conditions.py
- Create: tests/unit/platform/kernel/test_validation.py

- [ ] **Step 1: 写安全条件测试**

~~~python
import pytest

from src.platform.kernel.conditions import evaluate_condition, resolve_path
from src.platform.kernel.contracts import Condition


STATE = {
    "input": {"name": "demo"},
    "nodes": {"recognize": {"output": {"needs_review": True, "count": 2}}},
    "human": {},
}


def test_resolve_only_dotted_dict_paths():
    assert resolve_path(STATE, "$.nodes.recognize.output.count") == 2
    with pytest.raises(ValueError):
        resolve_path(STATE, "$.__class__.__mro__")


@pytest.mark.parametrize(
    ("operator", "value", "expected"),
    [
        ("eq", True, True),
        ("ne", False, True),
        ("exists", None, True),
        ("in", [True, False], True),
    ],
)
def test_condition_operators(operator, value, expected):
    condition = Condition(
        path="$.nodes.recognize.output.needs_review",
        operator=operator,
        value=value,
    )
    assert evaluate_condition(STATE, condition) is expected
~~~

- [ ] **Step 2: 写 Graph 失败校验测试**

~~~python
import pytest

from src.platform.kernel.contracts import (
    BudgetLimits,
    CapabilityRef,
    GraphDefinition,
    GraphNode,
    NodeKind,
)
from src.platform.kernel.validation import GraphValidationError, validate_graph


def make_graph(nodes, start="start"):
    return GraphDefinition(
        graph_id="test.graph",
        name="test",
        start_node=start,
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        budget=BudgetLimits(
            max_steps=20,
            max_wall_seconds=60,
            max_cost_micros=1000,
            max_tokens=0,
        ),
        nodes=nodes,
    )


def test_rejects_missing_target():
    graph = make_graph([
        GraphNode(
            node_id="start",
            kind=NodeKind.CAPABILITY,
            capability=CapabilityRef(capability_id="core.echo", version="1.0.0"),
            next_node="missing",
        )
    ])
    with pytest.raises(GraphValidationError, match="missing"):
        validate_graph(graph)


def test_rejects_unbounded_cycle():
    graph = make_graph([
        GraphNode(
            node_id="start",
            kind=NodeKind.DECISION,
            condition=Condition(
                path="$.input.repeat",
                operator="eq",
                value=True,
            ),
            true_node="start",
            false_node="done",
        ),
        GraphNode(node_id="done", kind=NodeKind.END),
    ])
    with pytest.raises(GraphValidationError, match="unbounded cycle"):
        validate_graph(graph)


def test_requires_reachable_end():
    graph = make_graph([
        GraphNode(
            node_id="start",
            kind=NodeKind.CAPABILITY,
            capability=CapabilityRef(capability_id="core.echo", version="1.0.0"),
            next_node="loop",
        ),
        GraphNode(
            node_id="loop",
            kind=NodeKind.CAPABILITY,
            capability=CapabilityRef(capability_id="core.echo", version="1.0.0"),
            next_node="loop",
            max_iterations=2,
        ),
    ])
    with pytest.raises(GraphValidationError, match="reachable end"):
        validate_graph(graph)
~~~

- [ ] **Step 3: 运行并确认失败**

~~~bash
XONSH_HISTORY_BACKEND=dummy PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/unit/platform/kernel/test_conditions.py tests/unit/platform/kernel/test_validation.py -q
~~~

Expected: FAIL，两个模块尚不存在。

- [ ] **Step 4: 实现受控条件**

~~~python
from __future__ import annotations

from typing import Any

from .contracts import Condition, ConditionOperator


_ALLOWED_ROOTS = {"input", "nodes", "human"}


def resolve_path(state: dict[str, Any], path: str) -> Any:
    if not path.startswith("$."):
        raise ValueError("path must start with $.")
    parts = path[2:].split(".")
    if not parts or parts[0] not in _ALLOWED_ROOTS:
        raise ValueError("path root is not allowed")
    current: Any = state
    for part in parts:
        if not part or part.startswith("_") or not isinstance(current, dict):
            raise ValueError("unsafe or invalid path")
        if part not in current:
            raise KeyError(path)
        current = current[part]
    return current


def evaluate_condition(state: dict[str, Any], condition: Condition) -> bool:
    try:
        actual = resolve_path(state, condition.path)
        exists = True
    except KeyError:
        actual = None
        exists = False

    op = condition.operator
    expected = condition.value
    if op == ConditionOperator.EXISTS:
        return exists
    if not exists:
        return False
    if op == ConditionOperator.EQ:
        return actual == expected
    if op == ConditionOperator.NE:
        return actual != expected
    if op == ConditionOperator.GT:
        return actual > expected
    if op == ConditionOperator.GTE:
        return actual >= expected
    if op == ConditionOperator.LT:
        return actual < expected
    if op == ConditionOperator.LTE:
        return actual <= expected
    if op == ConditionOperator.IN:
        if not isinstance(expected, list):
            raise ValueError("in operator requires list value")
        return actual in expected
    raise ValueError(f"unsupported operator: {op}")
~~~

- [ ] **Step 5: 实现 Graph 校验**

~~~python
from __future__ import annotations

from collections import defaultdict, deque

from .contracts import GraphDefinition, GraphNode, NodeKind


class GraphValidationError(ValueError):
    """Graph definition violates a frozen Stage 0-1 invariant."""


def _targets(node: GraphNode) -> list[str]:
    if node.kind in (NodeKind.CAPABILITY, NodeKind.HUMAN):
        return [node.next_node] if node.next_node else []
    if node.kind == NodeKind.DECISION:
        return [x for x in (node.true_node, node.false_node) if x]
    return []


def _validate_shape(node: GraphNode) -> None:
    if node.kind == NodeKind.CAPABILITY:
        if node.capability is None or node.next_node is None:
            raise GraphValidationError(f"{node.node_id}: capability and next_node required")
    elif node.kind == NodeKind.DECISION:
        if node.condition is None or not node.true_node or not node.false_node:
            raise GraphValidationError(f"{node.node_id}: condition/true_node/false_node required")
    elif node.kind == NodeKind.HUMAN:
        if not node.task_type or not node.next_node:
            raise GraphValidationError(f"{node.node_id}: task_type and next_node required")
    elif node.kind == NodeKind.END:
        if _targets(node):
            raise GraphValidationError(f"{node.node_id}: end cannot have targets")


def _strongly_connected(adjacency: dict[str, list[str]]) -> list[set[str]]:
    index = 0
    stack: list[str] = []
    indices: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    result: list[set[str]] = []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = index
        low[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for target in adjacency[node]:
            if target not in indices:
                visit(target)
                low[node] = min(low[node], low[target])
            elif target in on_stack:
                low[node] = min(low[node], indices[target])
        if low[node] == indices[node]:
            component: set[str] = set()
            while True:
                item = stack.pop()
                on_stack.remove(item)
                component.add(item)
                if item == node:
                    break
            result.append(component)

    for node in adjacency:
        if node not in indices:
            visit(node)
    return result


def validate_graph(graph: GraphDefinition) -> None:
    nodes = {node.node_id: node for node in graph.nodes}
    if len(nodes) != len(graph.nodes):
        raise GraphValidationError("duplicate node_id")
    if graph.start_node not in nodes:
        raise GraphValidationError("start_node missing")

    adjacency: dict[str, list[str]] = defaultdict(list)
    reverse: dict[str, list[str]] = defaultdict(list)
    for node in graph.nodes:
        _validate_shape(node)
        for target in _targets(node):
            if target not in nodes:
                raise GraphValidationError(f"{node.node_id}: target {target} missing")
            adjacency[node.node_id].append(target)
            reverse[target].append(node.node_id)
        adjacency.setdefault(node.node_id, [])

    reachable: set[str] = set()
    queue = deque([graph.start_node])
    while queue:
        node_id = queue.popleft()
        if node_id in reachable:
            continue
        reachable.add(node_id)
        queue.extend(adjacency[node_id])

    ends = {node.node_id for node in graph.nodes if node.kind == NodeKind.END}
    reachable_ends = ends & reachable
    if not reachable_ends:
        raise GraphValidationError("graph requires a reachable end")

    can_reach_end: set[str] = set(reachable_ends)
    queue = deque(reachable_ends)
    while queue:
        node_id = queue.popleft()
        for source in reverse[node_id]:
            if source not in can_reach_end:
                can_reach_end.add(source)
                queue.append(source)
    if not reachable.issubset(can_reach_end):
        raise GraphValidationError("every reachable node must reach an end")

    for component in _strongly_connected(adjacency):
        self_loop = len(component) == 1 and next(iter(component)) in adjacency[next(iter(component))]
        if len(component) > 1 or self_loop:
            if not all(nodes[node_id].max_iterations for node_id in component):
                raise GraphValidationError(f"unbounded cycle: {sorted(component)}")
~~~

- [ ] **Step 6: 运行测试并提交**

~~~bash
XONSH_HISTORY_BACKEND=dummy PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/unit/platform/kernel/test_conditions.py tests/unit/platform/kernel/test_validation.py -q
git add src/platform/kernel/conditions.py src/platform/kernel/validation.py tests/unit/platform/kernel
git commit -m "feat(kernel): validate bounded graph definitions"
~~~

Expected: 所有新测试通过；不存在 eval 或动态 import。

## Task 5: 建立 PostgreSQL 智能内核 schema

**Files:**
- Create: alembic.ini
- Create: migrations/platform/env.py
- Create: migrations/platform/script.py.mako
- Create: migrations/platform/versions/20260804_0001_foundation.py
- Create: migrations/postgres/002_graph_kernel.sql
- Modify: compose.yaml
- Create: tests/integration/test_graph_schema.py

- [ ] **Step 1: 为 Compose 增加隔离测试数据库**

在 services 下增加：

~~~yaml
  postgres-test:
    image: pgvector/pgvector:0.8.0-pg16
    profiles: ["test"]
    environment:
      POSTGRES_USER: sku_test
      POSTGRES_PASSWORD: graph-kernel-test-only
      POSTGRES_DB: sku_graph_test
    ports: ["55432:5432"]
    tmpfs:
      - /var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U sku_test -d sku_graph_test"]
      interval: 2s
      timeout: 2s
      retries: 30
~~~

这只用于测试，不挂业务 volume，不连接现有 pgdata。

- [ ] **Step 2: 创建 Alembic 配置**

alembic.ini：

~~~ini
[alembic]
script_location = migrations/platform
prepend_sys_path = .

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
~~~

migrations/platform/env.py：

~~~python
from logging.config import fileConfig
import os

from alembic import context
from sqlalchemy import engine_from_config, pool


config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

database_url = os.environ["APP_DATABASE_URL"]
config.set_main_option("sqlalchemy.url", database_url)
target_metadata = None


def run_migrations_offline() -> None:
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section) or {},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
~~~

使用 alembic init 生成的标准 script.py.mako，不改模板语义。

- [ ] **Step 3: 创建 forward-only 迁移**

迁移必须创建以下表和约束；执行 Agent 使用 op.create_table 逐表实现，列定义不得偏离本表：

| 表 | 必需列/约束 |
|---|---|
| iam.tenant | tenant_id PK、name、status、created_at |
| iam.customer | customer_id PK、tenant_id FK、name、created_at |
| iam.project | project_id PK、tenant_id/customer_id FK、name、created_at |
| iam.principal | principal_id PK、tenant_id FK、token_sha256 UNIQUE、active、created_at |
| iam.principal_grant | principal_id/project_id/scope 复合 PK |
| capability.definition | capability_id/version 复合 PK、effect、schemas、scopes、handler_key、cost、enabled |
| graph.definition | graph_id/tenant_id、name、created_at，复合 PK |
| graph.version | graph_version_id PK、graph_id/tenant_id FK、version_no、status、definition_json、definition_sha256、published_at |
| graph.run | run_id PK、tenant/customer/project、graph_version_id、status、input/state/budget/spent JSONB、idempotency_key、version_no、timestamps |
| graph.node_execution | node_execution_id PK、run/node/iteration/attempt、status、capability、input/output/error/cost、idempotency_key、lease、available_at、timestamps |
| graph.run_event | event_id PK、run_id、sequence_no、event_type、payload、created_at；run_id+sequence_no UNIQUE |
| graph.checkpoint | checkpoint_id PK、run_id、sequence_no、state_json、state_sha256、created_at |
| policy.decision | decision_id PK、run/node、rule_version、decision、reason、evidence、created_at |
| policy.human_task | task_id PK、run/node、status、task_type、payload/decision、assignee、timestamps |
| policy.pending_command | command_id PK、run、target/version、command、risk、status、审批字段 |
| billing.usage_event | usage_event_id PK、run/node/capability、event_type、cost_micros、token、work_units、idempotency_key UNIQUE、created_at |
| audit.audit_event | audit_event_id PK、tenant/project/principal、action/object/result/payload/correlation_id、created_at |

所有 JSON 使用 JSONB；所有时间使用 TIMESTAMPTZ；所有金额使用 BIGINT micros。graph.run 在 tenant_id、idempotency_key 上唯一。graph.node_execution 在 run_id、node_id、iteration、attempt_no 上唯一。

迁移末尾创建：

~~~python
op.create_index(
    "ix_node_claim",
    "node_execution",
    ["status", "available_at", "lease_until"],
    schema="graph",
)
op.create_index(
    "ix_run_tenant_status_created",
    "run",
    ["tenant_id", "status", "created_at"],
    schema="graph",
)
~~~

对 graph.version 的 published 行，以及 graph.run_event、graph.checkpoint、policy.decision、billing.usage_event、audit.audit_event 创建数据库触发器：禁止 DELETE；对追加式表同时禁止 UPDATE。downgrade 必须：

~~~python
def downgrade() -> None:
    raise RuntimeError("graph kernel migration is forward-only; disable feature flag instead")
~~~

不得在 rollback 中 DROP schema。

为了消除实施歧义，`migrations/platform/versions/20260804_0001_foundation.py` 固定为读取同仓库 SQL，不能在执行阶段重新设计表：

~~~python
from pathlib import Path

from alembic import op


revision = "20260804_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql_path = Path(__file__).resolve().parents[2] / "postgres" / "002_graph_kernel.sql"
    sql = sql_path.read_text(encoding="utf-8")
    driver_connection = op.get_bind().connection.driver_connection
    driver_connection.execute(sql, prepare=False)


def downgrade() -> None:
    raise RuntimeError("graph kernel migration is forward-only; disable feature flag instead")
~~~

`migrations/postgres/002_graph_kernel.sql` 的精确内容如下。`principal_grant` 显式携带 tenant_id，使 principal 与 project 不可能跨租户组合；audit 表故意不设业务外键，以便即使主体停用仍保留历史证据：

~~~sql
CREATE SCHEMA IF NOT EXISTS iam;
CREATE SCHEMA IF NOT EXISTS capability;
CREATE SCHEMA IF NOT EXISTS graph;
CREATE SCHEMA IF NOT EXISTS policy;
CREATE SCHEMA IF NOT EXISTS billing;
CREATE SCHEMA IF NOT EXISTS audit;

ALTER TABLE IF EXISTS public.audit_outbox
    ADD COLUMN IF NOT EXISTS delivery_status TEXT NOT NULL DEFAULT 'pending';
ALTER TABLE IF EXISTS public.audit_outbox
    ADD COLUMN IF NOT EXISTS delivered_at DOUBLE PRECISION;
DO $$
BEGIN
    IF to_regclass('public.audit_outbox') IS NOT NULL
       AND NOT EXISTS (
           SELECT 1 FROM pg_constraint
           WHERE conrelid='public.audit_outbox'::regclass
             AND conname='audit_outbox_delivery_status_ck'
       ) THEN
        ALTER TABLE public.audit_outbox
            ADD CONSTRAINT audit_outbox_delivery_status_ck
            CHECK (delivery_status IN ('pending','delivered','dead'));
    END IF;
END;
$$;

CREATE TABLE iam.tenant (
    tenant_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'suspended')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE iam.customer (
    customer_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES iam.tenant(tenant_id),
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (customer_id, tenant_id)
);

CREATE TABLE iam.project (
    project_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES iam.tenant(tenant_id),
    customer_id TEXT NOT NULL,
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_id, tenant_id),
    UNIQUE (project_id, customer_id, tenant_id),
    FOREIGN KEY (customer_id, tenant_id)
        REFERENCES iam.customer(customer_id, tenant_id)
);

CREATE TABLE iam.principal (
    principal_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES iam.tenant(tenant_id),
    token_sha256 TEXT NOT NULL UNIQUE CHECK (length(token_sha256) = 64),
    active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (principal_id, tenant_id)
);

CREATE TABLE iam.principal_grant (
    principal_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    scope TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (principal_id, project_id, scope),
    FOREIGN KEY (principal_id, tenant_id)
        REFERENCES iam.principal(principal_id, tenant_id),
    FOREIGN KEY (project_id, tenant_id)
        REFERENCES iam.project(project_id, tenant_id)
);

CREATE TABLE capability.definition (
    capability_id TEXT NOT NULL,
    version TEXT NOT NULL,
    name TEXT NOT NULL,
    effect TEXT NOT NULL CHECK (effect IN ('read_only', 'system_write', 'domain_command')),
    input_schema_json JSONB NOT NULL,
    output_schema_json JSONB NOT NULL,
    required_scopes_json JSONB NOT NULL,
    handler_key TEXT NOT NULL,
    timeout_seconds INTEGER NOT NULL CHECK (timeout_seconds BETWEEN 1 AND 3600),
    max_attempts INTEGER NOT NULL CHECK (max_attempts BETWEEN 1 AND 10),
    fixed_cost_micros BIGINT NOT NULL CHECK (fixed_cost_micros >= 0),
    enabled BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (capability_id, version)
);

CREATE TABLE graph.definition (
    graph_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL REFERENCES iam.tenant(tenant_id),
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (graph_id, tenant_id)
);

CREATE TABLE graph.version (
    graph_version_id TEXT PRIMARY KEY,
    graph_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    version_no INTEGER NOT NULL CHECK (version_no > 0),
    status TEXT NOT NULL CHECK (status IN ('draft', 'published', 'retired')),
    definition_json JSONB NOT NULL,
    definition_sha256 TEXT NOT NULL CHECK (length(definition_sha256) = 64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at TIMESTAMPTZ,
    UNIQUE (graph_id, tenant_id, version_no),
    FOREIGN KEY (graph_id, tenant_id)
        REFERENCES graph.definition(graph_id, tenant_id)
);

CREATE TABLE graph.run (
    run_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    graph_version_id TEXT NOT NULL REFERENCES graph.version(graph_version_id),
    status TEXT NOT NULL CHECK (status IN (
        'created', 'ready', 'running', 'waiting_human', 'paused',
        'completed', 'failed', 'cancelled', 'budget_exhausted', 'policy_blocked'
    )),
    input_json JSONB NOT NULL,
    state_json JSONB NOT NULL,
    budget_json JSONB NOT NULL,
    spent_json JSONB NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_sha256 TEXT NOT NULL CHECK (length(request_sha256) = 64),
    version_no INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    deadline_at TIMESTAMPTZ,
    suspended_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    UNIQUE (tenant_id, idempotency_key),
    FOREIGN KEY (principal_id, tenant_id)
        REFERENCES iam.principal(principal_id, tenant_id),
    FOREIGN KEY (project_id, customer_id, tenant_id)
        REFERENCES iam.project(project_id, customer_id, tenant_id)
);

CREATE TABLE graph.node_execution (
    node_execution_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES graph.run(run_id),
    node_id TEXT NOT NULL,
    iteration INTEGER NOT NULL CHECK (iteration >= 0),
    attempt_no INTEGER NOT NULL CHECK (attempt_no >= 0),
    status TEXT NOT NULL CHECK (status IN (
        'queued', 'leased', 'running', 'waiting_human', 'succeeded', 'failed', 'cancelled'
    )),
    capability_id TEXT,
    capability_version TEXT,
    input_json JSONB NOT NULL,
    output_json JSONB,
    error_code TEXT,
    error_detail TEXT,
    cost_micros BIGINT NOT NULL DEFAULT 0 CHECK (cost_micros >= 0),
    idempotency_key TEXT NOT NULL,
    lease_owner TEXT,
    lease_until TIMESTAMPTZ,
    available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    UNIQUE (run_id, node_id, iteration, attempt_no),
    FOREIGN KEY (capability_id, capability_version)
        REFERENCES capability.definition(capability_id, version)
);

CREATE TABLE graph.run_event (
    event_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES graph.run(run_id),
    sequence_no BIGINT NOT NULL,
    event_type TEXT NOT NULL,
    payload_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, sequence_no)
);

CREATE TABLE graph.checkpoint (
    checkpoint_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES graph.run(run_id),
    sequence_no BIGINT NOT NULL,
    state_json JSONB NOT NULL,
    state_sha256 TEXT NOT NULL CHECK (length(state_sha256) = 64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, sequence_no)
);

CREATE TABLE policy.decision (
    decision_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES graph.run(run_id),
    node_execution_id TEXT NOT NULL REFERENCES graph.node_execution(node_execution_id),
    rule_version TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('allow', 'deny', 'human_required')),
    reason_code TEXT NOT NULL,
    evidence_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE policy.human_task (
    task_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES graph.run(run_id),
    node_execution_id TEXT NOT NULL REFERENCES graph.node_execution(node_execution_id),
    task_type TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('open', 'completed', 'cancelled')),
    payload_json JSONB NOT NULL,
    decision_json JSONB,
    decision_sha256 TEXT,
    idempotency_key TEXT,
    assignee_principal_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    UNIQUE (run_id, idempotency_key)
);

CREATE TABLE policy.pending_command (
    command_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES graph.run(run_id),
    node_execution_id TEXT NOT NULL REFERENCES graph.node_execution(node_execution_id),
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    expected_version TEXT NOT NULL,
    command_json JSONB NOT NULL,
    risk_level TEXT NOT NULL CHECK (risk_level IN ('low', 'medium', 'high', 'critical')),
    status TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'rejected', 'executed', 'expired')),
    requested_by TEXT NOT NULL,
    approved_by TEXT,
    approved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE billing.usage_event (
    usage_event_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES graph.run(run_id),
    node_execution_id TEXT NOT NULL REFERENCES graph.node_execution(node_execution_id),
    capability_id TEXT,
    event_type TEXT NOT NULL,
    cost_micros BIGINT NOT NULL CHECK (cost_micros >= 0),
    input_tokens BIGINT NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
    output_tokens BIGINT NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
    work_units_json JSONB NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE audit.audit_event (
    audit_event_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    action TEXT NOT NULL,
    object_type TEXT NOT NULL,
    object_id TEXT NOT NULL,
    result TEXT NOT NULL,
    payload_json JSONB NOT NULL,
    correlation_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_node_claim
    ON graph.node_execution(status, available_at, lease_until);
CREATE INDEX ix_run_tenant_status_created
    ON graph.run(tenant_id, status, created_at);
CREATE INDEX ix_human_task_project_status
    ON policy.human_task(status, created_at);
CREATE INDEX ix_audit_scope_time
    ON audit.audit_event(tenant_id, project_id, created_at);

CREATE OR REPLACE FUNCTION audit.reject_append_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_SCHEMA || '.' || TG_TABLE_NAME;
END;
$$;

CREATE OR REPLACE FUNCTION audit.freeze_graph_version()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'graph versions cannot be deleted';
    END IF;
    IF OLD.status = 'published' THEN
        RAISE EXCEPTION 'published graph version is immutable';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER freeze_graph_version
BEFORE UPDATE OR DELETE ON graph.version
FOR EACH ROW EXECUTE FUNCTION audit.freeze_graph_version();

CREATE TRIGGER freeze_capability_definition
BEFORE UPDATE OR DELETE ON capability.definition
FOR EACH ROW EXECUTE FUNCTION audit.reject_append_mutation();

CREATE TRIGGER append_only_run_event
BEFORE UPDATE OR DELETE ON graph.run_event
FOR EACH ROW EXECUTE FUNCTION audit.reject_append_mutation();

CREATE TRIGGER append_only_checkpoint
BEFORE UPDATE OR DELETE ON graph.checkpoint
FOR EACH ROW EXECUTE FUNCTION audit.reject_append_mutation();

CREATE TRIGGER append_only_policy_decision
BEFORE UPDATE OR DELETE ON policy.decision
FOR EACH ROW EXECUTE FUNCTION audit.reject_append_mutation();

CREATE TRIGGER append_only_usage_event
BEFORE UPDATE OR DELETE ON billing.usage_event
FOR EACH ROW EXECUTE FUNCTION audit.reject_append_mutation();

CREATE TRIGGER append_only_audit_event
BEFORE UPDATE OR DELETE ON audit.audit_event
FOR EACH ROW EXECUTE FUNCTION audit.reject_append_mutation();
~~~

- [ ] **Step 4: 写 schema 测试**

~~~python
import uuid

import pytest
from sqlalchemy import create_engine, inspect, text


def test_graph_schemas_and_append_only_trigger(test_database_url):
    engine = create_engine(test_database_url)
    inspector = inspect(engine)
    assert "run" in inspector.get_table_names(schema="graph")
    assert "definition" in inspector.get_table_names(schema="capability")
    assert "usage_event" in inspector.get_table_names(schema="billing")

    audit_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO audit.audit_event "
            "(audit_event_id, tenant_id, project_id, principal_id, action, object_type, object_id, result, payload_json, correlation_id) "
            "VALUES (:id, 'tenant_local', 'project_local', 'principal_local', 'test', 'test', '1', 'ok', '{}'::jsonb, 'corr')"
        ), {"id": audit_id})
    with pytest.raises(Exception):
        with engine.begin() as conn:
            conn.execute(text(
                "UPDATE audit.audit_event SET result='changed' WHERE audit_event_id=:id"
            ), {"id": audit_id})
~~~

- [ ] **Step 5: 启动测试库、迁移并验证**

~~~bash
docker compose --profile test up -d postgres-test
APP_DATABASE_URL=postgresql+psycopg://<user>:<password>@127.0.0.1:55432/sku_graph_test python3 -m alembic upgrade head
APP_DATABASE_URL=postgresql+psycopg://<user>:<password>@127.0.0.1:55432/sku_graph_test XONSH_HISTORY_BACKEND=dummy PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/integration/test_graph_schema.py -q
~~~

Expected: 1 passed；alembic current 指向 20260804_0001。测试后保留容器，除非用户明确允许停止；不得删除业务 volume。

- [ ] **Step 6: 提交**

~~~bash
git add alembic.ini migrations/platform compose.yaml tests/integration/test_graph_schema.py
git commit -m "feat(kernel): add forward-only graph postgres schema"
~~~

## Task 6: 实现 PostgreSQL Graph Repository

**Files:**
- Create: src/platform/data/__init__.py
- Create: src/platform/data/database.py
- Create: src/platform/data/repositories.py
- Create: src/platform/data/graph_repository.py
- Create: tests/integration/conftest.py
- Create: tests/integration/test_graph_repository.py

- [ ] **Step 1: 写 Repository 集成测试**

~~~python
import uuid

import pytest

from src.platform.kernel.contracts import (
    BudgetLimits,
    CapabilityRef,
    GraphDefinition,
    GraphNode,
    NodeKind,
    RequestContext,
)


def context(prefix: str) -> RequestContext:
    return RequestContext(
        principal_id=f"principal_{prefix}",
        tenant_id=f"tenant_{prefix}",
        customer_id=f"customer_{prefix}",
        project_id=f"project_{prefix}",
        scopes=frozenset({"graph:write", "run:create", "capability:echo"}),
        correlation_id=str(uuid.uuid4()),
    )


def definition(graph_id: str) -> GraphDefinition:
    return GraphDefinition(
        graph_id=graph_id,
        name="echo",
        start_node="echo",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        budget=BudgetLimits(
            max_steps=4,
            max_wall_seconds=30,
            max_cost_micros=1000,
            max_tokens=0,
        ),
        nodes=[
            GraphNode(
                node_id="echo",
                kind=NodeKind.CAPABILITY,
                capability=CapabilityRef(capability_id="core.echo", version="1.0.0"),
                next_node="done",
            ),
            GraphNode(node_id="done", kind=NodeKind.END),
        ],
    )


def test_published_version_is_immutable(repository):
    ctx = context(uuid.uuid4().hex[:8])
    repository.bootstrap_scope(ctx, token_sha256="0" * 64)
    draft = repository.create_draft_version(ctx, definition("echo"))
    published = repository.publish_version(ctx, draft.graph_version_id)
    assert published.status == "published"
    with pytest.raises(Exception):
        repository.replace_draft(ctx, draft.graph_version_id, definition("changed"))


def test_run_idempotency_and_tenant_scope(repository):
    ctx = context(uuid.uuid4().hex[:8])
    repository.bootstrap_scope(ctx, token_sha256="1" * 64)
    draft = repository.create_draft_version(ctx, definition("echo"))
    version = repository.publish_version(ctx, draft.graph_version_id)

    first = repository.create_run(
        ctx,
        version.graph_version_id,
        {"message": "hello"},
        idempotency_key="same-key",
    )
    second = repository.create_run(
        ctx,
        version.graph_version_id,
        {"message": "hello"},
        idempotency_key="same-key",
    )
    assert first.run_id == second.run_id

    other = context(uuid.uuid4().hex[:8])
    repository.bootstrap_scope(other, token_sha256="2" * 64)
    assert repository.get_run(other, first.run_id) is None
~~~

- [ ] **Step 2: 创建测试 fixture**

~~~python
import os

import pytest

from src.platform.data.database import create_database
from src.platform.data.graph_repository import PostgresGraphRepository


@pytest.fixture(scope="session")
def test_database_url():
    url = os.environ.get("APP_DATABASE_URL")
    if not url:
        pytest.skip("APP_DATABASE_URL required for integration tests")
    if "sku_graph_test" not in url:
        raise RuntimeError("integration tests refuse non-test database")
    return url


@pytest.fixture
def repository(test_database_url):
    database = create_database(test_database_url)
    return PostgresGraphRepository(database)
~~~

- [ ] **Step 3: 运行并确认失败**

~~~bash
APP_DATABASE_URL=postgresql+psycopg://<user>:<password>@127.0.0.1:55432/sku_graph_test XONSH_HISTORY_BACKEND=dummy PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/integration/test_graph_repository.py -q
~~~

Expected: FAIL，persistence/repository 模块尚不存在。

- [ ] **Step 4: 创建数据库事务边界**

~~~python
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


@dataclass(frozen=True)
class Database:
    engine: Engine
    session_factory: sessionmaker[Session]

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self.session_factory()
        try:
            with session.begin():
                yield session
        finally:
            session.close()


def create_database(url: str) -> Database:
    engine = create_engine(
        url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        future=True,
    )
    return Database(
        engine=engine,
        session_factory=sessionmaker(bind=engine, expire_on_commit=False),
    )
~~~

- [ ] **Step 5: 创建 Repository 记录与 Protocol**

~~~python
from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from .contracts import GraphDefinition, RequestContext


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GraphVersionRecord(Record):
    graph_version_id: str
    graph_id: str
    version_no: int
    status: str
    definition: GraphDefinition
    definition_sha256: str


class RunRecord(Record):
    run_id: str
    graph_version_id: str
    status: str
    input: dict[str, Any]
    state: dict[str, Any]
    budget: dict[str, Any]
    spent: dict[str, Any]
    version_no: int
    created_at: datetime
    updated_at: datetime


class ClaimedNode(Record):
    node_execution_id: str
    run_id: str
    node_id: str
    iteration: int
    attempt_no: int
    capability_id: str | None
    capability_version: str | None
    input: dict[str, Any]
    idempotency_key: str


class GraphRepository(Protocol):
    def create_draft_version(
        self, context: RequestContext, definition: GraphDefinition
    ) -> GraphVersionRecord: ...

    def publish_version(
        self, context: RequestContext, graph_version_id: str
    ) -> GraphVersionRecord: ...

    def create_run(
        self,
        context: RequestContext,
        graph_version_id: str,
        run_input: dict[str, Any],
        idempotency_key: str,
    ) -> RunRecord: ...

    def get_run(
        self, context: RequestContext, run_id: str
    ) -> RunRecord | None: ...
~~~

- [ ] **Step 6: 实现 Graph/Run Repository**

src/platform/data/graph_repository.py 必须使用参数化 SQL，禁止拼接 tenant_id：

~~~python
from __future__ import annotations

import hashlib
import json
import uuid

from sqlalchemy import text

from src.platform.kernel.contracts import GraphDefinition, RequestContext
from src.platform.data.repositories import GraphVersionRecord, RunRecord
from src.platform.kernel.validation import validate_graph
from .database import Database


def canonical_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


class PostgresGraphRepository:
    def __init__(self, database: Database):
        self.database = database

    def bootstrap_scope(self, context: RequestContext, token_sha256: str) -> None:
        with self.database.session() as session:
            session.execute(text(
                "INSERT INTO iam.tenant(tenant_id,name,status) VALUES (:id,:name,'active') "
                "ON CONFLICT (tenant_id) DO NOTHING"
            ), {"id": context.tenant_id, "name": context.tenant_id})
            session.execute(text(
                "INSERT INTO iam.customer(customer_id,tenant_id,name) VALUES (:id,:tenant,:name) "
                "ON CONFLICT (customer_id) DO NOTHING"
            ), {"id": context.customer_id, "tenant": context.tenant_id, "name": context.customer_id})
            session.execute(text(
                "INSERT INTO iam.project(project_id,tenant_id,customer_id,name) "
                "VALUES (:id,:tenant,:customer,:name) ON CONFLICT (project_id) DO NOTHING"
            ), {
                "id": context.project_id,
                "tenant": context.tenant_id,
                "customer": context.customer_id,
                "name": context.project_id,
            })
            session.execute(text(
                "INSERT INTO iam.principal(principal_id,tenant_id,token_sha256,active) "
                "VALUES (:id,:tenant,:token,true) ON CONFLICT (principal_id) DO NOTHING"
            ), {
                "id": context.principal_id,
                "tenant": context.tenant_id,
                "token": token_sha256,
            })
            for scope in sorted(context.scopes):
                session.execute(text(
                    "INSERT INTO iam.principal_grant(principal_id,project_id,tenant_id,scope) "
                    "VALUES (:principal,:project,:tenant,:scope) ON CONFLICT DO NOTHING"
                ), {
                    "principal": context.principal_id,
                    "project": context.project_id,
                    "tenant": context.tenant_id,
                    "scope": scope,
                })

    def create_draft_version(
        self, context: RequestContext, definition: GraphDefinition
    ) -> GraphVersionRecord:
        validate_graph(definition)
        payload = definition.model_dump(mode="json")
        digest = sha256_json(payload)
        version_id = str(uuid.uuid4())
        with self.database.session() as session:
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                {"key": f"{context.tenant_id}:{definition.graph_id}"},
            )
            session.execute(text(
                "INSERT INTO graph.definition(graph_id,tenant_id,name) "
                "VALUES (:graph_id,:tenant_id,:name) "
                "ON CONFLICT (graph_id,tenant_id) DO UPDATE SET name=EXCLUDED.name"
            ), {
                "graph_id": definition.graph_id,
                "tenant_id": context.tenant_id,
                "name": definition.name,
            })
            version_no = session.execute(text(
                "SELECT COALESCE(MAX(version_no),0)+1 FROM graph.version "
                "WHERE graph_id=:graph_id AND tenant_id=:tenant_id"
            ), {
                "graph_id": definition.graph_id,
                "tenant_id": context.tenant_id,
            }).scalar_one()
            session.execute(text(
                "INSERT INTO graph.version("
                "graph_version_id,graph_id,tenant_id,version_no,status,definition_json,definition_sha256"
                ") VALUES (:id,:graph_id,:tenant_id,:version_no,'draft',CAST(:definition AS jsonb),:sha)"
            ), {
                "id": version_id,
                "graph_id": definition.graph_id,
                "tenant_id": context.tenant_id,
                "version_no": version_no,
                "definition": canonical_json(payload),
                "sha": digest,
            })
        return GraphVersionRecord(
            graph_version_id=version_id,
            graph_id=definition.graph_id,
            version_no=version_no,
            status="draft",
            definition=definition,
            definition_sha256=digest,
        )

    def _version(self, context: RequestContext, graph_version_id: str) -> GraphVersionRecord:
        with self.database.session() as session:
            row = session.execute(text(
                "SELECT graph_version_id,graph_id,version_no,status,definition_json,definition_sha256 "
                "FROM graph.version WHERE graph_version_id=:id AND tenant_id=:tenant"
            ), {"id": graph_version_id, "tenant": context.tenant_id}).mappings().one()
        return GraphVersionRecord(
            graph_version_id=row["graph_version_id"],
            graph_id=row["graph_id"],
            version_no=row["version_no"],
            status=row["status"],
            definition=GraphDefinition.model_validate(row["definition_json"]),
            definition_sha256=row["definition_sha256"],
        )

    def publish_version(
        self, context: RequestContext, graph_version_id: str
    ) -> GraphVersionRecord:
        with self.database.session() as session:
            changed = session.execute(text(
                "UPDATE graph.version SET status='published',published_at=now() "
                "WHERE graph_version_id=:id AND tenant_id=:tenant AND status='draft'"
            ), {"id": graph_version_id, "tenant": context.tenant_id}).rowcount
            if changed != 1:
                raise ValueError("draft graph version not found")
        return self._version(context, graph_version_id)

    def replace_draft(
        self,
        context: RequestContext,
        graph_version_id: str,
        definition: GraphDefinition,
    ) -> GraphVersionRecord:
        validate_graph(definition)
        payload = definition.model_dump(mode="json")
        digest = sha256_json(payload)
        with self.database.session() as session:
            changed = session.execute(text(
                "UPDATE graph.version SET definition_json=CAST(:definition AS jsonb),definition_sha256=:sha "
                "WHERE graph_version_id=:id AND tenant_id=:tenant AND status='draft'"
            ), {
                "definition": canonical_json(payload),
                "sha": digest,
                "id": graph_version_id,
                "tenant": context.tenant_id,
            }).rowcount
            if changed != 1:
                raise ValueError("only draft graph can be replaced")
        return self._version(context, graph_version_id)

    def create_run(
        self,
        context: RequestContext,
        graph_version_id: str,
        run_input: dict,
        idempotency_key: str,
    ) -> RunRecord:
        request_sha = sha256_json({
            "graph_version_id": graph_version_id,
            "input": run_input,
        })
        run_id = str(uuid.uuid4())
        with self.database.session() as session:
            version = session.execute(text(
                "SELECT definition_json FROM graph.version "
                "WHERE graph_version_id=:version AND tenant_id=:tenant AND status='published'"
            ), {
                "version": graph_version_id,
                "tenant": context.tenant_id,
            }).mappings().one_or_none()
            if version is None:
                raise ValueError("published graph version not found")
            definition = GraphDefinition.model_validate(version["definition_json"])
            session.execute(text(
                "INSERT INTO graph.run("
                "run_id,tenant_id,customer_id,project_id,principal_id,correlation_id,"
                "graph_version_id,status,"
                "input_json,state_json,budget_json,spent_json,idempotency_key,request_sha256"
                ") VALUES ("
                ":run_id,:tenant,:customer,:project,:principal,:correlation,:version,'ready',"
                "CAST(:input AS jsonb),CAST(:state AS jsonb),CAST(:budget AS jsonb),"
                "'{\"steps\":0,\"cost_micros\":0,\"tokens\":0}'::jsonb,:key,:sha"
                ") ON CONFLICT (tenant_id,idempotency_key) DO NOTHING"
            ), {
                "run_id": run_id,
                "tenant": context.tenant_id,
                "customer": context.customer_id,
                "project": context.project_id,
                "principal": context.principal_id,
                "correlation": context.correlation_id,
                "version": graph_version_id,
                "input": canonical_json(run_input),
                "state": canonical_json({"input": run_input, "nodes": {}, "human": {}}),
                "budget": canonical_json(definition.budget.model_dump(mode="json")),
                "key": idempotency_key,
                "sha": request_sha,
            })
            row = session.execute(text(
                "SELECT * FROM graph.run WHERE tenant_id=:tenant AND idempotency_key=:key"
            ), {"tenant": context.tenant_id, "key": idempotency_key}).mappings().one()
            if row["request_sha256"] != request_sha:
                raise ValueError("idempotency key reused with different request")
        return self._run_record(row)

    def get_run(self, context: RequestContext, run_id: str) -> RunRecord | None:
        with self.database.session() as session:
            row = session.execute(text(
                "SELECT * FROM graph.run WHERE run_id=:run_id AND tenant_id=:tenant "
                "AND project_id=:project"
            ), {
                "run_id": run_id,
                "tenant": context.tenant_id,
                "project": context.project_id,
            }).mappings().one_or_none()
        return self._run_record(row) if row else None

    @staticmethod
    def _run_record(row) -> RunRecord:
        return RunRecord(
            run_id=row["run_id"],
            graph_version_id=row["graph_version_id"],
            status=row["status"],
            input=row["input_json"],
            state=row["state_json"],
            budget=row["budget_json"],
            spent=row["spent_json"],
            version_no=row["version_no"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
~~~

迁移中的 graph.run 已固定包含 request_sha256、principal_id 和 correlation_id。create_run 后的起始节点入队在 Task 9 的 start_run 实现，避免本任务提前混入运行时职责。

- [ ] **Step 7: 运行测试并提交**

~~~bash
APP_DATABASE_URL=postgresql+psycopg://<user>:<password>@127.0.0.1:55432/sku_graph_test XONSH_HISTORY_BACKEND=dummy PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/integration/test_graph_repository.py -q
git add src/platform/data src/platform/data/repositories.py tests/integration
git commit -m "feat(kernel): persist immutable graphs and idempotent runs"
~~~

Expected: 2 passed；相同幂等键/相同请求返回同一 run_id，不同请求失败。

## Task 7: 建立 Capability 白名单与 Policy/预算判断

**Files:**
- Create: src/platform/modules/__init__.py
- Create: src/platform/modules/capability.py
- Create: src/modules/reference_echo/capability.py
- Create: src/platform/modules/capability_registry.py
- Create: src/platform/kernel/policy.py
- Create: tests/unit/platform/modules/test_capability_registry.py
- Create: tests/unit/platform/kernel/test_policy.py

- [ ] **Step 1: 写白名单和策略测试**

~~~python
import pytest

from src.modules.reference_echo.capability import EchoCapability
from src.platform.kernel.contracts import (
    CapabilityDefinition,
    CapabilityEffect,
    RequestContext,
)
from src.platform.kernel.policy import PolicyEngine
from src.platform.modules.capability_registry import CapabilityRegistry


def definition(effect=CapabilityEffect.READ_ONLY):
    return CapabilityDefinition(
        capability_id="core.echo",
        version="1.0.0",
        name="Echo",
        effect=effect,
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        required_scopes=["capability:echo"],
        timeout_seconds=5,
        max_attempts=1,
        fixed_cost_micros=10,
        handler_key="core.echo",
    )


def context(scopes=frozenset({"capability:echo"})):
    return RequestContext(
        principal_id="p",
        tenant_id="t",
        customer_id="c",
        project_id="pr",
        scopes=scopes,
        correlation_id="corr",
    )


def test_registry_refuses_database_import_path():
    registry = CapabilityRegistry({"core.echo": EchoCapability()})
    registry.register(definition())
    assert registry.resolve("core.echo", "1.0.0").handler_key == "core.echo"
    bad = definition().model_copy(update={"handler_key": "os.system"})
    with pytest.raises(ValueError, match="handler"):
        registry.register(bad)


def test_policy_denies_missing_scope_and_budget():
    engine = PolicyEngine()
    missing = engine.authorize(
        context(frozenset()),
        definition(),
        budget={"max_cost_micros": 100},
        spent={"cost_micros": 0},
    )
    assert not missing.allowed
    exhausted = engine.authorize(
        context(),
        definition(),
        budget={"max_cost_micros": 5},
        spent={"cost_micros": 0},
    )
    assert not exhausted.allowed
~~~

- [ ] **Step 2: 运行并确认失败**

~~~bash
XONSH_HISTORY_BACKEND=dummy PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/unit/platform/modules/test_capability_registry.py tests/unit/platform/kernel/test_policy.py -q
~~~

Expected: FAIL，registry/policy/capabilities 尚不存在。

- [ ] **Step 3: 创建 Capability Protocol 与 Echo**

~~~python
from __future__ import annotations

from typing import Protocol

from src.platform.kernel.contracts import CapabilityExecutionContext, CapabilityResult


class CapabilityHandler(Protocol):
    def execute(
        self,
        context: CapabilityExecutionContext,
        payload: dict,
    ) -> CapabilityResult: ...
~~~

~~~python
from src.platform.kernel.contracts import CapabilityExecutionContext, CapabilityResult


class EchoCapability:
    def execute(
        self,
        context: CapabilityExecutionContext,
        payload: dict,
    ) -> CapabilityResult:
        return CapabilityResult(
            output={"echo": payload, "ok": True},
            actual_cost_micros=10,
        )
~~~

- [ ] **Step 4: 创建代码白名单 Registry**

~~~python
from __future__ import annotations

from dataclasses import dataclass

from .capabilities.base import CapabilityHandler
from .contracts import CapabilityDefinition


@dataclass(frozen=True)
class RegisteredCapability:
    definition: CapabilityDefinition
    handler: CapabilityHandler

    @property
    def handler_key(self) -> str:
        return self.definition.handler_key


class CapabilityRegistry:
    def __init__(self, handler_allowlist: dict[str, CapabilityHandler]):
        self._handler_allowlist = dict(handler_allowlist)
        self._definitions: dict[tuple[str, str], RegisteredCapability] = {}

    def register(self, definition: CapabilityDefinition) -> None:
        handler = self._handler_allowlist.get(definition.handler_key)
        if handler is None:
            raise ValueError(f"handler not allowlisted: {definition.handler_key}")
        key = (definition.capability_id, definition.version)
        existing = self._definitions.get(key)
        if existing and existing.definition != definition:
            raise ValueError(f"capability version already registered: {key}")
        self._definitions[key] = RegisteredCapability(definition, handler)

    def resolve(self, capability_id: str, version: str) -> RegisteredCapability:
        try:
            return self._definitions[(capability_id, version)]
        except KeyError as exc:
            raise KeyError(f"capability unavailable: {capability_id}@{version}") from exc

    def list(self) -> list[CapabilityDefinition]:
        return [
            item.definition
            for _, item in sorted(self._definitions.items(), key=lambda pair: pair[0])
        ]
~~~

- [ ] **Step 5: 创建无副作用 PolicyEngine**

~~~python
from __future__ import annotations

from dataclasses import dataclass

from .contracts import CapabilityDefinition, CapabilityEffect, RequestContext


@dataclass(frozen=True)
class PolicyResult:
    allowed: bool
    reason_code: str
    reserved_cost_micros: int
    requires_human_approval: bool


class PolicyEngine:
    def authorize(
        self,
        context: RequestContext,
        capability: CapabilityDefinition,
        budget: dict,
        spent: dict,
    ) -> PolicyResult:
        missing = sorted(set(capability.required_scopes) - set(context.scopes))
        if missing:
            return PolicyResult(False, "missing_scope", 0, False)

        current = int(spent.get("cost_micros", 0))
        maximum = int(budget.get("max_cost_micros", 0))
        estimate = capability.fixed_cost_micros
        if current + estimate > maximum:
            return PolicyResult(False, "cost_budget_exhausted", 0, False)

        requires_human = capability.effect == CapabilityEffect.DOMAIN_COMMAND
        if requires_human and "domain:command:auto" not in context.scopes:
            return PolicyResult(False, "human_approval_required", 0, True)

        return PolicyResult(True, "allowed", estimate, requires_human)
~~~

- [ ] **Step 6: 测试并提交**

~~~bash
XONSH_HISTORY_BACKEND=dummy PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/unit/platform/modules/test_capability_registry.py tests/unit/platform/kernel/test_policy.py -q
git add src/platform/modules/capability.py src/platform/modules/capability_registry.py src/modules/reference_echo/capability.py src/platform/kernel/policy.py tests/unit/platform/kernel tests/unit/platform/modules
git commit -m "feat(kernel): register allowlisted capabilities and enforce policy"
~~~

Expected: 新测试通过；os.system 等任意 handler_key 无法注册。

## Task 8: 实现纯 Graph 状态转换

**Files:**
- Create: src/platform/kernel/runtime.py
- Create: tests/unit/platform/kernel/test_runtime.py

- [ ] **Step 1: 写状态转换测试**

~~~python
import pytest

from src.platform.kernel.contracts import (
    BudgetLimits,
    CapabilityRef,
    CapabilityResult,
    Condition,
    GraphDefinition,
    GraphNode,
    NodeKind,
)
from src.platform.kernel.runtime import (
    BudgetExhausted,
    apply_capability_result,
    decide_next_node,
    node_idempotency_key,
)


def graph():
    return GraphDefinition(
        graph_id="recognition.min",
        name="recognition",
        start_node="recognize",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        budget=BudgetLimits(
            max_steps=5,
            max_wall_seconds=60,
            max_cost_micros=1000,
            max_tokens=0,
        ),
        nodes=[
            GraphNode(
                node_id="recognize",
                kind=NodeKind.CAPABILITY,
                capability=CapabilityRef(capability_id="vision.recognize", version="1.0.0"),
                next_node="needs_review",
            ),
            GraphNode(
                node_id="needs_review",
                kind=NodeKind.DECISION,
                condition=Condition(
                    path="$.nodes.recognize.output.needs_review",
                    operator="eq",
                    value=True,
                ),
                true_node="review",
                false_node="done",
            ),
            GraphNode(
                node_id="review",
                kind=NodeKind.HUMAN,
                task_type="recognition_review",
                next_node="done",
            ),
            GraphNode(node_id="done", kind=NodeKind.END),
        ],
    )


def test_result_updates_state_and_routes_to_human():
    state = {"input": {}, "nodes": {}, "human": {}, "_iterations": {}}
    state, spent = apply_capability_result(
        state,
        "recognize",
        CapabilityResult(
            output={"needs_review": True},
            actual_cost_micros=25,
        ),
        {"steps": 0, "cost_micros": 0, "tokens": 0},
        graph().budget.model_dump(),
    )
    assert state["nodes"]["recognize"]["output"]["needs_review"] is True
    assert spent["steps"] == 1
    decision = graph().nodes[1]
    assert decide_next_node(decision, state) == "review"


def test_budget_is_fail_closed():
    with pytest.raises(BudgetExhausted):
        apply_capability_result(
            {"input": {}, "nodes": {}, "human": {}, "_iterations": {}},
            "recognize",
            CapabilityResult(output={}, actual_cost_micros=1001),
            {"steps": 0, "cost_micros": 0, "tokens": 0},
            graph().budget.model_dump(),
        )


def test_node_idempotency_is_stable_per_iteration():
    assert node_idempotency_key("run", "node", 0) == node_idempotency_key("run", "node", 0)
    assert node_idempotency_key("run", "node", 0) != node_idempotency_key("run", "node", 1)
~~~

- [ ] **Step 2: 运行并确认失败**

~~~bash
XONSH_HISTORY_BACKEND=dummy PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/unit/platform/kernel/test_runtime.py -q
~~~

Expected: FAIL，runtime 尚不存在。

- [ ] **Step 3: 实现纯转换函数**

~~~python
from __future__ import annotations

import hashlib
from copy import deepcopy

from .conditions import evaluate_condition
from .contracts import CapabilityResult, GraphNode, NodeKind


class BudgetExhausted(RuntimeError):
    """A frozen run budget was exceeded and execution must stop."""


def node_idempotency_key(run_id: str, node_id: str, iteration: int) -> str:
    raw = f"{run_id}:{node_id}:{iteration}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def apply_capability_result(
    state: dict,
    node_id: str,
    result: CapabilityResult,
    spent: dict,
    budget: dict,
) -> tuple[dict, dict]:
    next_state = deepcopy(state)
    next_spent = dict(spent)
    next_spent["steps"] = int(next_spent.get("steps", 0)) + 1
    next_spent["cost_micros"] = int(next_spent.get("cost_micros", 0)) + result.actual_cost_micros
    next_spent["tokens"] = (
        int(next_spent.get("tokens", 0))
        + result.input_tokens
        + result.output_tokens
    )
    if next_spent["steps"] > int(budget["max_steps"]):
        raise BudgetExhausted("step budget exhausted")
    if next_spent["cost_micros"] > int(budget["max_cost_micros"]):
        raise BudgetExhausted("cost budget exhausted")
    if next_spent["tokens"] > int(budget["max_tokens"]):
        raise BudgetExhausted("token budget exhausted")
    next_state.setdefault("nodes", {})[node_id] = {
        "output": result.output,
        "evidence_refs": result.evidence_refs,
    }
    return next_state, next_spent


def decide_next_node(node: GraphNode, state: dict) -> str | None:
    if node.kind in (NodeKind.CAPABILITY, NodeKind.HUMAN):
        return node.next_node
    if node.kind == NodeKind.DECISION:
        assert node.condition is not None
        return node.true_node if evaluate_condition(state, node.condition) else node.false_node
    if node.kind == NodeKind.END:
        return None
    raise ValueError(f"unsupported node kind: {node.kind}")


def next_iteration(state: dict, node: GraphNode) -> tuple[dict, int]:
    next_state = deepcopy(state)
    iterations = next_state.setdefault("_iterations", {})
    iteration = int(iterations.get(node.node_id, 0))
    if node.max_iterations is not None and iteration >= node.max_iterations:
        raise BudgetExhausted(f"node iteration exhausted: {node.node_id}")
    iterations[node.node_id] = iteration + 1
    return next_state, iteration
~~~

- [ ] **Step 4: 测试并提交**

~~~bash
XONSH_HISTORY_BACKEND=dummy PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/unit/platform/kernel/test_runtime.py -q
git add src/platform/kernel/runtime.py tests/unit/platform/kernel/test_runtime.py
git commit -m "feat(kernel): add deterministic graph state transitions"
~~~

Expected: 3 passed；runtime 无数据库、HTTP 或模型依赖。

## Task 9: 实现持久节点队列、Worker 与崩溃恢复

**Files:**
- Modify: src/platform/data/repositories.py
- Modify: src/platform/data/graph_repository.py
- Create: src/platform/kernel/worker.py
- Create: tests/integration/test_worker_recovery.py

- [ ] **Step 1: 写恢复集成测试**

~~~python
import uuid

from sqlalchemy import text

from src.platform.kernel.contracts import CapabilityDefinition, CapabilityEffect
from src.modules.reference_echo.capability import EchoCapability
from src.platform.kernel.policy import PolicyEngine
from src.platform.modules.capability_registry import CapabilityRegistry
from src.platform.kernel.worker import GraphWorker
from tests.integration.test_graph_repository import context, definition


def echo_capability_definition():
    return CapabilityDefinition(
        capability_id="core.echo",
        version="1.0.0",
        name="Echo",
        effect=CapabilityEffect.READ_ONLY,
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        required_scopes=["capability:echo"],
        timeout_seconds=5,
        max_attempts=1,
        fixed_cost_micros=10,
        handler_key="core.echo",
    )


def test_expired_lease_reuses_node_and_idempotency(repository):
    suffix = uuid.uuid4().hex[:8]
    ctx = context(suffix)
    repository.bootstrap_scope(ctx, token_sha256="3" * 64)
    repository.upsert_capability_definition(ctx, echo_capability_definition())
    draft = repository.create_draft_version(ctx, definition("echo"))
    version = repository.publish_version(ctx, draft.graph_version_id)
    run = repository.create_run(ctx, version.graph_version_id, {"message": "x"}, "worker-recovery")
    repository.start_run(ctx, run.run_id)

    first = repository.claim_next("worker_a", lease_seconds=1)
    assert first is not None
    with repository.database.session() as session:
        session.execute(text(
            "UPDATE graph.node_execution SET lease_until=now()-interval '1 second' "
            "WHERE node_execution_id=:id"
        ), {"id": first.node_execution_id})

    second = repository.claim_next("worker_b", lease_seconds=60)
    assert second is not None
    assert second.node_execution_id == first.node_execution_id
    assert second.idempotency_key == first.idempotency_key


def test_worker_completes_echo_graph_once(repository):
    suffix = uuid.uuid4().hex[:8]
    ctx = context(suffix)
    repository.bootstrap_scope(ctx, token_sha256="4" * 64)
    capability_definition = echo_capability_definition()
    repository.upsert_capability_definition(ctx, capability_definition)
    draft = repository.create_draft_version(ctx, definition("echo"))
    version = repository.publish_version(ctx, draft.graph_version_id)
    run = repository.create_run(ctx, version.graph_version_id, {"message": "x"}, "worker-complete")
    repository.start_run(ctx, run.run_id)

    registry = CapabilityRegistry({"core.echo": EchoCapability()})
    registry.register(capability_definition)
    worker = GraphWorker("worker_test", repository, registry, PolicyEngine(), lease_seconds=60)
    assert worker.run_once()
    assert worker.run_once()
    completed = repository.get_run(ctx, run.run_id)
    assert completed is not None
    assert completed.status == "completed"
    assert completed.spent["cost_micros"] == 10
~~~

- [ ] **Step 2: 运行并确认失败**

~~~bash
APP_DATABASE_URL=postgresql+psycopg://<user>:<password>@127.0.0.1:55432/sku_graph_test XONSH_HISTORY_BACKEND=dummy PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/integration/test_worker_recovery.py -q
~~~

Expected: FAIL，start_run、claim_next 和 GraphWorker 尚不存在。

- [ ] **Step 3: 扩展执行记录类型**

在 src/platform/data/repositories.py 增加：

~~~python
class ExecutionBundle(Record):
    claim: ClaimedNode
    context: RequestContext
    graph: GraphDefinition
    node: GraphNode
    state: dict[str, Any]
    budget: dict[str, Any]
    spent: dict[str, Any]
    deadline_at: datetime


class GraphRepository(Protocol):
    def start_run(self, context: RequestContext, run_id: str) -> None: ...
    def expire_overdue_runs(self, limit: int = 100) -> int: ...
    def claim_next(self, worker_id: str, lease_seconds: int) -> ClaimedNode | None: ...
    def load_execution(self, claim: ClaimedNode) -> ExecutionBundle: ...
    def complete_node(
        self,
        bundle: ExecutionBundle,
        result: CapabilityResult,
        next_node_id: str | None,
        next_state: dict[str, Any],
        next_spent: dict[str, Any],
    ) -> None: ...
    def fail_node(
        self,
        bundle: ExecutionBundle,
        error_code: str,
        error_detail: str,
        retryable: bool,
        max_attempts: int,
    ) -> None: ...
~~~

- [ ] **Step 4: 增加 Repository 队列方法**

在 PostgresGraphRepository 中增加下列辅助方法。所有调用都在 database.session 的单事务内：

同时把 Task 14 给出的 `upsert_capability_definition` 精确实现提前到本任务；`_enqueue` 的 capability 外键要求能力版本先持久化，测试不得临时删除外键或绕过 Registry。

~~~python
def _append_event(self, session, run_id: str, event_type: str, payload: dict) -> int:
    sequence = session.execute(text(
        "SELECT COALESCE(MAX(sequence_no),0)+1 FROM graph.run_event "
        "WHERE run_id=:run_id"
    ), {"run_id": run_id}).scalar_one()
    session.execute(text(
        "INSERT INTO graph.run_event(event_id,run_id,sequence_no,event_type,payload_json) "
        "VALUES (:id,:run_id,:sequence,:type,CAST(:payload AS jsonb))"
    ), {
        "id": str(uuid.uuid4()),
        "run_id": run_id,
        "sequence": sequence,
        "type": event_type,
        "payload": canonical_json(payload),
    })
    return sequence


def _checkpoint(self, session, run_id: str, sequence: int, state: dict) -> None:
    session.execute(text(
        "INSERT INTO graph.checkpoint(checkpoint_id,run_id,sequence_no,state_json,state_sha256) "
        "VALUES (:id,:run_id,:sequence,CAST(:state AS jsonb),:sha)"
    ), {
        "id": str(uuid.uuid4()),
        "run_id": run_id,
        "sequence": sequence,
        "state": canonical_json(state),
        "sha": sha256_json(state),
    })


def _enqueue(self, session, run_id: str, node: GraphNode, state: dict) -> None:
    iteration = session.execute(text(
        "SELECT COALESCE(MAX(iteration),-1)+1 FROM graph.node_execution "
        "WHERE run_id=:run_id AND node_id=:node_id"
    ), {"run_id": run_id, "node_id": node.node_id}).scalar_one()
    if node.max_iterations is not None and iteration >= node.max_iterations:
        raise ValueError(f"node iteration exhausted: {node.node_id}")
    input_payload = state["input"] if not node.input_mapping else {
        key: resolve_path(state, path)
        for key, path in node.input_mapping.items()
    }
    session.execute(text(
        "INSERT INTO graph.node_execution("
        "node_execution_id,run_id,node_id,iteration,attempt_no,status,"
        "capability_id,capability_version,input_json,idempotency_key,available_at"
        ") VALUES ("
        ":id,:run_id,:node_id,:iteration,0,'queued',:capability_id,:capability_version,"
        "CAST(:input AS jsonb),:key,now())"
    ), {
        "id": str(uuid.uuid4()),
        "run_id": run_id,
        "node_id": node.node_id,
        "iteration": iteration,
        "capability_id": node.capability.capability_id if node.capability else None,
        "capability_version": node.capability.version if node.capability else None,
        "input": canonical_json(input_payload),
        "key": node_idempotency_key(run_id, node.node_id, iteration),
    })
~~~

在该文件导入 resolve_path、node_idempotency_key、GraphNode、CapabilityResult 和 ExecutionBundle。

实现 start_run：

~~~python
def start_run(self, context: RequestContext, run_id: str) -> None:
    with self.database.session() as session:
        row = session.execute(text(
            "SELECT r.*,v.definition_json FROM graph.run r "
            "JOIN graph.version v ON v.graph_version_id=r.graph_version_id "
            "WHERE r.run_id=:run_id AND r.tenant_id=:tenant AND r.project_id=:project "
            "FOR UPDATE OF r"
        ), {
            "run_id": run_id,
            "tenant": context.tenant_id,
            "project": context.project_id,
        }).mappings().one()
        if row["status"] == "running":
            return
        if row["status"] != "ready":
            raise ValueError(f"run cannot start from {row['status']}")
        graph = GraphDefinition.model_validate(row["definition_json"])
        node = next(item for item in graph.nodes if item.node_id == graph.start_node)
        self._enqueue(session, run_id, node, row["state_json"])
        session.execute(text(
            "UPDATE graph.run SET status='running',started_at=COALESCE(started_at,now()),"
            "deadline_at=COALESCE(deadline_at,now()+((budget_json->>'max_wall_seconds')::int "
            "* interval '1 second')),suspended_at=NULL,"
            "updated_at=now(),version_no=version_no+1 WHERE run_id=:run_id"
        ), {"run_id": run_id})
        sequence = self._append_event(session, run_id, "run_started", {"node_id": node.node_id})
        self._checkpoint(session, run_id, sequence, row["state_json"])
~~~

实现 claim_next：

~~~python
def claim_next(self, worker_id: str, lease_seconds: int) -> ClaimedNode | None:
    with self.database.session() as session:
        row = session.execute(text(
            "WITH candidate AS ("
            " SELECT n.node_execution_id FROM graph.node_execution n "
            " JOIN graph.run r ON r.run_id=n.run_id "
            " WHERE r.status='running' AND r.deadline_at>now() AND n.available_at<=now() "
            " AND (n.status='queued' OR (n.status='leased' AND n.lease_until<now())) "
            " ORDER BY n.available_at,n.created_at "
            " FOR UPDATE OF n SKIP LOCKED LIMIT 1"
            ") UPDATE graph.node_execution n SET status='leased',lease_owner=:worker,"
            "lease_until=now()+(:lease || ' seconds')::interval,started_at=COALESCE(started_at,now()) "
            "FROM candidate c WHERE n.node_execution_id=c.node_execution_id "
            "RETURNING n.*"
        ), {"worker": worker_id, "lease": lease_seconds}).mappings().one_or_none()
    if row is None:
        return None
    return ClaimedNode(
        node_execution_id=row["node_execution_id"],
        run_id=row["run_id"],
        node_id=row["node_id"],
        iteration=row["iteration"],
        attempt_no=row["attempt_no"],
        capability_id=row["capability_id"],
        capability_version=row["capability_version"],
        input=row["input_json"],
        idempotency_key=row["idempotency_key"],
    )
~~~

实现 load_execution；Worker 身份上下文必须从 run 的 principal/project 及当前 grant 重建，不能使用超级权限或请求 body：

~~~python
def load_execution(self, claim: ClaimedNode) -> ExecutionBundle:
    with self.database.session() as session:
        row = session.execute(text(
            "SELECT r.*,v.definition_json,n.status AS node_status "
            "FROM graph.node_execution n "
            "JOIN graph.run r ON r.run_id=n.run_id "
            "JOIN graph.version v ON v.graph_version_id=r.graph_version_id "
            "WHERE n.node_execution_id=:node AND n.run_id=:run AND n.status='leased'"
        ), {
            "node": claim.node_execution_id,
            "run": claim.run_id,
        }).mappings().one()
        scopes = session.execute(text(
            "SELECT scope FROM iam.principal_grant "
            "WHERE principal_id=:principal AND project_id=:project AND tenant_id=:tenant"
        ), {
            "principal": row["principal_id"],
            "project": row["project_id"],
            "tenant": row["tenant_id"],
        }).scalars().all()
    if not scopes:
        raise ValueError("policy_blocked: principal has no current project grant")
    graph = GraphDefinition.model_validate(row["definition_json"])
    node = next(item for item in graph.nodes if item.node_id == claim.node_id)
    return ExecutionBundle(
        claim=claim,
        context=RequestContext(
            principal_id=row["principal_id"],
            tenant_id=row["tenant_id"],
            customer_id=row["customer_id"],
            project_id=row["project_id"],
            scopes=frozenset(scopes),
            correlation_id=row["correlation_id"],
        ),
        graph=graph,
        node=node,
        state=row["state_json"],
        budget=row["budget_json"],
        spent=row["spent_json"],
        deadline_at=row["deadline_at"],
    )
~~~

实现 Worker 周期性 deadline sweep；只处理 running，paused/waiting_human 已冻结 deadline，不在 sweep 范围：

~~~python
def expire_overdue_runs(self, limit: int = 100) -> int:
    if limit < 1 or limit > 1000:
        raise ValueError("limit out of range")
    with self.database.session() as session:
        rows = session.execute(text(
            "SELECT run_id,state_json FROM graph.run "
            "WHERE status='running' AND deadline_at<=now() "
            "ORDER BY deadline_at FOR UPDATE SKIP LOCKED LIMIT :limit"
        ), {"limit": limit}).mappings().all()
        for row in rows:
            session.execute(text(
                "UPDATE graph.run SET status='budget_exhausted',finished_at=now(),"
                "updated_at=now(),version_no=version_no+1 WHERE run_id=:run"
            ), {"run": row["run_id"]})
            session.execute(text(
                "UPDATE graph.node_execution SET status='cancelled',finished_at=now(),"
                "lease_until=NULL WHERE run_id=:run AND status IN ('queued','leased','running')"
            ), {"run": row["run_id"]})
            sequence = self._append_event(
                session,
                row["run_id"],
                "wall_budget_exhausted",
                {"reason": "deadline reached"},
            )
            self._checkpoint(session, row["run_id"], sequence, row["state_json"])
    return len(rows)
~~~

- [ ] **Step 5: 实现 load_execution 和成功提交**

load_execution 必须按 run.principal_id 查询 iam.principal_grant，重建 RequestContext；迁移和 create_run 同时补充 principal_id、correlation_id 两列。

~~~python
def complete_node(
    self,
    bundle: ExecutionBundle,
    result: CapabilityResult,
    next_node_id: str | None,
    next_state: dict,
    next_spent: dict,
) -> None:
    with self.database.session() as session:
        run = session.execute(text(
            "SELECT status,(deadline_at>now()) AS wall_available FROM graph.run "
            "WHERE run_id=:run_id FOR UPDATE"
        ), {"run_id": bundle.claim.run_id}).mappings().one()
        if run["status"] != "running":
            raise ValueError("run no longer running")
        if not run["wall_available"]:
            raise BudgetExhausted("wall budget exhausted before commit")
        changed = session.execute(text(
            "UPDATE graph.node_execution SET status='succeeded',output_json=CAST(:output AS jsonb),"
            "cost_micros=:cost,finished_at=now(),lease_until=NULL "
            "WHERE node_execution_id=:id AND status='leased'"
        ), {
            "output": canonical_json(result.output),
            "cost": result.actual_cost_micros,
            "id": bundle.claim.node_execution_id,
        }).rowcount
        if changed != 1:
            raise ValueError("node lease lost")
        session.execute(text(
            "UPDATE graph.run SET state_json=CAST(:state AS jsonb),spent_json=CAST(:spent AS jsonb),"
            "status=:status,finished_at=CASE WHEN :status='completed' THEN now() ELSE finished_at END,"
            "updated_at=now(),version_no=version_no+1 WHERE run_id=:run_id"
        ), {
            "state": canonical_json(next_state),
            "spent": canonical_json(next_spent),
            "status": "completed" if next_node_id is None else "running",
            "run_id": bundle.claim.run_id,
        })
        session.execute(text(
            "INSERT INTO billing.usage_event("
            "usage_event_id,run_id,node_execution_id,capability_id,event_type,cost_micros,"
            "input_tokens,output_tokens,work_units_json,idempotency_key"
            ") VALUES (:id,:run,:node,:capability,'node_execution',:cost,:input_tokens,:output_tokens,"
            "'{}'::jsonb,:key)"
        ), {
            "id": str(uuid.uuid4()),
            "run": bundle.claim.run_id,
            "node": bundle.claim.node_execution_id,
            "capability": bundle.claim.capability_id,
            "cost": result.actual_cost_micros,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "key": bundle.claim.idempotency_key,
        })
        sequence = self._append_event(session, bundle.claim.run_id, "node_succeeded", {
            "node_id": bundle.claim.node_id,
            "node_execution_id": bundle.claim.node_execution_id,
            "next_node_id": next_node_id,
        })
        self._checkpoint(session, bundle.claim.run_id, sequence, next_state)
        if next_node_id is not None:
            next_node = next(item for item in bundle.graph.nodes if item.node_id == next_node_id)
            self._enqueue(session, bundle.claim.run_id, next_node, next_state)
~~~

load_execution 的返回必须包含 GraphDefinition、GraphNode、state/budget/spent、RequestContext；找不到 matching tenant/project grant 时抛 policy_blocked，不得构造超级权限。

- [ ] **Step 6: 实现失败与重试**

~~~python
def fail_node(
    self,
    bundle: ExecutionBundle,
    error_code: str,
    error_detail: str,
    retryable: bool,
    max_attempts: int,
) -> None:
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    with self.database.session() as session:
        run_status = session.execute(text(
            "SELECT status FROM graph.run WHERE run_id=:run_id FOR UPDATE"
        ), {"run_id": bundle.claim.run_id}).scalar_one()
        if run_status == "cancelled":
            self._append_event(session, bundle.claim.run_id, "late_worker_result_discarded", {
                "node_id": bundle.claim.node_id,
                "node_execution_id": bundle.claim.node_execution_id,
                "error_code": error_code,
            })
            return
        if run_status != "running":
            raise ValueError(f"cannot fail node while run is {run_status}")
        session.execute(text(
            "UPDATE graph.node_execution SET status='failed',error_code=:code,error_detail=:detail,"
            "finished_at=now(),lease_until=NULL WHERE node_execution_id=:id"
        ), {
            "code": error_code,
            "detail": error_detail[:4000],
            "id": bundle.claim.node_execution_id,
        })
        next_attempt = bundle.claim.attempt_no + 1
        if retryable and next_attempt < max_attempts:
            delay = min(60, 2 ** next_attempt)
            session.execute(text(
                "INSERT INTO graph.node_execution("
                "node_execution_id,run_id,node_id,iteration,attempt_no,status,capability_id,"
                "capability_version,input_json,idempotency_key,available_at"
                ") VALUES (:id,:run,:node_id,:iteration,:attempt,'queued',:capability,:version,"
                "CAST(:input AS jsonb),:key,now()+(:delay || ' seconds')::interval)"
            ), {
                "id": str(uuid.uuid4()),
                "run": bundle.claim.run_id,
                "node_id": bundle.claim.node_id,
                "iteration": bundle.claim.iteration,
                "attempt": next_attempt,
                "capability": bundle.claim.capability_id,
                "version": bundle.claim.capability_version,
                "input": canonical_json(bundle.claim.input),
                "key": bundle.claim.idempotency_key,
                "delay": delay,
            })
            event_type = "node_retry_scheduled"
        else:
            session.execute(text(
                "UPDATE graph.run SET status='failed',finished_at=now(),updated_at=now(),"
                "version_no=version_no+1 WHERE run_id=:run"
            ), {"run": bundle.claim.run_id})
            event_type = "run_failed"
        self._append_event(session, bundle.claim.run_id, event_type, {
            "node_id": bundle.claim.node_id,
            "error_code": error_code,
            "attempt_no": bundle.claim.attempt_no,
        })
~~~

max_attempts 只能来自 Worker 已解析的、版本锁定的 CapabilityDefinition；Repository 不得再次猜测或查询“最新版本”。

- [ ] **Step 7: 创建 GraphWorker**

~~~python
from __future__ import annotations

from datetime import datetime, timezone
import math

from .contracts import CapabilityExecutionContext, CapabilityResult, NodeKind
from .policy import PolicyEngine
from .registry import CapabilityRegistry
from .repositories import GraphRepository
from .runtime import BudgetExhausted, apply_capability_result, decide_next_node


class GraphWorker:
    def __init__(
        self,
        worker_id: str,
        repository: GraphRepository,
        registry: CapabilityRegistry,
        policy: PolicyEngine,
        lease_seconds: int,
    ):
        self.worker_id = worker_id
        self.repository = repository
        self.registry = registry
        self.policy = policy
        self.lease_seconds = lease_seconds

    def run_once(self) -> bool:
        self.repository.expire_overdue_runs()
        claim = self.repository.claim_next(self.worker_id, self.lease_seconds)
        if claim is None:
            return False
        bundle = self.repository.load_execution(claim)
        max_attempts = 1
        result_for_billing = None
        try:
            if datetime.now(timezone.utc) >= bundle.deadline_at:
                raise BudgetExhausted("wall budget exhausted before node execution")
            if bundle.node.kind == NodeKind.CAPABILITY:
                registered = self.registry.resolve(
                    claim.capability_id or "",
                    claim.capability_version or "",
                )
                max_attempts = registered.definition.max_attempts
                decision = self.policy.authorize(
                    bundle.context,
                    registered.definition,
                    bundle.budget,
                    bundle.spent,
                )
                self.repository.record_policy(bundle, decision)
                if not decision.allowed:
                    self.repository.block_node(bundle, decision.reason_code)
                    return True
                result = registered.handler.execute(
                    CapabilityExecutionContext(
                        request=bundle.context,
                        run_id=claim.run_id,
                        node_execution_id=claim.node_execution_id,
                        idempotency_key=claim.idempotency_key,
                        timeout_seconds=min(
                            registered.definition.timeout_seconds,
                            max(
                                1,
                                math.ceil(
                                    (bundle.deadline_at - datetime.now(timezone.utc)).total_seconds()
                                ),
                            ),
                        ),
                    ),
                    claim.input,
                )
            elif bundle.node.kind == NodeKind.DECISION:
                selected = decide_next_node(bundle.node, bundle.state)
                result = CapabilityResult(output={"selected_node": selected}, actual_cost_micros=0)
            elif bundle.node.kind == NodeKind.END:
                selected = None
                result = CapabilityResult(output={"completed": True}, actual_cost_micros=0)
            elif bundle.node.kind == NodeKind.HUMAN:
                self.repository.open_human_task(bundle)
                return True
            else:
                raise ValueError(f"unsupported node kind: {bundle.node.kind}")

            result_for_billing = result
            if datetime.now(timezone.utc) >= bundle.deadline_at:
                raise BudgetExhausted("wall budget exhausted after node execution")
            next_state, next_spent = apply_capability_result(
                bundle.state,
                bundle.node.node_id,
                result,
                bundle.spent,
                bundle.budget,
            )
            next_node = (
                selected
                if bundle.node.kind == NodeKind.DECISION
                else decide_next_node(bundle.node, next_state)
            )
            self.repository.complete_node(
                bundle,
                result,
                next_node,
                next_state,
                next_spent,
            )
        except BudgetExhausted as exc:
            self.repository.exhaust_budget(bundle, str(exc), result_for_billing)
        except Exception as exc:
            self.repository.fail_node(
                bundle,
                error_code=type(exc).__name__,
                error_detail=str(exc),
                retryable=True,
                max_attempts=max_attempts,
            )
        return True
~~~

Task 9 必须同时落下 Task 10 Step 4 给出的 `record_policy` 精确实现，因为 Worker 的第一条 read_only 路径已经调用它。`block_node`、`open_human_task` 和 `exhaust_budget` 在 Task 10 补齐；这三条分支在 Task 9 尚不进入验收范围，Task 10 完成前不得对外启用 Worker。

- [ ] **Step 8: 运行恢复测试并提交**

~~~bash
APP_DATABASE_URL=postgresql+psycopg://<user>:<password>@127.0.0.1:55432/sku_graph_test XONSH_HISTORY_BACKEND=dummy PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/integration/test_worker_recovery.py -q
git add src/platform/data/repositories.py src/platform/kernel/worker.py src/platform/data/graph_repository.py tests/integration/test_worker_recovery.py
git commit -m "feat(kernel): execute durable nodes with lease recovery"
~~~

Expected: 2 passed；过期 lease 被另一个 Worker 领取时 node_execution_id 和幂等键不变；Echo 与 End 各有且仅有一条 UsageEvent，总计 2 条。

## Task 10: 完成人工检查点、Policy 证据与追加式账本

**Files:**
- Create: src/platform/billing/ledger_repository.py
- Modify: src/platform/data/graph_repository.py
- Modify: src/platform/data/repositories.py
- Create: tests/integration/test_human_task.py
- Create: tests/integration/test_usage_ledger.py

- [ ] **Step 1: 写人工暂停/恢复测试**

~~~python
import uuid

from src.platform.kernel.contracts import (
    BudgetLimits,
    GraphDefinition,
    GraphNode,
    NodeKind,
)
from src.platform.kernel.policy import PolicyEngine
from src.platform.modules.capability_registry import CapabilityRegistry
from src.platform.kernel.worker import GraphWorker
from tests.integration.test_graph_repository import context


def human_graph():
    return GraphDefinition(
        graph_id="human.demo",
        name="human",
        start_node="approve",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        budget=BudgetLimits(
            max_steps=4,
            max_wall_seconds=60,
            max_cost_micros=1000,
            max_tokens=0,
        ),
        nodes=[
            GraphNode(
                node_id="approve",
                kind=NodeKind.HUMAN,
                task_type="approval",
                next_node="done",
            ),
            GraphNode(node_id="done", kind=NodeKind.END),
        ],
    )


def test_human_task_resumes_same_run(repository):
    suffix = uuid.uuid4().hex[:8]
    ctx = context(suffix)
    repository.bootstrap_scope(ctx, token_sha256="5" * 64)
    draft = repository.create_draft_version(ctx, human_graph())
    version = repository.publish_version(ctx, draft.graph_version_id)
    run = repository.create_run(ctx, version.graph_version_id, {"request": "approve"}, "human")
    repository.start_run(ctx, run.run_id)
    worker = GraphWorker("worker_human", repository, CapabilityRegistry({}), PolicyEngine(), 60)
    assert worker.run_once()
    waiting = repository.get_run(ctx, run.run_id)
    assert waiting.status == "waiting_human"
    task = repository.get_open_human_task(ctx, run.run_id)
    repository.complete_human_task(
        ctx,
        task.task_id,
        {"approved": True, "reviewer": "tester"},
        idempotency_key="human-decision-1",
    )
    assert worker.run_once()
    assert repository.get_run(ctx, run.run_id).status == "completed"
~~~

- [ ] **Step 2: 写账本不可变测试**

~~~python
import pytest
from sqlalchemy import text


def test_usage_event_is_single_and_append_only(repository, prepared_echo_run):
    worker, ctx, run_id = prepared_echo_run
    assert worker.run_once()
    assert worker.run_once()
    with repository.database.session() as session:
        count = session.execute(text(
            "SELECT count(*) FROM billing.usage_event WHERE run_id=:run_id"
        ), {"run_id": run_id}).scalar_one()
        assert count == 2
        event_id = session.execute(text(
            "SELECT usage_event_id FROM billing.usage_event WHERE run_id=:run_id LIMIT 1"
        ), {"run_id": run_id}).scalar_one()
    with pytest.raises(Exception):
        with repository.database.session() as session:
            session.execute(text(
                "UPDATE billing.usage_event SET cost_micros=999 WHERE usage_event_id=:id"
            ), {"id": event_id})
~~~

prepared_echo_run fixture 复用 Task 9 的 echo 创建过程，返回 worker、context、run_id。Echo 和 End 都产生 UsageEvent，因此预期 2 条，其中 End cost_micros=0。

- [ ] **Step 3: 创建同事务 LedgerWriter**

~~~python
from __future__ import annotations

import json
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.platform.kernel.contracts import CapabilityResult, RequestContext


class PostgresLedgerWriter:
    def append_usage(
        self,
        session: Session,
        *,
        run_id: str,
        node_execution_id: str,
        capability_id: str | None,
        idempotency_key: str,
        result: CapabilityResult,
    ) -> None:
        session.execute(text(
            "INSERT INTO billing.usage_event("
            "usage_event_id,run_id,node_execution_id,capability_id,event_type,cost_micros,"
            "input_tokens,output_tokens,work_units_json,idempotency_key"
            ") VALUES (:id,:run,:node,:capability,'node_execution',:cost,:input,:output,"
            "CAST(:work AS jsonb),:key) ON CONFLICT (idempotency_key) DO NOTHING"
        ), {
            "id": str(uuid.uuid4()),
            "run": run_id,
            "node": node_execution_id,
            "capability": capability_id,
            "cost": result.actual_cost_micros,
            "input": result.input_tokens,
            "output": result.output_tokens,
            "work": json.dumps({}, separators=(",", ":")),
            "key": idempotency_key,
        })

    def append_audit(
        self,
        session: Session,
        context: RequestContext,
        *,
        action: str,
        object_type: str,
        object_id: str,
        result: str,
        payload: dict,
    ) -> None:
        session.execute(text(
            "INSERT INTO audit.audit_event("
            "audit_event_id,tenant_id,project_id,principal_id,action,object_type,object_id,"
            "result,payload_json,correlation_id"
            ") VALUES (:id,:tenant,:project,:principal,:action,:object_type,:object_id,"
            ":result,CAST(:payload AS jsonb),:correlation)"
        ), {
            "id": str(uuid.uuid4()),
            "tenant": context.tenant_id,
            "project": context.project_id,
            "principal": context.principal_id,
            "action": action,
            "object_type": object_type,
            "object_id": object_id,
            "result": result,
            "payload": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            "correlation": context.correlation_id,
        })
~~~

PostgresGraphRepository 构造函数创建 self.ledger = PostgresLedgerWriter()。Task 9 complete_node 中的直接 INSERT 替换为 self.ledger.append_usage，保证事务不拆开。

- [ ] **Step 4: 实现 Policy 证据和阻断终态**

~~~python
def record_policy(self, bundle: ExecutionBundle, result: PolicyResult) -> None:
    with self.database.session() as session:
        session.execute(text(
            "INSERT INTO policy.decision("
            "decision_id,run_id,node_execution_id,rule_version,decision,reason,evidence_json"
            ") VALUES (:id,:run,:node,'policy-v1',:decision,:reason,CAST(:evidence AS jsonb))"
        ), {
            "id": str(uuid.uuid4()),
            "run": bundle.claim.run_id,
            "node": bundle.claim.node_execution_id,
            "decision": (
                "allow" if result.allowed
                else "human_required" if result.requires_human_approval
                else "deny"
            ),
            "reason": result.reason_code,
            "evidence": canonical_json({
                "reserved_cost_micros": result.reserved_cost_micros,
                "requires_human_approval": result.requires_human_approval,
            }),
        })


def block_node(self, bundle: ExecutionBundle, reason_code: str) -> None:
    with self.database.session() as session:
        session.execute(text(
            "SELECT run_id FROM graph.run WHERE run_id=:run FOR UPDATE"
        ), {"run": bundle.claim.run_id})
        session.execute(text(
            "UPDATE graph.node_execution SET status='failed',error_code=:reason,finished_at=now() "
            "WHERE node_execution_id=:node"
        ), {"reason": reason_code, "node": bundle.claim.node_execution_id})
        session.execute(text(
            "UPDATE graph.run SET status='policy_blocked',finished_at=now(),updated_at=now(),"
            "version_no=version_no+1 WHERE run_id=:run"
        ), {"run": bundle.claim.run_id})
        self._append_event(session, bundle.claim.run_id, "policy_blocked", {
            "node_id": bundle.claim.node_id,
            "reason_code": reason_code,
        })


def exhaust_budget(
    self,
    bundle: ExecutionBundle,
    reason: str,
    result: CapabilityResult | None = None,
) -> None:
    spent = dict(bundle.spent)
    if result is not None:
        spent["steps"] = int(spent.get("steps", 0)) + 1
        spent["cost_micros"] = int(spent.get("cost_micros", 0)) + result.actual_cost_micros
        spent["tokens"] = (
            int(spent.get("tokens", 0)) + result.input_tokens + result.output_tokens
        )
    with self.database.session() as session:
        session.execute(text(
            "SELECT run_id FROM graph.run WHERE run_id=:run FOR UPDATE"
        ), {"run": bundle.claim.run_id})
        session.execute(text(
            "UPDATE graph.node_execution SET status='failed',error_code='budget_exhausted',"
            "error_detail=:reason,output_json=CAST(:output AS jsonb),cost_micros=:cost,"
            "finished_at=now(),lease_until=NULL WHERE node_execution_id=:node"
        ), {
            "reason": reason,
            "output": canonical_json(result.output) if result else "null",
            "cost": result.actual_cost_micros if result else 0,
            "node": bundle.claim.node_execution_id,
        })
        session.execute(text(
            "UPDATE graph.run SET status='budget_exhausted',spent_json=CAST(:spent AS jsonb),"
            "finished_at=now(),updated_at=now(),"
            "version_no=version_no+1 WHERE run_id=:run"
        ), {"run": bundle.claim.run_id, "spent": canonical_json(spent)})
        if result is not None:
            self.ledger.append_usage(
                session,
                run_id=bundle.claim.run_id,
                node_execution_id=bundle.claim.node_execution_id,
                capability_id=bundle.claim.capability_id,
                idempotency_key=bundle.claim.idempotency_key,
                result=result,
            )
        sequence = self._append_event(session, bundle.claim.run_id, "budget_exhausted", {
            "node_id": bundle.claim.node_id,
            "reason": reason,
        })
        self._checkpoint(session, bundle.claim.run_id, sequence, bundle.state)
~~~

- [ ] **Step 5: 实现 HumanTask**

open_human_task：

~~~python
def open_human_task(self, bundle: ExecutionBundle) -> None:
    with self.database.session() as session:
        session.execute(text(
            "SELECT run_id FROM graph.run WHERE run_id=:run FOR UPDATE"
        ), {"run": bundle.claim.run_id})
        task_id = str(uuid.uuid4())
        session.execute(text(
            "INSERT INTO policy.human_task("
            "task_id,run_id,node_execution_id,status,task_type,payload_json"
            ") VALUES (:id,:run,:node,'open',:type,CAST(:payload AS jsonb))"
        ), {
            "id": task_id,
            "run": bundle.claim.run_id,
            "node": bundle.claim.node_execution_id,
            "type": bundle.node.task_type,
            "payload": canonical_json(bundle.claim.input),
        })
        session.execute(text(
            "UPDATE graph.node_execution SET status='waiting_human',lease_until=NULL "
            "WHERE node_execution_id=:node"
        ), {"node": bundle.claim.node_execution_id})
        session.execute(text(
            "UPDATE graph.run SET status='waiting_human',suspended_at=now(),"
            "updated_at=now(),version_no=version_no+1 "
            "WHERE run_id=:run"
        ), {"run": bundle.claim.run_id})
        self._append_event(session, bundle.claim.run_id, "human_task_opened", {
            "task_id": task_id,
            "node_id": bundle.claim.node_id,
            "task_type": bundle.node.task_type,
        })
~~~

在 src/platform/data/repositories.py 增加返回类型：

~~~python
class HumanTaskRecord(Record):
    task_id: str
    run_id: str
    node_execution_id: str
    task_type: str
    status: str
    payload: dict[str, Any]
    decision: dict[str, Any] | None
~~~

`get_open_human_task` 与 `complete_human_task` 使用以下精确实现。它通过 human_task → run join 校验 tenant/project，在同一事务锁定 task 与 run；重放必须同时匹配 idempotency_key 和 decision_sha256：

~~~python
def _human_task_record(self, row) -> HumanTaskRecord:
    return HumanTaskRecord(
        task_id=row["task_id"],
        run_id=row["run_id"],
        node_execution_id=row["node_execution_id"],
        task_type=row["task_type"],
        status=row["status"],
        payload=row["payload_json"],
        decision=row["decision_json"],
    )


def get_open_human_task(
    self,
    context: RequestContext,
    run_id: str,
) -> HumanTaskRecord:
    with self.database.session() as session:
        row = session.execute(text(
            "SELECT ht.* FROM policy.human_task ht "
            "JOIN graph.run r ON r.run_id=ht.run_id "
            "WHERE ht.run_id=:run AND ht.status='open' "
            "AND r.tenant_id=:tenant AND r.project_id=:project"
        ), {
            "run": run_id,
            "tenant": context.tenant_id,
            "project": context.project_id,
        }).mappings().one()
    return self._human_task_record(row)


def complete_human_task(
    self,
    context: RequestContext,
    task_id: str,
    decision: dict,
    idempotency_key: str,
) -> HumanTaskRecord:
    decision_sha = sha256_json(decision)
    with self.database.session() as session:
        row = session.execute(text(
            "SELECT ht.*,r.state_json,r.budget_json,r.spent_json,r.status AS run_status,"
            "v.definition_json,n.node_id,n.idempotency_key AS node_idempotency_key "
            "FROM policy.human_task ht "
            "JOIN graph.run r ON r.run_id=ht.run_id "
            "JOIN graph.version v ON v.graph_version_id=r.graph_version_id "
            "JOIN graph.node_execution n ON n.node_execution_id=ht.node_execution_id "
            "WHERE ht.task_id=:task AND r.tenant_id=:tenant AND r.project_id=:project "
            "FOR UPDATE OF ht,r,n"
        ), {
            "task": task_id,
            "tenant": context.tenant_id,
            "project": context.project_id,
        }).mappings().one()

        if row["status"] == "completed":
            if (
                row["idempotency_key"] == idempotency_key
                and row["decision_sha256"] == decision_sha
            ):
                return self._human_task_record(row)
            raise ValueError("human decision already completed with different request")
        if row["status"] != "open" or row["run_status"] != "waiting_human":
            raise ValueError("human task is not open")

        graph = GraphDefinition.model_validate(row["definition_json"])
        node = next(item for item in graph.nodes if item.node_id == row["node_id"])
        result = CapabilityResult(output=decision, actual_cost_micros=0)
        next_state, next_spent = apply_capability_result(
            row["state_json"],
            node.node_id,
            result,
            row["spent_json"],
            row["budget_json"],
        )
        next_state["human"][node.node_id] = decision

        session.execute(text(
            "UPDATE policy.human_task SET status='completed',decision_json=CAST(:decision AS jsonb),"
            "decision_sha256=:sha,idempotency_key=:key,assignee_principal_id=:principal,"
            "completed_at=now() WHERE task_id=:task"
        ), {
            "decision": canonical_json(decision),
            "sha": decision_sha,
            "key": idempotency_key,
            "principal": context.principal_id,
            "task": task_id,
        })
        session.execute(text(
            "UPDATE graph.node_execution SET status='succeeded',output_json=CAST(:decision AS jsonb),"
            "finished_at=now() WHERE node_execution_id=:node AND status='waiting_human'"
        ), {
            "decision": canonical_json(decision),
            "node": row["node_execution_id"],
        })
        session.execute(text(
            "UPDATE graph.run SET status='running',state_json=CAST(:state AS jsonb),"
            "spent_json=CAST(:spent AS jsonb),"
            "deadline_at=deadline_at+(now()-suspended_at),suspended_at=NULL,"
            "updated_at=now(),version_no=version_no+1 "
            "WHERE run_id=:run"
        ), {
            "state": canonical_json(next_state),
            "spent": canonical_json(next_spent),
            "run": row["run_id"],
        })
        self.ledger.append_usage(
            session,
            run_id=row["run_id"],
            node_execution_id=row["node_execution_id"],
            capability_id=None,
            idempotency_key=row["node_idempotency_key"],
            result=result,
        )
        sequence = self._append_event(session, row["run_id"], "human_task_completed", {
            "task_id": task_id,
            "node_id": node.node_id,
            "decision_sha256": decision_sha,
        })
        self._checkpoint(session, row["run_id"], sequence, next_state)
        self.ledger.append_audit(
            session,
            context,
            action="human_task.complete",
            object_type="human_task",
            object_id=task_id,
            result="completed",
            payload={"run_id": row["run_id"], "decision_sha256": decision_sha},
        )
        next_node = next(item for item in graph.nodes if item.node_id == node.next_node)
        self._enqueue(session, row["run_id"], next_node, next_state)
        completed = dict(row)
        completed.update({
            "status": "completed",
            "decision_json": decision,
            "decision_sha256": decision_sha,
            "idempotency_key": idempotency_key,
        })
        return self._human_task_record(completed)
~~~

该文件同步导入 HumanTaskRecord、apply_capability_result。数据库唯一约束固定为 `(run_id, idempotency_key)`；不得使用跨租户全局唯一的人类可读键。

- [ ] **Step 6: 运行测试并提交**

~~~bash
APP_DATABASE_URL=postgresql+psycopg://<user>:<password>@127.0.0.1:55432/sku_graph_test XONSH_HISTORY_BACKEND=dummy PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/integration/test_human_task.py tests/integration/test_usage_ledger.py -q
git add src/platform/billing/ledger_repository.py src/platform/data/graph_repository.py src/platform/data/repositories.py tests/integration
git commit -m "feat(kernel): persist human checkpoints policy and usage"
~~~

Expected: HumanTask 完成后原 run_id 继续并完成；UsageEvent/PolicyDecision/AuditEvent 均不可修改。

## Task 11: 建立身份上下文和 FastAPI 控制面

**Files:**
- Create: src/platform/api/auth.py
- Create: src/platform/api/dependencies.py
- Create: src/platform/api/main.py
- Create: src/platform/api/routes/__init__.py
- Create: src/platform/api/routes/health.py
- Create: src/platform/api/routes/graphs.py
- Create: src/platform/api/routes/capabilities.py
- Create: src/platform/api/routes/runs.py
- Create: src/platform/api/routes/human_tasks.py
- Create: tests/integration/test_control_plane_api.py

- [ ] **Step 1: 写 API 安全和幂等测试**

~~~python
import uuid

from fastapi.testclient import TestClient


def auth(token: str, project_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Project-ID": project_id,
        "X-Correlation-ID": str(uuid.uuid4()),
    }


def test_health_is_public_but_graphs_require_auth(app):
    client = TestClient(app)
    assert client.get("/health/live").status_code == 200
    assert client.post("/api/graph/v1/definitions", json={}).status_code == 401


def test_create_publish_and_idempotent_run(app, bootstrap_identity, echo_graph_json):
    token, project_id = bootstrap_identity
    client = TestClient(app)
    draft = client.post(
        "/api/graph/v1/definitions",
        headers=auth(token, project_id),
        json=echo_graph_json,
    )
    assert draft.status_code == 201
    version_id = draft.json()["graph_version_id"]
    published = client.post(
        f"/api/graph/v1/versions/{version_id}/publish",
        headers=auth(token, project_id),
    )
    assert published.status_code == 200

    headers = auth(token, project_id) | {"Idempotency-Key": "api-run-1"}
    first = client.post(
        "/api/runs/v1",
        headers=headers,
        json={"graph_version_id": version_id, "input": {"message": "hello"}},
    )
    second = client.post(
        "/api/runs/v1",
        headers=headers,
        json={"graph_version_id": version_id, "input": {"message": "hello"}},
    )
    assert first.status_code == 202
    assert first.json()["run_id"] == second.json()["run_id"]


def test_project_scope_is_not_taken_from_request_body(app, two_project_identities):
    client = TestClient(app)
    first, second = two_project_identities
    response = client.get(
        f"/api/runs/v1/{first.run_id}",
        headers=auth(second.token, second.project_id),
    )
    assert response.status_code == 404
~~~

- [ ] **Step 2: 运行并确认失败**

~~~bash
APP_DATABASE_URL=postgresql+psycopg://<user>:<password>@127.0.0.1:55432/sku_graph_test APP_BOOTSTRAP_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx XONSH_HISTORY_BACKEND=dummy PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/integration/test_control_plane_api.py -q
~~~

Expected: FAIL，control_plane app/routes/auth 尚不存在。

- [ ] **Step 3: 实现 AuthService**

~~~python
from __future__ import annotations

import hashlib
import secrets
import uuid

from sqlalchemy import text

from src.platform.kernel.contracts import RequestContext
from src.platform.data.database import Database


class AuthenticationError(ValueError):
    """Bearer token or project grant could not be resolved."""


class AuthService:
    def __init__(self, database: Database):
        self.database = database

    @staticmethod
    def token_sha256(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def resolve(
        self,
        bearer_token: str,
        project_id: str,
        correlation_id: str | None,
    ) -> RequestContext:
        digest = self.token_sha256(bearer_token)
        with self.database.session() as session:
            principal = session.execute(text(
                "SELECT p.principal_id,p.tenant_id,pr.customer_id "
                "FROM iam.principal p JOIN iam.project pr ON pr.tenant_id=p.tenant_id "
                "WHERE p.token_sha256=:digest AND p.active=true AND pr.project_id=:project"
            ), {"digest": digest, "project": project_id}).mappings().one_or_none()
            if principal is None:
                raise AuthenticationError("invalid token or project")
            scopes = session.execute(text(
                "SELECT scope FROM iam.principal_grant "
                "WHERE principal_id=:principal AND project_id=:project AND tenant_id=:tenant"
            ), {
                "principal": principal["principal_id"],
                "project": project_id,
                "tenant": principal["tenant_id"],
            }).scalars().all()
        if not scopes:
            raise AuthenticationError("no project grant")
        return RequestContext(
            principal_id=principal["principal_id"],
            tenant_id=principal["tenant_id"],
            customer_id=principal["customer_id"],
            project_id=project_id,
            scopes=frozenset(scopes),
            correlation_id=correlation_id or str(uuid.uuid4()),
        )


def extract_bearer(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise AuthenticationError("bearer token required")
    token = authorization[7:]
    if len(token) < 32 or not secrets.compare_digest(token, token.strip()):
        raise AuthenticationError("invalid bearer token")
    return token
~~~

租户、客户和项目来自数据库 join，不接受 body 中的 tenant_id/customer_id。

- [ ] **Step 4: 装配 FastAPI 依赖**

src/platform/api/dependencies.py：

~~~python
from functools import lru_cache

from fastapi import Header, HTTPException

from src.platform.api.auth import AuthService, AuthenticationError, extract_bearer
from src.platform.api.settings import ControlPlaneSettings
from src.modules.reference_echo.capability import EchoCapability
from src.platform.kernel.contracts import (
    CapabilityDefinition,
    CapabilityEffect,
    RequestContext,
)
from src.platform.kernel.policy import PolicyEngine
from src.platform.modules.capability_registry import CapabilityRegistry
from src.platform.data.database import create_database
from src.platform.data.graph_repository import PostgresGraphRepository


@lru_cache
def settings() -> ControlPlaneSettings:
    return ControlPlaneSettings()


@lru_cache
def repository() -> PostgresGraphRepository:
    return PostgresGraphRepository(create_database(settings().app_database_url))


@lru_cache
def registry() -> CapabilityRegistry:
    result = CapabilityRegistry({"core.echo": EchoCapability()})
    result.register(CapabilityDefinition(
        capability_id="core.echo",
        version="1.0.0",
        name="Echo",
        effect=CapabilityEffect.READ_ONLY,
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        required_scopes=["capability:echo"],
        timeout_seconds=5,
        max_attempts=1,
        fixed_cost_micros=10,
        handler_key="core.echo",
    ))
    return result


@lru_cache
def policy() -> PolicyEngine:
    return PolicyEngine()


def request_context(
    authorization: str | None = Header(default=None),
    x_project_id: str = Header(alias="X-Project-ID"),
    x_correlation_id: str | None = Header(default=None, alias="X-Correlation-ID"),
) -> RequestContext:
    try:
        token = extract_bearer(authorization)
        return AuthService(repository().database).resolve(
            token,
            x_project_id,
            x_correlation_id,
        )
    except AuthenticationError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
~~~

- [ ] **Step 5: 创建 health 与 Graph 路由**

health.py：

~~~python
from fastapi import APIRouter
from sqlalchemy import text

from src.platform.api.dependencies import registry, repository


router = APIRouter()


@router.get("/health/live")
def live():
    return {"ok": True, "service": "graph-control-plane"}


@router.get("/health/ready")
def ready():
    with repository().database.session() as session:
        session.execute(text("SELECT 1"))
    return {
        "ok": True,
        "database": "ready",
        "capabilities": len(registry().list()),
    }
~~~

graphs.py：

~~~python
from fastapi import APIRouter, Depends, HTTPException, status

from src.platform.api.dependencies import repository, request_context
from src.platform.kernel.contracts import GraphDefinition, RequestContext


router = APIRouter(prefix="/api/graph/v1")


@router.post("/definitions", status_code=status.HTTP_201_CREATED)
def create_definition(
    definition: GraphDefinition,
    context: RequestContext = Depends(request_context),
):
    if "graph:write" not in context.scopes:
        raise HTTPException(status_code=403, detail="graph:write required")
    return repository().create_draft_version(context, definition).model_dump(mode="json")


@router.post("/versions/{graph_version_id}/publish")
def publish(
    graph_version_id: str,
    context: RequestContext = Depends(request_context),
):
    if "graph:publish" not in context.scopes:
        raise HTTPException(status_code=403, detail="graph:publish required")
    try:
        return repository().publish_version(context, graph_version_id).model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
~~~

- [ ] **Step 6: 创建 Capability、Run 与 HumanTask 路由**

capabilities.py：

~~~python
from fastapi import APIRouter, Depends

from src.platform.api.dependencies import registry, request_context
from src.platform.kernel.contracts import RequestContext


router = APIRouter(prefix="/api/capabilities/v1")


@router.get("")
def list_capabilities(context: RequestContext = Depends(request_context)):
    visible = [
        item.model_dump(mode="json")
        for item in registry().list()
        if set(item.required_scopes).issubset(context.scopes)
    ]
    return {"items": visible}
~~~

runs.py：

~~~python
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict

from src.platform.api.dependencies import repository, request_context
from src.platform.kernel.contracts import RequestContext


class CreateRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    graph_version_id: str
    input: dict[str, Any]


router = APIRouter(prefix="/api/runs/v1")


@router.post("", status_code=status.HTTP_202_ACCEPTED)
def create_run(
    body: CreateRunRequest,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    context: RequestContext = Depends(request_context),
):
    if "run:create" not in context.scopes:
        raise HTTPException(status_code=403, detail="run:create required")
    try:
        run = repository().create_run(
            context,
            body.graph_version_id,
            body.input,
            idempotency_key,
        )
        repository().start_run(context, run.run_id)
        return {"run_id": run.run_id, "status": "running"}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{run_id}")
def get_run(run_id: str, context: RequestContext = Depends(request_context)):
    run = repository().get_run(context, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return repository().get_run_detail(context, run_id)


@router.post("/{run_id}/pause")
def pause(run_id: str, context: RequestContext = Depends(request_context)):
    if "run:control" not in context.scopes:
        raise HTTPException(status_code=403, detail="run:control required")
    try:
        return repository().pause_run(context, run_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{run_id}/resume")
def resume(run_id: str, context: RequestContext = Depends(request_context)):
    if "run:control" not in context.scopes:
        raise HTTPException(status_code=403, detail="run:control required")
    try:
        return repository().resume_run(context, run_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{run_id}/cancel")
def cancel(run_id: str, context: RequestContext = Depends(request_context)):
    if "run:control" not in context.scopes:
        raise HTTPException(status_code=403, detail="run:control required")
    try:
        return repository().cancel_run(context, run_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
~~~

human_tasks.py：

~~~python
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict

from src.platform.api.dependencies import repository, request_context
from src.platform.kernel.contracts import RequestContext


class CompleteHumanTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: dict[str, Any]


router = APIRouter(prefix="/api/human-tasks/v1")


@router.get("")
def list_open(context: RequestContext = Depends(request_context)):
    if "human:read" not in context.scopes:
        raise HTTPException(status_code=403, detail="human:read required")
    return {"items": repository().list_open_human_tasks(context)}


@router.post("/{task_id}/complete")
def complete(
    task_id: str,
    body: CompleteHumanTaskRequest,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    context: RequestContext = Depends(request_context),
):
    if "human:complete" not in context.scopes:
        raise HTTPException(status_code=403, detail="human:complete required")
    try:
        return repository().complete_human_task(
            context,
            task_id,
            body.decision,
            idempotency_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
~~~

- [ ] **Step 7: 创建 App 工厂**

~~~python
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.platform.api.dependencies import repository, settings
from src.platform.api.routes import capabilities, graphs, health, human_tasks, runs


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not settings().graph_kernel_enabled:
        raise RuntimeError("GRAPH_KERNEL_ENABLED must be true to start control plane")
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Graph+Loop Control Plane",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(health.router)
    app.include_router(graphs.router)
    app.include_router(capabilities.router)
    app.include_router(runs.router)
    app.include_router(human_tasks.router)
    return app


app = create_app()
~~~

Repository 使用以下四个独立方法，不接受万能 `update_status`。Stage 1 的 pause 只在没有 leased/running 节点时成功；这样不会出现“外部调用已完成但无法提交”的半状态。调用方遇到 `in-flight node prevents pause` 时等待该节点完成后重试：

~~~python
def get_run_detail(self, context: RequestContext, run_id: str) -> dict:
    with self.database.session() as session:
        run = session.execute(text(
            "SELECT * FROM graph.run WHERE run_id=:run AND tenant_id=:tenant AND project_id=:project"
        ), {
            "run": run_id,
            "tenant": context.tenant_id,
            "project": context.project_id,
        }).mappings().one_or_none()
        if run is None:
            raise ValueError("run not found")
        nodes = session.execute(text(
            "SELECT * FROM graph.node_execution WHERE run_id=:run ORDER BY created_at,node_execution_id"
        ), {"run": run_id}).mappings().all()
        events = session.execute(text(
            "SELECT * FROM graph.run_event WHERE run_id=:run ORDER BY sequence_no"
        ), {"run": run_id}).mappings().all()
        checkpoint = session.execute(text(
            "SELECT * FROM graph.checkpoint WHERE run_id=:run ORDER BY sequence_no DESC LIMIT 1"
        ), {"run": run_id}).mappings().one_or_none()
    run_payload = dict(run)
    run_payload["input"] = run_payload.pop("input_json")
    run_payload["state"] = run_payload.pop("state_json")
    run_payload["budget"] = run_payload.pop("budget_json")
    run_payload["spent"] = run_payload.pop("spent_json")
    return {
        **run_payload,
        "node_executions": [dict(item) for item in nodes],
        "events": [dict(item) for item in events],
        "latest_checkpoint": dict(checkpoint) if checkpoint else None,
    }


def pause_run(self, context: RequestContext, run_id: str) -> dict:
    with self.database.session() as session:
        run = session.execute(text(
            "SELECT status FROM graph.run WHERE run_id=:run AND tenant_id=:tenant "
            "AND project_id=:project FOR UPDATE"
        ), {
            "run": run_id,
            "tenant": context.tenant_id,
            "project": context.project_id,
        }).mappings().one_or_none()
        if run is None:
            raise ValueError("run not found")
        if run["status"] != "running":
            raise ValueError(f"run cannot pause from {run['status']}")
        in_flight = session.execute(text(
            "SELECT count(*) FROM graph.node_execution "
            "WHERE run_id=:run AND status IN ('leased','running')"
        ), {"run": run_id}).scalar_one()
        if in_flight:
            raise ValueError("in-flight node prevents pause")
        session.execute(text(
            "UPDATE graph.run SET status='paused',suspended_at=now(),"
            "updated_at=now(),version_no=version_no+1 "
            "WHERE run_id=:run"
        ), {"run": run_id})
        self._append_event(session, run_id, "run_paused", {})
        self.ledger.append_audit(
            session, context, action="run.pause", object_type="run",
            object_id=run_id, result="paused", payload={},
        )
    return {"run_id": run_id, "status": "paused"}


def resume_run(self, context: RequestContext, run_id: str) -> dict:
    with self.database.session() as session:
        changed = session.execute(text(
            "UPDATE graph.run SET status='running',deadline_at=deadline_at+(now()-suspended_at),"
            "suspended_at=NULL,updated_at=now(),version_no=version_no+1 "
            "WHERE run_id=:run AND tenant_id=:tenant AND project_id=:project AND status='paused'"
        ), {
            "run": run_id,
            "tenant": context.tenant_id,
            "project": context.project_id,
        }).rowcount
        if changed != 1:
            raise ValueError("paused run not found")
        self._append_event(session, run_id, "run_resumed", {})
        self.ledger.append_audit(
            session, context, action="run.resume", object_type="run",
            object_id=run_id, result="running", payload={},
        )
    return {"run_id": run_id, "status": "running"}


def cancel_run(self, context: RequestContext, run_id: str) -> dict:
    terminal = (
        "completed", "failed", "cancelled", "budget_exhausted", "policy_blocked"
    )
    with self.database.session() as session:
        run = session.execute(text(
            "SELECT status FROM graph.run WHERE run_id=:run AND tenant_id=:tenant "
            "AND project_id=:project FOR UPDATE"
        ), {
            "run": run_id,
            "tenant": context.tenant_id,
            "project": context.project_id,
        }).mappings().one_or_none()
        if run is None:
            raise ValueError("run not found")
        if run["status"] in terminal:
            raise ValueError(f"run cannot cancel from {run['status']}")
        session.execute(text(
            "UPDATE graph.run SET status='cancelled',finished_at=now(),updated_at=now(),"
            "version_no=version_no+1 WHERE run_id=:run"
        ), {"run": run_id})
        session.execute(text(
            "UPDATE graph.node_execution SET status='cancelled',finished_at=now(),lease_until=NULL "
            "WHERE run_id=:run AND status IN ('queued','leased','running','waiting_human')"
        ), {"run": run_id})
        session.execute(text(
            "UPDATE policy.human_task SET status='cancelled',completed_at=now() "
            "WHERE run_id=:run AND status='open'"
        ), {"run": run_id})
        self._append_event(session, run_id, "run_cancelled", {})
        self.ledger.append_audit(
            session, context, action="run.cancel", object_type="run",
            object_id=run_id, result="cancelled", payload={},
        )
    return {"run_id": run_id, "status": "cancelled"}


def list_open_human_tasks(self, context: RequestContext) -> list[dict]:
    with self.database.session() as session:
        rows = session.execute(text(
            "SELECT ht.* FROM policy.human_task ht "
            "JOIN graph.run r ON r.run_id=ht.run_id "
            "WHERE ht.status='open' AND r.tenant_id=:tenant AND r.project_id=:project "
            "ORDER BY ht.created_at,ht.task_id"
        ), {
            "tenant": context.tenant_id,
            "project": context.project_id,
        }).mappings().all()
    return [self._human_task_record(row).model_dump(mode="json") for row in rows]
~~~

为 pause、resume、cancel 各写一个集成测试：分别断言非法前置状态返回冲突、resume 不重复 enqueue、cancel 只追加记录且不删除任何 Node/HumanTask。跨项目对以上四个方法一律表现为 not found。

- [ ] **Step 8: 生成 OpenAPI、测试并提交**

扩展 scripts/export_contracts.py：

~~~python
from src.platform.api.main import create_app

write_json(
    ROOT / "contracts/openapi/control-plane-v1.json",
    create_app().openapi(),
)
~~~

write_json 与 write_schema 相同，使用 sort_keys=True 和结尾换行。

~~~bash
APP_DATABASE_URL=postgresql+psycopg://<user>:<password>@127.0.0.1:55432/sku_graph_test APP_BOOTSTRAP_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx GRAPH_KERNEL_ENABLED=true python3 scripts/export_contracts.py
APP_DATABASE_URL=postgresql+psycopg://<user>:<password>@127.0.0.1:55432/sku_graph_test APP_BOOTSTRAP_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx GRAPH_KERNEL_ENABLED=true XONSH_HISTORY_BACKEND=dummy PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/integration/test_control_plane_api.py -q
git add src/platform/api scripts/export_contracts.py contracts/openapi tests/integration/test_control_plane_api.py
git commit -m "feat(kernel): expose authenticated graph control plane api"
~~~

Expected: 所有 API 测试通过；OpenAPI 再生成无 diff；无 token 返回 401，跨项目返回 404。

## Task 12: 接入最小非识别 Graph 和识别 Capability

**Files:**
- Create: src/modules/reference_echo/graphs/echo-v1.json
- Create: src/modules/fmcg_vision/graphs/minimal-recognition-v1.json
- Create: src/modules/fmcg_vision/adapters/legacy_recognition.py
- Modify: src/platform/api/dependencies.py
- Modify: src/recognize/service.py
- Modify: src/data/warehouse.py
- Modify: migrations/sqlite/001_schema.sql
- Modify: migrations/postgres/001_schema.sql
- Create: tests/unit/platform/kernel/test_recognition_capability.py
- Create: tests/unit/test_recognition_request_id.py
- Create: tests/unit/test_audit_outbox_evidence.py

- [ ] **Step 1: 创建两份发布前 Graph 配置**

src/modules/reference_echo/graphs/echo-v1.json：

~~~json
{
  "schema_version": "1.0",
  "graph_id": "core.echo",
  "name": "Non-vision echo validation",
  "description": "证明 Graph Runtime 不包含 FMCG 特例",
  "start_node": "echo",
  "input_schema": {"type": "object", "required": ["message"]},
  "output_schema": {"type": "object"},
  "budget": {
    "max_steps": 4,
    "max_wall_seconds": 30,
    "max_cost_micros": 1000,
    "max_tokens": 0
  },
  "required_scopes": ["capability:echo"],
  "nodes": [
    {
      "node_id": "echo",
      "kind": "capability",
      "capability": {"capability_id": "core.echo", "version": "1.0.0"},
      "next_node": "done"
    },
    {"node_id": "done", "kind": "end"}
  ]
}
~~~

src/modules/fmcg_vision/graphs/minimal-recognition-v1.json：

~~~json
{
  "schema_version": "1.0",
  "graph_id": "fmcg.recognition.min",
  "name": "Minimal FMCG recognition",
  "description": "单图识别并在不确定时暂停人工",
  "start_node": "recognize",
  "input_schema": {
    "type": "object",
    "oneOf": [
      {"required": ["asset_id"]},
      {"required": ["image_base64"]}
    ]
  },
  "output_schema": {"type": "object"},
  "budget": {
    "max_steps": 8,
    "max_wall_seconds": 300,
    "max_cost_micros": 100000,
    "max_tokens": 0
  },
  "required_scopes": ["capability:recognize"],
  "nodes": [
    {
      "node_id": "recognize",
      "kind": "capability",
      "capability": {"capability_id": "vision.recognize", "version": "1.0.0"},
      "next_node": "needs_review"
    },
    {
      "node_id": "needs_review",
      "kind": "decision",
      "condition": {
        "path": "$.nodes.recognize.output.needs_review",
        "operator": "eq",
        "value": true
      },
      "true_node": "human_review",
      "false_node": "done"
    },
    {
      "node_id": "human_review",
      "kind": "human",
      "task_type": "recognition_review",
      "next_node": "done"
    },
    {"node_id": "done", "kind": "end"}
  ]
}
~~~

- [ ] **Step 2: 写 RecognitionCapability 测试**

~~~python
import httpx

from src.modules.fmcg_vision.adapters.legacy_recognition import RecognitionCapability
from src.platform.kernel.contracts import CapabilityExecutionContext, RequestContext


def test_recognition_forwards_stable_request_id():
    captured = {}

    def handler(request: httpx.Request):
        captured["json"] = __import__("json").loads(request.content)
        return httpx.Response(200, json={
            "run_id": captured["json"]["request_id"],
            "products": [{"sku_id": "sku_1", "needs_review": False}],
            "count": 1,
            "elapsed_ms": 5,
            "audit_written": True,
        })

    capability = RecognitionCapability(
        base_url="http://recognize.test",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    context = CapabilityExecutionContext(
        request=RequestContext(
            principal_id="p",
            tenant_id="t",
            customer_id="c",
            project_id="pr",
            scopes=frozenset({"capability:recognize"}),
            correlation_id="corr",
        ),
        run_id="run",
        node_execution_id="node",
        idempotency_key="stable-request-id",
        timeout_seconds=30,
    )
    result = capability.execute(context, {"asset_id": "asset_1"})
    assert captured["json"]["request_id"] == "stable-request-id"
    assert result.output["needs_review"] is False
~~~

- [ ] **Step 3: 实现 RecognitionCapability**

~~~python
from __future__ import annotations

import httpx

from src.platform.kernel.contracts import CapabilityExecutionContext, CapabilityResult


class RecognitionCapability:
    def __init__(
        self,
        base_url: str,
        client: httpx.Client | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.client = client or httpx.Client(base_url=self.base_url)

    def execute(
        self,
        context: CapabilityExecutionContext,
        payload: dict,
    ) -> CapabilityResult:
        request = {
            key: payload[key]
            for key in ("asset_id", "image_base64", "conf")
            if key in payload
        }
        if ("asset_id" in request) == ("image_base64" in request):
            raise ValueError("exactly one of asset_id/image_base64 is required")
        request["request_id"] = context.idempotency_key
        response = self.client.post(
            "/v2/recognize",
            json=request,
            headers={"X-Correlation-ID": context.request.correlation_id},
            timeout=context.timeout_seconds,
        )
        if response.status_code == 429:
            raise RuntimeError("RECOGNITION_OVERLOADED")
        if response.status_code >= 500:
            raise RuntimeError("RECOGNITION_UNAVAILABLE")
        response.raise_for_status()
        body = response.json()
        products = body.get("products", [])
        needs_review = any(
            item.get("needs_review") is True
            or item.get("status") == "needs_review"
            for item in products
        )
        return CapabilityResult(
            output={
                "legacy_run_id": body["run_id"],
                "products": products,
                "count": body.get("count", len(products)),
                "needs_review": needs_review,
                "audit_written": body.get("audit_written", False),
            },
            actual_cost_micros=1000,
            evidence_refs=[f"legacy-recognition:{body['run_id']}"],
        )
~~~

- [ ] **Step 4: 让旧识别服务支持稳定 request_id**

在 src/recognize/service.py 增加稳定 ID、请求指纹与已存在结果读取。指纹基于解码后的图片字节和 conf，因此同一图片从 asset_id 或 base64 进入仍可识别为同一请求：

~~~python
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


class RecognitionIdempotencyConflict(ValueError):
    """A stable recognition request id was reused for different input."""


def normalize_request_id(value) -> str:
    if value is None:
        return str(uuid.uuid4())
    value = str(value).strip()
    if not _SAFE_REQUEST_ID.fullmatch(value):
        raise ValueError("invalid request_id")
    return value


def recognition_request_sha(image_bytes: bytes, conf: float) -> str:
    payload = json.dumps({
        "image_sha256": hashlib.sha256(image_bytes).hexdigest(),
        "conf": conf,
    }, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _decode_model_versions(value) -> dict:
    if isinstance(value, str):
        return json.loads(value or "{}")
    return dict(value or {})


def _decode_products(value) -> list:
    if isinstance(value, str):
        return json.loads(value or "[]")
    return list(value or [])


def _load_existing_recognition(run_id: str) -> dict | None:
    conn = wh.connect()
    wh.migrate(conn)
    main = conn.execute(
        "SELECT asset_id,model_versions,decisions_json FROM recognition_run WHERE run_id=?",
        (run_id,),
    ).fetchone()
    if main:
        model_versions = _decode_model_versions(main["model_versions"])
        result = {
            "source": "recognition_run",
            "asset_id": main["asset_id"],
            "request_sha256": model_versions.get("_extra", {}).get("request_sha256"),
            "products": _decode_products(main["decisions_json"]),
        }
        conn.close()
        return result
    pending = conn.execute(
        "SELECT asset_id,payload_json,delivery_status FROM audit_outbox WHERE run_id=?",
        (run_id,),
    ).fetchone()
    conn.close()
    if pending is None:
        return None
    payload = json.loads(pending["payload_json"])
    model_versions = _decode_model_versions(payload["model_versions"])
    return {
        "source": "audit_outbox",
        "asset_id": pending["asset_id"],
        "request_sha256": model_versions.get("_extra", {}).get("request_sha256"),
        "products": _decode_products(payload["products"]),
        "delivery_status": pending["delivery_status"],
    }
~~~

补 import hashlib、re。Handler.do_POST 的 /v2/recognize 分支在解码图片和读取 conf 后、推理前执行：

~~~python
try:
    run_id = normalize_request_id(req.get("request_id"))
except ValueError:
    return self._send(400, '{"error":"invalid request_id"}')

request_sha = recognition_request_sha(img_bytes, conf)
existing = _load_existing_recognition(run_id)
if existing is not None:
    if existing["request_sha256"] != request_sha:
        return self._send(409, '{"error":"request_id_conflict"}')
    products = existing["products"]
    return self._send(200, json.dumps({
        "run_id": run_id,
        "products": products,
        "count": len(products),
        "elapsed_ms": 0,
        "audit_written": existing["source"] == "recognition_run",
        "audit_pending": existing["source"] == "audit_outbox",
        "idempotent_replay": True,
    }, ensure_ascii=False))
~~~

替换当前无条件 uuid.uuid4。首次推理写审计时必须传入 `extra={"request_sha256": request_sha}`。_write_audit 在 INSERT 前执行并且冲突异常位于通用失败/outbox catch 之外：

~~~python
existing = _load_existing_recognition(run_id)
if existing is not None:
    expected_sha = (extra or {}).get("request_sha256")
    same = (
        existing["request_sha256"] == expected_sha
        and existing["products"] == products
    )
    if not same:
        raise RecognitionIdempotencyConflict(
            "request_id reused with different recognition payload"
        )
    return existing["source"] == "recognition_run"
~~~

Handler 捕获 RecognitionIdempotencyConflict 并返回 409。audit_outbox 禁止 INSERT OR REPLACE，改为 INSERT OR IGNORE；若 rowcount=0，重新读取并比较指纹/结果，不同则抛冲突，绝不覆盖历史证据。

outbox 本次同时修复“成功重放即 DELETE”的证据链缺口。SQLite/PostgreSQL 的 audit_outbox 增加：

~~~sql
delivery_status TEXT NOT NULL DEFAULT 'pending'
    CHECK(delivery_status IN ('pending','delivered','dead')),
delivered_at REAL
~~~

PostgreSQL 的 delivered_at 使用 DOUBLE PRECISION，与该 legacy 表现有 epoch 时间保持兼容。warehouse.migrate 在 SQLite 通过 `PRAGMA table_info(audit_outbox)` 检测旧库，缺列时逐列 ALTER TABLE；不得重建或清空表。_replay_outbox_once 只读取 delivery_status='pending'：

- 成功时 UPDATE delivery_status='delivered'、delivered_at、last_try，保留完整 payload；
- 失败时更新 attempts/last_try；达到 20 次改为 dead，仍保留；
- recognition_run 已存在时先比较 request_sha256/products，一致才标 delivered，不一致标 dead 并输出审计告警；
- 任何路径都不得 DELETE audit_outbox。

新增 SQLite 迁移测试：先创建旧版 audit_outbox，再调用 wh.migrate，断言两列被追加、原记录仍在；重放成功后断言 outbox 记录仍在且 delivery_status=delivered。

- [ ] **Step 5: 写旧服务幂等测试**

~~~python
import pytest


def test_write_audit_is_idempotent(tmp_path, monkeypatch):
    from src.data import warehouse as wh
    from src.recognize import service

    monkeypatch.setattr(wh, "DB", tmp_path / "audit.sqlite")
    payload = [{"sku_id": "sku_1", "confidence": 0.9}]
    assert service._write_audit("stable-id", "asset", {"detector": "v4"}, payload)
    assert service._write_audit("stable-id", "asset", {"detector": "v4"}, payload)
    conn = wh.connect()
    count = conn.execute(
        "SELECT count(*) FROM recognition_run WHERE run_id='stable-id'"
    ).fetchone()[0]
    conn.close()
    assert count == 1


def test_write_audit_rejects_same_id_with_different_result(tmp_path, monkeypatch):
    from src.data import warehouse as wh
    from src.recognize import service

    monkeypatch.setattr(wh, "DB", tmp_path / "audit-conflict.sqlite")
    assert service._write_audit(
        "stable-id",
        "asset",
        {"detector": "v4"},
        [{"sku_id": "sku_1"}],
        extra={"request_sha256": "a" * 64},
    )
    with pytest.raises(service.RecognitionIdempotencyConflict):
        service._write_audit(
            "stable-id",
            "asset",
            {"detector": "v4"},
            [{"sku_id": "sku_2"}],
            extra={"request_sha256": "b" * 64},
        )
~~~

- [ ] **Step 6: 注册识别能力**

dependencies.registry 增加 handler allowlist 和定义：

~~~python
recognition = RecognitionCapability(settings().recognize_v2_url)
result = CapabilityRegistry({
    "core.echo": EchoCapability(),
    "vision.recognize": recognition,
})
result.register(CapabilityDefinition(
    capability_id="vision.recognize",
    version="1.0.0",
    name="Legacy cascade recognition adapter",
    effect=CapabilityEffect.SYSTEM_WRITE,
    input_schema={"type": "object"},
    output_schema={"type": "object"},
    required_scopes=["capability:recognize"],
    timeout_seconds=30,
    max_attempts=3,
    fixed_cost_micros=1000,
    handler_key="vision.recognize",
))
~~~

- [ ] **Step 7: 测试、校验 Graph 并提交**

~~~bash
XONSH_HISTORY_BACKEND=dummy PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/unit/platform/kernel/test_recognition_capability.py tests/unit/test_recognition_request_id.py tests/unit/test_audit_outbox_evidence.py -q
python3 -c "import json; from src.platform.kernel.contracts import GraphDefinition; from src.platform.kernel.validation import validate_graph; [validate_graph(GraphDefinition.model_validate(json.load(open(p)))) for p in ['src/modules/reference_echo/graphs/echo-v1.json','src/modules/fmcg_vision/graphs/minimal-recognition-v1.json']]"
git add src/modules/reference_echo/graphs/echo-v1.json src/modules/fmcg_vision/graphs/minimal-recognition-v1.json src/modules/fmcg_vision/adapters/legacy_recognition.py src/platform/api/dependencies.py src/recognize/service.py src/data/warehouse.py migrations/sqlite/001_schema.sql migrations/postgres/001_schema.sql tests/unit
git commit -m "feat(kernel): adapt recognition as an idempotent capability"
~~~

Expected: 两份 Graph 校验通过；相同节点重试不会新增 recognition_run。

## Task 13: 建立最小 React 智能工作台

**Files:**
- Create: web/package.json
- Create: web/tsconfig.json
- Create: web/vite.config.ts
- Create: web/index.html
- Create: web/src/main.tsx
- Create: web/src/test-setup.ts
- Create: web/src/platform/App.tsx
- Create: web/src/platform/types.ts
- Create: web/src/platform/api/client.ts
- Create: web/src/platform/features/runs/RunLauncher.tsx
- Create: web/src/platform/features/runs/RunTimeline.tsx
- Create: web/src/platform/features/tasks/HumanTaskPanel.tsx
- Create: web/src/platform/features/capabilities/CapabilityCatalog.tsx
- Create: web/src/platform/styles.css
- Create: web/src/platform/features/runs/RunLauncher.test.tsx
- Create: web/src/platform/features/runs/RunTimeline.test.tsx
- Modify: src/platform/api/routes/graphs.py
- Modify: src/platform/data/graph_repository.py

- [ ] **Step 1: 创建前端工具链**

web/package.json：

~~~json
{
  "name": "graph-loop-workbench",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "test": "vitest run",
    "lint": "tsc --noEmit"
  },
  "dependencies": {
    "react": "^19.1.0",
    "react-dom": "^19.1.0"
  },
  "devDependencies": {
    "@vitejs/plugin-react": "^4.5.2",
    "@testing-library/jest-dom": "^6.6.3",
    "@testing-library/react": "^16.3.0",
    "@types/react": "^19.1.8",
    "@types/react-dom": "^19.1.6",
    "jsdom": "^26.1.0",
    "typescript": "^5.8.3",
    "vite": "^7.0.0",
    "vitest": "^3.2.4"
  }
}
~~~

vite.config.ts：

~~~typescript
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 8410,
    proxy: {"/api": "http://127.0.0.1:8400", "/health": "http://127.0.0.1:8400"}
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test-setup.ts"
  }
});
~~~

tsconfig.json：

~~~json
{
  "compilerOptions": {
    "target": "ES2022",
    "useDefineForClassFields": true,
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "allowJs": false,
    "skipLibCheck": true,
    "esModuleInterop": true,
    "allowSyntheticDefaultImports": true,
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "forceConsistentCasingInFileNames": true,
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "types": ["vitest/globals"]
  },
  "include": ["src", "vite.config.ts"]
}
~~~

web/src/test-setup.ts：

~~~typescript
import "@testing-library/jest-dom/vitest";
~~~

- [ ] **Step 2: 固定前端类型与 API client**

~~~typescript
export type RunStatus =
  | "created" | "ready" | "running" | "waiting_human" | "paused"
  | "completed" | "failed" | "cancelled" | "budget_exhausted" | "policy_blocked";

export interface GraphVersion {
  graph_version_id: string;
  graph_id: string;
  version_no: number;
  status: "draft" | "published" | "retired";
  definition: {name: string; description: string};
}

export interface NodeExecution {
  node_execution_id: string;
  node_id: string;
  iteration: number;
  attempt_no: number;
  status: string;
  cost_micros: number;
  error_code?: string | null;
}

export interface RunDetail {
  run_id: string;
  status: RunStatus;
  graph_version_id: string;
  spent: {steps: number; cost_micros: number; tokens: number};
  node_executions: NodeExecution[];
  events: Array<{sequence_no: number; event_type: string; created_at: string}>;
}

export interface HumanTask {
  task_id: string;
  run_id: string;
  task_type: string;
  payload: Record<string, unknown>;
  status: "open" | "completed" | "cancelled";
}
~~~

~~~typescript
export class ApiClient {
  constructor(
    private readonly token: string,
    private readonly projectId: string
  ) {}

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const response = await fetch(path, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + this.token,
        "X-Project-ID": this.projectId,
        "X-Correlation-ID": crypto.randomUUID(),
        ...(init.headers ?? {})
      }
    });
    if (!response.ok) {
      throw new Error((await response.text()) || "HTTP " + response.status);
    }
    return response.json() as Promise<T>;
  }

  listGraphs() {
    return this.request<{items: import("../types").GraphVersion[]}>(
      "/api/graph/v1/versions?status=published"
    );
  }

  listCapabilities() {
    return this.request<{items: Array<Record<string, unknown>>}>("/api/capabilities/v1");
  }

  createRun(graphVersionId: string, input: Record<string, unknown>) {
    return this.request<{run_id: string; status: string}>("/api/runs/v1", {
      method: "POST",
      headers: {"Idempotency-Key": crypto.randomUUID()},
      body: JSON.stringify({graph_version_id: graphVersionId, input})
    });
  }

  getRun(runId: string) {
    return this.request<import("../types").RunDetail>("/api/runs/v1/" + runId);
  }

  listHumanTasks() {
    return this.request<{items: import("../types").HumanTask[]}>("/api/human-tasks/v1");
  }

  completeHumanTask(taskId: string, decision: Record<string, unknown>) {
    return this.request("/api/human-tasks/v1/" + taskId + "/complete", {
      method: "POST",
      headers: {"Idempotency-Key": crypto.randomUUID()},
      body: JSON.stringify({decision})
    });
  }
}
~~~

Token 只保存在 React state，不写 localStorage、sessionStorage 或 URL。

- [ ] **Step 3: 为 Graph 列表补后端查询**

PostgresGraphRepository 增加 tenant/project 受限的 list_versions：

~~~python
def list_versions(
    self,
    context: RequestContext,
    status: str | None = None,
) -> list[GraphVersionRecord]:
    query = (
        "SELECT graph_version_id,graph_id,version_no,status,definition_json,definition_sha256 "
        "FROM graph.version WHERE tenant_id=:tenant "
    )
    params = {"tenant": context.tenant_id}
    if status:
        query += "AND status=:status "
        params["status"] = status
    query += "ORDER BY graph_id,version_no DESC"
    with self.database.session() as session:
        rows = session.execute(text(query), params).mappings().all()
    return [
        GraphVersionRecord(
            graph_version_id=row["graph_version_id"],
            graph_id=row["graph_id"],
            version_no=row["version_no"],
            status=row["status"],
            definition=GraphDefinition.model_validate(row["definition_json"]),
            definition_sha256=row["definition_sha256"],
        )
        for row in rows
    ]
~~~

graphs.py 增加：

~~~python
@router.get("/versions")
def list_versions(
    status: str | None = None,
    context: RequestContext = Depends(request_context),
):
    if status not in (None, "draft", "published", "retired"):
        raise HTTPException(status_code=400, detail="invalid status")
    return {
        "items": [
            item.model_dump(mode="json")
            for item in repository().list_versions(context, status)
        ]
    }
~~~

- [ ] **Step 4: 先写组件测试**

RunLauncher.test.tsx：

~~~typescript
import {fireEvent, render, screen, waitFor} from "@testing-library/react";
import {describe, expect, it, vi} from "vitest";
import {RunLauncher} from "./RunLauncher";

describe("RunLauncher", () => {
  it("submits selected graph and parsed JSON", async () => {
    const onLaunch = vi.fn().mockResolvedValue("run-1");
    render(<RunLauncher graphs={[{
      graph_version_id: "v1",
      graph_id: "core.echo",
      version_no: 1,
      status: "published",
      definition: {name: "Echo", description: "test"}
    }]} onLaunch={onLaunch} />);
    fireEvent.change(screen.getByLabelText("Graph"), {target: {value: "v1"}});
    fireEvent.change(screen.getByLabelText("Input JSON"), {
      target: {value: '{"message":"hello"}'}
    });
    fireEvent.click(screen.getByRole("button", {name: "启动 Run"}));
    await waitFor(() => {
      expect(onLaunch).toHaveBeenCalledWith("v1", {message: "hello"});
    });
  });
});
~~~

RunTimeline.test.tsx：

~~~typescript
import {render, screen} from "@testing-library/react";
import {expect, it} from "vitest";
import {RunTimeline} from "./RunTimeline";

it("shows node cost and terminal status", () => {
  render(<RunTimeline run={{
    run_id: "run-1",
    status: "completed",
    graph_version_id: "v1",
    spent: {steps: 2, cost_micros: 10, tokens: 0},
    node_executions: [{
      node_execution_id: "n1",
      node_id: "echo",
      iteration: 0,
      attempt_no: 0,
      status: "succeeded",
      cost_micros: 10
    }],
    events: []
  }} />);
  expect(screen.getByText("completed")).toBeInTheDocument();
  expect(screen.getByText("echo")).toBeInTheDocument();
  expect(screen.getByText("10 µcredit")).toBeInTheDocument();
});
~~~

- [ ] **Step 5: 实现最小组件**

RunLauncher.tsx：

~~~typescript
import {useState} from "react";
import type {GraphVersion} from "../../types";

export function RunLauncher(props: {
  graphs: GraphVersion[];
  onLaunch: (versionId: string, input: Record<string, unknown>) => Promise<string>;
}) {
  const [versionId, setVersionId] = useState(props.graphs[0]?.graph_version_id ?? "");
  const [input, setInput] = useState('{"message":"hello"}');
  const [error, setError] = useState("");
  async function submit() {
    try {
      setError("");
      await props.onLaunch(versionId, JSON.parse(input) as Record<string, unknown>);
    } catch (value) {
      setError(value instanceof Error ? value.message : String(value));
    }
  }
  return <section>
    <h2>启动智能任务</h2>
    <label>Graph
      <select value={versionId} onChange={event => setVersionId(event.target.value)}>
        {props.graphs.map(graph =>
          <option key={graph.graph_version_id} value={graph.graph_version_id}>
            {graph.definition.name} v{graph.version_no}
          </option>
        )}
      </select>
    </label>
    <label>Input JSON
      <textarea value={input} onChange={event => setInput(event.target.value)} />
    </label>
    <button disabled={!versionId} onClick={submit}>启动 Run</button>
    {error && <p role="alert">{error}</p>}
  </section>;
}
~~~

RunTimeline.tsx：

~~~typescript
import type {RunDetail} from "../../types";

export function RunTimeline({run}: {run: RunDetail | null}) {
  if (!run) return <section><h2>Run 时间线</h2><p>尚未启动</p></section>;
  return <section>
    <h2>Run 时间线</h2>
    <p><strong>{run.status}</strong> · {run.spent.steps} steps · {run.spent.cost_micros} µcredit</p>
    <ol>
      {run.node_executions.map(node => <li key={node.node_execution_id}>
        <span>{node.node_id}</span>
        <span>{node.status}</span>
        <span>{node.cost_micros} µcredit</span>
      </li>)}
    </ol>
  </section>;
}
~~~

HumanTaskPanel.tsx：

~~~typescript
import type {HumanTask} from "../../types";

export function HumanTaskPanel(props: {
  tasks: HumanTask[];
  onComplete: (taskId: string, decision: Record<string, unknown>) => Promise<void>;
}) {
  return <section>
    <h2>待人工决定</h2>
    {props.tasks.length === 0 && <p>暂无</p>}
    {props.tasks.map(task => <article key={task.task_id}>
      <h3>{task.task_type}</h3>
      <pre>{JSON.stringify(task.payload, null, 2)}</pre>
      <button onClick={() => props.onComplete(task.task_id, {approved: true})}>批准并继续</button>
      <button onClick={() => props.onComplete(task.task_id, {approved: false})}>拒绝并继续</button>
    </article>)}
  </section>;
}
~~~

CapabilityCatalog.tsx：

~~~typescript
export function CapabilityCatalog({items}: {items: Array<Record<string, unknown>>}) {
  return <section>
    <h2>能力目录</h2>
    <ul>{items.map(item =>
      <li key={String(item.capability_id) + String(item.version)}>
        {String(item.name)} · {String(item.effect)}
      </li>
    )}</ul>
  </section>;
}
~~~

- [ ] **Step 6: 装配 App**

App.tsx 使用 token/project 输入，认证前不调用 API；认证后并行加载 Graph、Capability、HumanTask。Run 启动后每秒轮询，进入终态时停止：

~~~typescript
import {useEffect, useMemo, useState} from "react";
import {ApiClient} from "./api/client";
import {CapabilityCatalog} from "./features/capabilities/CapabilityCatalog";
import {RunLauncher} from "./features/runs/RunLauncher";
import {RunTimeline} from "./features/runs/RunTimeline";
import {HumanTaskPanel} from "./features/tasks/HumanTaskPanel";
import type {GraphVersion, HumanTask, RunDetail} from "./types";

const terminal = new Set([
  "completed", "failed", "cancelled", "budget_exhausted", "policy_blocked"
]);

export default function App() {
  const [token, setToken] = useState("");
  const [projectId, setProjectId] = useState("project_local");
  const [connected, setConnected] = useState(false);
  const [graphs, setGraphs] = useState<GraphVersion[]>([]);
  const [capabilities, setCapabilities] = useState<Array<Record<string, unknown>>>([]);
  const [tasks, setTasks] = useState<HumanTask[]>([]);
  const [run, setRun] = useState<RunDetail | null>(null);
  const client = useMemo(() => new ApiClient(token, projectId), [token, projectId]);

  useEffect(() => {
    if (!connected) return;
    Promise.all([client.listGraphs(), client.listCapabilities(), client.listHumanTasks()])
      .then(([g, c, t]) => {
        setGraphs(g.items);
        setCapabilities(c.items);
        setTasks(t.items);
      });
  }, [client, connected]);

  useEffect(() => {
    if (!run || terminal.has(run.status)) return;
    const timer = window.setInterval(() => {
      client.getRun(run.run_id).then(setRun);
      client.listHumanTasks().then(value => setTasks(value.items));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [client, run]);

  if (!connected) return <main>
    <h1>Graph+Loop 智能工作台</h1>
    <label>本机 Token<input type="password" value={token} onChange={e => setToken(e.target.value)} /></label>
    <label>Project<input value={projectId} onChange={e => setProjectId(e.target.value)} /></label>
    <button disabled={token.length < 32} onClick={() => setConnected(true)}>连接</button>
  </main>;

  return <main>
    <h1>Graph+Loop 智能工作台</h1>
    <RunLauncher graphs={graphs} onLaunch={async (version, input) => {
      const created = await client.createRun(version, input);
      setRun(await client.getRun(created.run_id));
      return created.run_id;
    }} />
    <RunTimeline run={run} />
    <HumanTaskPanel tasks={tasks} onComplete={async (taskId, decision) => {
      await client.completeHumanTask(taskId, decision);
      setTasks((await client.listHumanTasks()).items);
    }} />
    <CapabilityCatalog items={capabilities} />
  </main>;
}
~~~

main.tsx：

~~~typescript
import {StrictMode} from "react";
import {createRoot} from "react-dom/client";
import App from "./App";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode><App /></StrictMode>
);
~~~

styles.css 固定使用两栏响应式布局、系统字体、可见焦点和 44px 最小按钮高度，不加入品牌素材：

~~~css
:root {
  color: #172033;
  background: #f4f6f9;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  font-synthesis: none;
}

* { box-sizing: border-box; }
body { margin: 0; min-width: 320px; min-height: 100vh; }
main {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
  width: min(1280px, calc(100% - 32px));
  margin: 0 auto;
  padding: 24px 0;
}
h1 { grid-column: 1 / -1; }
section, main > label {
  padding: 18px;
  border: 1px solid #d8deea;
  border-radius: 12px;
  background: #fff;
}
label { display: grid; gap: 8px; margin-bottom: 12px; }
input, select, textarea, button {
  min-height: 44px;
  border: 1px solid #aab4c5;
  border-radius: 8px;
  padding: 9px 12px;
  font: inherit;
}
textarea { min-height: 140px; font-family: ui-monospace, SFMono-Regular, monospace; }
button { cursor: pointer; color: #fff; background: #2457d6; border-color: #2457d6; }
button:disabled { cursor: not-allowed; opacity: .55; }
:focus-visible { outline: 3px solid #f1a33c; outline-offset: 2px; }
ol li { display: grid; grid-template-columns: 1fr auto auto; gap: 12px; padding: 8px 0; }
[role="alert"] { color: #a11b1b; }

@media (max-width: 760px) {
  main { grid-template-columns: 1fr; width: min(100% - 20px, 680px); }
  h1 { grid-column: 1; }
}
~~~

- [ ] **Step 7: 测试与构建**

~~~bash
cd web
npm install
npm test
npm run lint
npm run build
~~~

Expected: Vitest 全部通过；TypeScript 无错误；web/dist 生成。package-lock.json 必须提交，web/dist 不提交。

- [ ] **Step 8: 提交**

~~~bash
git add web/package.json web/package-lock.json web/tsconfig.json web/vite.config.ts web/index.html web/src src/platform/api/routes/graphs.py src/platform/data/graph_repository.py
git commit -m "feat(workbench): add graph run and human task console"
~~~

## Task 14: 增加本机初始化、Worker CLI 与服务清单

**Files:**
- Create: src/platform/api/bootstrap.py
- Modify: src/platform/kernel/worker.py
- Create: scripts/run_control_plane.sh
- Create: scripts/run_graph_worker.sh
- Modify: docs/services.json
- Modify: docs/runbook.md
- Modify: docs/structure.md

- [ ] **Step 1: 创建幂等本机 bootstrap**

src/platform/api/bootstrap.py：

~~~python
from __future__ import annotations

import json
from pathlib import Path

from src.platform.api.auth import AuthService
from src.platform.api.dependencies import registry, repository, settings
from src.platform.kernel.contracts import GraphDefinition, RequestContext


ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP_SCOPES = frozenset({
    "graph:read",
    "graph:write",
    "graph:publish",
    "run:create",
    "run:read",
    "run:control",
    "capability:echo",
    "capability:recognize",
    "human:read",
    "human:complete",
    "audit:read",
})


def bootstrap() -> dict:
    config = settings()
    context = RequestContext(
        principal_id="principal_local_admin",
        tenant_id=config.app_default_tenant_id,
        customer_id=config.app_default_customer_id,
        project_id=config.app_default_project_id,
        scopes=BOOTSTRAP_SCOPES,
        correlation_id="bootstrap-local",
    )
    repository().bootstrap_scope(
        context,
        token_sha256=AuthService.token_sha256(config.app_bootstrap_token),
    )
    for capability in registry().list():
        repository().upsert_capability_definition(context, capability)

    versions = []
    for relative in (
        "src/modules/reference_echo/graphs/echo-v1.json",
        "src/modules/fmcg_vision/graphs/minimal-recognition-v1.json",
    ):
        definition = GraphDefinition.model_validate(
            json.loads((ROOT / relative).read_text(encoding="utf-8"))
        )
        existing = repository().find_version_by_sha(
            context,
            definition.graph_id,
            definition,
        )
        version = existing or repository().create_draft_version(context, definition)
        if version.status == "draft":
            version = repository().publish_version(context, version.graph_version_id)
        versions.append(version.graph_version_id)
    return {
        "tenant_id": context.tenant_id,
        "project_id": context.project_id,
        "capabilities": len(registry().list()),
        "graph_versions": versions,
    }


if __name__ == "__main__":
    print(json.dumps(bootstrap(), ensure_ascii=False, indent=2))
~~~

PostgresGraphRepository 增加以下精确方法。Capability 版本冲突时比较完整定义，相同则幂等，不同则失败，不能覆盖已注册版本；Graph 只复用 draft/published，不会把 retired 版本重新发布：

~~~python
def upsert_capability_definition(
    self,
    context: RequestContext,
    definition: CapabilityDefinition,
) -> None:
    payload = definition.model_dump(mode="json")
    with self.database.session() as session:
        session.execute(text(
            "INSERT INTO capability.definition("
            "capability_id,version,name,effect,input_schema_json,output_schema_json,"
            "required_scopes_json,handler_key,timeout_seconds,max_attempts,fixed_cost_micros,enabled"
            ") VALUES (:id,:version,:name,:effect,CAST(:input AS jsonb),CAST(:output AS jsonb),"
            "CAST(:scopes AS jsonb),:handler,:timeout,:attempts,:cost,true) "
            "ON CONFLICT (capability_id,version) DO NOTHING"
        ), {
            "id": definition.capability_id,
            "version": definition.version,
            "name": definition.name,
            "effect": definition.effect.value,
            "input": canonical_json(definition.input_schema),
            "output": canonical_json(definition.output_schema),
            "scopes": canonical_json(sorted(definition.required_scopes)),
            "handler": definition.handler_key,
            "timeout": definition.timeout_seconds,
            "attempts": definition.max_attempts,
            "cost": definition.fixed_cost_micros,
        })
        row = session.execute(text(
            "SELECT * FROM capability.definition WHERE capability_id=:id AND version=:version"
        ), {"id": definition.capability_id, "version": definition.version}).mappings().one()
        stored = CapabilityDefinition(
            capability_id=row["capability_id"],
            version=row["version"],
            name=row["name"],
            effect=row["effect"],
            input_schema=row["input_schema_json"],
            output_schema=row["output_schema_json"],
            required_scopes=row["required_scopes_json"],
            timeout_seconds=row["timeout_seconds"],
            max_attempts=row["max_attempts"],
            fixed_cost_micros=row["fixed_cost_micros"],
            handler_key=row["handler_key"],
        )
        if stored != definition:
            raise ValueError(
                f"capability version conflict: {definition.capability_id}@{definition.version}"
            )
        session.execute(text(
            "INSERT INTO audit.audit_event("
            "audit_event_id,tenant_id,project_id,principal_id,action,object_type,object_id,"
            "result,payload_json,correlation_id) "
            "VALUES (:event,:tenant,:project,:principal,'capability.ensure','capability_version',"
            ":object,'unchanged_or_created',CAST(:payload AS jsonb),:correlation)"
        ), {
            "event": str(uuid.uuid4()),
            "tenant": context.tenant_id,
            "project": context.project_id,
            "principal": context.principal_id,
            "object": f"{definition.capability_id}@{definition.version}",
            "payload": canonical_json({"definition_sha256": sha256_json(payload)}),
            "correlation": context.correlation_id,
        })


def find_version_by_sha(
    self,
    context: RequestContext,
    graph_id: str,
    definition: GraphDefinition,
) -> GraphVersionRecord | None:
    digest = sha256_json(definition.model_dump(mode="json"))
    with self.database.session() as session:
        row = session.execute(text(
            "SELECT graph_version_id FROM graph.version "
            "WHERE tenant_id=:tenant AND graph_id=:graph AND definition_sha256=:sha "
            "AND status IN ('draft','published') "
            "ORDER BY CASE status WHEN 'published' THEN 0 ELSE 1 END,version_no DESC LIMIT 1"
        ), {
            "tenant": context.tenant_id,
            "graph": graph_id,
            "sha": digest,
        }).mappings().one_or_none()
    return self._version(context, row["graph_version_id"]) if row else None
~~~

该文件同步导入 CapabilityDefinition。每次 bootstrap 都追加 audit 事件，因此 bootstrap 是业务状态幂等、审计追加式；不得用 UPDATE 覆盖 CapabilityDefinition。

- [ ] **Step 2: 为 Worker 增加 CLI**

在 src/platform/kernel/worker.py 增加：

~~~python
def main() -> None:
    import signal
    import time

    from src.platform.api.dependencies import policy, registry, repository, settings

    config = settings()
    if not config.graph_kernel_enabled:
        raise RuntimeError("GRAPH_KERNEL_ENABLED must be true to start worker")
    worker = GraphWorker(
        config.graph_worker_id,
        repository(),
        registry(),
        policy(),
        config.graph_lease_seconds,
    )
    stopping = False

    def stop(*_args):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    while not stopping:
        if not worker.run_once():
            time.sleep(config.graph_poll_interval_ms / 1000)


if __name__ == "__main__":
    main()
~~~

Worker 收到 SIGTERM 后不领取新节点；正在执行节点完成事务后退出。

- [ ] **Step 3: 创建本机启动脚本**

scripts/run_control_plane.sh：

~~~bash
#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT_PATH="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT_PATH"
PROJECT_PYTHON_PATH="${PROJECT_PYTHON_PATH:-python3}"
exec "$PROJECT_PYTHON_PATH" -m uvicorn src.platform.api.main:app --host 127.0.0.1 --port 8400
~~~

scripts/run_graph_worker.sh：

~~~bash
#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT_PATH="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT_PATH"
PROJECT_PYTHON_PATH="${PROJECT_PYTHON_PATH:-python3}"
exec "$PROJECT_PYTHON_PATH" -m src.platform.kernel.worker
~~~

不使用 nohup，不把 token 写入脚本。环境从未提交的 .env 读取。

- [ ] **Step 4: 更新机器可读服务清单**

docs/services.json 增加：

~~~json
{
  "name": "graph-control-plane",
  "port": 8400,
  "command": "bash scripts/run_control_plane.sh",
  "health": "http://127.0.0.1:8400/health/ready",
  "role": "Graph+Loop 智能内核控制面",
  "writable": true,
  "status": "experimental",
  "feature_flag": "GRAPH_KERNEL_ENABLED"
},
{
  "name": "graph-worker",
  "port": null,
  "command": "bash scripts/run_graph_worker.sh",
  "health": "无独立 HTTP；通过 control-plane 的 queued/leased 节点与进程状态联合检查",
  "role": "持久 NodeExecution 执行与恢复",
  "writable": true,
  "status": "experimental",
  "feature_flag": "GRAPH_KERNEL_ENABLED"
}
~~~

architecture 字段改为“Graph+Loop kernel + capability packs；FMCG cascade is first domain capability”。旧 8091、8304 等服务保持原端口和 supported/legacy 状态。

- [ ] **Step 5: 更新 runbook 和 structure**

runbook 必须写出固定启动顺序：

1. docker compose up -d postgres；
2. APP_DATABASE_URL 从 .env 读取，alembic upgrade head；
3. python -m src.platform.api.bootstrap；
4. 启动现有 recognize 8091；
5. 启动 graph worker；
6. 启动 control plane 8400；
7. 可选启动 web dev 8410。

同时写出停止规则：先停止新 Run，等待 leased 节点完成，再 SIGTERM Worker，最后停止 control plane；不删除数据库或 runtime 文件。

structure.md 增加 kernel、control_plane、persistence、contracts、web 目录；明确现有 src/ls_platform 是 Capability Provider/legacy orchestrator，不是新内核。

- [ ] **Step 6: 验证并提交**

~~~bash
bash -n scripts/run_control_plane.sh
bash -n scripts/run_graph_worker.sh
python3 -m json.tool docs/services.json >/dev/null
git add src/platform/api/bootstrap.py src/platform/kernel/worker.py scripts/run_control_plane.sh scripts/run_graph_worker.sh docs/services.json docs/runbook.md docs/structure.md
git commit -m "chore(kernel): add local bootstrap worker and runbook"
~~~

## Task 15: 建立端到端、恢复和性能验收

**Files:**
- Create: tests/e2e/test_minimal_graphs.py
- Create: scripts/benchmark_graph_kernel.py
- Modify: docs/experiments/GK0-stage0-1-execution-evidence.md

- [ ] **Step 1: 写非识别 E2E**

~~~python
def test_echo_graph_completes_via_api_and_worker(
    control_plane_client,
    bootstrap_identity,
    published_echo_version,
    graph_worker,
):
    token, project_id = bootstrap_identity
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Project-ID": project_id,
        "Idempotency-Key": "e2e-echo",
    }
    created = control_plane_client.post(
        "/api/runs/v1",
        headers=headers,
        json={
            "graph_version_id": published_echo_version,
            "input": {"message": "hello"},
        },
    )
    assert created.status_code == 202
    run_id = created.json()["run_id"]
    drained = 0
    while graph_worker.run_once():
        drained += 1
    assert drained == 2
    detail = control_plane_client.get(
        f"/api/runs/v1/{run_id}",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Project-ID": project_id,
        },
    ).json()
    assert detail["status"] == "completed"
    assert [item["node_id"] for item in detail["node_executions"]] == ["echo", "done"]
~~~

- [ ] **Step 2: 写识别 + 人工 E2E**

测试 fixture 将 RecognitionCapability 替换为确定性 handler，返回 needs_review=true：

~~~python
def test_recognition_graph_waits_and_resumes_human(
    control_plane_client,
    bootstrap_identity,
    published_recognition_version,
    graph_worker,
):
    token, project_id = bootstrap_identity
    base_headers = {
        "Authorization": f"Bearer {token}",
        "X-Project-ID": project_id,
    }
    created = control_plane_client.post(
        "/api/runs/v1",
        headers=base_headers | {"Idempotency-Key": "e2e-recognition"},
        json={
            "graph_version_id": published_recognition_version,
            "input": {"asset_id": "fixture-asset"},
        },
    )
    run_id = created.json()["run_id"]
    for _ in range(3):
        assert graph_worker.run_once()
    detail = control_plane_client.get(
        f"/api/runs/v1/{run_id}",
        headers=base_headers,
    ).json()
    assert detail["status"] == "waiting_human"

    tasks = control_plane_client.get(
        "/api/human-tasks/v1",
        headers=base_headers,
    ).json()["items"]
    task = next(item for item in tasks if item["run_id"] == run_id)
    completed = control_plane_client.post(
        f"/api/human-tasks/v1/{task['task_id']}/complete",
        headers=base_headers | {"Idempotency-Key": "e2e-human"},
        json={"decision": {"approved": True, "reviewer": "e2e"}},
    )
    assert completed.status_code == 200
    drained = 0
    while graph_worker.run_once():
        drained += 1
    assert drained == 1
    final = control_plane_client.get(
        f"/api/runs/v1/{run_id}",
        headers=base_headers,
    ).json()
    assert final["status"] == "completed"
~~~

- [ ] **Step 3: 写性能脚本**

scripts/benchmark_graph_kernel.py 只创建 echo Run，不调用识别模型：

~~~python
from __future__ import annotations

import argparse
import concurrent.futures
import os
import statistics
import time
import uuid

import httpx


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8400")
    parser.add_argument("--token", default=os.environ.get("APP_BOOTSTRAP_TOKEN"))
    parser.add_argument("--project", default="project_local")
    parser.add_argument("--graph-id", default="core.echo")
    parser.add_argument("--runs", type=int, default=1000)
    parser.add_argument("--concurrency", type=int, default=16)
    parser.add_argument("--terminal-timeout", type=int, default=120)
    args = parser.parse_args()
    if not args.token:
        parser.error("--token or APP_BOOTSTRAP_TOKEN is required")
    if args.runs < 1 or args.concurrency < 1:
        parser.error("runs and concurrency must be positive")

    client = httpx.Client(base_url=args.url, timeout=10)
    base_headers = {
        "Authorization": f"Bearer {args.token}",
        "X-Project-ID": args.project,
    }
    graph_response = client.get(
        "/api/graph/v1/versions?status=published",
        headers=base_headers,
    )
    graph_response.raise_for_status()
    matches = [
        item for item in graph_response.json()["items"]
        if item["graph_id"] == args.graph_id
    ]
    if not matches:
        raise RuntimeError(f"published graph not found: {args.graph_id}")
    graph_version_id = max(matches, key=lambda item: item["version_no"])["graph_version_id"]
    benchmark_id = uuid.uuid4().hex

    def create(index: int) -> tuple[str, float]:
        start = time.perf_counter()
        response = client.post(
            "/api/runs/v1",
            headers={
                **base_headers,
                "Idempotency-Key": f"benchmark-{benchmark_id}-{index}",
            },
            json={
                "graph_version_id": graph_version_id,
                "input": {"message": str(index)},
            },
        )
        response.raise_for_status()
        return response.json()["run_id"], (time.perf_counter() - start) * 1000

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        created = list(pool.map(create, range(args.runs)))
    run_ids = [item[0] for item in created]
    latencies = [item[1] for item in created]

    terminal = {"completed", "failed", "cancelled", "budget_exhausted", "policy_blocked"}
    pending = set(run_ids)
    final_status: dict[str, str] = {}
    deadline = time.monotonic() + args.terminal_timeout

    def read_status(run_id: str) -> tuple[str, str]:
        response = client.get(f"/api/runs/v1/{run_id}", headers=base_headers)
        response.raise_for_status()
        return run_id, response.json()["status"]

    while pending and time.monotonic() < deadline:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            statuses = list(pool.map(read_status, sorted(pending)))
        for run_id, status in statuses:
            if status in terminal:
                pending.remove(run_id)
                final_status[run_id] = status
        if pending:
            time.sleep(0.25)

    ordered = sorted(latencies)
    p95 = ordered[int(len(ordered) * 0.95) - 1]
    print({
        "benchmark_id": benchmark_id,
        "graph_version_id": graph_version_id,
        "runs": len(latencies),
        "p50_ms": statistics.median(latencies),
        "p95_ms": p95,
        "max_ms": max(latencies),
        "terminal_counts": {
            status: sum(1 for value in final_status.values() if value == status)
            for status in sorted(terminal)
        },
        "pending_after_timeout": len(pending),
    })
    if pending:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
~~~

- [ ] **Step 4: 执行全量测试**

~~~bash
XONSH_HISTORY_BACKEND=dummy PYTHONDONTWRITEBYTECODE=1 APP_DATABASE_URL=postgresql+psycopg://<user>:<password>@127.0.0.1:55432/sku_graph_test APP_BOOTSTRAP_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx GRAPH_KERNEL_ENABLED=true python3 -m pytest -p no:cacheprovider -q
cd web
npm test
npm run lint
npm run build
~~~

Expected:

- 原 74 项测试全部保持通过；
- 新 unit/integration/e2e 全部通过；
- 前端测试、类型和 build 全部通过；
- 无测试连接非 sku_graph_test 数据库。

- [ ] **Step 5: 执行恢复矩阵**

按顺序人工注入并记录证据：

1. Node leased 后强制结束 Worker，再启动新 Worker；同 node_execution_id 恢复。
2. 外部 recognition 返回 429；同 idempotency_key 延迟重试，不新增 UsageEvent。
3. PostgreSQL 临时不可用；Worker 不标成功，恢复后继续。
4. Run paused 时不调度新节点；resume 后只继续一次。
5. HumanTask 等待时重启控制面和 Worker；任务仍存在并能完成。
6. 同 Idempotency-Key 不同 body 返回 409。
7. 另一个 tenant/project 查询 run 返回 404。
8. published GraphVersion 的 UPDATE/DELETE 被数据库拒绝。

- [ ] **Step 6: 执行 Stage 1 性能门**

启动 4 个不同 GRAPH_WORKER_ID 的 Worker，仅压 echo：

~~~bash
python3 scripts/benchmark_graph_kernel.py --graph-id core.echo --runs 1000 --concurrency 16
~~~

命令从当前环境读取 APP_BOOTSTRAP_TOKEN，并通过受权限控制的 Graph 列表解析最新 published `core.echo` 版本；不得把 token 写进命令历史。记录：

- Run create p95 ≤250ms；
- 1000 Run 全部进入 completed；任何其他终态都算性能门失败；
- UsageEvent 无重复 idempotency_key；
- NodeExecution 无永远 leased；
- Worker 重启后队列可清空；
- PostgreSQL 连接数不超过配置上限；
- 峰值 RSS 和数据库增长记录到证据文档。

该门只证明 Graph 内核，不宣称达到十万张/天识别吞吐。

- [ ] **Step 7: 可选真实识别 smoke**

只有 8091 /v2/health 返回 200 且项目负责人允许使用现有模型时，执行一张已授权测试图：

1. 通过最小识别 Graph 启动；
2. 验证 Graph run_id、node_execution_id、legacy recognition run_id 三者关联；
3. 若 needs_review=true，完成 HumanTask；
4. 验证只有一次识别审计和一次非零识别 UsageEvent；
5. 不切换模型、不写训练数据、不改变生产结果。

若模型不可用，记录 skipped: recognition service unhealthy；不能用 echo 结果伪装真实识别成功。

- [ ] **Step 8: 更新证据并提交**

GK0 证据文件必须填入：

- migration revision；
- contract SHA256；
- 两条 Graph version/SHA；
- 测试数量；
- 恢复矩阵 8 项结果；
- echo 性能；
- 真实识别 smoke 或跳过原因；
- 未解决风险；
- production_switch=false；
- legacy_ports_changed=false；
- deleted_files=false。

~~~bash
git add tests/e2e scripts/benchmark_graph_kernel.py docs/experiments/GK0-stage0-1-execution-evidence.md
git commit -m "test(kernel): verify minimal graph loop recovery and performance"
~~~

## Task 16: Graph Kernel 子关卡验收

**Files:**
- Modify: docs/experiments/GK0-stage0-1-execution-evidence.md
- Create: docs/experiments/GK1-graph-kernel-checkpoint.md

- [ ] **Step 1: 运行最终只读差异审计**

~~~bash
git status --short
git diff main...HEAD --stat
git diff main...HEAD --check
git diff main...HEAD --name-only
~~~

Expected: 不出现原图、SQLite、模型权重、训练数据、.env、日志或生成数据库。

- [ ] **Step 2: 写验收结论**

GK1 Graph Kernel checkpoint 必须逐项给 PASS/FAIL 和证据路径：

| 门禁 | 通过条件 |
|---|---|
| K-01 契约 | Graph/Capability/OpenAPI 可重复生成且无 diff |
| K-02 PostgreSQL | Graph 事实只写 PG；测试拒绝非 test DB |
| K-03 不可变 | published Graph 和所有追加式事件拒绝修改/删除 |
| K-04 恢复 | Worker/控制面重启后从 Checkpoint 继续 |
| K-05 幂等 | Run、Node 外调、HumanTask、Usage 均不重复 |
| K-06 权限 | tenant/project/scope 不能由 body 扩大 |
| K-07 有界 Loop | step/time/cost/token/iteration 均 fail-closed |
| K-08 人工节点 | waiting_human 可跨重启恢复 |
| K-09 双域证明 | echo 与 FMCG 最小 Graph 都通过契约/E2E |
| K-10 兼容 | 8091/8304 未切换，旧测试全部通过 |
| K-11 性能 | echo 1000 Run p95 和终态门通过 |
| K-12 证据 | Run → Node → Policy → Usage → Checkpoint 可追溯 |

任何一项 FAIL，Stage 1 结论必须是 NOT ACCEPTED，并保留全部失败证据。不得进入 Stage 2 实施。

- [ ] **Step 3: 最终测试和提交**

~~~bash
XONSH_HISTORY_BACKEND=dummy PYTHONDONTWRITEBYTECODE=1 APP_DATABASE_URL=postgresql+psycopg://<user>:<password>@127.0.0.1:55432/sku_graph_test APP_BOOTSTRAP_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx GRAPH_KERNEL_ENABLED=true python3 -m pytest -p no:cacheprovider -q
cd web
npm test
npm run build
cd ..
git add docs/experiments/GK0-stage0-1-execution-evidence.md docs/experiments/GK1-graph-kernel-checkpoint.md
git commit -m "docs(kernel): record graph kernel checkpoint"
~~~

- [ ] **Step 4: 只在子关卡通过后进入统一底座任务**

任一 K 门失败时停止并修复，不得跳过；全部通过后只能进入 Task 17。即使 Graph Kernel 已通过，也不得：

- 合并到 main；
- 启用生产 feature flag；
- 替换 8304 编排入口；
- 修改 Label Studio；
- 开始完整照片质量或识别平台改造；
- 启动训练；
- 删除测试容器、数据库、失败产物或临时证据。

## Task 17: 建立 Module SDK、注册表和生命周期

**Files:**
- Create: src/platform/modules/manifest.py
- Create: src/platform/modules/registry.py
- Create: src/platform/modules/lifecycle.py
- Create: contracts/module/v1/module-manifest.schema.json
- Create: tests/unit/platform/modules/test_manifest.py
- Create: tests/unit/platform/modules/test_registry.py
- Create: tests/integration/test_module_lifecycle.py
- Modify: scripts/export_contracts.py

- [ ] **Step 1: 先写 Manifest 契约失败测试**

~~~python
import pytest
from pydantic import ValidationError

from src.platform.modules.manifest import ModuleManifest


def valid_manifest() -> dict:
    return {
        "module_id": "reference_echo",
        "version": "1.0.0",
        "foundation_api": ">=1.0,<2.0",
        "schema_name": "mod_reference_echo",
        "dependencies": [],
        "capabilities": ["core.echo"],
        "graphs": ["core.echo.v1"],
        "routes": [],
        "web_slots": ["workspace.tools"],
        "meters": ["echo.call"],
        "health_checks": ["database"],
    }


def test_manifest_rejects_unknown_fields_and_invalid_ids():
    body = valid_manifest() | {"module_id": "../echo", "python_import": "evil.run"}
    with pytest.raises(ValidationError):
        ModuleManifest.model_validate(body)


def test_manifest_requires_owned_schema_and_foundation_range():
    body = valid_manifest() | {"schema_name": "graph", "foundation_api": "*"}
    with pytest.raises(ValidationError):
        ModuleManifest.model_validate(body)
~~~

运行：

~~~bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/unit/platform/modules/test_manifest.py -q
~~~

Expected: FAIL，模块 Manifest 尚不存在。

- [ ] **Step 2: 实现严格 Manifest 与 JSON Schema**

最低实现：

~~~python
from pydantic import BaseModel, ConfigDict, Field, field_validator

_RESERVED_SCHEMAS = {"public", "iam", "module_registry", "graph", "asset", "job", "billing", "audit"}


class ModuleDependency(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    module_id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    version: str
    required: bool = True


class ModuleManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    module_id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    foundation_api: str
    schema_name: str = Field(pattern=r"^mod_[a-z][a-z0-9_]{2,59}$")
    dependencies: tuple[ModuleDependency, ...] = ()
    capabilities: tuple[str, ...] = ()
    graphs: tuple[str, ...] = ()
    routes: tuple[str, ...] = ()
    web_slots: tuple[str, ...] = ()
    meters: tuple[str, ...] = ()
    health_checks: tuple[str, ...] = ()

    @field_validator("foundation_api")
    @classmethod
    def bounded_foundation_api(cls, value: str) -> str:
        if value == "*" or ">=" not in value or "<" not in value:
            raise ValueError("foundation_api must have lower and upper bounds")
        return value

    @field_validator("schema_name")
    @classmethod
    def schema_is_owned(cls, value: str) -> str:
        if value in _RESERVED_SCHEMAS:
            raise ValueError("module cannot own a foundation schema")
        return value
~~~

`scripts/export_contracts.py` 必须原子写出 `contracts/module/v1/module-manifest.schema.json`，连续执行两次 SHA256 相同。

- [ ] **Step 3: 写注册与依赖排序失败测试**

测试必须覆盖：重复 `module_id`、缺少依赖、版本不兼容、依赖环、未签名的未知 Manifest、Capability/route/meter 冲突、禁用必需依赖。注册表只接受启动代码明确给出的工厂，不读取 Manifest 中的 Python import path。

~~~python
def test_registry_rejects_dependency_cycle(registry, manifests):
    manifests["a"] = manifests.make("a", depends_on="b")
    manifests["b"] = manifests.make("b", depends_on="a")
    with pytest.raises(ModuleDependencyCycle):
        registry.resolve(manifests.values())


def test_foundation_never_imports_module_handlers_from_manifest(registry, manifest):
    raw = manifest.model_dump() | {"python_import": "src.modules.reference_echo.capability:Echo"}
    with pytest.raises(ValidationError):
        registry.parse(raw)
~~~

- [ ] **Step 4: 实现 Registry 和生命周期状态机**

固定状态：`discovered → installed → enabled → degraded → disabled → retired`。`failed_install` 和 `failed_upgrade` 是可恢复故障状态。生命周期必须：

1. 获取 `module_id` advisory lock；
2. 验证 Foundation API、依赖和声明冲突；
3. 在模块自有 schema 执行 forward-only migration；
4. 写 `module_registry.module_installation` 和不可变事件；
5. 只有事务提交后暴露 capability/route/web slot；
6. disable 只停止新工作，保留历史资源、证据、计量和查询；
7. upgrade 失败回到上一个可用版本，保留失败迁移证据，不执行 DROP。

注册必须是显式工厂映射：

~~~python
ModuleFactoryMap = dict[str, ModuleFactory]


def build_registry(factories: ModuleFactoryMap) -> ModuleRegistry:
    if any(not module_id.isidentifier() for module_id in factories):
        raise ValueError("invalid module factory id")
    return ModuleRegistry(factories=factories)
~~~

- [ ] **Step 5: 集成测试启停与失败隔离**

~~~bash
PYTHONDONTWRITEBYTECODE=1 APP_DATABASE_URL=postgresql+psycopg://<user>:<password>@127.0.0.1:55432/sku_graph_test python3 -m pytest -p no:cacheprovider tests/unit/platform/modules tests/integration/test_module_lifecycle.py -q
~~~

Expected: 禁用 Reference Echo 后其新 Run 返回 409 `module_disabled`，但历史 Run 可读；故意使 Echo 升级失败时 FMCG Bridge 与控制面仍健康。

- [ ] **Step 6: 导出契约并提交**

~~~bash
python3 scripts/export_contracts.py
shasum -a 256 contracts/module/v1/module-manifest.schema.json
git add src/platform/modules contracts/module tests/unit/platform/modules tests/integration/test_module_lifecycle.py scripts/export_contracts.py
git commit -m "feat(platform): add module sdk and lifecycle"
~~~

## Task 18: 统一 IAM、平台迁移和模块 schema 所有权

**Files:**
- Create: src/platform/iam/__init__.py
- Create: src/platform/iam/contracts.py
- Create: src/platform/iam/service.py
- Create: src/platform/data/migrations.py
- Create: migrations/platform/versions/20260804_0002_platform_services.py
- Create: tests/unit/platform/iam/test_scope.py
- Create: tests/integration/test_platform_schema_ownership.py
- Modify: src/platform/api/auth.py
- Modify: src/platform/api/dependencies.py

- [ ] **Step 1: 写 fail-closed 授权测试**

~~~python
from src.platform.iam.contracts import Action, PrincipalContext, ResourceScope


def test_request_body_cannot_expand_authenticated_scope(iam):
    principal = PrincipalContext(
        principal_id="user_a",
        tenant_id="tenant_a",
        project_ids=frozenset({"project_a"}),
        scopes=frozenset({"run:read"}),
    )
    requested = ResourceScope(tenant_id="tenant_b", project_id="project_b")
    decision = iam.authorize(principal, Action.RUN_READ, requested)
    assert decision.allowed is False
    assert decision.reason_code == "tenant_scope_mismatch"


def test_missing_data_domain_is_denied(iam, principal):
    decision = iam.authorize_data(principal, "customer_sales", "read")
    assert decision.allowed is False
~~~

测试还必须覆盖：tenant、project、module、data_domain、field/row policy、管理员委派到期、禁用用户、服务账号、Agent capability scope。

- [ ] **Step 2: 实现不可扩大 PrincipalContext**

`PrincipalContext` 从签名 token/本机 bootstrap 映射生成，所有字段 frozen；路由 body 不能包含 `scopes`、`roles` 或授权 tenant 列表。`IAMService.authorize` 返回结构化 `PolicyDecision`，并把 allow/deny 都写入审计队列。

~~~python
class PrincipalContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    principal_id: str
    tenant_id: str
    project_ids: frozenset[str]
    roles: frozenset[str] = frozenset()
    scopes: frozenset[str]
    data_domains: frozenset[str] = frozenset()
    expires_at: datetime | None = None
~~~

- [ ] **Step 3: 创建平台服务迁移**

`20260804_0002_platform_services.py` 创建：

- `module_registry.module_installation/module_event`；
- `iam.principal/principal_role/role_scope/data_domain_grant`；
- `asset.asset_object/asset_ref/evidence_bundle/retention_hold`；
- `job.job/job_attempt/outbox_event/inbox_receipt/dead_letter`；
- `projection.work_item/data_product/resource_lineage`；
- `billing.meter/rate_card/rate_card_version/usage_event/cost_entry/price_entry`；
- `audit.audit_event/decision_event/export_event`。

所有 tenant/project 事实表必须含 scope 列和复合索引；所有不可变事件表由数据库 trigger 拒绝 UPDATE/DELETE；金额统一 `BIGINT micros`；时间统一 `TIMESTAMPTZ`；payload 必须有 schema version。

- [ ] **Step 4: 实现迁移编排与 schema 所有权检查**

`MigrationOrchestrator` 顺序固定：Foundation → 必需依赖 → 可选模块。只执行代码注册的迁移目录；同一模块只允许访问自己的 schema。测试使用受限数据库 role，证明模块 migration 不能 `CREATE/ALTER/DROP` 其他模块或 Foundation schema。

~~~python
def test_module_role_cannot_write_foundation_schema(module_connection):
    with pytest.raises(ProgrammingError):
        module_connection.execute(text("insert into iam.principal(principal_id) values ('x')"))


def test_migration_plan_is_dependency_ordered(orchestrator):
    assert orchestrator.plan([fmcg_manifest, echo_manifest]).module_ids == (
        "foundation",
        "reference_echo",
        "fmcg_vision",
    )
~~~

- [ ] **Step 5: 运行隔离集成测试**

~~~bash
APP_DATABASE_URL=postgresql+psycopg://<user>:<password>@127.0.0.1:55432/sku_graph_test python3 -m alembic upgrade head
PYTHONDONTWRITEBYTECODE=1 APP_DATABASE_URL=postgresql+psycopg://<user>:<password>@127.0.0.1:55432/sku_graph_test python3 -m pytest -p no:cacheprovider tests/unit/platform/iam tests/integration/test_platform_schema_ownership.py tests/integration/test_control_plane_api.py -q
~~~

Expected: 全部通过；跨租户查询对调用方返回 404；数据库角色的越界写入失败且产生审计证据。

- [ ] **Step 6: 提交**

~~~bash
git add src/platform/iam src/platform/data/migrations.py src/platform/api/auth.py src/platform/api/dependencies.py migrations/platform/versions/20260804_0002_platform_services.py tests/unit/platform/iam tests/integration/test_platform_schema_ownership.py
git commit -m "feat(platform): enforce iam and schema ownership"
~~~

## Task 19: 建立 CAS、EvidenceBundle 和保留策略

**Files:**
- Create: src/platform/assets/__init__.py
- Create: src/platform/assets/contracts.py
- Create: src/platform/assets/cas.py
- Create: src/platform/assets/evidence.py
- Create: src/platform/assets/repository.py
- Create: tests/unit/platform/assets/test_contracts.py
- Create: tests/integration/test_asset_evidence.py
- Modify: src/platform/api/settings.py
- Modify: .env.example

- [ ] **Step 1: 写不可变资产失败测试**

~~~python
def test_same_bytes_deduplicate_without_overwrite(asset_service):
    first = asset_service.put_bytes(b"same", media_type="image/jpeg", source="upload")
    second = asset_service.put_bytes(b"same", media_type="image/jpeg", source="url_download")
    assert first.asset_id == second.asset_id
    assert first.sha256 == second.sha256
    assert first.source_event_id != second.source_event_id


def test_asset_id_cannot_be_forged_from_path(asset_service, tmp_path):
    with pytest.raises(ValidationError):
        asset_service.resolve({"asset_id": str(tmp_path / "photo.jpg")})


def test_retention_hold_blocks_physical_delete(asset_service, held_asset):
    with pytest.raises(RetentionHoldActive):
        asset_service.purge(held_asset.asset_id)
~~~

测试还必须覆盖：下载 URL 与最终响应分离记录、redirect chain、响应哈希、MIME sniff、大小上限、同哈希多 tenant 逻辑隔离、EvidenceBundle 完整性校验、缺失 blob readiness 失败。

- [ ] **Step 2: 固定 ResourceRef 与 EvidenceBundle 契约**

~~~python
class ResourceRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    resource_type: str
    resource_id: UUID
    version: int = Field(ge=1)
    tenant_id: str
    project_id: str


class EvidenceItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    role: str
    asset: ResourceRef
    captured_at: datetime
    source_event_id: UUID
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
~~~

EvidenceBundle 是只追加版本：照片原件、预处理产物、模型输入、模型输出、人工动作、门店门头照、定位采样等都通过 role 关联；新版本不能覆盖旧版本。

- [ ] **Step 3: 实现本机 CAS 后端**

本地路径为 `${APP_ASSET_ROOT}/sha256/ab/cd/<full_sha256>`；先写同目录临时文件、`fsync`、校验哈希，再原子 rename。数据库提交失败时 blob 保留为 orphan candidate，后台只生成清理候选报告，Stage 0–1 禁止自动删除。

~~~python
def _object_path(root: Path, digest: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("invalid sha256")
    path = root / "sha256" / digest[:2] / digest[2:4] / digest
    if root.resolve() not in path.resolve().parents:
        raise ValueError("path escape")
    return path
~~~

配置新增 `APP_ASSET_ROOT`，默认只允许 worktree 下 `var/assets`；测试使用 pytest 临时目录，不读取真实照片目录。

- [ ] **Step 4: 实现证据服务和保留状态机**

保留状态：`active`、`expired_candidate`、`legal_hold`、`business_hold`、`purge_approved`。任何物理删除都需要独立审批事件；本阶段 `purge()` 默认永远拒绝，避免 Agent 自动清理。生成 `verify_bundle(bundle_id)`，逐项验证数据库哈希、blob 哈希、scope 和 lineage。

- [ ] **Step 5: 执行测试与故障注入**

~~~bash
PYTHONDONTWRITEBYTECODE=1 APP_DATABASE_URL=postgresql+psycopg://<user>:<password>@127.0.0.1:55432/sku_graph_test APP_ASSET_ROOT=/tmp/llm-image-cas-test python3 -m pytest -p no:cacheprovider tests/unit/platform/assets tests/integration/test_asset_evidence.py -q
~~~

故障注入必须证明：写一半进程退出不产生有效 Asset；数据库失败不覆盖已有 blob；blob 被人工篡改后 `verify_bundle` 报 `hash_mismatch`；没有任何测试访问业务原图。

- [ ] **Step 6: 提交**

~~~bash
git add src/platform/assets src/platform/api/settings.py .env.example tests/unit/platform/assets tests/integration/test_asset_evidence.py
git commit -m "feat(platform): add immutable assets and evidence chain"
~~~

## Task 20: 建立通用 Job、Attempt、Outbox 和隔离 Worker

**Files:**
- Create: src/platform/jobs/__init__.py
- Create: src/platform/jobs/contracts.py
- Create: src/platform/jobs/repository.py
- Create: src/platform/jobs/worker.py
- Create: src/platform/jobs/handlers.py
- Create: tests/unit/platform/jobs/test_retry_policy.py
- Create: tests/integration/test_job_worker.py
- Create: scripts/run_job_worker.sh
- Modify: src/platform/api/settings.py

- [ ] **Step 1: 写 lease、幂等和死信失败测试**

~~~python
def test_two_workers_cannot_claim_same_job(job_repo, queued_job):
    first = job_repo.claim(worker_id="w1", lease_seconds=30)
    second = job_repo.claim(worker_id="w2", lease_seconds=30)
    assert first.job_id == queued_job.job_id
    assert second is None


def test_expired_lease_reuses_job_but_creates_new_attempt(job_repo, queued_job, clock):
    first = job_repo.claim("w1", 30)
    clock.advance(seconds=31)
    second = job_repo.claim("w2", 30)
    assert second.job_id == first.job_id
    assert second.attempt_no == first.attempt_no + 1


def test_retry_budget_exhaustion_moves_to_dead_letter(worker, failing_job):
    worker.drain(max_cycles=10)
    assert worker.repo.read(failing_job.job_id).status == "dead_letter"
    assert worker.repo.count_usage(failing_job.idempotency_key) == 0
~~~

- [ ] **Step 2: 固定 Job 契约**

固定状态：`queued`、`leased`、`running`、`succeeded`、`retry_wait`、`failed`、`dead_letter`、`cancelled`。必填：tenant/project/module/job_type/payload_schema_version/idempotency_key/priority/available_at/max_attempts/timeout_seconds/resource_class。资源档位固定为 `cpu_small`、`cpu_large`、`gpu_optional`、`gpu_required`、`network_io`；本机 Worker 通过允许列表认领，不能执行任意 shell 或 import path。

~~~python
class JobHandler(Protocol):
    job_type: str
    payload_model: type[BaseModel]

    def execute(self, context: JobContext, payload: BaseModel) -> JobResult: ...
~~~

- [ ] **Step 3: 实现数据库队列与 Outbox/Inbox**

claim 使用 `FOR UPDATE SKIP LOCKED`；成功事务同时写 Attempt、Job 状态、OutboxEvent、UsageEvent 候选；消费者以 `event_id + consumer_id` 写 InboxReceipt。网络调用发生在数据库事务外，但必须使用稳定 idempotency key；完成提交使用 compare-and-swap 校验 lease owner 和 attempt。

- [ ] **Step 4: 实现 Worker 资源和背压策略**

每个 Worker 通过 `APP_JOB_WORKER_CLASSES`、`APP_JOB_WORKER_CONCURRENCY`、`APP_JOB_TENANT_MAX_INFLIGHT` 限流。优先级不能让低优先队列永久饥饿；每 10 次认领至少检查一次最低优先级。SIGTERM 停止认领，等待当前 attempt 到安全边界，不把未知结果标成功。

- [ ] **Step 5: 运行并发和恢复测试**

~~~bash
PYTHONDONTWRITEBYTECODE=1 APP_DATABASE_URL=postgresql+psycopg://<user>:<password>@127.0.0.1:55432/sku_graph_test python3 -m pytest -p no:cacheprovider tests/unit/platform/jobs tests/integration/test_job_worker.py -q
~~~

Expected: 4 个 Worker 并发处理 1000 个无副作用测试 Job，成功 1000、重复 handler 0、丢失 0、永久 leased 0；强制中断一个 Worker 后全部恢复；恶意 payload 不能调用 shell、文件路径或未注册 handler。

- [ ] **Step 6: 提交**

~~~bash
git add src/platform/jobs src/platform/api/settings.py scripts/run_job_worker.sh tests/unit/platform/jobs tests/integration/test_job_worker.py
git commit -m "feat(platform): add durable jobs and isolated workers"
~~~

## Task 21: 建立 DataProduct、Lineage 与统一 WorkItemProjection

**Files:**
- Create: src/platform/data/resources.py
- Create: src/platform/data/lineage.py
- Create: src/platform/data/work_items.py
- Create: contracts/data/v1/resource-ref.schema.json
- Create: contracts/data/v1/data-product.schema.json
- Create: contracts/data/v1/work-item.schema.json
- Create: tests/unit/platform/data/test_resources.py
- Create: tests/integration/test_work_item_projection.py
- Modify: scripts/export_contracts.py

- [ ] **Step 1: 写跨模块边界失败测试**

~~~python
def test_data_product_requires_versioned_contract_and_lineage():
    with pytest.raises(ValidationError):
        DataProduct(
            product_id="recognized_items",
            producer_module="fmcg_vision",
            contract_version="latest",
            resources=[],
            lineage=[] ,
        )


def test_projection_is_not_a_domain_write_api(work_items, principal):
    with pytest.raises(AttributeError):
        work_items.update_domain_payload(principal, "item-1", {"approved": True})


def test_consumer_cannot_resolve_resource_outside_scope(resource_service, tenant_a_ref, tenant_b_principal):
    assert resource_service.resolve(tenant_b_principal, tenant_a_ref) is None
~~~

- [ ] **Step 2: 实现版本化资源与数据产品**

`ResourceRef` 只表达身份和版本，不嵌入路径；`DataProduct` 固定 producer、contract URI/version、资源集合、生成时间、输入 lineage、质量摘要和权限标签。Lineage 边固定 `derived_from`、`reviewed_from`、`corrected_from`、`exported_from`、`trained_from`，禁止自由文本替代关系类型。

~~~python
class DataProduct(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    product_id: UUID
    product_type: str
    producer_module: str
    contract_uri: str
    contract_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    resources: tuple[ResourceRef, ...]
    lineage: tuple[LineageEdge, ...]
    quality_summary: dict[str, int | float | str]
    policy_labels: frozenset[str]
    created_at: datetime
~~~

- [ ] **Step 3: 实现只读工作项投影**

统一工作台只读 `projection.work_item`：`work_item_id/tenant/project/module/type/title/status/priority/assignee/due_at/source_ref/action_contract/updated_at`。领域模块通过 Outbox 发布投影事件；平台 projector 幂等 upsert 投影。用户点击操作时，API 根据 `action_contract` 调回模块 DomainCommand；WorkItemService 本身没有领域写方法。

测试覆盖：乱序事件、重复事件、模块禁用、历史任务查询、跨租户隔离、source resource 缺失、投影重建。投影丢失可以由事件重放恢复，不影响领域事实。

- [ ] **Step 4: 导出三份契约并验证稳定性**

~~~bash
python3 scripts/export_contracts.py
shasum -a 256 contracts/data/v1/resource-ref.schema.json contracts/data/v1/data-product.schema.json contracts/data/v1/work-item.schema.json
python3 scripts/export_contracts.py
git diff --exit-code contracts/data
~~~

Expected: 第二次导出无 diff。

- [ ] **Step 5: 运行测试并提交**

~~~bash
PYTHONDONTWRITEBYTECODE=1 APP_DATABASE_URL=postgresql+psycopg://<user>:<password>@127.0.0.1:55432/sku_graph_test python3 -m pytest -p no:cacheprovider tests/unit/platform/data tests/integration/test_work_item_projection.py -q
git add src/platform/data contracts/data tests/unit/platform/data tests/integration/test_work_item_projection.py scripts/export_contracts.py
git commit -m "feat(platform): add resource lineage and work projections"
~~~

## Task 22: 建立用量、内部成本、客户价格和审计服务

**Files:**
- Create: src/platform/billing/metering.py
- Create: src/platform/billing/rates.py
- Create: src/platform/billing/pricing.py
- Create: src/platform/audit/__init__.py
- Create: src/platform/audit/service.py
- Create: src/platform/audit/export.py
- Create: tests/unit/platform/billing/test_rates.py
- Create: tests/integration/test_metering.py
- Create: tests/integration/test_audit_trail.py
- Modify: src/platform/billing/ledger_repository.py

- [ ] **Step 1: 写财务正确性失败测试**

~~~python
def test_usage_event_is_idempotent_and_integer_only(metering, usage):
    first = metering.record(usage)
    second = metering.record(usage)
    assert first.event_id == second.event_id
    assert metering.count(usage.idempotency_key) == 1
    with pytest.raises(ValidationError):
        usage.model_copy(update={"quantity": 0.1})


def test_cost_and_customer_price_are_separate(metering, completed_usage, rate_cards):
    result = metering.rate(completed_usage, rate_cards)
    assert result.internal_cost_micros != result.customer_price_micros
    assert result.rate_card_version_id is not None


def test_rerating_never_mutates_original_entries(metering, completed_usage, changed_rate_card):
    before = metering.rate(completed_usage)
    after = metering.rerate(completed_usage, changed_rate_card)
    assert before.entry_id != after.entry_id
    assert before.superseded_by == after.entry_id
~~~

- [ ] **Step 2: 固定 Meter 和 RateCard 契约**

Meter 至少支持：`api.request`、`asset.byte_ingested`、`asset.byte_stored_day`、`job.cpu_ms`、`job.gpu_ms`、`model.inference`、`model.input_token`、`model.output_token`、`human.review_item`、`map.request`、`graph.node`。用量 quantity 用整数最小单位；金额用 micros；准确率档位是价格/服务承诺标签，不是伪造计量单位。

RateCard 版本不可变，含生效区间、客户/套餐、meter、阶梯、最低费用、币种、税前规则和舍入规则。历史重算生成 correction entry，永不覆盖原行。

- [ ] **Step 3: 扩展同事务计量与对账**

每个 billable 成功动作必须在其完成事务写 UsageEvent，失败和重试只有明确可计费供应商成本时才记录 cost event，不能重复记客户价格。实现 `reconcile(run_id|job_id|tenant/date)`，比较执行事实、用量、成本、价格；差异输出报告，不自动补账。

- [ ] **Step 4: 建立四类审计链**

`AuditService` 记录：

1. 管理操作：模块启停、权限、RateCard、配置；
2. 决策：Policy allow/deny、模型路由、人工审核；
3. 数据：导入、派生、导出、下载、删除申请；
4. Agent：Graph/Run/Node/capability/input hash/output hash/token/预算。

敏感 payload 只存摘要和 ResourceRef；导出事件含查询条件、字段、行数、文件哈希、发起人。审计表禁止 UPDATE/DELETE。

- [ ] **Step 5: 运行测试和财务不变量查询**

~~~bash
PYTHONDONTWRITEBYTECODE=1 APP_DATABASE_URL=postgresql+psycopg://<user>:<password>@127.0.0.1:55432/sku_graph_test python3 -m pytest -p no:cacheprovider tests/unit/platform/billing tests/integration/test_metering.py tests/integration/test_audit_trail.py -q
~~~

Expected: 重放 10 次同一事件仍只有 1 个原始用量；所有价格条目可追到 RateCard 版本；账本平衡查询差异为 0；越权导出被拒且有 deny 证据。

- [ ] **Step 6: 提交**

~~~bash
git add src/platform/billing src/platform/audit tests/unit/platform/billing tests/integration/test_metering.py tests/integration/test_audit_trail.py
git commit -m "feat(platform): add metering pricing and audit trails"
~~~

## Task 23: 把 React 工作台升级为统一 Web Shell

**Files:**
- Create: web/src/platform/modules/types.ts
- Create: web/src/platform/modules/registry.ts
- Create: web/src/platform/layout/AppShell.tsx
- Create: web/src/platform/features/modules/ModuleAdmin.tsx
- Create: web/src/platform/features/work/WorkInbox.tsx
- Create: web/src/platform/features/audit/AuditExplorer.tsx
- Create: web/src/platform/features/usage/UsageSummary.tsx
- Create: web/src/platform/features/modules/ModuleAdmin.test.tsx
- Create: web/src/platform/features/work/WorkInbox.test.tsx
- Modify: web/src/platform/App.tsx
- Modify: web/src/platform/api/client.ts
- Modify: src/platform/api/main.py
- Create: src/platform/api/routes/modules.py
- Create: src/platform/api/routes/work_items.py
- Create: src/platform/api/routes/usage.py
- Create: src/platform/api/routes/audit.py

- [ ] **Step 1: 写壳层和模块失败测试**

~~~tsx
it("hides disabled module routes but keeps historical work readable", async () => {
  server.use(moduleList([{ module_id: "reference_echo", status: "disabled" }]));
  render(<App />);
  expect(await screen.findByText("统一工作台")).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Reference Echo" })).not.toBeInTheDocument();
  expect(await screen.findByText("历史任务")).toBeInTheDocument();
});

it("does not render a module outside principal scope", async () => {
  server.use(moduleList([{ module_id: "fmcg_vision", status: "enabled", authorized: false }]));
  render(<App />);
  expect(screen.queryByText("FMCG Vision")).not.toBeInTheDocument();
});
~~~

- [ ] **Step 2: 固定 Web Slot 契约**

初始 slot：`navigation.primary`、`workspace.home`、`workspace.tools`、`workspace.detail`、`admin.modules`。后端只返回已授权且 enabled/degraded 的模块贡献；前端 registry 使用明确组件映射，禁止后端下发任意 JS URL。模块加载失败由 ErrorBoundary 隔离，不能白屏整个系统。

~~~ts
export type ModuleContribution = {
  moduleId: string;
  version: string;
  status: "enabled" | "degraded";
  slots: readonly { slot: WebSlot; componentKey: string; route: string }[];
};
~~~

- [ ] **Step 3: 实现统一工作台页面**

AppShell 固定提供：全局租户/项目上下文、模块导航、统一工作项、Graph Run、审计、用量、系统健康。ModuleAdmin 展示版本、依赖、迁移、健康、feature flag 和影响预览；Stage 0–1 的 enable/disable 按钮必须二次确认并要求 `module:admin`，不允许卸载或删除数据。

- [ ] **Step 4: 实现受 scope 保护的 API**

路由返回稳定分页 envelope；模块列表基于 Registry + IAM；WorkItem 只查询投影；Usage 只读汇总；Audit 默认不返回敏感 payload。跨租户仍返回 404。OpenAPI 重新导出并验证无未说明 breaking change。

- [ ] **Step 5: 测试可访问性、隔离和构建**

~~~bash
cd web
npm test
npm run lint
npm run build
cd ..
PYTHONDONTWRITEBYTECODE=1 APP_DATABASE_URL=postgresql+psycopg://<user>:<password>@127.0.0.1:55432/sku_graph_test python3 -m pytest -p no:cacheprovider tests/integration/test_control_plane_api.py -q
~~~

Expected: 键盘可操作、loading/empty/error/unauthorized/degraded 状态均有测试；禁用一个模块不影响 Shell 和另一模块；生产 build 成功。

- [ ] **Step 6: 提交**

~~~bash
git add web/src/platform src/platform/api/main.py src/platform/api/routes contracts/openapi/control-plane-v1.json tests/integration/test_control_plane_api.py
git commit -m "feat(web): add modular platform shell"
~~~

## Task 24: 将两个验证模块打包并证明 Foundation 不依赖业务模块

**Files:**
- Create: src/modules/reference_echo/__init__.py
- Create: src/modules/reference_echo/manifest.json
- Create: src/modules/reference_echo/module.py
- Create: migrations/modules/reference_echo/versions/20260804_0001_echo.py
- Create: src/modules/fmcg_vision/__init__.py
- Create: src/modules/fmcg_vision/manifest.json
- Create: src/modules/fmcg_vision/module.py
- Create: migrations/modules/fmcg_vision/versions/20260804_0001_bridge.py
- Create: tests/architecture/test_module_boundaries.py
- Create: tests/e2e/test_module_isolation.py
- Modify: src/platform/api/dependencies.py

- [ ] **Step 1: 写架构边界失败测试**

~~~python
from pathlib import Path
import ast


def imports_under(path: Path) -> set[str]:
    names: set[str] = set()
    for file in path.rglob("*.py"):
        tree = ast.parse(file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module)
    return names


def test_foundation_does_not_import_domain_modules():
    imports = imports_under(Path("src/platform"))
    assert not {name for name in imports if name.startswith("src.modules")}


def test_modules_do_not_import_each_other():
    for module in Path("src/modules").iterdir():
        if module.is_dir():
            assert not any(
                name.startswith("src.modules.") and not name.startswith(f"src.modules.{module.name}")
                for name in imports_under(module)
            )
~~~

- [ ] **Step 2: 创建显式 composition root**

只有顶层 composition root 可以同时 import Foundation 和模块工厂；将该文件放在 `src/app/composition.py`，不放进 `src/platform`。工厂列表为发行版构建配置，不可由数据库或请求动态注入。

~~~python
from src.modules.fmcg_vision.module import build_module as build_fmcg
from src.modules.reference_echo.module import build_module as build_echo
from src.platform.modules.registry import ModuleRegistry


def build_module_registry() -> ModuleRegistry:
    return ModuleRegistry.from_factories({
        "reference_echo": build_echo,
        "fmcg_vision": build_fmcg,
    })
~~~

- [ ] **Step 3: 打包 Reference Echo**

Echo module 只贡献 `core.echo`、一条 Graph、一个 meter、一个人工确认 action 和一个 Web slot。自有 schema 只存示例 domain record，绝不写 FMCG 或平台表；通过 Foundation repository/service 完成 Graph、Usage、Audit 和 WorkItemProjection。

- [ ] **Step 4: 打包 FMCG Vision Bridge**

Bridge 只贡献 `vision.recognize.legacy`、最小识别 Graph、识别用量 meter 和旧 8091 adapter。不得把旧 SQLite 宣称为新平台事实库；adapter 的输出以 versioned DataProduct + EvidenceBundle 引用保存。8091 不健康时模块为 degraded，Echo 和 Shell 必须继续运行。

- [ ] **Step 5: 执行模块隔离矩阵**

~~~bash
PYTHONDONTWRITEBYTECODE=1 APP_DATABASE_URL=postgresql+psycopg://<user>:<password>@127.0.0.1:55432/sku_graph_test python3 -m pytest -p no:cacheprovider tests/architecture/test_module_boundaries.py tests/e2e/test_module_isolation.py -q
~~~

矩阵必须证明：

1. 禁用 Echo，FMCG Bridge 正常；
2. 禁用 FMCG Bridge，Echo 正常；
3. FMCG 迁移失败，Foundation 和 Echo ready；
4. 8091 超时只使 FMCG degraded；
5. 模块历史 Run、Evidence、Usage 仍可读；
6. 任何模块不能写另一个 schema；
7. Foundation AST 无 `src.modules` import；
8. 两模块 manifest 契约和 SHA 可重复验证。

- [ ] **Step 6: 提交**

~~~bash
git add src/app/composition.py src/modules migrations/modules tests/architecture/test_module_boundaries.py tests/e2e/test_module_isolation.py src/platform/api/dependencies.py
git commit -m "feat(modules): package foundation verification modules"
~~~

## Task 25: 完成本机运维、备份恢复、性能和安全验收

**Files:**
- Create: scripts/bootstrap_foundation.py
- Create: scripts/verify_foundation.py
- Create: scripts/backup_foundation.sh
- Create: scripts/restore_foundation_test.sh
- Create: scripts/benchmark_foundation.py
- Create: docs/runbooks/unified-foundation-local.md
- Create: docs/experiments/UF0-foundation-execution-evidence.md
- Create: tests/e2e/test_foundation_recovery.py
- Modify: config/services.yaml
- Modify: compose.yaml

- [ ] **Step 1: 建立幂等 bootstrap 和 verify 命令**

`bootstrap_foundation.py` 只创建测试/本机 tenant、project、bootstrap principal、两模块安装记录和发布 Graph；重复运行不新增重复事实。`verify_foundation.py` 只读检查数据库 revision、对象根目录、模块状态、Graph、Worker 心跳、Outbox backlog、审计追加性和旧服务端口，输出 JSON 并以非零退出码表示失败。

~~~bash
APP_ENV=local python3 scripts/bootstrap_foundation.py
APP_ENV=local python3 scripts/bootstrap_foundation.py
APP_ENV=local python3 scripts/verify_foundation.py --json
~~~

Expected: 第二次 bootstrap 为 `changed=false`；verify 为 `status=ready`；不写生产/历史数据库。

- [ ] **Step 2: 实现非破坏备份和隔离恢复演练**

备份包含 PostgreSQL 自定义格式 dump、Manifest/Graph/contract SHA 清单、CAS inventory、配置模板和版本信息；不包含明文 secret。`restore_foundation_test.sh` 只能恢复到名称含 `_restore_test` 的数据库和临时 CAS 根，发现其他目标立即退出。脚本禁止清理原备份和测试恢复产物，统一在报告中列出，由用户决定是否删除。

- [ ] **Step 3: 执行 Foundation 性能门**

测试机记录 CPU、内存、磁盘、Python、PostgreSQL 配置。最低门：

- 1000 Echo Graph Run、并发 16：创建 p95 ≤250ms，最终完成率 100%；
- 10,000 Job、4 Worker：重复执行 0、永久 lease 0、恢复后 backlog 0；
- 10,000 WorkItem 投影重放：最终一致 100%，重复事实 0；
- 10,000 UsageEvent 对账：差异 0；
- 1,000 个 1MiB 测试 blob：同内容去重，bundle verify 100%；
- Web Shell 首次本机构建产物 gzip 后主壳 JS 目标 ≤500KiB，模块 chunk 独立；超标必须解释或优化。

~~~bash
APP_DATABASE_URL=postgresql+psycopg://<user>:<password>@127.0.0.1:55432/sku_graph_test APP_ASSET_ROOT=/tmp/llm-image-foundation-bench python3 scripts/benchmark_foundation.py --runs 1000 --jobs 10000 --work-items 10000 --usage-events 10000 --blobs 1000
~~~

- [ ] **Step 4: 执行安全和故障矩阵**

必须覆盖：跨 tenant/project、伪造 ResourceRef、Graph 条件注入、任意 import、任意 shell、任意 SQL、路径穿越、超大 URL 下载、MIME 伪装、SSRF 私网地址、重复计费、过期 token、模块依赖环、数据库重启、Worker SIGKILL、CAS 只读、Outbox 堆积、模块升级失败。每项记录预期/实际/证据；未知结果一律 FAIL。

- [ ] **Step 5: 跑全量测试并生成 UF0**

~~~bash
XONSH_HISTORY_BACKEND=dummy PYTHONDONTWRITEBYTECODE=1 APP_DATABASE_URL=postgresql+psycopg://<user>:<password>@127.0.0.1:55432/sku_graph_test APP_BOOTSTRAP_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx APP_ASSET_ROOT=/tmp/llm-image-foundation-test GRAPH_KERNEL_ENABLED=true python3 -m pytest -p no:cacheprovider -q
cd web
npm test
npm run lint
npm run build
cd ..
git diff main...HEAD --check
~~~

UF0 记录基线/最终测试数、迁移、契约 SHA、两模块版本、性能原始输出、恢复结果、安全矩阵、备份恢复、磁盘增长、已知风险，以及 `production_switch=false`、`training_started=false`、`deleted_files=false`。

- [ ] **Step 6: 提交**

~~~bash
git add scripts/bootstrap_foundation.py scripts/verify_foundation.py scripts/backup_foundation.sh scripts/restore_foundation_test.sh scripts/benchmark_foundation.py docs/runbooks/unified-foundation-local.md docs/experiments/UF0-foundation-execution-evidence.md tests/e2e/test_foundation_recovery.py config/services.yaml compose.yaml
git commit -m "test(platform): verify local foundation operations"
~~~

## Task 26: Foundation Milestone 最终门禁与停止点

**Files:**
- Create: docs/experiments/UF1-foundation-acceptance.md
- Modify: docs/experiments/UF0-foundation-execution-evidence.md

- [ ] **Step 1: 只读审计实现范围**

~~~bash
git status --short
git diff main...HEAD --stat
git diff main...HEAD --check
git diff main...HEAD --name-only
git log --oneline main..HEAD
~~~

Expected: 不出现真实原图、SQLite、模型、训练数据、secret、运行日志或生成数据库；每个任务有独立提交；没有无关用户文件。

- [ ] **Step 2: 填写 Foundation 验收矩阵**

| 门禁 | 通过条件 |
|---|---|
| F-01 唯一架构 | 实现与 L0 SSOT 一致，无第二套底座 |
| F-02 Module SDK | Manifest、依赖、兼容、生命周期和契约 SHA 通过 |
| F-03 依赖方向 | Foundation 不 import Domain Pack；模块不互相 import |
| F-04 数据所有权 | 平台/模块 schema 隔离，跨域只走正式契约 |
| F-05 Graph+Loop | 有界、可恢复、可审计、人工节点可跨重启 |
| F-06 IAM | tenant/project/module/data domain fail-closed |
| F-07 Asset/Evidence | CAS 不可变，来源/派生/人工动作可验证 |
| F-08 Job/Event | lease、重试、死信、Outbox/Inbox 无丢失重复 |
| F-09 Billing/Audit | 用量、成本、价格分离，对账差异为 0 |
| F-10 Web Shell | 模块插槽、统一工作项、审计和用量可用 |
| F-11 双模块隔离 | Echo/FMCG 可独立启停、升级失败不拖垮平台 |
| F-12 兼容旧系统 | 8091/8304 未切换，原基线测试无回归 |
| F-13 运维恢复 | 幂等 bootstrap、备份、隔离恢复、故障矩阵通过 |
| F-14 性能 | Task 25 全部门槛通过并保留原始结果 |
| F-15 安全与保留 | 无任意执行、越权、自动删除或证据覆盖 |

任一门禁 FAIL，结论必须写 `NOT ACCEPTED`；不得用“基本可用”或“后续补齐”替代失败。

- [ ] **Step 3: 运行最终验证**

~~~bash
APP_ENV=local python3 scripts/verify_foundation.py --json
XONSH_HISTORY_BACKEND=dummy PYTHONDONTWRITEBYTECODE=1 APP_DATABASE_URL=postgresql+psycopg://<user>:<password>@127.0.0.1:55432/sku_graph_test APP_BOOTSTRAP_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx APP_ASSET_ROOT=/tmp/llm-image-foundation-test GRAPH_KERNEL_ENABLED=true python3 -m pytest -p no:cacheprovider -q
cd web
npm test
npm run build
cd ..
git diff main...HEAD --check
~~~

- [ ] **Step 4: 提交验收证据并停止**

~~~bash
git add docs/experiments/UF0-foundation-execution-evidence.md docs/experiments/UF1-foundation-acceptance.md
git commit -m "docs(platform): record foundation acceptance"
~~~

提交后停止，向用户报告：门禁、证据路径、commit 列表、未解决风险、磁盘占用、服务端口。不得自动合并、部署、清理、切换旧入口、实施 Stage 2 或启动训练。只有用户审核 `UF1=ACCEPTED` 后，Stage 2 Agent 才能开工。

## 27. 任务依赖顺序

~~~text
Task 1 基线隔离
  → Task 2 依赖与配置
  → Task 3 契约
  → Task 4 Graph 校验
  → Task 5 PostgreSQL schema
  → Task 6 Repository
  → Task 7 Registry/Policy
  → Task 8 纯 Runtime
  → Task 9 Worker/恢复
  → Task 10 Human/Usage/Audit
  → Task 11 FastAPI
  → Task 12 两条最小 Graph
  → Task 13 React 工作台
  → Task 14 本机运行
  → Task 15 E2E/性能
  → Task 16 Graph Kernel 子关卡
  → Task 17 Module SDK/生命周期
  → Task 18 IAM/schema 所有权
  → Task 19 CAS/Evidence
  → Task 20 Job/Outbox/Worker
  → Task 21 DataProduct/WorkItem
  → Task 22 Metering/Pricing/Audit
  → Task 23 Web Shell
  → Task 24 双模块隔离
  → Task 25 运维/恢复/性能/安全
  → Task 26 Foundation 最终门禁
~~~

Tasks 3–4 可在数据库任务前完成；Task 19 的纯契约可与 Task 20 的纯契约并行评审，但落库和装配必须遵循依赖顺序。不得并行修改同一迁移、Repository、composition root、OpenAPI 或 contracts 文件。Task 16 只是子关卡，Task 26 才是 Stage 0–1 完成门。

## 28. 回滚策略

Stage 0-1 的回滚是停用和前向修复，不是删除历史：

1. 设置 GRAPH_KERNEL_ENABLED=false；
2. 停止 Worker 和 8400 控制面；
3. 旧 8091、8304 继续按原入口运行；
4. 回退应用 commit；
5. 保留平台和模块全部 schema、CAS blob、账本、审计和失败证据；
6. 新建修复迁移，不执行 DROP schema 或 downgrade；
7. 已产生的 Run 标记为 paused/failed/cancelled，不删除。
8. 模块故障优先 disable/degraded 隔离；不得卸载 schema 或清理历史资源。
9. RateCard、GraphVersion、Manifest 版本和用量账本只允许前向替代，不允许原地回写。

## 29. 完成定义

只有同时满足以下条件，才能称为 Stage 0-1 完成：

- Graph+Loop 是实际运行主干，不是前端聊天框。
- Module SDK 是所有业务模块的唯一接入方式，Foundation 不 import Domain Pack。
- 识别是 vision.recognize Capability，不在 Runtime 中出现 FMCG 特例。
- Reference Echo 与 FMCG Vision Bridge 可独立启停、独立迁移、独立降级。
- IAM 同时控制 tenant、project、module、capability 和 data domain，默认拒绝。
- CAS 与 EvidenceBundle 保存原始、派生、模型和人工证据，任何版本不可覆盖。
- Job/Attempt/Outbox/Inbox 在崩溃和重试下无丢失、无重复成功、无重复计费。
- ResourceRef、DataProduct 和 WorkItemProjection 是跨模块统一数据接口。
- Run、Node、Checkpoint、Policy、Usage 和 Audit 可从 PostgreSQL 关联查询。
- published Graph 和追加式事实不可被覆盖。
- Worker 崩溃恢复不重复外部调用或计费。
- Agent/API 无法越租户、越项目、扩大工具或预算。
- HumanTask 可以跨重启暂停和恢复。
- React Web Shell 展示模块、Graph、Run、统一工作项、审计和用量，模块故障不导致整站白屏。
- 用量、内部成本和客户价格分层，任何账目可按版本重放与对账。
- 本机 bootstrap、备份、隔离恢复、性能和安全矩阵全部通过。
- 原 74 项测试及新增测试全部通过。
- 没有删除、覆盖或静默迁移任何历史业务数据。
- 没有切换生产模型、生产入口或启动训练。
