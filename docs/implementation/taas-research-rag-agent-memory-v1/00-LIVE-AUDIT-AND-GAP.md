# 当前系统审计与差距

## 1. 审计范围与方法

本次只读核对了：

- TaaS 完整规范和两份原始分案；
- `docs/CODEX-PROJECT-HANDBOOK.md`、`docs/PROJECT-STRUCTURE.md`、`docs/LOCAL-ASSETS.md` 与当前产品架构文档；
- Agent Kernel、Agent Runtime、Supervisor、Blackboard、Memory、Workflow、Graph/Loop、PlatformStore 和 Import Center 的当前代码；
- `runtime/platform/platform.sqlite` 的现场表、行数、迁移版本和完整性；
- 新版 `frontend/`、兼容 `web/`、模块注册和同源 `/api/v1` 接口边界；
- Agent/Blackboard/Runtime 针对性测试。

现场基线：

| 项目 | 结果 |
|---|---|
| 唯一开发目录 | `/Users/zhangweiqi/Documents/QY/TaaS by Agent Operation` |
| Branch | `codex/taas-agent-operation-v1`，相对远端分支 ahead 8 |
| HEAD | `5bbbf89861cc658fdfbb4a7b5b3ad9967e4b6610` |
| 最新迁移 | `061_gate_run_v1` |
| SQLite | `runtime/platform/platform.sqlite`，`PRAGMA integrity_check = ok`；`.platform` 为兼容链接 |
| 针对性测试 | `17 passed, 1 warning in 6.20s` |
| 起始工作树 | tracked/untracked 均为空；本轮只新增本目录文档 |
| 本地资产边界 | `training-data/`、`recognition-models/`、`runtime/` 的实体不进入 Git，本轮未修改 |

测试命令：

```bash
XONSH_HISTORY_BACKEND=dummy PYTHONDONTWRITEBYTECODE=1 \
.venv/bin/python -m pytest \
  -p no:cacheprovider -q \
  tests/platform/test_agent_kernel_blackboard.py \
  tests/platform/test_abos_v3_agent_runtime.py
```

## 2. 当前真实结构

### 2.1 执行与 Agent

当前同时存在：

- `GraphEngine v1`：静态 GraphDefinition；
- `LoopEngine v2`：typed edge 和 feedback；
- `WorkflowService`：wait/parallel/join/loop/approval/subflow，通用能力最完整；
- `AgentRuntime`：关键词确定性规划、有界工具调用、可选 LLM 组织答案；
- `SupervisorAgent`：另一条规则/DeepSeek 对话运行路径；
- Job Worker 和训练控制状态机。

`src/platform/agents/kernel.py` 的 `_BUILTIN` 当前声明 12 个 Manifest；`src/platform/agents/runtime.py` 的 `_SEVEN_AGENTS` 只为 7 个 Agent 建 Runtime Definition。二者不是同一事实源。迁移项目的干净运行数据库当前为 `agent_manifest_v1=0`、`agent_definition_v1=7`，因此不能把代码声明数、运行定义数和数据库投影数混成一个“Agent 数量”。

### 2.2 记忆

当前存在两套长期记忆入口：

1. `memory_entry_v1` + `MemoryService`：包含 level、scope、ACL、confidence、evidence、validity 和 supersedes；
2. `agent_memory_v1` + `AgentRuntime.remember()`：允许 `L0-L4`、保存 content/ACL/supersedes/status。

迁移项目现场数据为 `memory_entry_v1=0`、`agent_memory_v1=0`。虽然当前没有需要搬迁的记忆实体，但代码仍同时允许两套表和 `L0-L4` 层级，而完整规范要求 L1/L2/L3。当前也没有 L1→L2 Consolidate、L2→L3 人工确认、统一检索索引或记忆冲突处理运行链。

Blackboard 的结构约束较成熟：表级触发器禁止 update/delete，服务限制跨 Agent supersede；迁移项目现场为 `blackboard_event_v1=0`。它尚未明确拆成“短期协作投影”和“永久 L1 原始事件账本”。

### 2.3 知识与 Skill

当前存在三个含义不同的“KB”：

- `.kb/`：指向 `training-data/processed/knowledge-base` 的兼容入口，服务 SKU 识别知识与图文向量；
- `knowledge_document_v1`：Import Center 写入的文档元数据，现场 0 条；
- `agent_asset_v1(kind=kb|skill|prompt)`：Runtime 资产草稿/发布表，现场 0 条。

三者没有统一来源版本、文档内容、chunk、证据片段、实体、索引版本和引用协议。`knowledge_document_v1` 只含标题、来源、版本、有效期等元数据，未与 `agent_asset_v1` 的内容建立强关系。

当前 `kb.search` 的实现是：从已发布 `agent_asset_v1(kind='kb')` 读取标题和前 160 个字符，执行双向子串/分词包含判断，最多返回 5 条。它没有：

- BM25/倒排排名；
- dense vector 召回；
- reranker；
- 权限、客户、项目和生效时间前置过滤；
- chunk/span 级定位；
- 引证与 Claim 绑定；
- query decomposition、迭代检索或反证搜索；
- 检索质量评测。

### 2.4 运行证据和 Scope

系统已有 `business_run_v1`、`work_item_v2`、`event_envelope_v1`、`evidence_bundle_v1`、`usage_event_v2` 和多轮 scope 修复。这些是新系统最值得复用的基础。

但 Research RAG 仍缺：

- Claim 到 evidence span 的多对多关系；
- 研究问题/子问题/查询/命中/读证据/矛盾/停止理由；
- 检索和模型版本绑定；
- corpus/index snapshot 与最终报告绑定；
- citation precision/recall、unsupported claim 等机器评测。

