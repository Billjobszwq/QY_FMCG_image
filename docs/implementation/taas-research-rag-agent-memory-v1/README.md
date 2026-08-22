# TaaS Agent 编排、记忆与 Research RAG V1

> 状态：`DESIGN_READY_FOR_REVIEW`
>
> 唯一开发基线：`/Users/zhangweiqi/Documents/QY/TaaS by Agent Operation`
>
> 现场快照：2026-08-20，分支 `codex/taas-agent-operation-v1`，设计时 HEAD `5bbbf89861cc658fdfbb4a7b5b3ad9967e4b6610`
>
> 性质：目标架构、开发计划、约束和执行提示词。本文档不是实施完成证明，也不授权训练、生产切换、部署、合并、推送或删除任何资产。

## 1. 结论

最优路线不是在现有 `kb.search` 上直接增加 embedding，也不是重新开发一套与平台并行的“RAG 服务”。应当在现有 Graph+Loop、Workflow、Agent Run、Evidence、Usage 和 Scope 基础上增加一个有明确边界的 `cognition` 认知内核，并逐步收敛当前双 Agent、双记忆和双知识入口。

原项目 `/Users/zhangweiqi/Documents/QY/项目/LLM-Image` 只作为迁移来源和历史证据，不是本计划的实施目录。所有新增源码、迁移、测试、UI 和实施状态文件都必须落在本页声明的唯一开发基线中。

目标系统由四个闭环组成：

1. **执行闭环**：所有 Agent 与 Research 任务最终编译为同一 Run/NodeAttempt/Approval/Evidence 协议。
2. **治理闭环**：规则由版本化 Policy 决定，Supervisor 只能调度，Silent Agent 只能监察和申请熔断，人类最终裁决。
3. **认知闭环**：L1 原始事件 → L2 业务事件 → L3 人工确认的方法论；知识、记忆和 Skill 保持独立事实源，通过统一查询网关联邦检索。
4. **研究闭环**：问题分解 → 多路检索 → 证据抽取 → 缺口/冲突搜索 → Claim 图 → 带引证综合 → 逐 Claim 核验。

这使 TaaS 的 RAG 从“根据一句话找几个相似文本”升级为“围绕研究目标持续寻找、核验、组织和引用证据”。

## 2. 阅读顺序

| 顺序 | 文件 | 用途 |
|---:|---|---|
| 1 | [00-LIVE-AUDIT-AND-GAP.md](00-LIVE-AUDIT-AND-GAP.md) | 当前代码、数据库和测试的事实审计 |
| 2 | [01-TARGET-ARCHITECTURE-AND-DECISIONS.md](01-TARGET-ARCHITECTURE-AND-DECISIONS.md) | 目标架构、方案比较和关键决策 |
| 3 | [02-DATA-CONTRACTS-AND-SECURITY.md](02-DATA-CONTRACTS-AND-SECURITY.md) | 数据模型、API、权限、版本和安全约束 |
| 4 | [03-RESEARCH-RAG-TECHNICAL-DESIGN.md](03-RESEARCH-RAG-TECHNICAL-DESIGN.md) | Research RAG 摄取、索引、检索、研究循环和评测 |
| 5 | [04-AGENT-GOVERNANCE-MEMORY-AND-PROMPTS.md](04-AGENT-GOVERNANCE-MEMORY-AND-PROMPTS.md) | Agent 编排、三权治理、记忆规则和运行提示词 |
| 6 | [05-IMPLEMENTATION-PLAN-AND-GATES.md](05-IMPLEMENTATION-PLAN-AND-GATES.md) | 分阶段 TDD 实施计划、文件安排、质量门 |
| 7 | [06-REFERENCES.md](06-REFERENCES.md) | TaaS 原始材料、项目证据和 Research RAG 一手资料 |
| 8 | [AGENT-EXECUTION-PROMPT.md](AGENT-EXECUTION-PROMPT.md) | 可直接复制给开发 Agent 的完整执行提示词 |
| 9 | [round-2-hardening/README.md](round-2-hardening/README.md) | 2026-08-21 fresh 复核后的 P0/P1 收口架构、计划、Gate 与新提示词 |

## 3. 方案权威顺序

出现冲突时按以下顺序裁决：

1. 用户当前明确指令和人工批准记录；
2. `TaaS 原生智能体操作系统：统一架构设计规范.md`；
3. 当前代码、测试、数据库和运行事实；
4. 本目录已记录的决策；
5. 两份原始分案及历史实施文档；
6. 外部论文和工具默认做法。

原始分案用于保留设计动机，不用于覆盖完整规范。项目手册用于接续，不是架构或训练授权。

## 4. 实施边界

本设计明确不做以下事情：

- 不启动长时间训练、模型晋级或生产 bundle 切换；
- 不移动、清理、暂存或删除 `.superpowers/`、数据集、模型、SQLite、报告和证据资产；
- 不把外部网页文本、上传文档或记忆内容当作系统指令；
- 不让 LLM 直接写 L2/L3、发布规则、发布 Skill 或恢复被熔断的 workflow；
- 不以向量相似度、模型自评或“回答看起来正确”代替可回查证据；
- 不在缺少权限标签时降级为全局检索；
- 不把 SKU 图像 `.kb` 直接改造成企业知识库事实源。

## 5. 完成定义

只有以下条件全部满足，才能称为 Research RAG V1 完成：

- 单一 Agent Definition/Manifest 投影关系已建立，旧入口没有产生新的事实分叉；
- L1/L2/L3、Knowledge、Skill、Research 事实表及其版本/来源/ACL 契约落地；
- 查询前置权限过滤、有效期过滤、客户/项目隔离均为 fail-closed；
- 本地知识检索具备 lexical + dense + metadata + rerank，并输出可定位证据片段；
- Research Graph 支持计划、缺口发现、反证搜索、暂停/恢复、预算和停止条件；
- 每个可验证 Claim 都能回到 `source_version + evidence_span`；
- 检索、生成、引证、安全、延迟和成本评测通过固定金标准；
- 迁移可回滚，历史数据不丢失，SQLite integrity 仍为 `ok`；
- 人类完成 UAT 并明确批准后，状态才可从 `READY_FOR_UAT` 进入 `ACCEPTED`。

## 6. 当前实施状态

Round 1 自动化框架已经大面积落地，但 2026-08-21 fresh 复核确认迁移预检顺序、
Research run scope 授权、Research Graph、Claim 支持性、真实 dense/hybrid、固定评测和
系统验收尚未闭环。当前权威状态为
`BLOCKED_BY_SECURITY_MIGRATION_AND_EVALUATION`。下一轮必须从
[Round 2 收口包](round-2-hardening/README.md) 开始，不得直接沿用旧日志中的
“Task 1–13 DONE”或 `READY_FOR_UAT`。
