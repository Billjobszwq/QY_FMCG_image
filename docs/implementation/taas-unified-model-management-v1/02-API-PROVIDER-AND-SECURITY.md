# 02｜API、Provider Adapter 与安全规范

## 1. API边界

全部接口使用现有session cookie、CSRF和`/api/v1`前缀。

### 1.1 Connection

```text
GET  /api/v1/models/connections
GET  /api/v1/models/connections/{id}
POST /api/v1/models/connections/drafts
POST /api/v1/models/connections/{id}/versions/{v}/secret
POST /api/v1/models/connections/{id}/versions/{v}/test
POST /api/v1/models/connections/{id}/versions/{v}/submit
POST /api/v1/models/connections/{id}/versions/{v}/approve
POST /api/v1/models/connections/{id}/versions/{v}/disable
```

`GET`返回：配置、status、health、`secret_configured`、`secret_version`、`last_rotated_at`。不得返回API Key、密文、认证header或可逆掩码。

### 1.2 Catalog

```text
GET  /api/v1/models/catalog
POST /api/v1/models/connections/{id}/versions/{v}/discover
POST /api/v1/models/catalog/manual
POST /api/v1/models/catalog/{catalog_id}/probe
```

发现失败允许人工登记；未通过probe的模型不能绑定为candidate。

### 1.3 Binding

```text
GET  /api/v1/models/bindings
POST /api/v1/models/bindings/drafts
POST /api/v1/models/bindings/{id}/versions/{v}/validate
POST /api/v1/models/bindings/{id}/versions/{v}/submit
POST /api/v1/models/bindings/{id}/versions/{v}/approve
POST /api/v1/models/bindings/{id}/versions/{v}/activate-canary
POST /api/v1/models/bindings/{id}/versions/{v}/activate
POST /api/v1/models/bindings/{id}/rollback
```

### 1.4 Usage/Governance

```text
GET /api/v1/models/usage/summary
GET /api/v1/models/usage/timeseries
GET /api/v1/models/usage/rows
GET /api/v1/models/health
GET /api/v1/models/alerts
GET /api/v1/models/audit
```

## 2. 稳定错误语义

| HTTP | 语义 |
|---|---|
| 401 | 未登录/会话过期 |
| 403 | 已登录但缺少模型管理或用量权限 |
| 404 | 资源不存在或跨租户不可见，统一零泄漏 |
| 409 | CAS冲突、状态非法、身份不匹配或并发单赢家失败 |
| 422 | 合同、Endpoint、能力或Secret输入不合法 |
| 429 | 平台配额/限流或Provider 429，返回安全Retry-After |
| 503 | SecretStore/Provider/模型不可用 |

Provider错误进入稳定错误码，例如：

```text
MODEL_AUTH_FAILED
MODEL_ENDPOINT_BLOCKED
MODEL_DISCOVERY_UNSUPPORTED
MODEL_CAPABILITY_MISMATCH
MODEL_DIMENSION_MISMATCH
MODEL_RATE_LIMITED
MODEL_TIMEOUT
MODEL_METERING_INCOMPLETE
```

响应不得包含请求header、API Key、完整Provider body或内部堆栈。

## 3. Adapter协议

```python
class ModelProviderAdapter(Protocol):
    def list_models(self) -> list[ProviderModel]: ...
    def probe(self, model_id: str, capability: str) -> ProbeResult: ...
    def embed(self, request: EmbedRequest) -> EmbedResult: ...
    def chat(self, request: ChatRequest) -> ChatResult: ...
```

结果必须规范化：provider request ID、model ID、latency、status、usage、retry_after和安全错误码。

### 3.1 OpenAI-compatible

覆盖：本地OMLX、OpenAI以及兼容服务。配置项：

```text
base_url
api_flavor = responses | chat_completions | auto
auth_scheme = bearer
models_path = /models（固定）
embeddings_path = /embeddings（固定）
timeout_ms
max_retries
```

禁止用户输入任意路径或任意header。确有额外header需求时，必须进入加密Secret payload并由adapter allowlist验证。

### 3.2 Anthropic

原生支持：`GET /v1/models`、`POST /v1/messages`，使用`x-api-key`或批准的短期Bearer凭据以及固定`anthropic-version`。Anthropic不是OpenAI-compatible，不得通过字段改名强行复用OpenAI response parser。

Anthropic V1只声明chat/reasoning/vision能力；不为其伪造Embedding能力。

## 4. OMLX Bootstrap

Bootstrap只创建draft：

```yaml
connection_id: local-omlx
location: local
adapter_kind: openai_compatible
api_flavor: chat_completions
base_url: http://127.0.0.1:8455/v1
secret_ref: model-secret/local-omlx
```

目录必须从受控Models API发现或人工登记：

```yaml
model_id: Qwen3-Embedding-0.6B-8bit
capabilities: [embedding]
embedding_dimension: 1024
normalization_version: v1
```

文档和日志不保存用户提供的密钥。执行时从UI写入SecretStore或由部署工具注入。

## 5. SecretStore

V1实现`EncryptedSQLiteSecretStore`，接口允许后续替换Vault/KMS：

```python
class SecretStore(Protocol):
    def put(self, scope: SecretScope, value: bytes, actor: str) -> SecretRef: ...
    def lease(self, ref: SecretRef, scope: SecretScope) -> SecretLease: ...
    def rotate(self, ref: SecretRef, value: bytes, actor: str) -> SecretRef: ...
    def revoke(self, ref: SecretRef, actor: str) -> None: ...
```

- 算法：AES-256-GCM。
- 每个secret version独立随机DEK和nonce。
- AAD包含tenant、secret_ref、version、adapter_kind。
- KEK不存数据库；由`TAAS_MODEL_SECRET_KEK`或企业KMS提供。
- KEK缺失时SecretStore状态为unavailable；禁止用默认key或自动落盘key。
- API只接受secret value一次；成功响应不回显。
- 轮换后旧版本revoke；运行时不得自动回落。

## 6. EndpointPolicy与SSRF

保存和测试都执行同一策略：

- scheme只允许https；location=local时允许http。
- 拒绝userinfo、fragment、空host、超长URL和非标准危险scheme。
- local只允许回环或安装策略批准的RFC1918网段。
- api拒绝loopback、RFC1918、link-local、multicast和云metadata地址。
- DNS解析后复核所有IP；连接时复核peer IP；重定向重新执行策略。
- 固定请求路径、超时、响应体上限和重试预算。
- TLS证书默认严格验证；自定义CA必须由部署管理员配置，不能在UI关闭验证。

## 7. IAM

新增权限：

```text
models.use
models.config.read
models.connection.manage
models.secret.rotate
models.binding.manage
models.release.approve
models.usage.read
models.audit.read
```

普通员工没有任何管理权限。模型管理员能创建、测试、轮换和提交；审批人能批准他人；审计员只读；财务只能读取授权范围Usage。即使同一主体拥有manage和approve，`maker != checker`仍强制。

## 8. 日志与审计

审计记录动作、资源引用、版本、actor、tenant/customer/project、结果和request ID。禁止记录secret值、密文、Provider完整错误体、Prompt正文或模型输出正文。

安全扫描关键字至少覆盖：`api_key`、`authorization`、`x-api-key`、`secret`、`token`。其中Token计量字段名允许存在，但值不得与凭据指纹匹配。