## 3. 严重度排序的结构差距

### P0-1：双 Agent 事实源会让治理和权限漂移

证据：`AgentManifest` 与 `AgentDefinition` 分别维护 Agent 列表、权限、Prompt、工具、预算和记忆策略；代码声明为 12 对 7，干净数据库投影为 0 对 7。

影响：Rules/Silent/Knowledge/Research Agent 即使加入其中一处，也可能无法在另一运行入口执行或无法被正确授权。

修复：建立唯一 `agent_definition_version`；Manifest 变成由 Definition + Module Registry 生成的只读投影。禁止新的双写。

### P0-2：检索权限没有成为物理查询前置条件

证据：`kb.search` 查询所有已发布 KB 资产，未使用 `customer_id`、权限、有效期或 `ExecutionScope`。

影响：企业 KB 上线后可能跨客户、跨项目或返回失效规则。这不是相关性问题，而是数据泄露和错误执行问题。

修复：所有 Retriever 必须接收不可变 `CognitiveQueryContext`，Repository 在候选进入评分前执行 scope/ACL/status/effective-time 过滤；上下文缺失 fail-closed。

### P0-3：双记忆表且层级语义冲突

证据：`memory_entry_v1` 与 `agent_memory_v1` 并存；代码允许 L0-L4，完整规范要求 L1/L2/L3。迁移项目两表当前均为空，这正适合先建立新契约，再导入任何真实记忆。

影响：Agent 不知道哪个是长期事实，L3 可能被普通接口直接写入，无法保证方法论经人工确认。

修复：新建规范化 L1/L2/L3 表；旧表只通过迁移适配器读取。L1 只追加，L2 由 Consolidate Graph 生成，L3 只能从候选经人工批准发布。

### P0-4：当前 KB 不是 Research RAG

证据：子串 top-5，无 chunk、无 evidence span、无 query loop、无 citation verifier。

影响：系统可以“找到标题”，但无法完成跨文档研究、冲突识别、证据覆盖和可核查报告。

修复：采用联邦混合检索和 Research Graph，详见 `03-RESEARCH-RAG-TECHNICAL-DESIGN.md`。

### P0-5：治理角色尚未成为可执行控制链

证据：当前内置 Agent 中没有 Rules Agent、Silent Agent、Knowledge Agent 或 Research Agent 的统一 Runtime Definition；也没有规范中的治理规则/告警事实模型。

影响：治理只存在于文档或 Prompt，不能成为可审计、可回放的系统边界。

修复：先实现 deterministic Policy Decision Point、告警账本和 pause gate，再把治理 Agent 接到这些受限命令上。Prompt 不能替代强制执行。

### P1-1：Evidence 只到 bundle，未到 Claim

影响：报告有 evidence bundle 不等于每个结论被证据支持。

修复：增加 `research_claim`、`claim_evidence`、`evidence_span` 和 citation verifier；无证据 Claim 必须删除、降级为推断或明确标注未知。

### P1-2：知识、记忆、Skill 被“统一资产表”过度合并

影响：三者生命周期和权威性不同。知识有生效/废止，记忆有冲突/衰减，Skill 有输入输出/执行/风险/评测。一个 `kind` 字段不能安全表达。

修复：事实表分离，统一的是查询协议、索引目录和证据引用，不是底层内容表。

### P1-3：研究过程不可恢复、不可评测

影响：一次长研究若失败，只能重跑；也无法判断是检索失败、阅读失败、综合失败还是引用失败。

修复：Research Graph 的每个节点写 checkpoint、预算、查询、命中、证据、claim 和停止理由，并挂统一 Run/Usage/Evidence。

## 4. 已有资产的复用判断

| 现有资产 | 处理 |
|---|---|
| WorkflowService | 作为用户可见的 canonical definition/runtime，优先复用 |
| Graph/Loop v1/v2 | 作为受限 DSL/Domain 执行器，逐步编译到统一运行协议 |
| AgentRuntime | 保留 Run/Tool/Usage/Evidence 机制；替换关键词规划和双定义 |
| SupervisorAgent | 停止新增能力，迁移到统一 AgentRuntime 后退役 |
| blackboard_event_v1 | 保留不可变事件，拆出 current projection 和 L1 语义 |
| evidence_bundle_v1 | 保留 bundle；上层增加 span/claim/citation 关系 |
| ScopeResolver | 扩展为 CognitiveQueryContext 的唯一 scope 来源 |
| `.kb` SKU 向量 | 保留为 FMCG Domain Pack 专用索引，不并入企业 KB 事实表 |
| knowledge_document_v1 | 迁移为 source/document/version 的元数据来源，不继续扩字段硬撑完整 RAG |
| agent_asset_v1 | 只做旧兼容；Skill/Prompt/KB 新版本写入各自 registry |

### 4.1 前端接入判断

`frontend/` 是当前正式支持的新版产品前端，`docs/services.json` 将其登记为 `:4173` 服务，并通过同源代理访问平台 `:8400` 的 `/api/v1`；`web/` 仍是兼容工作台。Research Workbench、知识治理、记忆审批和 Agent 研究进度应优先接入 `frontend/src/` 的模块注册与 API 客户端，后端契约保持 UI 无关。除非明确存在兼容需求，不在两个前端同时开发第二套事实源。

## 5. 审计结论

当前系统已经具备可复用的运行账本、Workflow、审批、Evidence、Usage、Scope 和 append-only Blackboard，但认知层仍处于“演示级资产管理 + 子串检索”。Research RAG 的建设应从事实源、权限和证据契约开始，不应从选择向量数据库或 embedding 模型开始。
