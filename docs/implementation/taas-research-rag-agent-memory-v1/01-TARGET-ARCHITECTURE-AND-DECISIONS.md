# 目标架构与关键决策

## 1. 三种路径比较

### A. 在现有 `kb.search` 上增加向量检索

优点：改动小，能很快演示语义搜索。

缺点：保留双 Agent、双记忆、KB 元数据/内容分叉、权限缺失和无 Claim 引证的问题。它最多是 Hybrid Search，不是 Research RAG。

结论：只允许作为检索基线实验，不作为目标架构。

### B. 独立重写 Agent、Memory、RAG 微服务

优点：边界干净，可直接选新技术栈。

缺点：会复制现有 Run、Workflow、Scope、Approval、Evidence、Usage 和 IAM；迁移期形成两套控制面，真实业务风险最高。

结论：拒绝大爆炸重写。

### C. 在现有平台内建立 Cognition Bounded Context

优点：复用现有执行与治理资产；可先双读、再切读、最后停旧写；每阶段都有可工作的纵向切片。

代价：需要兼容层和明确的退役计划，短期文件数量会增加。

结论：采用。它最符合 TaaS “内核统一、Domain Pack 可定制”和现有项目的安全边界。

## 2. 目标分层

```text
┌────────────────────────────────────────────────────────────┐
│ Human Decision / UAT / Approval                            │
└──────────────────────────┬─────────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────────┐
│ Governance Plane                                            │
│ Policy Service + Rules Agent + Silent Agent + Audit/Pause   │
└──────────────────────────┬─────────────────────────────────┘
                           │ policy decision / alerts
┌──────────────────────────▼─────────────────────────────────┐
│ Orchestration Plane                                         │
│ Workflow canonical DSL → Unified Run/Node/Approval/Budget   │
│ Supervisor / Domain Agents / Research Graph                 │
└──────────────────────────┬─────────────────────────────────┘
                           │ typed commands/events
┌──────────────────────────▼─────────────────────────────────┐
│ Cognition Plane                                             │
│ Memory L1/L2/L3 │ Knowledge │ Skill │ Research Evidence     │
│ Federated Query Gateway + ACL-first Retrieval + Indexes      │
└──────────────────────────┬─────────────────────────────────┘
                           │ immutable refs
┌──────────────────────────▼─────────────────────────────────┐
│ Data Plane                                                  │
│ Metadata/UoW │ CAS/Object Store │ Lexical │ Vector │ Graph   │
└────────────────────────────────────────────────────────────┘
```

## 3. 唯一事实源

| 概念 | 唯一事实源 | 只读投影/兼容入口 |
|---|---|---|
| Agent 定义 | `agent_definition_version` | `agent_manifest_projection` |
| 规则 | `policy_rule_version` | Agent prompt cache、UI |
| Agent 运行 | 统一 Run/NodeAttempt | `agent_run_v1` 兼容投影 |
| L1 记忆 | `memory_l1_event` | Blackboard current cards |
| L2 记忆 | `memory_l2_episode` | Agent episodic summary |
| L3 记忆 | `memory_l3_methodology_version` | Skill 候选、建议视图 |
| 知识 | source → document → version → chunk/span | 搜索结果、摘要、实体图 |
| Skill | `skill_definition_version` | tool catalog、Agent allowlist |
| Research | `research_run/step/query/claim/evidence` | 报告、引用、进度 UI |
| 文件 | CAS `ArtifactRef` | 本地/MinIO/S3 adapter |
| 索引 | 可重建派生物 + `index_build` 清单 | lexical/vector/graph backend |

索引不是事实源。删除并重建索引不能改变知识、记忆、Skill 或研究结论的原始版本。

## 4. 统一执行协议

Workflow 是面向用户的 canonical definition。Graph v1、Loop v2、Agent tool loop 和 Domain pipeline 最终都映射到以下协议：

```text
DefinitionVersion
  └─ Run
      ├─ NodeAttempt
      │   ├─ Input/Output ArtifactRef
      │   ├─ Transition
      │   ├─ Usage
      │   └─ Evidence
      ├─ Approval
      ├─ Checkpoint
      └─ Final Report
```

Agent 只负责做有界 plan/decision，不拥有另一套状态机。Worker 只负责 lease、隔离、重试和取消，不解释业务。Domain Pack 只提供 typed node handler、schema、policy 和 UI slot。

## 5. Agent 架构

### 5.1 永久治理角色

- **Supervisor Agent**：目标拆解、Graph 选择、预算、委派、结果汇总；不直接修改长期记忆和规则。
- **Rules Agent**：起草和版本化规则；只有人类批准才能发布。
- **Silent Agent**：观察事件、检查策略/索引/引用/预算异常；只能发告警和请求 pause，不能参与业务或改写事实。

