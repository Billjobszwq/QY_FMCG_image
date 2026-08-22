# TaaS Research RAG and Cognitive Kernel Implementation Plan

> **For implementation agents:** use `superpowers:executing-plans` to implement this plan task-by-task. Only use subagents when the user or active project instructions explicitly authorize delegation. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不破坏现有业务、训练资产和运行证据的前提下，收敛 Agent/Memory/Knowledge/Skill 事实源，并交付具备权限隔离、迭代研究、Claim 级引用和固定评测的 Research RAG V1。

**Architecture:** 在 `src/platform/cognition/` 建立 bounded context，通过 Repository/UoW 接入当前 PlatformStore。Workflow 作为 canonical definition/runtime，Research 是可恢复 Graph；Knowledge、Memory、Skill 分表，统一通过 `CognitiveQueryGateway` 联邦检索。旧表先只读兼容、再切读、最后停止旧写，不做大爆炸迁移。

**Tech Stack:** Python 3.13、FastAPI、Pydantic、SQLite 当前适配器、PostgreSQL/pgvector 目标适配器、CAS、React/TypeScript、Pytest；lexical/vector/reranker/graph 均通过端口抽象。

---

## 0. 实施规则

- 每个行为变化先写失败测试，再做最小实现；
- 只有用户明确授权本地 commit 时才按 Task 独立提交；未授权时保留工作树 diff，禁止 `git add -A`；
- 不修改、暂存、移动或删除任何现有未跟踪数据/模型/证据和 `.superpowers/`；
- 不启动长训练，不切 production，不 merge/push/deploy；
- 新迁移只追加，不改写历史迁移；
- 每次迁移前备份 SQLite，迁移后检查 integrity/count/hash；
- 新代码不得增加对 `store._conn` 的直接访问，统一经过 repository/UoW；
- 每个新 API 默认鉴权、CSRF（mutation）、scope、rate limit 和 audit；
- 每个 Task 更新本目录实施时新建的 `STATUS.md`、`ISSUES.md`、`DECISIONS.md`、`EXECUTION-LOG.md`，但不要把当前设计状态提前写成 DONE。
- 下文每个“提交”检查项都是条件动作：没有用户对本地 commit 的明确授权就跳过，不得因此阻断测试和文档证据。

## 1. 目标文件结构

```text
src/platform/cognition/
├── __init__.py
├── context.py                 # CognitiveContext，服务端构造
├── contracts.py               # typed request/result/artifact/claim contracts
├── errors.py                  # fail-closed error taxonomy
├── repository.py              # repository ports + UoW
├── policy.py                  # query/write policy decision
├── sources/
│   ├── service.py             # capture/version/publish/quarantine
│   ├── parsers.py             # parser registry
│   ├── chunking.py            # structure-aware chunking
│   └── models.py
├── memory/
│   ├── service.py             # L1/L2/L3 lifecycle
│   ├── consolidation.py       # candidate generation contracts
│   ├── projection.py          # Blackboard/current projection
│   └── legacy.py              # old tables read adapter
├── knowledge/
│   ├── service.py             # knowledge draft/publish/version/conflict
│   └── models.py
├── skills/
│   ├── service.py             # skill lifecycle/evaluation/publish
│   └── models.py
├── index/
│   ├── gateway.py             # federated CognitiveQueryGateway
│   ├── catalog.py             # index snapshot/activation
│   ├── lexical.py             # lexical port/adapter
│   ├── vector.py              # vector port/adapter
│   ├── fusion.py              # RRF/dedup/rerank
│   └── graph.py               # optional hierarchy/entity port
├── research/
│   ├── graph.py               # canonical Research Graph definition
│   ├── service.py             # start/resume/cancel/status
│   ├── planner.py
│   ├── reader.py
│   ├── critic.py
│   ├── claims.py
│   ├── synthesizer.py
│   ├── citations.py
│   └── budgets.py
└── evaluation/
    ├── dataset.py
    ├── retrieval.py
    ├── citations.py
    ├── safety.py
    └── report.py

src/platform/governance/
├── policy_service.py
├── alert_service.py
├── pause_service.py
└── agents.py

src/platform/api/
├── cognition_api.py
├── research_api.py
└── governance_api.py

tests/cognition/
tests/governance/
tests/research/
tests/fixtures/cognition/
scripts/cognition_migrate_legacy.py
scripts/build_cognition_index.py
scripts/eval_research_rag.py
scripts/reconcile_cognition.py
```

不要为每个类创建文件。以上是责任边界，实施时单文件超过约 400-500 行或承担多种职责再拆分。

