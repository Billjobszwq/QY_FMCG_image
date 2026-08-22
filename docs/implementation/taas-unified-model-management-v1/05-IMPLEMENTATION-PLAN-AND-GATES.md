# TaaS Unified Model Management V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` only when the user explicitly authorizes subagents; otherwise use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 TaaS 内实现独立系统级模型管理模块，安全管理本地OMLX与OpenAI/OpenAI-compatible/Anthropic模型，为系统能力、模块和Agent分配模型，并完成账号级计量、监控、审批、Canary、回滚与Research RAG真实语义Gate。

**Architecture:** 复用现有FastAPI、SQLite、IAM/Scope、Governance、Agent Definition、Usage、Cognition和React桌面。新增Connection/Catalog/Binding/SecretStore/Adapter/Resolver薄层；Provider调用继续进入现有Run/Event/Usage/Evidence，不建立平行运行内核。

**Tech Stack:** Python 3.11–3.13、FastAPI、Pydantic、SQLite、AES-256-GCM、OpenAI SDK、Anthropic SDK或等价受控HTTP Adapter、React 19、TypeScript、Vitest、Playwright、Pytest。

---

## 0. 执行纪律

- M1→M10顺序执行；前一Gate不通过不得伪装完成后一Task。
- 所有行为变化先写红测试，再做最小实现，再跑相邻回归。
- 新迁移从072开始，禁止修改001–071。
- live DB只读；迁移验证仅使用`mktemp -d`中的显式副本。
- Secret不得出现在命令行、文档、日志、测试快照或Git。
- 未获明确授权跳过commit/stage/push，但不能因此跳过测试或状态记录。
- 不删除任何文件。旧`/vision/models`在兼容别名验收完成前不得移除。

## 1. 文件责任图

### 新建后端

```text
src/platform/models/__init__.py
src/platform/models/contracts.py              # fail-closed Pydantic合同与枚举
src/platform/models/endpoint_policy.py        # URL/SSRF/DNS/redirect策略
src/platform/models/secrets.py                # SecretStore port + AES-GCM adapter
src/platform/models/repository.py              # Connection/Catalog/Binding持久化
src/platform/models/resolver.py                # scope-first绑定解析
src/platform/models/providers/base.py          # Adapter协议与规范化结果
src/platform/models/providers/openai_compatible.py
src/platform/models/providers/anthropic.py
src/platform/models/metering.py                # model_call/Usage/预算结算
src/platform/models/service.py                 # 生命周期、probe、审批、CAS、回滚
src/platform/api/model_management_api.py       # /api/v1/models/*
scripts/reconcile_model_management.py          # 只读对账
tests/models/helpers.py
tests/models/test_contracts_and_migrations.py
tests/models/test_secret_store_and_endpoint_policy.py
tests/models/test_provider_adapters.py
tests/models/test_repository_resolver.py
tests/models/test_model_management_api_security.py
tests/models/test_metering_budget_monitoring.py
tests/models/test_release_canary_rollback.py
tests/models/test_omlx_embedding_e2e.py
```

### 新建前端

```text
frontend/src/pages/models/Connections.tsx
frontend/src/pages/models/Catalog.tsx
frontend/src/pages/models/Bindings.tsx
frontend/src/pages/models/Governance.tsx
frontend/src/pages/models/LocalModels.tsx
frontend/src/pages/models/modelPages.test.tsx
frontend/src/modules/registry.test.tsx
frontend/e2e/model-management.spec.ts
```

### 修改

```text
pyproject.toml
src/platform/data/store.py
src/platform/iam.py
src/platform/module_catalog.py
src/platform/api/app.py
src/platform/api/health.py
src/platform/cognition/composition.py
src/platform/cognition/index/catalog.py
src/platform/cognition/index/gateway.py
src/platform/cognition/index/providers.py
src/platform/agents/runtime.py
src/platform/agents/definition_service.py
src/common/omlx.py
src/catalog/build_kb.py
src/labeling/assign.py
src/pipeline/recognize.py
frontend/src/lib/api.ts
frontend/src/store/auth.ts
frontend/src/modules/registry.tsx
frontend/src/pages/DemoDesktop.tsx
frontend/src/pages/vision/Models.tsx
scripts/eval_research_rag.py
scripts/reconcile_cognition.py
```

## M1：只读基线、保护测试与迁移072–074

**Files:** `src/platform/data/store.py`、`tests/models/test_contracts_and_migrations.py`、`scripts/reconcile_model_management.py`

- [ ] **Step 1：写迁移保护红测试**

