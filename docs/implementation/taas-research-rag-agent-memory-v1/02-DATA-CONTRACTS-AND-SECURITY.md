# 数据契约、接口与安全约束

## 1. 共同上下文

所有认知读写都必须携带服务端生成的上下文：

```python
@dataclass(frozen=True)
class CognitiveContext:
    principal_id: str
    tenant_id: str
    customer_id: str
    project_id: str
    test_run_id: str
    data_scope: str
    action: str
    permission_tags: tuple[str, ...]
    purpose: str
    correlation_id: str
    parent_run_id: str | None
    as_of: datetime
```

约束：

- 任何字段不得由 LLM 自行填写；
- 缺 tenant/action/principal 时 fail-closed；
- `customer_id/project_id` 可为空的唯一情况必须由 Policy 明确声明；
- test/UAT 数据默认不能出现在 operational 查询；
- `as_of` 决定知识有效版本和时间旅行查询；
- 权限过滤发生在候选评分和计数前。

## 2. Source、Document、Chunk 与 Evidence

```yaml
source_artifact:
  source_id: string
  artifact_ref: string          # CAS hash
  source_type: file|url|api|database|manual
  original_uri: string
  media_type: string
  sha256: string
  tenant_id: string
  customer_id: string
  project_id: string
  permission_tags: [string]
  trust_tier: authoritative|internal|external_primary|external_secondary|unverified
  captured_at: datetime
  effective_from: datetime|null
  effective_to: datetime|null
  status: active|quarantined|superseded|revoked

knowledge_document_version:
  document_id: string
  version: integer
  source_id: string
  title: string
  content_hash: string
  parser_version: string
  normalization_version: string
  language: string
  status: draft|reviewed|published|superseded|revoked
  owner: string
  approved_by: string|null

knowledge_chunk:
  chunk_id: string
  document_id: string
  document_version: integer
  parent_chunk_id: string|null
  ordinal: integer
  heading_path: [string]
  text: string
  token_count: integer
  char_start: integer
  char_end: integer
  page_start: integer|null
  page_end: integer|null
  table_ref: string|null
  content_hash: string

evidence_span:
  span_id: string
  chunk_id: string
  quote_start: integer
  quote_end: integer
  quote_hash: string
  normalized_quote: string
  locator: object               # page/section/cell/timecode
```

原文不可覆盖。重新解析必须生成新 document version 或新的派生 build，不得原地修改旧 chunk。

## 3. Knowledge Item

知识条目只保存“应然”规则或规范化事实，不等于所有文档 chunk：

```yaml
knowledge_item_version:
  knowledge_id: string
  version: integer
  type: organization|policy|process|contract|finance|technical|conduct|law
  title: string
  body: string
  summary: string
  owner: string
  effective_from: datetime
  effective_to: datetime|null
  status: draft|published|superseded|revoked
  permission_tags: [string]
  source_spans: [span_id]
  related_knowledge: [knowledge_id]
  extracted_entities: object
  approval_id: string
```

任何 published 条目至少有一个 source span 和一个人类 approval。知识冲突不得用“最新更新时间”自动解决；先按有效期、权威层级和适用 scope 计算，仍冲突则交 Rules Agent 生成裁决请求。

## 4. Memory L1/L2/L3

### 4.1 L1 原始事件

```yaml
memory_l1_event:
  event_id: string
  task_id: string
  run_id: string
  node_id: string
  actor_id: string
  actor_kind: human|agent|system
  event_type: string
  payload_ref: ArtifactRef|inline-safe-json
  context_meaning: string|null
  evidence_refs: [string]
  occurred_at: datetime
  ingested_at: datetime
  permission_tags: [string]
  retention_class: string
```

只追加；不 update/delete。Blackboard current card 是基于 L1/supersession 的投影。

### 4.2 L2 业务事件

```yaml
memory_l2_episode:
  episode_id: string
  task_id: string
  period_start: datetime
  period_end: datetime
  entities: [string]
  solution: string
  result: string
  issues: [string]
  conflicts: [string]
  responsibility_status: unjudged|pending_human|decided
  human_decision: string|null
  source_l1_ids: [string]
  source_hash: string
  confidence: float
  status: candidate|published|superseded|archived|conflict
  permission_tags: [string]
```

同一 `source_hash + consolidator_version` 幂等。冲突并存，不静默覆盖。

### 4.3 L3 方法论

```yaml
memory_l3_methodology_version:
  methodology_id: string
  version: integer
  statement: string
  trigger_conditions: [string]
  scope: object
  confidence: float
  source_l2_ids: [string]
  supporting_event_count: integer
  counterexample_ids: [string]
  status: candidate|published|superseded|revoked
  approved_by: string|null
  approval_id: string|null
  skill_ref: string|null
```

LLM 只能创建 candidate。发布必须经人类批准，并至少包含规则规定的独立事件数量、反例搜索结果和来源列表。

## 5. Skill 契约