## Phase 0：冻结事实和安全边界

### Task 1：建立只读基线与禁止行为测试

**Files:**

- Create: `tests/cognition/test_live_contract_baseline.py`
- Create: `scripts/audit_cognition_baseline.py`
- Create: `docs/implementation/taas-research-rag-agent-memory-v1/STATUS.md`
- Create: `docs/implementation/taas-research-rag-agent-memory-v1/ISSUES.md`
- Create: `docs/implementation/taas-research-rag-agent-memory-v1/DECISIONS.md`
- Create: `docs/implementation/taas-research-rag-agent-memory-v1/EXECUTION-LOG.md`

- [ ] 记录 HEAD、branch、tracked/untracked 边界、SQLite path/hash、迁移、表计数、production bundle 和训练进程。
- [ ] 写测试锁定旧表存在且迁移不能 drop/rename：`agent_manifest_v1`、`agent_definition_v1`、`memory_entry_v1`、`agent_memory_v1`、`knowledge_document_v1`、`agent_asset_v1`。
- [ ] 写测试锁定 `.superpowers/` 和训练/模型目录不进入 stage。
- [ ] 运行测试，确认在当前基线通过。
- [ ] 提交：`test(cognition): freeze live migration and asset boundaries`。

### Task 2：定义 CognitiveContext 和公共契约

**Files:**

- Create: `src/platform/cognition/context.py`
- Create: `src/platform/cognition/contracts.py`
- Create: `src/platform/cognition/errors.py`
- Create: `tests/cognition/test_context_contracts.py`

- [ ] 写失败测试：缺 principal/tenant/action 必须拒绝；test scope 不得降级 operational；LLM 输入不能覆盖服务端 context。
- [ ] 写 Pydantic/dataclass 契约：Context、QueryRequest/Result、ArtifactRef、EvidenceSpan、Claim、IndexSnapshot。
- [ ] 实现从现有 `ScopeResolver` 生成 CognitiveContext 的 adapter。
- [ ] 添加 JSON round-trip、hash stability、未知字段拒绝测试。
- [ ] 运行 `tests/cognition/test_context_contracts.py` 和现有 scope 测试。
- [ ] 提交：`feat(cognition): add fail-closed cognitive context contracts`。

## Phase 1：治理与 Agent 事实源收敛

### Task 3：建立单一 Agent Definition 和 Manifest 投影

**Files:**

- Create: `src/platform/agents/definition_service.py`
- Create: `src/platform/agents/manifest_projection.py`
- Modify: `src/platform/agents/kernel.py`
- Modify: `src/platform/agents/runtime.py`
- Test: `tests/governance/test_agent_definition_projection.py`

- [ ] 写失败测试：Manifest 和 Definition 的 Agent ID/version/tool scope 不一致时 Gate 失败。
- [ ] 定义 canonical AgentDefinitionVersion；Manifest 只从已发布定义 + Module Registry 投影。
- [ ] 为现有 12 个 Agent 生成明确迁移报告；缺 Runtime Definition 的状态为 `declared`，不得伪装 healthy。
- [ ] 将 `_SEVEN_AGENTS` seed 移到版本化定义 service；保留兼容读取。
- [ ] 禁止新代码直接写 `agent_manifest_v1`。
- [ ] 运行 Agent Kernel/Runtime 全部测试。
- [ ] 提交：`refactor(agents): derive manifests from versioned definitions`。

### Task 4：实现 Policy、Rules、Silent 和 Pause 基础

**Files:**

- Create: `src/platform/governance/policy_service.py`
- Create: `src/platform/governance/alert_service.py`
- Create: `src/platform/governance/pause_service.py`
- Create: `src/platform/governance/agents.py`
- Modify: `src/platform/data/store.py`（只追加新 migration）
- Test: `tests/governance/test_policy_alert_pause.py`

- [ ] 写迁移红测试：policy version、approval、alert、snapshot、pause request 必须 append-only/CAS。
- [ ] 实现 deterministic Policy Decision Point，输入 Context/action/resource/risk，输出 allow/deny/human_gate/rule refs。
- [ ] 实现 Rules Agent 只能创建 draft，发布必须 approval。
- [ ] 实现 Silent Agent 只能创建 alert/snapshot/pause request；恢复必须 human approval。
- [ ] 写 prompt injection、越权、旧规则、maker=checker、并发 CAS 负例。
- [ ] 将 Research/Knowledge/Memory 写入点接 policy hook 接口，但此 Task 不实现业务写入。
- [ ] 提交：`feat(governance): add versioned policy alert and pause controls`。

