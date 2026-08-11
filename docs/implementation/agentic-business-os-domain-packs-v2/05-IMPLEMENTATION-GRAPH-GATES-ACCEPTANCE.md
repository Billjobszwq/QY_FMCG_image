# 实施 Graph、门禁与验收

## 1. 总原则

- 采用纵向切片，不做“大批 schema + 大批页面 + 最后联调”。
- 每个切片必须从 UI/API/Agent 进入，同一 workflow run 执行，产生 domain record/event/evidence/usage，再回到任务详情与报表。
- 先写红契约与真实浏览器复现，再修改；不得为了绿测删除断言。
- 不启动训练、不切 production、不删除历史资产，除非获得单独授权。

## 2. 阶段顺序

### T0：现场冻结与治理

- 完整阅读本目录、全局路由、CODEX 手册、现有用户手册和最近提交；
- 保存 HEAD/branch/worktree/services/DB/schema/API/browser baseline；
- 建立 `IMPLEMENTATION-LIST.md`、`EXECUTION-LOG.md`、`ISSUES.md`、`DECISIONS.md`、`ACCEPTANCE.md`；
- 把本文件 Bug 编号逐项写入红测试。

Gate G0：事实可复现，用户资产零触碰，production/训练零变化。

### T1：P0 连续性与 UI 修复

- 统一 current task projection，旧 250 不再进入当前待办；
- 快速目标服务端持久化并传给主管；
- 识别任务详情显示 trace/evidence/error/tier/usage；
- 1024/768 抽屉、导航和表格修复；
- Service Tier 未真实实现前禁用虚假档位。

Gate G1：浏览器四视口、API/DB 对账和 supersession 测试全过。

### T2：Work/Event/Usage Foundation

- migration 与 domain services；
- outbox、投影、幂等、状态机、证据和计量；
- 兼容迁移识别/审核/训练/Agent 命令；
- current projection 可从事件重建。

Gate G2：至少一条识别任务贯通 `goal/command → run → node → recognition → usage → evidence → timeline`，所有 ID 一致。

### T3：Workflow Kernel + Studio MVP

- WorkflowDefinition/Version/Node/Edge/Trigger；
- Runtime/checkpoint/retry/pause/resume/cancel/dead-letter；
- 节点 schema、权限、meter；
- Studio 画布、向导、Agent 草稿、lint、simulate、approve、publish；
- Native Adapter，n8n/Dify 只建立 SPI 和受控 PoC，不接管事实源。

Gate G3：照片识别模板真实运行；重启后可恢复；失败节点可重试；版本不可变；预算/权限越界 fail-closed。

### T4：IAM + Master Data

- tenant/customer/project/user/role/policy；
- SKU/客户/项目库；
- 迁移现有识别数据到 scope 映射，不改历史 ID；
- 账号、角色和数据权限 UI/API。

Gate G4：两个客户的数据、任务、报表、Usage 相互不可见；Agent 权限同样受限。

### T5：Survey 纵向切片

- 题型、版本、跳题、评分、响应、修正；
- 拍照题 → 质量 → 识别建议 → 人工确认 → 得分 → 报表；
- 后台修正事件与重算。

Gate G5：用真实样板完成一份含全部首批题型的问卷；跳题、评分、照片识别和报表数值可追溯。

### T6：BI 纵向切片

- semantic layer、指标/维度、ReportSpec、Dashboard；
- NL draft、预览、批准、发布；
- anomaly → 追问 WorkItem → 反馈 → 报告新版本。

Gate G6：Agent 不能生成越权查询；同一数字能下钻到数据版本和问卷/识别证据。

### T7：Geo/Field 纵向切片

- 员工、地址、地理编码、地图；
- VRP 规划、多项目、费用、围栏；
- 外勤 → 到店 → 问卷/拍照 → 费用。

Gate G7：路线约束、未分配原因和费用可解释；低置信度地址不自动派发；位置权限与保留策略通过。

### T8：Finance/Billing 纵向切片

- contract/rate card/meter/usage/invoice/settlement；
- 月订阅、按照片、按 token；
- 客户/项目拆分、冲正和对账。

Gate G8：所有账单行能追溯到 immutable usage 和业务 run；历史价格不被新价格覆盖。

### T9：系统级收口

- 性能、容量、rate limit、备份恢复、安全、WCAG；
- 完整用户手册、管理员 Runbook、开发指南、OpenAPI/SDK；
- 模块禁用/升级/迁移/回滚演练。

Gate G9：只可写 `READY_FOR_USER_ACCEPTANCE`；用户验收前禁止声称 production-ready。

## 3. 每阶段必测

1. Unit：状态机、规则、计算；
2. Contract：Manifest/Capability/schema/event/usage；
3. Integration：DB 事务、outbox、恢复、幂等、权限；
4. E2E：Web/API/Agent 三入口；
5. Browser：四视口、键盘、错误恢复；
6. Security：tenant 越权、CSRF/SSRF、secret、注入、rate limit；
7. Performance：API p50/p95、workflow node、并发、队列积压；
8. Reconciliation：run/node/domain/event/usage/evidence/projection 数量与 ID。

## 4. 完成状态词

- `NOT_STARTED`：未实现；
- `IMPLEMENTED_UNVERIFIED`：代码存在但未完成真实验证；
- `VERIFIED_LOCAL`：本机证据通过；
- `READY_FOR_USER_ACCEPTANCE`：所有自动验收通过，等待用户；
- `ACCEPTED`：用户完成验收；
- `BLOCKED`：有明确外部阻断。

禁止使用模糊的“基本完成”“大致可用”“框架已搭好”。planned 页面、smoke、mock、静态截图不能计为业务完成。

## 5. 最终报告格式

按以下顺序：HEAD/branch/worktree、commit 链、阅读清单、before 证据、Bug 逐项根因/修复/测试、schema/migration、统一 ID 对账、Workflow 模板、各 Domain Pack 实跑、Agent/权限、Usage/费用、UI 四视口、测试与性能、安全、服务健康、未改变声明、未关闭问题、当前 Gate、用户唯一需要做的下一动作。