```yaml
skill_definition_version:
  skill_id: string
  version: integer
  name: string
  description: string
  skill_type: builtin|curated|derived
  input_schema: JSONSchema
  output_schema: JSONSchema
  execution_ref: string
  tool_scopes: [string]
  dependency_versions: object
  applicable_scenarios: [string]
  forbidden_scenarios: [string]
  risk_level: low|medium|high|critical
  approval_policy_id: string
  permission_tags: [string]
  source_refs: [knowledge_id|methodology_id]
  evaluation_ref: string
  status: draft|validated|published|degraded|revoked
```

Skill RAG 只负责发现候选 Skill。真正执行前仍要：schema 校验、版本解析、allowlist、Policy 决策、预算、人工 gate 和运行证据。

## 6. Research 契约

```yaml
research_run:
  research_run_id: string
  parent_run_id: string
  question: string
  mode: lookup|case_analysis|methodology|deep_research
  plan_version: integer
  corpus_snapshot_id: string
  index_snapshot_ids: [string]
  model_profile_ids: [string]
  budget: object
  status: planned|running|waiting_human|succeeded|failed|cancelled
  stop_reason: string|null

research_query:
  query_id: string
  research_run_id: string
  subquestion_id: string
  query_text: string
  target_kinds: [knowledge|memory_l2|memory_l3|skill|external]
  filters: object
  strategy: lexical|dense|graph|hierarchical|hybrid
  iteration: integer

retrieval_hit:
  query_id: string
  target_type: string
  target_id: string
  rank: integer
  lexical_score: float|null
  dense_score: float|null
  rerank_score: float|null
  fusion_score: float
  index_snapshot_id: string

research_claim:
  claim_id: string
  research_run_id: string
  text: string
  claim_type: fact|inference|recommendation|unknown
  importance: low|medium|high
  support_status: supported|partially_supported|contradicted|unsupported
  confidence: float

claim_evidence:
  claim_id: string
  span_id: string
  relation: supports|contradicts|context
  verifier_score: float
  verifier_version: string
```

## 7. 查询接口

```python
class CognitiveQueryGateway(Protocol):
    def search(self, request: CognitiveQueryRequest,
               context: CognitiveContext) -> SearchResult: ...

class CognitiveQueryRequest:
    query: str
    target_kinds: tuple[str, ...]
    mode: str
    top_k: int
    filters: Mapping[str, Any]
    include_history: bool
    require_citations: bool
```

返回值必须包含：候选 ID、来源类型、版本、score 分解、权限决策摘要、evidence span、index snapshot、retrieval trace。默认只返回安全摘要和指针，全文读取需二次授权检查。

禁止提供任意 SQL、任意文件路径读取或绕过 scope 的 debug 参数。

## 8. 安全模型

### 8.1 Prompt Injection

- 上传文件、网页、邮件、PDF、OCR、记忆和检索结果全部标记为 `UNTRUSTED_CONTENT`；
- 内容中的“忽略规则”“调用工具”“泄露密钥”等文本只作为证据，不进入 system/developer 指令；
- Reader 只能输出结构化 evidence candidate，不能调用业务写工具；
- 任何工具参数必须来自 planner schema + Policy 校验，不从文档原样执行；
- 检测到可疑指令时隔离 source version，创建治理告警，不污染正常索引。

### 8.2 权限与隐私

- pre-retrieval filter，而不是 post-filter；
- 搜索计数、facet、相似度和“是否存在”同样受权限约束；
- 敏感内容不写普通日志、Prompt、embedding debug 或 L1 共享黑板；
- embedding/index 继承源权限与删除/撤销状态；
- 外部研究默认禁止上传企业机密查询；允许时须使用批准的脱敏 query。

### 8.3 版本与完整性

- source、chunk、index build、Prompt、model、policy、Skill 和 report 均版本化；
- 最终报告保存 corpus/index/model/prompt/policy snapshot；
- ArtifactRef 记录 SHA-256、大小、媒体类型、producer run 和 retention；
- 发布后修改必须新版本；旧版本可回查但默认不检索。

### 8.4 人工门

以下动作必须显式人工批准：

- 发布/废止知识规则；
- 发布/废止 L3；
- 发布/提升 Skill；
- 扩大 Agent tool/data scope；
- 启用外部网页检索处理机密问题；
- 对外发布研究报告；
- 解除 Silent Agent 的严重熔断；
- 删除或销毁受 retention 管理的原始资产。

## 9. API 最小表面

```text
POST /api/v1/cognition/sources/ingest-preview
POST /api/v1/cognition/sources/{id}/approve
GET  /api/v1/cognition/knowledge/search
GET  /api/v1/cognition/memory/search
GET  /api/v1/cognition/skills/search
POST /api/v1/research/runs
GET  /api/v1/research/runs/{id}
POST /api/v1/research/runs/{id}/resume
POST /api/v1/research/runs/{id}/cancel
GET  /api/v1/research/runs/{id}/claims
GET  /api/v1/research/runs/{id}/citations
POST /api/v1/governance/policies/{id}/draft
POST /api/v1/governance/approvals/{id}/decide
GET  /api/v1/governance/alerts
```

所有 mutation 使用 CSRF/session、action permission、idempotency key、审计、rate limit 和 UoW。读取也必须鉴权；不存在“公开 debug KB”。