## Phase 2：认知事实底座

### Task 5：Source/Document/Chunk/Evidence 版本链

**Files:**

- Create: `src/platform/cognition/repository.py`
- Create: `src/platform/cognition/sources/models.py`
- Create: `src/platform/cognition/sources/service.py`
- Create: `src/platform/cognition/sources/parsers.py`
- Create: `src/platform/cognition/sources/chunking.py`
- Modify: `src/platform/data/store.py`（新 migration）
- Test: `tests/cognition/test_source_versioning.py`

- [ ] 写失败测试：原文不可 update/delete；相同 hash 幂等；新内容生成新版本；chunk 可回到 locator。
- [ ] 定义 Repository/UoW，禁止新服务直接 `_conn`。
- [ ] 实现 text/markdown 最小 parser 和结构化 chunking；其他格式先注册为明确 unsupported，不伪装成功。
- [ ] 实现 injection quarantine、parser error、空文档、权限缺失负例。
- [ ] 将原始文件写 CAS，并保存 ArtifactRef/hash/producer/retention。
- [ ] 实现 corpus snapshot manifest。
- [ ] 提交：`feat(cognition): add immutable source document and evidence chain`。

### Task 6：建立规范 L1/L2/L3 与旧记忆兼容

**Files:**

- Create: `src/platform/cognition/memory/service.py`
- Create: `src/platform/cognition/memory/consolidation.py`
- Create: `src/platform/cognition/memory/projection.py`
- Create: `src/platform/cognition/memory/legacy.py`
- Create: `scripts/cognition_migrate_legacy.py`
- Test: `tests/cognition/test_memory_lifecycle.py`
- Test: `tests/cognition/test_memory_legacy_migration.py`

- [ ] 写失败测试：L1 append-only；普通 Agent 不能写 L2/L3；L3 candidate 未批准不可检索为 published。
- [ ] 实现 L1/L2/L3 表与 source lineage、conflict、supersession、retention。
- [ ] Blackboard 改为 L1 current projection，保留旧 API 兼容。
- [ ] 映射旧 `l1/l2/l4`：无法确定含义的 `l4` 进入 quarantine/candidate，不强制映射为 L3。
- [ ] 迁移脚本先 `--dry-run`，输出逐行决策与 hash；无 delete/update 旧表。
- [ ] 实现 L1→L2 candidate 的确定性幂等和人工发布门。
- [ ] 实现 L2→L3 candidate + 反例/最小事件数校验。
- [ ] 提交：`feat(memory): add governed l1 l2 l3 lifecycle and legacy adapter`。

### Task 7：Knowledge 与 Skill 独立生命周期

**Files:**

- Create: `src/platform/cognition/knowledge/models.py`
- Create: `src/platform/cognition/knowledge/service.py`
- Create: `src/platform/cognition/skills/models.py`
- Create: `src/platform/cognition/skills/service.py`
- Test: `tests/cognition/test_knowledge_lifecycle.py`
- Test: `tests/cognition/test_skill_lifecycle.py`

- [ ] 写失败测试：Knowledge publish 必须 owner/effective/source spans/approval；过期/撤销默认不返回。
- [ ] 写失败测试：Skill publish 必须 schemas/execution ref/risk/eval/approval；Skill RAG 命中不等于可执行。
- [ ] 实现 knowledge conflict report，不自动“最新者胜”。
- [ ] 实现 Skill draft→validated→published→degraded/revoked。
- [ ] 为 `knowledge_document_v1`、`agent_asset_v1` 提供只读兼容投影；停止新增旧写入口。
- [ ] 提交：`feat(cognition): separate governed knowledge and skill registries`。

## Phase 3：联邦检索与 Research RAG

### Task 8：Index Catalog 与 ACL-first 混合检索

**Files:**

- Create: `src/platform/cognition/index/catalog.py`
- Create: `src/platform/cognition/index/lexical.py`
- Create: `src/platform/cognition/index/vector.py`
- Create: `src/platform/cognition/index/fusion.py`
- Create: `src/platform/cognition/index/gateway.py`
- Create: `scripts/build_cognition_index.py`
- Test: `tests/cognition/test_federated_retrieval.py`
- Test: `tests/cognition/test_retrieval_security.py`

