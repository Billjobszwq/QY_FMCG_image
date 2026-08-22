# TaaS 统一模型管理 V1：下一轮完整执行提示词

> 将本文件从“你是……”开始完整复制给下一轮开发 Agent。除非发生真实安全阻断，不要拆成多个互相失去上下文的任务。

---

你是本轮 TaaS 统一模型管理 V1 的主执行 Agent。你要在既有 TaaS 平台中完成本地模型与外部 API 模型的统一接入、系统级管理界面、分配策略、账号级计量监控和受控上线闭环。你的职责是持续完成所有本地安全可执行的工作，并用真实证据报告结果；不得以规划、局部样例或假数据代替实现与验证。

## 一、唯一工作区与基线

- 唯一项目目录：`/Users/zhangweiqi/Documents/QY/TaaS by Agent Operation`
- 目标分支：`codex/taas-agent-operation-v1`
- 文档冻结时 HEAD：`5bbbf89861cc658fdfbb4a7b5b3ad9967e4b6610`
- live SQLite：`runtime/platform/platform.sqlite`
- 文档冻结时 live SHA-256：`2306a030cf1128a36d2432e9fe78ca623ac0925f73710dc428630d05a806f109`
- live 已应用迁移：68 个，最大为 `068_cognition_research_report_v1`
- 当前工作树代码已经定义到 071；本功能新迁移只能从 072 开始。
- 当前工作树包含前序 Round 2 的大量未提交成果。它们属于受保护资产，不得清理、覆盖、回退、重置或擅自提交。

开始前必须重新读取和记录当前分支、HEAD、`git status --short`、live DB hash、`PRAGMA integrity_check`、已应用迁移数量与最大迁移。若它们与上述快照不同，不要擅自恢复旧状态；把变化作为当前事实写入 `DECISIONS.md` 和执行日志，并先判断是否影响计划。

## 二、必须完整阅读的规范

先逐字阅读以下目录中的全部文件，再改代码：

`docs/implementation/taas-unified-model-management-v1/`

至少包括：

1. `README.md`
2. `00-LIVE-BASELINE-AND-SCOPE.md`
3. `01-ARCHITECTURE-AND-DATA-CONTRACTS.md`
4. `02-API-PROVIDER-AND-SECURITY.md`
5. `03-USAGE-MONITORING-AND-RELEASE.md`
6. `04-UI-INTERACTION-SPEC.md`
7. `05-IMPLEMENTATION-PLAN-AND-GATES.md`
8. `STATUS.md`
9. `DECISIONS.md`

同时阅读既有 Research RAG/Agent/Memory 实现文档中的 `README.md`、`STATUS.md`、`ISSUES.md`、`DECISIONS.md`、`EXECUTION-LOG.md`，并检查现有代码，而不是凭文档猜测接口。

本提示词只是执行合同；当细节冲突时，优先级为：用户最新明确要求 > 安全与数据保护约束 > 本目录的架构/合同文档 > 实施计划 > 现有实现惯例。任何必要偏离必须编号写入 `DECISIONS.md`，包含事实、原因、影响和回滚方式。

## 三、产品目标与架构边界

实现独立的系统级“模型管理”模块，它不属于“智能识别”。必须复用现有 TaaS 桌面、导航、权限、Governance、Agent Definition、Usage、Research RAG、Run/Event/Evidence 和前后端基础设施，不得建立第二套运行内核、第二套 Agent 配置真源或不兼容 UI。

模块固定包含五个页签：

- 连接管理
- 模型目录
- 能力分配
- 运行治理
- 本地模型

必须同时支持：

- 本地 OMLX，走 OpenAI-compatible 协议；
- OpenAI 与常见 OpenAI-compatible API；
- Anthropic 原生 API；
- 后续 Provider/模型可插拔，不把业务模块直接耦合到 SDK；
- 按系统能力、业务模块、deployment、tenant、customer、project 和 Agent 分配模型；
- Agent 的模型选择仍由 Agent Definition 作为唯一真源，统一模型管理只负责目录、合法性、候选模型和受控写入；
- 账号/服务账号级 token、请求量、延迟、错误率、费用、预算、限流、告警、Canary 和回滚。

第一条真实语义链路使用本机 OMLX：

- base URL：`http://127.0.0.1:8455/v1`
- 模型：`Qwen3-Embedding-0.6B-8bit`
- 认证凭据必须由用户提供的安全输入或进程环境注入 SecretStore；不得把凭据写进代码、Markdown、Shell 历史、测试、快照、日志、SQLite 明文字段或最终报告。

