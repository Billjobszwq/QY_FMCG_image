# Round 2 收口架构与技术契约

## 1. 方案选择

### 方案 A：只接 embedding，让语义 recall 变绿

改动最少，但保留迁移顺序、Research run 越权、假成功、伪支持引用和 Research Graph 骨架。拒绝。

### 方案 B：重写 cognition/research

边界看起来干净，但会丢失已经通过的 Source/Memory/Knowledge/Skill、预算、恢复和治理合同。风险和回归面过大。拒绝。

### 方案 C：在现有 Round 1 骨架上按安全依赖收口

先修数据与授权，再修终态一致性，然后接真实 dense、Research Graph、Citation 和完整评测。采用。它保留已通过资产，也保证后续质量门不能掩盖前置安全失败。

## 2. 收口后的关键数据流

```text
Authenticated Request
  -> IAM action permission
  -> ScopeResolver (server-side)
  -> CognitiveContext
  -> ResearchRunAccessPolicy
  -> ResearchService command/query
  -> Research UoW
       |- research_run / research_step
       |- business_run / work_item / event
       |- usage / evidence
       `- outbox/audit

Research node
  -> QueryPlanner
  -> CognitiveQueryGateway
       |- pre-filter ACL/effective/status
       |- lexical leg
       |- dense leg bound to index model
       `- rerank/fusion
  -> EvidenceReader
  -> SufficiencyCritic
       |- gap query
       `- counterevidence query
  -> ClaimBuilder
  -> ClaimSupportVerifier
  -> Synthesizer
  -> CitationGate
```

## 3. 迁移安全契约

### 3.1 调用顺序

正确顺序必须是：

```text
解析 CLI 参数
  -> 以 SQLite mode=ro 打开目标 DB
  -> 读取 schema_migrations / integrity / hash
  -> 校验备份文件存在、非空、integrity ok、目标身份匹配
  -> 输出 preflight report
  -> 若 dry-run：保持只读并退出
  -> 若 apply 且 preflight pass：显式创建可写 Store
  -> 显式 apply pending schema migrations
  -> 在事务中搬运 legacy rows
  -> reconciliation + integrity
```

备份校验不得依赖 `PlatformStore`。建议接口：

```python
@dataclass(frozen=True)
class MigrationPreflight:
    db_path: Path
    db_sha256: str
    migration_count: int
    latest_migration: int
    backup_path: Path | None
    backup_sha256: str | None
    backup_integrity: str | None
    allowed: bool
    reasons: tuple[str, ...]

def preflight_migration(db_path: Path, backup_dir: Path,
                        *, require_backup: bool) -> MigrationPreflight:
    """只允许 readonly sqlite3；禁止构造 PlatformStore。"""
```

硬不变量：

- preflight 失败时数据库 bytes、size、mtime、SHA、journal mode 和 migration count 不变；
- `--dry-run` 不创建 WAL/SHM，不应用 schema；
- `--apply` 必须显式同时提供确认参数和匹配目标的有效备份；
- live 已为 068，不回滚；修复只保护未来路径并在副本上演练。

## 4. Research 授权契约

### 4.1 API scope 不可信，服务端验证后才能使用

客户端可以请求 customer/project，但不能自证有权访问。共享 helper 必须：

1. 从 session 得到 principal；
2. 使用 `IAMService.authorize()` 校验 action permission 与 customer/project membership；
3. 用 `ScopeResolver.resolve()` 解析 operational/UAT/parent scope；
4. 用 `context_from_scope()` 构造不可变 `CognitiveContext`；
5. 对已有 run，再与 run 的持久化 scope 做完全匹配。

建议新增权限：

```text
cognition.read
cognition.manage
research.read
research.run
research.decide
```

角色是否获得这些权限由现有 IAM bundle 决定。未知权限、无 membership、空 scope 未获 Policy 允许时全部拒绝。

### 4.2 Run 访问规则

```python
class ResearchRunAccessPolicy:
    def require(self, ctx: CognitiveContext, run: Mapping[str, Any],
                *, permission: str) -> None: ...
