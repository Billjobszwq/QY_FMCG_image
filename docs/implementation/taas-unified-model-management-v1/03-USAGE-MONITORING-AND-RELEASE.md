# 03｜账号级 Usage、监控与模型上线

## 1. 计量事实源

继续使用不可变`usage_event_v2`，不建立第二套账单事实源。迁移074只追加模型调用归属字段：

```sql
ALTER TABLE usage_event_v2 ADD COLUMN principal_id TEXT NOT NULL DEFAULT '';
ALTER TABLE usage_event_v2 ADD COLUMN principal_kind TEXT NOT NULL DEFAULT '';
ALTER TABLE usage_event_v2 ADD COLUMN model_call_id TEXT NOT NULL DEFAULT '';
ALTER TABLE usage_event_v2 ADD COLUMN connection_id TEXT NOT NULL DEFAULT '';
ALTER TABLE usage_event_v2 ADD COLUMN connection_version INTEGER;
ALTER TABLE usage_event_v2 ADD COLUMN binding_id TEXT NOT NULL DEFAULT '';
ALTER TABLE usage_event_v2 ADD COLUMN binding_version INTEGER;
ALTER TABLE usage_event_v2 ADD COLUMN provider_request_id TEXT NOT NULL DEFAULT '';
ALTER TABLE usage_event_v2 ADD COLUMN meter_source TEXT NOT NULL DEFAULT '';
ALTER TABLE usage_event_v2 ADD COLUMN outcome TEXT NOT NULL DEFAULT '';
ALTER TABLE usage_event_v2 ADD COLUMN error_code TEXT NOT NULL DEFAULT '';
```

旧行保持不变。新增索引只覆盖查询需要的scope/time/model_call字段。

## 2. 计量单位

一次Provider请求生成稳定`model_call_id`，允许同一调用追加多行Usage：

| unit | 来源 | 说明 |
|---|---|---|
| `model_request` | 平台 | 每次外部/本地Provider调用1次 |
| `input_token` | Provider usage | 真实输入Token |
| `output_token` | Provider usage | 真实输出Token |
| `cached_input_token` | Provider usage | 命中缓存Token |
| `reasoning_token` | Provider usage | Provider明确返回的reasoning Token |
| `embedding_input` | 平台 | Embedding输入条目数 |
| `embedding_vector` | 平台 | 返回向量数 |
| `input_character` | 平台 | 无Token口径时的输入字符数 |
| `model_compute_ms` | 平台 | 客户端观测耗时 |

Provider未返回Token时，不允许使用字符数冒充Token。`meter_source`固定为`provider_reported`、`platform_observed`或`reconciled`。

## 3. 调用账本与失败恢复

远端请求不可回滚，必须先建立调用意图：

```text
1. 解析并冻结 Binding Identity
2. 生成 model_call_id 和 idempotency key
3. 持久化 model.call.requested / 预算预留
4. 调用 Provider
5. 追加 Usage + model.call.succeeded/failed
6. 释放或结算预算预留
```

步骤3失败不得调用Provider。步骤5失败时不得向上游报告完整成功，标记`MODEL_METERING_INCOMPLETE`并进入对账；未知外部结果禁止自动重试非幂等Chat调用。Embedding按content hash和batch identity可安全重放。

## 4. 配额与限流

保留现有请求次数限流，新增`ModelBudgetService`：

- 维度：principal、service account、tenant、customer、project、Agent、module、connection、model。
- 周期：分钟/小时/日/月。
- 单位：request、input/output/total token、compute milliseconds、customer price。
- 软阈值：80%告警，不阻断。
- 硬阈值：100%拒绝新调用，返回429和安全Retry-After/重置时间。
- Chat输出未知时先按配置的`max_output_tokens`预留，结束后按真实Usage结算。
- Provider 429与平台预算429必须用稳定错误码区分。

## 5. 成本

`rate_card`按connection/model/revision/unit/effective_from版本化。一次调用按当时价格快照写入`resource_cost/internal_cost/customer_price`，后续价格变化不改历史Usage。

外部Provider账单API是可选对账源：

- 支持则按provider request ID和日期对账；
- 不支持则保持`provider_reconciliation=unavailable`；
- 不得因为无法读取余额而把本地账本判为无效。

## 6. 监控

“模型管理 → 运行治理”提供以下真实指标：

- requests、input/output/cached/reasoning Token；
- embedding inputs/vectors、input characters；
- latency p50/p95、success/error/timeout/429；
- 按principal、tenant、customer、project、Agent、module、connection、model筛选；
- Token预算、成本、Provider健康、最近成功与最近错误；
- active/canary binding版本、Secret轮换时间；
- metering incomplete、usage unattributed、index identity mismatch。

告警规则至少包括：

```text
provider_unavailable
error_rate_threshold
latency_p95_threshold
budget_soft_limit
budget_hard_limit
secret_rotation_due
metering_incomplete
usage_unattributed
embedding_identity_mismatch
```

告警复用现有Governance Alert，不新建无审计通知表。

## 7. 上线流程

### 7.1 Connection

```text
draft
→ EndpointPolicy
→ Secret configured
→ auth/models probe
→ capability probe
→ ready
→ maker submit
→ checker approve
→ CAS active
```

### 7.2 Binding

```text
draft
→ resolve/impact validation
→ index impact validation
→ budget/rate-card validation
→ maker submit
→ checker approve
→ scoped canary
→ Gate evidence
→ CAS active
```

Canary范围必须是明确principal/customer/project。模型管理员不能用空scope把Canary扩成全租户。

## 8. 回滚

- 回滚目标必须是已批准、未revoke且健康的历史版本。
- Connection回滚不允许恢复被撤销Secret。
- Chat/Vision绑定可回滚到兼容模型。
- Embedding回滚必须同时恢复匹配的active index snapshot；没有匹配索引则拒绝。
- CAS失败返回409，Active保持不变。

## 9. OMLX Embedding发布Gate

本地OMLX接入必须按顺序：

1. `/health`正常；
2. 受控鉴权通过；
3. 模型可发现或人工登记后probe通过；
4. Embedding维度为配置值且批量数量一致；
5. 以完整Provider Identity构建新索引；
6. hybrid查询使用相同Identity；
7. `paraphrase.recall_at_10 >= 0.90`；
8. ACL、injection、forbidden、citation、resume、conflict和性能Gate保持通过；
9. Usage包含principal、model、connection、binding和诚实计量单位；
10. maker/checker批准Canary后才能进入active。

任一步失败，状态保持`BLOCKED_BY_PROVIDER_AUTH`或`BLOCKED_BY_SEMANTIC_GATE`，不得写READY。