- [ ] 先建 lexical only baseline 金标准并保存指标。
- [ ] 写失败测试：跨 tenant/customer/project、过期、revoked、draft、test scope 均零命中且不泄露 count。
- [ ] 实现 index build manifest、hash、quality report、active registry + CAS。
- [ ] 实现 lexical/vector ports；embedding provider 不可用时明确 degraded，不返回假向量结果。
- [ ] 实现 RRF、文档多样性去重、rerank port 和 score trace。
- [ ] 确保所有 source kinds 使用各自 lifecycle filter，再做跨源融合。
- [ ] 加入 SKU `.kb` Domain Retriever adapter，但不把其数据写入企业 KB。
- [ ] 提交：`feat(retrieval): add scoped federated hybrid query gateway`。

### Task 9：Research Graph、预算和恢复

**Files:**

- Create: `src/platform/cognition/research/graph.py`
- Create: `src/platform/cognition/research/service.py`
- Create: `src/platform/cognition/research/planner.py`
- Create: `src/platform/cognition/research/reader.py`
- Create: `src/platform/cognition/research/critic.py`
- Create: `src/platform/cognition/research/claims.py`
- Create: `src/platform/cognition/research/budgets.py`
- Modify: `src/platform/workflow.py`（仅补统一 Research node contract 所需接口）
- Test: `tests/research/test_research_graph.py`
- Test: `tests/research/test_research_resume_budget.py`

- [ ] 写研究状态机和每节点 schema 红测试。
- [ ] 实现 classify/plan/retrieve/read/sufficiency/gap/counterevidence/claim 节点。
- [ ] 写 loop 最大次数、query/tool/token/cost/deadline 预算负例。
- [ ] 注入每个节点失败/重启，验证 checkpoint/resume 不重复消费且 snapshot 不漂移。
- [ ] 发现冲突或需扩大 source scope 时进入 `waiting_human`。
- [ ] 所有 Research node 挂统一 Run/NodeAttempt/Usage/Evidence。
- [ ] 提交：`feat(research): add recoverable evidence-first research graph`。

### Task 10：综合、Claim 引证和发布 Gate

**Files:**

- Create: `src/platform/cognition/research/synthesizer.py`
- Create: `src/platform/cognition/research/citations.py`
- Test: `tests/research/test_claim_citation_gate.py`
- Test: `tests/research/test_contradiction_abstention.py`

- [ ] 写失败测试：高重要性 Claim 无 span、引用不支持、时间/scope 错误、只有 URL 无 locator 时 Gate 失败。
- [ ] 实现 `fact/inference/recommendation/unknown` schema 和 Claim Graph。
- [ ] Synthesizer 只读取 verified claims，不直接读取原始自由文本。
- [ ] Citation Verifier 逐 Claim 输出 pass/narrow/relabel/remove/research_more。
- [ ] 冲突证据并列；不足时 abstain，不以模型自信放行。
- [ ] 最终 report artifact 绑定 corpus/index/model/prompt/policy snapshot。
- [ ] 提交：`feat(research): enforce claim-level citations and abstention`。

## Phase 4：API、UI、评测与迁移收口

### Task 11：受控 API 和 Research Workbench

**Files:**