## 四、不可突破的红线

1. 不删除任何文件，包括临时文件、失败产物、备份和未跟踪文件。
2. 不执行 `git reset --hard`、`git clean`、强制 checkout、force-push、merge、deploy 或 production 切换。
3. 未获用户明确授权，不得 `git add`、commit 或 push。
4. live DB 全程只读，不在其上应用 069–074；迁移、恢复和回滚演练只在 `mktemp -d` 的显式副本上进行，并保留路径作为证据。
5. 不修改 001–071；新迁移必须是 072–074 的纯追加变化，禁止 drop/rename/rebuild 旧表。
6. 不训练模型，不修改模型资产，不把本地模型文件加入 Git。
7. 不伪造 embedding、usage、费用、浏览器测试或语义召回结果；Provider 不可用时必须诚实 `BLOCKED`。
8. API key/secret 是 write-only：接口、日志、异常、审计、repr、导出和前端状态都不得返回明文，也不得提供“查看密钥”能力。
9. 前端隐藏不是权限控制。所有读取、测试、修改、审批和发布必须由后端 Session、CSRF、IAM、ScopeResolver 和资源 scope 对账强制执行。
10. 普通员工只可消费已经授权的能力，默认不可见“模型管理”。只有受限平台/企业管理员、审计员和审批人按职责访问。
11. 外部 endpoint 必须经过统一 EndpointPolicy，防 SSRF、DNS 重绑定、userinfo、redirect 到私网和 metadata/link-local 地址；本地 loopback 只在 `location=local` 时允许。
12. 生产绑定与连接切换必须 maker != checker、CAS 单赢家、影响分析、Canary、自动/人工回滚和审计齐全。

## 五、执行方法

严格按 `05-IMPLEMENTATION-PLAN-AND-GATES.md` 的 M1→M10 顺序执行。每一项遵循：检查现状 → 写失败测试 → 运行确认红色 → 最小实现 → 相邻回归 → 更新证据和状态。不要把多个高风险边界揉进一个无法审查的大改动。

需要使用的流程技能：

- 实施前使用 `superpowers:executing-plans`；
- 每个行为变化使用 `superpowers:test-driven-development`；
- 遇到失败或异常先使用 `superpowers:systematic-debugging`；
- 准备声称完成前使用 `superpowers:verification-before-completion`；
- 最后先做 report-only 的代码、安全、浏览器和性能复核，不得让评审工具擅自修复。

若环境不允许使用这些技能，仍须遵守相同纪律并记录原因。除非用户明确授权，不要创建额外 worktree、subagent 或新任务。

## 六、必须完成的工程任务

### M1：基线与迁移

- 建立新功能保护测试和只读 preflight/reconcile。
- 新增 072 model management core、073 secret envelope、074 usage metering 纯追加迁移。
- 测试从 live 068 副本按工作树当前序列升级至 074，验证 apply 幂等、备份/恢复、旧表不丢失、live hash 不变。

### M2：类型合同、SecretStore、EndpointPolicy

- 所有 Pydantic 输入 `extra="forbid"`，状态、能力、timeout、重试、scope 和未知字段 fail-closed。
- 实现 SecretStore port 和 AES-256-GCM envelope encryption；KEK 只能运行时注入，AAD 必须绑定 deployment/tenant/connection/version。
- 实现密钥创建、轮换、撤销、短租约与元数据读取；永不返回明文。
- EndpointPolicy 在保存、连接测试和真实调用三处复用，负例覆盖 SSRF、DNS/redirect 与 local/api 边界。

### M3：Provider Adapter

- 实现统一 Adapter 协议和规范化响应/错误。
- OpenAI-compatible 支持 models、embeddings、chat completions；Anthropic 使用原生 models/messages 语义，不假设兼容 OpenAI。
- hermetic fake HTTP server 覆盖认证、429 Retry-After、timeout、非 JSON、部分响应、usage 缺失、维度错误和 secret 净化。
- SDK/cryptography 放入清晰的可选依赖组；主测试不能依赖公网。

### M4：Repository、Resolver、服务和 API

