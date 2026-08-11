# 模块与 Agent 开发指南（Domain Pack 扩展手册）

> 面向后续开发 Agent/工程师。平台唯一事实源：`src/platform/registry.py`
> 的 `ModuleManifestV2` + `src/platform/module_catalog.py` 目录。
> 红线：平台（`src/platform`）不得 import Domain Pack；模块不得复制
> 身份/租户/证据/任务/审计/计费底座；Agent 不得直接 SQL/写客户数据。

## 1. 创建一个新 Domain Pack（以“问卷”为例）

1. **后端 Manifest**：在 `src/platform/module_catalog.py` 的
   `build_default_module_registry()` 中把模块从 planned 骨架扩展为完整声明
   （或新建 `src/modules/<domain>/manifest.py` 经组合根注册）：

```python
ModuleManifestV2(
    module_id="survey", name="调研与问卷", version="0.2.0",
    domain="survey", status="live",            # 有真实后端才可 live
    theme_token="cyan", primary_route="/survey",
    navigation=(NavRoute(route="/survey/design", label="问卷设计",
                         actions=("新建问卷", "发布")),),
    agents=("survey_agent",),
    capabilities=(CapabilitySpec(capability_id="survey.form.create",
                                 kind="survey"),),
    commands=("survey.form.create",), queries=("survey.forms.list",),
    events=("survey.response.received",),
    api_prefix="/api/v1/survey", openapi_tag="survey",
    data_products=("survey.responses_v1",),
    permission_scopes=("survey.read", "survey.manage"),
    billing_units=("response",),
    health_checks=(),
)
```

2. **注册校验自动生效**（fail-closed）：route/module_id/capability/agent
   冲突抛 `RegistryError`；依赖缺失自动投影为 degraded。
3. **领域服务与 API**：`src/modules/<domain>/service.py` +
   `src/platform/api/<domain>_api.py`（router 经 `create_app` 注入；
   身份用 `require_principal(auth, request)`，写操作 `csrf=True`）。
4. **前端**：`web/src/pages/` 新增页面；路由在 `web/src/App.tsx`
   按 Registry 的 navigation route 挂载；导航自动从 `/api/v1/modules`
   投影生成，无需改 PrimaryNav。
5. **迁移**：新表加编号迁移进 `src/platform/data/store.py` `MIGRATIONS`
   （幂等、append-only、带 tenant/project 列）。

## 2. ModuleManifestV2 字段速查

module_id / name / version / domain / status(live|beta|planned|degraded|disabled)
/ theme_token / primary_route / navigation(route,label,description,actions)
/ agents / capabilities / commands / queries / events / api_prefix
/ openapi_tag / data_products / permission_scopes / ui_slots
/ feature_flags / dependencies / compatibility / billing_units / health_checks。

## 3. Agent 接入

- AgentManifest 内置于 `src/platform/agents/kernel.py` `_BUILTIN`
  （首次访问自动 seed 进 `agent_manifest_v1`）。新增 Agent：
  capability_scopes 必须在 `GRANTABLE_SCOPES` 白名单内（新 scope 要先加白）。
- 模块↔Agent 关联在 ModuleManifestV2.agents（冲突 fail-closed）。
- 统一响应契约（前端实际消费）：
  `message / evidence_refs / ui_intents / command_previews / tasks /
  delegations / memory_updates / requires_approval / trace_id`。
- UIIntent 白名单：`navigate / open_panel / filter / highlight / compare /
  pin / show_evidence`；禁 html/js/script 字段（`validate_ui_intent`）。
- 高风险（production.switch、data.delete、publish.auto、finance.finalize）
  必须拒绝或两阶段人工批准；批准/拒绝落 `agent_command_v1` 并有
  decided_by/decided_at 审计。
- 命令批准后执行必须经组合根注入的钩子（参考
  `build_agent_approval_hook`），Agent 不直接写库。

## 4. 识别契约参考（所有域的命令模式样例）

`POST /api/v1/recognition/tasks/upload|url`：
- 必填 `recognition_profile_id`（只接受注册且 enabled 的 ID；
  拒绝 `.pt`/路径形式输入）、`service_tier`、`source`；可选 project_id；
  `Idempotency-Key` 头幂等。
- 响应回显冻结契约：profile/tier/source/trace_id；任务行持久化同样字段。
- 跨域复用：把“Profile/档位/幂等/trace/诚实错误”抄进你的域命令。

## 5. Data Product 与跨域

跨域只消费注册的 Data Product（schema/version/scope/freshness/PII/
retention/consumers/billing），不 join 他域私有表。BI 只读
`vision.recognition_daily_v1` 这类产品，禁止读取训练报告冒充经营数据。

## 6. 测试与验收要求

- 新模块必须附：Manifest 冲突测试、API 行为测试（登录/CSRF/幂等/
  fail-closed）、前端静态契约（`tests/contract/` 模式）。
- 全量：
  `python -m pytest -q -m "not host_mps"`（hermetic）与 `-m host_mps` 分开。
- 前端：`cd web && npm run typecheck && npm run build`。
- planned 模块不得带假数据/假图表；degraded 必须给出真实原因。

## 7. 参考实现索引

| 主题 | 位置 |
|---|---|
| Manifest/Registry | `src/platform/registry.py`、`src/platform/module_catalog.py` |
| 模块 API 投影 | `src/platform/api/modules_api.py` |
| 非识别参考模块 | `src/modules/reference_echo/`、`/api/v1/reference/echo` |
| 识别统一任务 | `src/platform/api/recognition_tasks.py` |
| Profile 派生 | `src/modules/training_control/profiles.py` |
| Agent 运行时 | `src/platform/agents/supervisor.py`、`src/platform/api/agent_runtime_api.py` |
| 前端壳层 | `web/src/App.tsx`、`web/src/platform/` |
| 栈控制 | `bin/abos` |
