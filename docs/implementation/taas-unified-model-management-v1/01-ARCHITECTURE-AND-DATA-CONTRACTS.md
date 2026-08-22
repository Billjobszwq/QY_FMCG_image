# 01｜目标架构与数据契约

## 1. 架构原则

统一模型管理是现有 TaaS 的系统配置模块，不是新的推理平台。它只负责回答三个问题：

1. `ModelConnection`：如何连接模型服务？
2. `ModelCatalogEntry`：连接提供哪些模型和能力？
3. `ModelBinding`：哪个系统能力或模块使用哪个模型？

实际执行继续进入现有 Cognition、Agent Runtime、Vision、Usage和Evidence链路。

```text
模型管理员 UI
  → /api/v1/models/*
  → Session + IAM + Scope + CSRF
  → ModelManagementService
      ├─ ConnectionRepository
      ├─ SecretStore
      ├─ ModelCatalogService
      ├─ ModelBindingService
      ├─ ProviderAdapterFactory
      └─ Governance/Usage/Audit
  → ModelResolver
      ├─ Cognition Embedding
      ├─ Agent Definition LLM
      ├─ Vision VLM/OCR
      └─ 后续 Reranker
```

## 2. 模块边界

新增后端 `ModuleManifestV2(module_id="models")`，新增前端 `MODULE_GROUPS.group="models"`。标签固定为：

- `/models/connections`
- `/models/catalog`
- `/models/bindings`
- `/models/governance`
- `/models/local`

`/vision/models` 不再出现在智能识别可见标签中。兼容解析把旧 UI intent 映射到 `/models/local`；在兼容期结束前不得删除别名。

## 3. 状态机

### ConnectionVersion

```text
draft → testing → ready → pending_approval → active
                       ↘ rejected
active → superseded | disabled
```

- 测试失败回到 `draft`，不得影响当前 active 版本。
- 同一 `connection_id` 只允许一个 active 版本。
- `disabled` 不允许被 Resolver 返回。

### BindingVersion

```text
draft → validated → pending_approval → canary → active → superseded
                                      ↘ rejected
```

`canary` 必须带明确 customer/project/principal范围；空范围不得解释为全量。

## 4. 新迁移

新增纯追加迁移：

- `072_model_management_core_v1`
- `073_model_secret_envelope_v1`
- `074_model_usage_metering_v1`

不得依赖 live DB 已经应用069–071。迁移 CLI 必须从目标 DB 动态读取当前版本，按代码清单补齐。

### 4.1 model_connection_version_v1

```sql
CREATE TABLE model_connection_version_v1 (
  connection_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  tenant_id TEXT NOT NULL,
  name TEXT NOT NULL,
  location TEXT NOT NULL CHECK(location IN ('local','api')),
  adapter_kind TEXT NOT NULL CHECK(adapter_kind IN (
    'openai_compatible','anthropic')),
  api_flavor TEXT NOT NULL DEFAULT '',
  base_url TEXT NOT NULL,
  secret_ref TEXT NOT NULL DEFAULT '',
  timeout_ms INTEGER NOT NULL,
  max_retries INTEGER NOT NULL,
  config_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL,
  etag TEXT NOT NULL,
  approval_id TEXT,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  activated_at TEXT,
  PRIMARY KEY(connection_id, version)
);
```

`config_json` 只允许经过Pydantic判别联合验证的非敏感参数；禁止任意 headers、代码、模板或未知字段。

### 4.2 model_catalog_entry_v1

```sql
CREATE TABLE model_catalog_entry_v1 (
  catalog_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  connection_id TEXT NOT NULL,
  connection_version INTEGER NOT NULL,
  model_id TEXT NOT NULL,
  model_revision TEXT NOT NULL DEFAULT '',
  capabilities_json TEXT NOT NULL,
  embedding_dimension INTEGER,
  normalization_version TEXT,
  source TEXT NOT NULL CHECK(source IN ('discovered','manual')),
  probe_status TEXT NOT NULL,
  probe_json TEXT NOT NULL DEFAULT '{}',
  last_verified_at TEXT,
  UNIQUE(tenant_id, connection_id, connection_version, model_id)
);
```