```

必须同时满足：

- IAM 拥有所需 permission；
- tenant、data_scope、test_run_id 与 run 完全一致；
- customer/project 与 run 匹配，平台管理员例外必须由 IAM 明确授权；
- citations/synthesize 使用 run 持久化 scope，不接受 query 参数改写；
- status/claims 不泄露“不存在”和“存在但无权”的差异，统一返回 404 或项目既有安全错误；
- mutation 写审计，使用 CSRF、rate limit、idempotency key 和 optimistic CAS。

### 4.3 并发与幂等

run mutation 使用预期版本或预期状态：

```sql
UPDATE research_run_v1
SET status = ?, state_json = ?, version = version + 1, updated_at = ?
WHERE research_run_id = ? AND version = ? AND status = ?;
```

`rowcount != 1` 返回稳定 conflict，不继续执行节点。resume/cancel/decide 不能采用“先读后无条件写”。

## 5. Research 终态一致性

禁止 `except Exception: pass`。finalize 必须在一个明确的 UoW 中完成：

```text
验证 Claim Gate
  -> 写 immutable report/evidence artifact
  -> 写 evidence_bundle
  -> 更新 research_run terminal status
  -> 更新 business_run/work_item terminal status
  -> 写 event/audit/outbox
  -> commit
```

任一步失败：

- UoW 回滚；
- Research Run 不得变成 succeeded；
- 错误分类为 retryable/provider/integrity/policy；
- 若连失败状态都无法写入，保留原状态并发 critical alert，不能吞错。

## 6. Dense/Hybrid 索引契约

### 6.1 Provider 端口

```python
class VectorProvider(Protocol):
    provider_id: str
    model_name: str
    model_revision: str
    dimension: int
    normalization_version: str

    def available(self) -> bool: ...
    def encode_documents(self, texts: Sequence[str]) -> list[list[float]]: ...
    def encode_queries(self, texts: Sequence[str]) -> list[list[float]]: ...
```

推荐实现顺序：

1. OpenAI-compatible adapter，复用当前环境已有的 `openai` SDK，但必须把它加入受控可选依赖并从环境读取 endpoint/model/key；不记录 key。
2. 可选 local sentence-transformers adapter，仅当用户已授权依赖和模型资产；测试和 hermetic 运行禁止自动下载模型。
3. `UnavailableVectorProvider` 继续作为诚实降级；它不能使 dense Gate 通过。

若现场没有可用 provider，代码、测试和接口仍应完成，但状态写 `BLOCKED_BY_EMBEDDING_PROVIDER`。禁止哈希伪向量、随机向量、gold-set 特制映射或词表别名冒充 dense。

### 6.2 Index identity

```text
index_snapshot_id = sha256(
  target_kind |
  corpus_snapshot_id |
  backend |
  provider_id |
  model_name |
  model_revision |
  dimension |
  normalization_version |
  analyzer_version |
  chunk_policy_version |
  canonical(parameters)
)
```

Artifact 和 DB build row 都保存上述字段、manifest hash、vector count、quality report 和 build status。模型或参数变化必须生成新 build；不得返回旧 lexical artifact。

激活条件：artifact hash 匹配、build ready、vector count 与可索引单元一致、provider identity 与查询侧一致、quality report 通过。查询侧 provider 不匹配时 fail-closed/degraded，不可比较不同模型向量。

## 7. Research Graph 契约

目标节点：

```text
classify -> plan -> retrieve -> read -> sufficiency
                                ^          |
                                |          +-- gap_query
                                |          +-- counterevidence
                                |          +-- ask_human
                                +----------+
                   -> claim -> synthesize -> verify -> finalize