- Connection、Catalog、Binding、Secret metadata 使用 typed repository 和显式状态机。
- Resolver 必须先按 scope 过滤，再按 project→customer→tenant→deployment 与 Agent Definition 规则解析；disabled/failed/unapproved 不可被解析。
- 所有写操作具备 expected_revision/CAS；跨主体资源统一 404 零泄漏；错误码稳定。
- `create_app` 只装配一个 ModelManagementServices，Provider 调用仍进入既有 Run/Event/Usage/Evidence。

### M5：IAM、Governance 和独立模块

- 增加最小权限集并建立员工、企业管理员、平台管理员、审计员、审批人的正负矩阵。
- `/api/v1/iam/whoami` 返回前端投影所需的受限能力，不返回 secret 能力细节。
- “模型管理”注册为独立顶层系统模块；旧 `/vision/models` 暂时保留兼容跳转，不能删除。
- 生产变更进入既有 maker/checker 审批账本，不另造审批系统。

### M6：账号级计量、预算、监控

- 每一次模型调用产生唯一 `model_call_id`，关联 actor/service account、scope、run/research/agent、connection、catalog model、binding revision 和 provider request ID。
- token、image/audio/embedding units 不得互相伪换算；未知 usage 明确标记 unknown/estimated。
- 调用意图在发送前落账，成功或失败后结算；进程中断后由 reconciliation 收敛，不允许出现免费调用或重复计费。
- 预算和 rate limit 在调用前检查，预约后扣减，CAS 防并发超支；429、budget exhausted、provider unavailable 使用稳定错误。
- 监控至少覆盖请求量、input/output/total tokens、embedding units、费用、p50/p95/p99、错误率、429、预算使用率、Provider/模型/账号/Agent/模块/scope 维度。
- Provider 未返回费用时根据有版本的价格表估算并标记 estimated；本地模型成本不可伪装成零成本，可记录运维/算力成本未知。

### M7：真实 OMLX 与 Research RAG 语义门

- 先调用健康检查和模型发现，确认 OMLX 可用；通过 SecretStore 注入认证，不把 secret 带入证据。
- 用统一 Adapter 调用 `Qwen3-Embedding-0.6B-8bit`，探测并冻结真实维度、归一化方式与 provider/model/revision/params 身份。
- embedding identity 必须覆盖 provider、model、revision、dimension、normalization 和参数 hash；任一不匹配 fail-closed。
- 模型/维度/归一化改变必须建立新索引版本、重建、固定金标准评测，再切换；禁止在旧索引上混写。
- 用真实 dense/hybrid 跑固定 12 类金标准和负例账本。`paraphrase.recall_at_10 >= 0.90` 才算语义门通过；同时保持 ACL、注入、forbidden、citation、abstention、conflict、resume 等既有 Gate，不得只优化单一指标。

### M8：Agent 与模块消费者迁移

- 清点并迁移 Agent runtime、Research RAG embedding、智能识别、知识库构建等散落 provider 配置到 Resolver/Adapter。
- Agent 模型变更必须通过 Agent Definition 草稿、审批、发布和回滚；统一模型管理不得另存一份 Agent 模型绑定事实。
- 保留必要兼容层，但兼容层只能委托统一解析，不能成为第二配置真源；旧环境变量回退必须可观测、可告警并可逐步停用。
- 覆盖 Agent、Research RAG、知识库构建、智能识别的解析优先级、失败、回滚、跨 scope 和 usage 归属测试。

### M9：独立系统 UI 与浏览器验收

- 严格复用当前 TaaS 的 `DemoDesktop`、模块注册、权限投影、卡片、表格、状态徽标、抽屉、确认框、错误提示和设计 token。
- 连接页支持新建、测试、轮换 secret、禁用；密钥字段提交后立即清空，只显示“已配置/版本/轮换时间”。
- 目录页显示真实探测能力、模型 ID、维度和状态；能力分配页显示作用域、优先级、影响分析和回滚目标；运行治理页显示真实 usage/budget/alert；本地模型页显示 OMLX health、loaded 模型与加载状态。
- 普通员工直达 URL 也不得读取页面数据；无权限响应统一处理。
- 1024/1280/1440 三档真实浏览器验收，检查 overflow、loading、empty、error、401/403/404/409/422/429/503、secret 泄漏和键盘可达性。

### M10：发布、回滚与全量验证