- Create: `src/platform/api/cognition_api.py`
- Create: `src/platform/api/research_api.py`
- Create: `src/platform/api/governance_api.py`
- Modify: `src/platform/api/app.py`
- Create: `frontend/src/pages/research/Workbench.tsx`
- Create: `frontend/src/pages/data/KnowledgeGovernance.tsx`
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/modules/registry.tsx`
- Test: `tests/research/test_research_api.py`
- Test: `frontend` lint/test/build/browser tests；`web/` 只做兼容回归

- [ ] 先写 API auth/scope/CSRF/idempotency/rate-limit 红测试。
- [ ] 实现 source preview/approve、知识/记忆/Skill search、research start/status/resume/cancel、claim/citation endpoints。
- [ ] UI 展示计划、当前步骤、预算、来源、Claim/引用、冲突、未知和人工决策；不展示隐藏推理链。
- [ ] 引用可定位打开 page/section/cell/timecode；无权内容不显示 snippet。
- [ ] 1024/1280/1440 和键盘/焦点/错误/空状态验收。
- [ ] 提交：`feat(frontend): add governed research and knowledge workbench`。

### Task 12：固定评测、负例账本和 Gate

**Files:**

- Create: `src/platform/cognition/evaluation/*.py`
- Create: `tests/fixtures/cognition/gold_queries.jsonl`
- Create: `tests/fixtures/cognition/injection_sources/`
- Create: `scripts/eval_research_rag.py`
- Create: `scripts/reconcile_cognition.py`
- Modify: `src/platform/gate_evaluator.py`
- Test: `tests/research/test_eval_reproducibility.py`

- [ ] 建立 lookup/paraphrase/temporal/multi-hop/global/conflict/abstain/ACL/injection/Skill/L2/L3 样本。
- [ ] 评测 lexical baseline，再评 hybrid、rerank、hierarchical/graph；只保留有统计和成本收益的组件。
- [ ] 输出 retrieval/reader/generation/citation/research/system/safety 分层指标，禁止只给总分。
- [ ] 建立跨租户、revoked、过期、注入、伪引用、snapshot drift、budget exhaustion 负例账本。
- [ ] Gate 读取机器生成 report + hash，并在实时路径重新计算 freshness。
- [ ] 提交：`test(research): add reproducible rag evaluation and release gate`。

### Task 13：双读迁移、回滚和收尾

**Files:**

- Modify: `scripts/cognition_migrate_legacy.py`
- Modify: `scripts/reconcile_cognition.py`
- Update: 本目录 `STATUS/ISSUES/DECISIONS/EXECUTION-LOG`
- Create: 本目录 `FINAL-REPORT.md`（仅在验收后）

- [ ] Stage A：旧写 + 新投影 shadow read，对账不影响用户结果。
- [ ] Stage B：新写 + 旧兼容投影，逐请求比较 search/ACL/version。
- [ ] Stage C：新读成为默认，旧入口 read-only；保留 kill switch。
- [ ] Stage D：人工 UAT 后停止旧写；不 drop 旧表。
- [ ] 对账行数、source refs、hash、ACL、active versions、index coverage、run/evidence/usage 链。
- [ ] fresh hermetic、host MPS（如相关）、typecheck/build、浏览器、SQLite integrity、备份恢复演练。
- [ ] 只有全部 Gate 通过才写 `READY_FOR_UAT`；人类 UAT 批准后才写 `ACCEPTED`。
- [ ] 未经用户明确授权，不 merge/push/deploy。

## 2. Gate 顺序

| Gate | 放行条件 |
|---|---|
| G0 Baseline | 资产保护、DB integrity、旧测试、现场快照完成 |
| G1 Contracts | Context/schema/hash/scope 负例通过 |
| G2 Governance | Policy/approval/alert/pause/CAS 通过 |
| G3 Sources | immutable source→span 可回查，注入隔离 |
| G4 Memory | L1/L2/L3 权限、候选、冲突、迁移通过 |
| G5 Knowledge/Skill | 生命周期、审批、版本、失效通过 |
| G6 Retrieval | ACL=0 泄露，固定召回/延迟门通过 |
| G7 Research | 循环、预算、反证、暂停/恢复通过 |
| G8 Citation | 高重要性 unsupported claim=0 |
| G9 System | API/UI/安全/性能/恢复/对账通过 |
| G10 UAT | 人类用真实授权数据完成验收 |

后一个 Gate 不得用来掩盖前一个 Gate 失败。任何 Gate 证据过期、hash 漂移或 scope 不明，状态必须 fail-closed。

## 3. 首个纵向切片

第一轮不要同时做 PDF/OCR/GraphRAG/外部 Web。首个可工作的切片是：

1. 一个 Markdown 企业制度 source；
2. source/version/chunk/span 全链；
3. ACL-first lexical + dense hybrid；
4. 一个 lookup 和一个 conflict query；
5. Research Graph 两轮 gap search；
6. 每个 Claim 有 span citation；
7. 一个跨客户负例和一个 prompt injection 负例；
8. UI 可打开具体段落；
9. 固定评测和 resume 注入通过。

这个切片通过后，再增加 PDF/table、L2/L3、Skill routing、global hierarchy 和外部 Web。

## 4. 完成前验证命令模板

实际命令以实施时依赖和文件为准，至少包含：

```bash
XONSH_HISTORY_BACKEND=dummy PYTHONDONTWRITEBYTECODE=1 \
.venv/bin/python -m pytest \
  -p no:cacheprovider -q tests/cognition tests/governance tests/research

XONSH_HISTORY_BACKEND=dummy PYTHONDONTWRITEBYTECODE=1 \
.venv/bin/python -m pytest \
  -p no:cacheprovider -q

python scripts/eval_research_rag.py --suite v1 --frozen
python scripts/reconcile_cognition.py --read-only --json
.venv/bin/python - <<'PY'
from pathlib import Path
import sqlite3
uri = Path('runtime/platform/platform.sqlite').resolve().as_uri() + '?mode=ro'
conn = sqlite3.connect(uri, uri=True)
print(conn.execute('PRAGMA integrity_check').fetchone()[0])
PY

cd frontend
npm run lint
npm run test
npm run build
```

不得从旧日志复制 PASS。每次完成声明必须引用本轮 fresh 输出和证据路径。