```

### 7.1 Planner

- lookup 可保持一个原子问题；deep_research 必须生成有界子问题和依赖；
- 每个子问题带 evidence type、target kinds、时间、scope、停止条件；
- 至少一个反证或替代解释查询；
- provider 不可用时 deep_research 明确 degraded/abstain，不能用单问题冒充规划完成。

### 7.2 Sufficiency 与 conflict

多个来源代表 evidence diversity，不代表矛盾。只有以下条件之一成立才是 conflict：

- 同一可比较命题存在 `supports` 与 `contradicts`；
- 数值、时间、版本、责任主体等规范化字段互斥；
- Critic 给出结构化 contradiction 且证据 locator 可回查。

gap、conflict、low-authority、stale-source 分别产生不同下一动作。每轮新 query 必须有 novelty key，连续两轮无新高价值 span 时停止。

## 8. Claim 支持性与 Citation Gate

Claim 创建时不得预填 `verifier_score=1.0`。验证分两层：

1. 确定性层：span/source/ACL/time/scope/locator；数字、实体、否定词和单位一致性；
2. 支持性层：判断 `supports/contradicts/context/insufficient`，输出 score、理由、verifier identity 和输入 hash。

```python
class ClaimSupportVerifier(Protocol):
    verifier_id: str
    verifier_version: str

    def verify(self, claim: Claim, spans: Sequence[EvidenceSpan],
               ctx: CognitiveContext) -> ClaimVerification: ...
```

高重要性 Claim 只有 deterministic validity 和 support verification 都通过才能发布。provider 不可用时高重要性 Claim 不得默认 pass；应返回 `research_more` 或 `remove`。Citation precision 必须基于带人工 gold label 的 claim-span 对计算，不能把关系字段本身当真值。

## 9. 评测与证据契约

固定集至少每类含正例和负例，并保存：query、scope、as_of、允许 corpus/index snapshot、期望 target/span/claim、禁止来源、预期 abstain/conflict。样本不得被 provider 训练或硬编码。

报告必须分层：

- Retrieval：Recall@5/10、MRR、nDCG、span recall、ACL/revoked/expired leakage；
- Reader：span precision/recall、locator accuracy；
- Generation：claim correctness、faithfulness、completeness、abstention；
- Citation：precision、high-importance recall、support rate、locator validity；
- Research：subquestion coverage、conflict discovery、counterevidence yield、resume；
- System：p50/p95、provider/model/index snapshot、cost、cache、freshness；
- Safety：cross-scope/revoked/injection success 均为 0。

`report_hash` 覆盖 suite、gold hash、corpus/index/provider/model/prompt/policy、全部指标、样本结果和生成时间。Gate 重新读取 artifact 并检查 freshness，不能只相信 JSON 中的 `pass`。

## 10. UI 与浏览器验收

Research Workbench 必须展示服务端固化的 scope、当前节点、预算、停止原因、degraded/provider 状态、子问题、来源、Claim、逐 Claim verdict、冲突、unknown 和 citation locator。UI 不允许提交任意 customer/project 去读取已有 run，也不展示隐藏推理链。

浏览器验收覆盖 1024/1280/1440、键盘焦点、401/403/404/409、空状态、provider unavailable、waiting_human、cancel、resume、citation block 和 locator 打开。浏览器静态渲染不能替代真实 API 行为断言。

## 11. 状态规则

- P0 未关闭：`BLOCKED_BY_SECURITY_*` 或 `BLOCKED_BY_MIGRATION_*`；
- provider 缺失：`BLOCKED_BY_EMBEDDING_PROVIDER`；
- eval 不绿：`BLOCKED_BY_EVALUATION`；
- 机器 Gate 全绿且证据 fresh：`READY_FOR_UAT`；
- 用户真实 UAT 明确批准：`ACCEPTED`。

任何日志中的旧 PASS 都不能覆盖当前失败。后一个 Gate 不得掩盖前一个 Gate。