治理 Agent 的“权力”由 deterministic service 提供。LLM Prompt 不是权限边界。

### 5.2 认知角色

- **Knowledge Agent**：摄取、结构化、版本候选和索引构建；不能自行发布知识。
- **Research Agent**：执行 Research Graph；不能绕过 Query Gateway 或 Citation Gate。
- **Memory Consolidator**：L1→L2 候选；L2→L3 只能生成 candidate。
- **Skill Curator**：把已批准 L3/知识流程转成 Skill candidate；不能直接发布。

Planner、Retriever、Evidence Reader、Contradiction Checker、Synthesizer 和 Citation Verifier 默认是 Research Graph 的受限 node role，不必都成为长期自治 Agent。这样可以减少人格/记忆/权限面，也使测试粒度更清楚。

### 5.3 Domain Agent

识别、财务、外勤、问卷、BI 等 Agent 保持 Domain Pack 边界。它们通过 `CognitiveQueryGateway` 查询规则、案例和 Skill，通过 Command Gateway 执行动作，不直接访问索引或底层表。

## 6. 认知系统不是“一张统一表”

完整规范中的“统一索引层”在工程上实现为统一查询协议和索引目录，而不是把所有内容混进同一 embedding 空间。

原因：

- 知识回答“应该怎么做”，需要状态、生效期和权威来源；
- L2 记忆回答“以前实际怎么发生”，允许冲突并随时间降权；
- L3 回答“哪些方法被验证”，必须人工确认；
- Skill 回答“系统能执行什么”，需要 schema、依赖、风险和版本；
- Research evidence 回答“这次结论被什么证据支持”，必须冻结在 corpus/index snapshot 上。

统一 Query Gateway 根据 `target_kinds` 调用不同 retriever，再做跨源融合。绝不在没有类型约束时直接对所有向量 top-k。

## 7. 研究模式

Research Agent 支持四类模式：

| 模式 | 目标 | 默认数据源 |
|---|---|---|
| `lookup` | 找到明确规则/定义/事实 | Knowledge 有效版本 |
| `case_analysis` | 查找相似实际事件 | L2，必要时回查 L1 |
| `methodology` | 使用已确认方法 | L3 + Skill |
| `deep_research` | 分解问题、跨源收集与综合 | Knowledge + L2/L3 + 允许的外部源 |

系统先分类再路由。简单查询不进入昂贵 Research Loop；全局/多跳/比较/审计问题才进入深研究。

## 8. 本地优先与未来扩展

### 首个可用版本

- 当前 SQLite 继续承载事务事实，新增 Repository/UoW，禁止新服务直接使用 `store._conn`；
- 本地 CAS 保存原文和派生产物；
- lexical、vector、graph 通过端口抽象，可用最小本地 adapter 建基线；
- 所有 index build 写版本、输入 hash、模型版本和参数。

### 生产前目标

- PostgreSQL 作为事务元数据事实源；
- pgvector 或等价 adapter 承载向量；
- PostgreSQL FTS 先作为 lexical 基线，若固定评测不足，再切换 OpenSearch/Tantivy adapter；
- MinIO/S3 兼容对象存储承载 CAS；
- Entity/Relation 先用关系表和 materialized projection，只有全局问题评测证明必要时才引入专用图数据库。

这避免为了“像 RAG”提前引入五套基础设施。

## 9. 决策记录

| ID | 决策 | 理由 |
|---|---|---|
| D-001 | 采用 Cognition bounded context 渐进收敛 | 避免双控制面和大爆炸迁移 |
| D-002 | Workflow 为 canonical definition | 当前通用节点、版本、恢复和审批能力最完整 |
| D-003 | Agent 不拥有独立执行状态机 | 所有运行都应共享取消、预算、证据和恢复 |
| D-004 | Knowledge/Memory/Skill 分表，查询统一 | 生命周期和权威性不同 |
| D-005 | ACL/scope 在召回前过滤 | 排序后过滤会泄露统计和内容 |
| D-006 | Claim-level citation 是发布硬门 | 文档级引用无法证明每条结论 |
| D-007 | GraphRAG/RAPTOR 为按需索引 | 全量预计算成本高，不是每个语料都受益 |
| D-008 | 外部网页永远是不可信数据 | 防止 prompt injection 进入控制面 |
| D-009 | 规则/Skill/L3 发布必须人工批准 | 保留人类最终裁决和可撤销性 |
| D-010 | 先评测基线，再选向量库/图数据库 | 组件选择由质量、成本和规模证据驱动 |