```python
def test_model_migrations_are_append_only_and_start_at_072():
    names = [name for name, _ in MIGRATIONS]
    assert names[-3:] == [
        "072_model_management_core_v1",
        "073_model_secret_envelope_v1",
        "074_model_usage_metering_v1",
    ]
    assert len(names) == len(set(names))

def test_readonly_preflight_does_not_upgrade_live_copy(tmp_path):
    db = copy_database_at_068(tmp_path)
    before = fingerprint(db)
    result = readonly_model_preflight(db)
    assert result["migration_count"] == 68
    assert fingerprint(db) == before
```

- [ ] **Step 2：运行红测试**

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q tests/models/test_contracts_and_migrations.py -x
```

Expected：FAIL，072–074尚不存在。

- [ ] **Step 3：实现纯追加schema**

按01文档创建Connection/Catalog/Binding/Secret表，向`usage_event_v2`追加归属列；为active唯一性、scope查询和model_call查询创建索引。不得drop、rename或重建旧表。

- [ ] **Step 4：实现只读对账脚本**

输出integrity、migration count、active connection/binding唯一性、orphan catalog/binding、secret metadata、usage未归属和Embedding索引身份漂移。任一漂移exit 1。

- [ ] **Step 5：验证副本迁移与幂等**

```bash
tmp_dir="$(mktemp -d)"
cp runtime/platform/platform.sqlite "$tmp_dir/platform.sqlite"
PYTHONPATH=src .venv/bin/python -m pytest -q tests/models/test_contracts_and_migrations.py
PYTHONPATH=src .venv/bin/python scripts/reconcile_model_management.py --db "$tmp_dir/platform.sqlite" --read-only
```

Expected：测试副本升级到074；live DB hash不变；临时目录保留并记录。

## M2：合同、SecretStore与EndpointPolicy

**Files:** `contracts.py`、`secrets.py`、`endpoint_policy.py`、`test_secret_store_and_endpoint_policy.py`

- [ ] **Step 1：写fail-closed合同红测试**

```python
def test_connection_contract_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        ConnectionDraft.model_validate({
            "name": "x", "location": "api",
            "adapter_kind": "openai_compatible",
            "base_url": "https://example.com/v1",
            "unexpected": "blocked",
        })
```

同时断言非法状态、capability、负timeout、明文`api_key`进入Connection config均拒绝。

- [ ] **Step 2：写加密与泄漏红测试**

```python
ref = store.put(scope, b"known-secret", actor="maker")
row = raw_secret_row(ref)
assert b"known-secret" not in bytes(row["ciphertext"])
assert store.lease(ref, scope).value == b"known-secret"
assert "known-secret" not in repr(ref)
assert "known-secret" not in json.dumps(public_connection_view())
```

断言错误KEK、AAD scope不符、revoke后lease、缺KEK全部fail-closed。

- [ ] **Step 3：写SSRF红测试**

拒绝`file://`、userinfo、loopback外部模式、metadata IP、link-local、DNS重绑定和重定向到私网；允许`local + http://127.0.0.1`与`api + https://批准域名`。

- [ ] **Step 4：实现最小合同和安全端口**

使用Pydantic `ConfigDict(extra="forbid")`；AESGCM随机DEK/nonce；KEK只从注入读取；EndpointPolicy在保存、test和实际调用三处共用。

- [ ] **Step 5：验证**

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q \
  tests/models/test_secret_store_and_endpoint_policy.py \
  tests/platform/test_si2_scope_isolation.py
