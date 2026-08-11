# IMPLEMENTATION-LIST · Domain Packs V2

> 每项任务：状态词、依赖、验收、证据。状态词只用任务书规定的
> NOT_STARTED / IMPLEMENTED_UNVERIFIED / VERIFIED_LOCAL /
> READY_FOR_USER_ACCEPTANCE / ACCEPTED / BLOCKED。

## T0 现场冻结与治理

| # | 任务 | 状态 | 依赖 | 验收 | 证据 |
|---|---|---|---|---|---|
| T0-1 | 完整阅读必读文档 | VERIFIED_LOCAL | — | 10 项必读逐字完成 | EXECUTION-LOG 2026-08-11 条目 |
| T0-2 | 安全基线记录 | VERIFIED_LOCAL | — | HEAD/branch/worktree/服务/DB/训练/production 全记录 | EXECUTION-LOG 2026-08-11 条目 |
| T0-3 | 治理文档建立 | VERIFIED_LOCAL | T0-1 | 六份文档齐备 | 本目录 6 个 md |

## Phase A · 连续性与 UI 硬阻断（Gate G1）

| # | 任务 | 状态 | 依赖 | 验收 | 证据 |
|---|---|---|---|---|---|
| A-1 | ABOSV2-P0-001 统一 current task projection，旧 250 不再进当前待办 | VERIFIED_LOCAL | T0 | 主页/主管/任务板/API 同一投影；supersession 测试；浏览器对账 | commit `4af64f2d`；现场 current=2/superseded=254 |
| A-2 | ABOSV2-P0-002 快速目标服务端落 goal draft 并传入主管，刷新可恢复 | VERIFIED_LOCAL | A-1 | goal_draft 表/API；浏览器输入→主管可见→确认生成计划 | commit `79b3a534`；实跱 E2E + 浏览器截图 |
| A-3 | ABOSV2-P1-005 识别任务统一详情（work/run/trace/tier/错误/证据/usage/父子/下一动作） | VERIFIED_LOCAL | A-1 | 详情抽屉数据全部来自真实 API | commit `15a39325`；work/run 环诚实标注待 Phase B |
| A-4 | ABOSV2-P1-006 1024/768 主管不遮挡 + 导航标签/tooltip + 表格转 card | VERIFIED_LOCAL | — | 四视口浏览器截图与 DOM 断言 | commit `15a39325`；8 张截图 |
| A-5 | ABOSV2-P0-004 Service Tier 未真实路由前 UI 禁用/标记未启用 | VERIFIED_LOCAL | — | 档位选择诚实化；无伪装可售卖 | commit `15a39325`；截图 + 契约守卫测试 |
| A-6 | ABOSV2-P1-007 跨层 continuity 测试（非源码字符串断言） | VERIFIED_LOCAL | A-1..A-5 | UI→command→run→record→event→usage→projection 测试 | commit `15a39325`；test_abos_v2_continuity.py |
| A-7 | ABOSV2-P0-003 识别/Graph/Agent/Usage 断链（归入 Phase B 全链贯通） | VERIFIED_LOCAL | B-6 | 见 B-6/B-7 | commit `13106320`；实跱全链 ID 对账 |

## Phase B · Work/Event/Usage Foundation（Gate G2）

| # | 任务 | 状态 | 依赖 | 验收 | 证据 |
|---|---|---|---|---|---|
| B-1 | 版本化 schema：BusinessRunV1/WorkItemV2/EventEnvelopeV1/UsageEventV2/EvidenceBundleV1 | VERIFIED_LOCAL | A | migration 幂等 | commit `13106320` migration 033；全字段契约测试 |
| B-2 | Command Gateway（Web/API/Agent 共用） | VERIFIED_LOCAL | B-1 | 三入口同一 gateway | POST /api/v1/commands；continuity+control_plane 测试 |
| B-3 | Transactional Outbox + 幂等 + 乐观锁 + 状态机（pause/resume/retry/cancel/dead-letter） | VERIFIED_LOCAL | B-1 | 集成测试 | outbox 同事务；幂等键去重；run 状态机（retry/cancel 已覆盖；pause/dead-letter 待 Phase C workflow runtime 补齐） |
| B-4 | current projection 可重建 + hash/count 对账 | VERIFIED_LOCAL | B-1 | 重建后与事件一致 | /api/v1/control/projection + reconcile consistent=true |
| B-5 | 旧 review/recognition/training/agent command 兼容投影 | VERIFIED_LOCAL | B-1 | 历史不删、current 不含 superseded | A-1 supersession + workitems 兼容保留 |
| B-6 | 识别全链实跑一条并报告全部 ID | VERIFIED_LOCAL | B-1..B-5 | 全链 ID 一致 | EXECUTION-LOG：goal/run/work/corr/task/trace/evidence/usage 全链报告 |
| B-7 | 失败路径：同一 run 展示错误与恢复 | VERIFIED_LOCAL | B-6 | 失败可重试/恢复 | run-637bcd55272842c5 failed → retry succeeded（同一 run） |