能力枚举：

```text
embedding
chat
reasoning
vision
ocr_text
ocr_boxes
rerank
```

目录能力是“已验证能力”而不是根据模型名猜测。人工登记后仍需探针才能进入ready。

### 4.3 model_binding_version_v1

```sql
CREATE TABLE model_binding_version_v1 (
  binding_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  tenant_id TEXT NOT NULL,
  customer_id TEXT NOT NULL DEFAULT '',
  project_id TEXT NOT NULL DEFAULT '',
  subject_kind TEXT NOT NULL CHECK(subject_kind IN (
    'system_capability','module')),
  subject_id TEXT NOT NULL,
  capability TEXT NOT NULL,
  connection_id TEXT NOT NULL,
  connection_version INTEGER NOT NULL,
  model_id TEXT NOT NULL,
  fallback_json TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL,
  etag TEXT NOT NULL,
  approval_id TEXT,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  activated_at TEXT,
  PRIMARY KEY(binding_id, version)
);
```

Agent 不写入该表。Agent 行由 `agent_definition_v1.provider` 与 `model` 投影；统一读取 API 返回 `source="agent_definition"`。

### 4.4 model_secret_envelope_v1

```sql
CREATE TABLE model_secret_envelope_v1 (
  secret_ref TEXT NOT NULL,
  version INTEGER NOT NULL,
  tenant_id TEXT NOT NULL,
  algorithm TEXT NOT NULL,
  key_id TEXT NOT NULL,
  wrapped_dek BLOB NOT NULL,
  nonce BLOB NOT NULL,
  ciphertext BLOB NOT NULL,
  aad_hash TEXT NOT NULL,
  status TEXT NOT NULL,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  rotated_at TEXT,
  PRIMARY KEY(secret_ref, version)
);
```

Connection API 永远不选择或返回 `wrapped_dek/nonce/ciphertext`。

## 5. ModelResolver

解析输入必须包含：

```python
ResolveRequest(
    principal_id,
    tenant_id,
    customer_id,
    project_id,
    subject_kind,
    subject_id,
    capability,
    as_of,
)
```

解析优先级：

```text
Agent published Definition
→ project 模块绑定
→ customer 模块绑定
→ tenant 模块绑定
→ project capability default
→ customer capability default
→ tenant capability default
→ deployment default
→ legacy env fallback（迁移期）
```

所有候选在排序前执行 tenant/customer/project、status、effective、permission过滤。Resolver返回完整身份：

```json
{
  "connection_id": "local-omlx",
  "connection_version": 1,
  "adapter_kind": "openai_compatible",
  "model_id": "Qwen3-Embedding-0.6B-8bit",
  "model_revision": "",
  "capability": "embedding",
  "embedding_dimension": 1024,
  "normalization_version": "v1",
  "binding_id": "cognition-embedding-default",
  "binding_version": 1,
  "source": "managed"
}
```

凭据不属于Resolver返回值；Adapter调用SecretStore时以connection identity换取短生命周期SecretValue。

## 6. Agent Definition

现有 `provider` 字段保存受管引用 `connection:<connection_id>@<version>`，`model`保存外部模型ID。UI修改Agent绑定时：

1. 读取published Definition；
2. 创建下一版本draft；
3. 只替换provider/model，保留Soul、Prompt、Tools、Budget、Memory ACL；
4. 进行连接/模型/能力/Scope校验；
5. 生成审批；
6. checker批准后调用现有publish并重建Manifest投影。

禁止直接更新published Definition。

## 7. Embedding身份

现有索引身份继续包含：provider、connection/version、model/revision、dimension、normalization、analyzer、chunk policy和canonical parameters。任何一项变化都产生新snapshot。

Embedding fallback规则固定为空。Provider失败时返回 `degraded/provider_unavailable`；身份不符返回 `degraded/provider_mismatch`，不得计算不同空间的cosine。