```

Expected：所有泄漏、跨scope和SSRF负例通过。

## M3：OpenAI-compatible与Anthropic Adapter

**Files:** `providers/*`、`pyproject.toml`、`tests/models/test_provider_adapters.py`

- [ ] **Step 1：建立本地契约HTTP服务器测试**

Fake server分别实现OpenAI `/models`、`/embeddings`、`/chat/completions`和Anthropic `/v1/models`、`/v1/messages`；记录收到的header但测试失败输出必须先净化。

- [ ] **Step 2：写规范化红测试**

```python
result = adapter.chat(ChatRequest(model_id="m", messages=[...]))
assert result.model_id == "m"
assert result.usage.input_tokens == 11
assert result.usage.output_tokens == 7
assert result.provider_request_id == "req-1"
assert result.latency_ms >= 0
```

覆盖401、429+Retry-After、超时、非JSON、数量不符和Embedding维度不符。

- [ ] **Step 3：实现Adapter**

Adapter构造参数只接受validated endpoint、secret lease、timeout/retry；`repr`和异常不得包含secret。Anthropic使用原生Messages parser，不复用OpenAI parser。

- [ ] **Step 4：依赖与回归**

在可选依赖组`model-providers`加入实际SDK和`cryptography`；主测试不联网。运行：

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q tests/models/test_provider_adapters.py
```

Expected：所有协议、错误和secret扫描通过。

## M4：Repository、Resolver、生命周期API

**Files:** `repository.py`、`resolver.py`、`service.py`、`model_management_api.py`、`app.py`、对应测试

- [ ] **Step 1：写解析优先级与ACL红测试**

建立tenant/customer/project默认和模块专属绑定，断言project→customer→tenant→deployment顺序；跨tenant查询返回None/404且SQL排序前已过滤。

- [ ] **Step 2：写CAS与状态机红测试**

两个连接同时activate只有一个成功；test失败不修改active；disabled connection不被resolve；未probe模型不能绑定。

- [ ] **Step 3：实现服务**

Repository只返回typed rows；Service负责状态机、审批引用、impact validation和审计；Resolver只读active/canary，绝不解密secret。

- [ ] **Step 4：装配API**

在`create_app`中构造唯一ModelManagementServices并挂`app.state.models`；所有写端点Session+CSRF+IAM，所有资源读取Scope-first并跨租户404。

- [ ] **Step 5：验证**

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q \
 tests/models/test_repository_resolver.py \
 tests/models/test_model_management_api_security.py
```

Expected：401/403/404/409/422/429/503语义和零泄漏通过。

## M5：IAM、Maker/Checker与独立模块投影

**Files:** `iam.py`、`module_catalog.py`、`governance/*`、`registry.tsx`、`auth.ts`、`DemoDesktop.tsx`

- [ ] **Step 1：写权限红测试**

普通员工无八个models scopes；模型管理员可draft/test但不能approve自己；审批人不能rotate secret；财务只有usage read；平台/租户角色严格按scope。

- [ ] **Step 2：写前端导航红测试**

```tsx
expect(visibleGroups(employeeScopes).some(g => g.group === "models")).toBe(false)
expect(visibleGroups(["models.config.read"])).toContainEqual(
  expect.objectContaining({ group: "models" })
)
```

- [ ] **Step 3：注册models ModuleManifestV2**

从vision manifest移除`/vision/models`可见导航，新增models manifest和五个routes。Frontend新增同名group和`requiredScopes`；旧route进入alias map指向`/models/local`。

- [ ] **Step 4：接入已有whoami scopes**

Auth store登录后加载`fetchIamWhoami()`；失败时受限模块fail-closed隐藏。后端授权不因前端结果变化。

- [ ] **Step 5：maker/checker与CAS回归**

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q \
 tests/models/test_model_management_api_security.py \
 tests/governance/test_policy_alert_pause.py
cd frontend && npm test -- registry && npm run build
```

## M6：账号级计量、预算、限流与监控

**Files:** `metering.py`、`store.py`、`usage_api.py`、`rate_limit.py`、`tests/models/test_metering_budget_monitoring.py`

- [ ] **Step 1：写Token规范化红测试**

OpenAI/Anthropic真实Usage分别落`input_token/output_token/cached_input_token/reasoning_token`；无Usage的OMLX只落`embedding_input/input_character/embedding_vector/model_compute_ms`。

- [ ] **Step 2：写账号归属和预算红测试**

每行必须含principal、tenant/customer/project、Agent/module、connection/model/binding、run/work和model_call_id。预留失败不调用Provider；达到硬额度返回429；80%产生Governance Alert。

- [ ] **Step 3：写metering failure红测试**

模拟外部调用成功但Usage finalize失败，断言响应为`MODEL_METERING_INCOMPLETE`、不会自动重放非幂等Chat，并可由reconcile恢复。

- [ ] **Step 4：实现计量和监控查询**

扩展现有Usage API或models usage API，支持按scope/principal/agent/module/model/time过滤，计算p50/p95、错误率、Token和诚实替代单位。

- [ ] **Step 5：验证**

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q \
 tests/models/test_metering_budget_monitoring.py \
 tests/platform/test_abos_v3_usage_workbench.py \
 tests/platform/test_uatcc_rate_limit.py
```

## M7：本地OMLX Embedding与Research RAG Gate

**Files:** `cognition/composition.py`、`catalog.py`、`gateway.py`、`providers.py`、`test_omlx_embedding_e2e.py`

- [ ] **Step 1：把静态provider改为受控Resolver**

Build和Query都使用当前CognitiveContext解析`cognition.embedding`；同一请求冻结Binding Identity。没有managed binding时才暴露`source=legacy_env`回退。

- [ ] **Step 2：用测试Secret配置local-omlx draft**

不得把secret写入测试文件或命令行。真实测试从受控环境/SecretStore读取；未配置则测试skip并报告`BLOCKED_BY_PROVIDER_AUTH`，不得用Fake替代质量证据。

- [ ] **Step 3：真实probe/build/query**

断言模型ID、维度1024、向量数量、finite values、index identity、build/query一致和Usage归属。

- [ ] **Step 4：跑语义Gate**

```bash
PYTHONPATH=src .venv/bin/python scripts/eval_research_rag.py \
  --profile v1-release \
  --out runtime/platform/evidence/model-management-rag-eval.json
```

Expected：`paraphrase.recall_at_10 >= 0.90`且既有citation/ACL/injection/resume/conflict/performance Gate保持通过；失败exit 1。

## M8：Agent与模块消费者迁移

**Files:** `agents/runtime.py`、`definition_service.py`、`common/omlx.py`及三个调用点、对应测试

- [ ] **Step 1：写Agent Definition绑定红测试**

UI/API修改Agent模型只创建新draft；Soul/Prompt/Tools/Budget/Memory ACL字节等价保留；checker批准后发布并重建Manifest；旧版本可回滚。

- [ ] **Step 2：移除直接DeepSeek配置路径**

Agent LLM通过ModelInvocationService解析published Definition；失败保持现有诚实规则降级，并记录明确Provider状态和Usage。

- [ ] **Step 3：建立OMLX兼容Facade**

平台运行态注入ModelInvocationPort；独立CLI允许明确legacy env fallback并在结果标识来源。迁移VLM、OCR、Embedding调用点，不允许全局可变secret。

- [ ] **Step 4：验证消费者**

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q \
 tests/platform/test_abos_v3_agent_runtime.py \
 tests/governance/test_agent_definition_projection.py \
 tests/cognition/test_vector_provider_integration.py \
 tests/models
```

## M9：独立系统UI与浏览器验收

**Files:** `frontend/src/pages/models/*`、`api.ts`、`registry.tsx`、`vision/Models.tsx`、Vitest/Playwright

- [ ] **Step 1：先写组件红测试**

覆盖空态、401、403、409、422、429、503、secret不可回显、测试不激活、maker不能批准自己、Embedding影响预览。

- [ ] **Step 2：实现五个页面**

复用现有PageHeader/ApiTable/StatusBadge/KV/Button/Input/Select和AppWindow；不添加新design tokens或样本数据。

- [ ] **Step 3：迁移LocalModels**

移动当前Models页面内容到`/models/local`，原API和诚实状态不变；`/vision/models`仅兼容转向，不复制组件状态源。

- [ ] **Step 4：浏览器权限与布局测试**

在1024/1280/1440验证管理员、审批人、财务和普通员工；检查DOM/网络响应无secret，旧route兼容，表格/子窗口无溢出。

- [ ] **Step 5：前端Gate**

```bash
cd frontend
npm test
npm run lint
npm run build
npx playwright test e2e/model-management.spec.ts
```

## M10：全量验证、对账与UAT准备

**Files:** `scripts/reconcile_model_management.py`、状态文档、证据报告

- [ ] **Step 1：全量hermetic测试**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  .venv/bin/python -m pytest -p no:cacheprovider -q
```

- [ ] **Step 2：安全与文档检查**

运行secret扫描、SSRF负例、跨tenant负例、`git diff --check`、文档链接/占位符检查；确认没有API Key、用户数据、模型权重或runtime evidence进入stage。

- [ ] **Step 3：迁移/恢复演练**

只在mktemp副本执行068→074、071→074、重复apply、错误KEK、备份恢复和只读对账；live DB hash保持不变。

- [ ] **Step 4：发布Gate汇总**

生成机器可读报告，必须覆盖G0–G9、gold hash、report hash、Provider Identity、Usage归属、浏览器矩阵和回滚证据。任一Gate失败exit 1。

- [ ] **Step 5：状态纪律**

G0–G9全绿才写`READY_FOR_UAT`；人工真实UAT后才写`ACCEPTED`。未获commit、production或deployment授权时保持工作树并报告。

## 2. Gate定义

| Gate | 必须通过 |
|---|---|
| G0 | 基线、live hash、资产保护、迁移预检 |
| G1 | typed contracts、SecretStore、EndpointPolicy、无泄漏 |
| G2 | OpenAI-compatible/Anthropic协议与错误合同 |
| G3 | Repository/Resolver/Scope/CAS/状态机 |
| G4 | 独立模块、IAM、maker/checker、导航零泄漏 |
| G5 | 账号级Usage、Token/替代计量、预算、限流、监控 |
| G6 | OMLX真实Embedding、索引身份、paraphrase Gate |
| G7 | Agent Definition和模块消费者绑定/回滚 |
| G8 | UI build/lint/test/浏览器/secret DOM扫描 |
| G9 | 全量回归、迁移恢复、对账、报告hash |