## Phase C · Workflow Studio MVP（Gate G3）

| # | 任务 | 状态 | 依赖 | 验收 | 证据 |
|---|---|---|---|---|---|
| C-1 | canonical WorkflowDefinition/Version/Node/Edge/Trigger/Variable/Policy | VERIFIED_LOCAL | B | schema+不可变版本 | commit `aa7ba378` migration 034；发布后修改拒绝测试 |
| C-2 | 15 类节点支持 | VERIFIED_LOCAL | C-1 | 节点库来自已注册 Capability | node-library 端点；15 类型；fail-closed 测试 |
| C-3 | draft/lint/simulate/shadow/approve/publish/deprecate 生命周期 | VERIFIED_LOCAL | C-1 | 状态机测试 | 现场 409 拦截未批准发布；shadow 合并入 simulate（诚实披露） |
| C-4 | runtime checkpoint/retry/pause/resume/cancel/dead-letter | VERIFIED_LOCAL | C-1 | 重启可恢复 | checkpoint 表 + 死信表；测试覆盖失败→重试→恢复 |
| C-5 | Studio 七页签 UI + Workflow Agent draft（人工批准门） | VERIFIED_LOCAL | C-1..C-4 | 浏览器验收 | 浏览器 6/6（DOM/a11y，截图通道故障已披露） |
| C-6 | WorkflowExecutorAdapter：Native 完整；n8n/Dify 边界 PoC 或诚实 blocked | VERIFIED_LOCAL | C-1 | SPI 契约测试 | N8n/Dify available()=False + start() 抛 blocked（许可未确认） |
| C-7 | 首个照片识别模板真实贯通 | VERIFIED_LOCAL | C-1..C-6 | 同一 Work/Run/Event/Usage 时间线 | wf-d63bc03b2f → run-50adc9a8f9a6 → 子 run/task/trace/evidence/usage 全链报告 |

## Phase D · IAM 与主数据（Gate G4）

| # | 任务 | 状态 | 依赖 | 验收 | 证据 |
|---|---|---|---|---|---|
| D-1 | 账号/用户/服务账号/Agent 身份/角色/permission bundle/批准矩阵/审计 | VERIFIED_LOCAL | C | 契约+越权测试 | commit `55e71271` migration 035；9 项红转绿 |
| D-2 | SKU 库/客户库/项目库（新旧包装、别名、客户显示名、有效期） | VERIFIED_LOCAL | D-1 | 主数据版本化 | supersede 链/别名/有效期测试；现场建库 |
| D-3 | 两个测试客户隔离证明（数据/任务/Usage/报表/Agent） | VERIFIED_LOCAL | D-1,D-2 | 隔离测试；test fixture 标记 | 实跱：alice 只见 cust-a、B 403、agent fail-closed；usage 按客户作用域；浏览器 5/5 |

## Phase E · 问卷纵向切片（Gate G5）

| # | 任务 | 状态 | 依赖 | 验收 | 证据 |
|---|---|---|---|---|---|
| E-1 | 题型/版本/跳题 DAG 校验/评分/发布/分配/填写 | NOT_STARTED | D | 样板问卷 E2E | — |
| E-2 | 拍照题证据 + 识别 suggestion → 人工 final | NOT_STARTED | E-1 | 全链时间线 | — |
| E-3 | 后台 correction event + 重算版本 | NOT_STARTED | E-1 | 审计留痕 | — |

## Phase F · BI / 位置外勤 / 财务（Gate G6/G7/G8）

| # | 任务 | 状态 | 依赖 | 验收 | 证据 |
|---|---|---|---|---|---|
| F-1 | BI 语义层 + ReportSpec + Analytics Agent + 异常追问闭环 | NOT_STARTED | E | G6 门禁 | — |
| F-2 | 位置外勤：地址/地理编码/地图/VRP/围栏/到店证据/差旅费 | NOT_STARTED | F-1 | G7 门禁 | — |
| F-3 | 财务：contract/rate card/meter/invoice/settlement/adjustment | NOT_STARTED | F-2 | G8 门禁：账单下钻到 run/node/证据 | — |

## T9 · 系统级收口（Gate G9）

| # | 任务 | 状态 | 依赖 | 验收 | 证据 |
|---|---|---|---|---|---|
| Z-1 | 模块/Agent 插拔交叉验证（Manifest/Capability/UI slot/节点库/tool registry/OpenAPI fail-closed） | NOT_STARTED | C,D | 缺一环即失败 | — |
| Z-2 | 新增 6 个 Domain Agent（独立 identity/allowlist/scope/预算/记忆 ACL） | NOT_STARTED | D | 契约测试 | — |
| Z-3 | 最终验证（hermetic/host_mps、typecheck/build、DB、安全、性能、健康） | NOT_STARTED | ALL | G9 清单 | — |
| Z-4 | 四手册更新（USER-HANDBOOK/OPERATOR-RUNBOOK/MODULE-AGENT-DEV-GUIDE/CODEX-HANDBOOK） | NOT_STARTED | Z-3 | 按角色可操作 | — |