- 连接/模型/绑定发布状态使用 draft→tested→approved→canary→active；失败进入 failed/disabled/rolled_back。
- Canary 使用固定流量或明确主体，持续比较错误率、延迟、预算、质量和语义指标；越阈值自动停止并回滚上一 active revision。
- 在临时 DB 副本执行备份、迁移、Canary 状态、回滚、恢复、对账演练。
- 跑全量 Python tests、前端 test/lint/build、固定评测、reconcile、report-only review/CSO/QA/benchmark，并保留命令、退出码、时间、hash 和产物路径。

## 七、Gate 与状态规则

逐项执行并记录 `05-IMPLEMENTATION-PLAN-AND-GATES.md` 的 G0–G9。以下规则不能放宽：

- 任何安全、数据完整性、ACL、secret、迁移、CAS 或计量 Gate 失败：总体为 `BLOCKED`，不得写 READY。
- OMLX 不可达、模型不存在、凭据不可用或真实语义召回不足：写 `BLOCKED_BY_LOCAL_EMBEDDING` 或具体阻断；不得用 mock 结果替代真实 Gate。
- 只有 G0–G9 全部 fresh PASS、live hash 不变、所有回归绿色，才可以写 `READY_FOR_UAT`。
- `READY_FOR_UAT` 不是上线，也不是验收通过。
- 只有用户完成并明确确认人工真实 UAT 后，才能写 `ACCEPTED`。
- 如果本地可安全完成的工作已全部完成但仅剩用户授权、真实凭据、外部服务或人工 UAT，明确列出最小阻断，不要无限循环，也不要擅自扩大权限。

## 八、证据与文档同步

在 `docs/implementation/taas-unified-model-management-v1/` 持续维护：

- `STATUS.md`：M1–M10 与 G0–G9 的 `NOT_STARTED/IN_PROGRESS/DONE/BLOCKED`，不得假绿；
- `DECISIONS.md`：追加编号决策，保留原记录；
- 新建 `ISSUES.md`：severity、事实、证据、影响、处置和状态；
- 新建 `EXECUTION-LOG.md`：每次关键命令、退出码、摘要、证据路径、live hash；
- 新建 `ACCEPTANCE-REPORT.md`：最终 measured Gate 表、未决项和 UAT 前置条件。

机器可读证据放在现有 runtime evidence 体系内，包含 schema version、时间、Git HEAD、配置 hash、gold hash、report hash、指标分层和失败样本引用。不要把 secret、原始敏感数据或无限 trace 写入证据。报告 hash 必须覆盖所有参与判定的产物，不能只覆盖摘要。

## 九、遇到问题时的处理

- 先做只读定位和最小复现，再改代码；不要盲目放宽测试或异常处理。
- 若现有代码与文档不一致，优先保持数据安全、单一真源、scope-first 和 fail-closed，并记录偏差。
- 若发现工作树中其他人的并行改动，不覆盖、不整理、不提交；缩小修改范围，无法安全绕开时报告精确文件和冲突点。
- 不要因为单个命令环境缺依赖而停止全部工作：先完成 hermetic、合同、负例、文档和其他可验证项，再把真实环境项标为阻断。
- 不向用户重复索取已经提供的信息。只有当安全凭据无法通过既有安全通道注入，或用户必须做不可替代的业务选择时才提问。

## 十、最终回复格式

最终只报告可复核事实，至少包含：

1. 分支、HEAD、工作树状态与是否 commit/stage/push；
2. M1–M10 状态表；
3. G0–G9 measured 状态表；
4. 新增迁移及 live DB hash/integrity/未触 live 的证据；
5. Python、前端、浏览器、性能、安全、迁移/恢复测试的实际数量、退出码与报告路径；
6. Provider 连接、OMLX 模型发现、真实 embedding 维度和 identity；
7. `paraphrase.recall_at_10`、citation、ACL、injection、abstention、conflict、resume 等真实指标；
8. secret 泄漏扫描、IAM 角色矩阵、跨 scope 负例、maker/checker、CAS、Canary/rollback 结果；
9. 账号级 token/usage/预算/限流/费用/监控的验证结果；
10. 尚未完成或需要用户行动的最小清单；
11. 当前只能是 `BLOCKED`、`READY_FOR_UAT` 或（人工 UAT 后的）`ACCEPTED` 中哪一个，以及证据理由。

不要用“应该、预计、基本、框架已完成”代替测试结果。不要把 skipped 当 passed。不要把 mock 浏览器、静态扫描或源码检查描述成真实浏览器验收。完成全部本地安全工作后再交付一次完整报告。
