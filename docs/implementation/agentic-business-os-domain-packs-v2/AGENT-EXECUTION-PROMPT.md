# Agent 执行提示词：连续任务底座、智能工作流与首批 Domain Packs

你要在仓库 `<legacy-workspace>` 继续实施 Agentic Business OS。本次不是做一批静态页面，而是修复现有任务断链，并建立可以让识别、问卷、BI、外勤、财务真正连续运行的 Graph+Loop 底座。

## 一、不可违反的定位

1. 这不是识别系统，也不是传统 SaaS。识别只是第一个 Domain Pack；核心是受权限、预算、证据、计量和人工节点约束的 Graph+Loop 智能业务操作系统。
2. 每个模块独立开发、独立版本、独立 Agent、独立数据产品和 API，通过版本化 Capability/Event/Workflow 接入主线。
3. 模块化不等于多套事实源。客户、项目、权限、Work、Run、Event、Evidence、Usage 必须统一。
4. 任何新页面必须连接真实 domain service；禁止假按钮、假图表、硬编码数字、静态成功卡和只保存于 localStorage 的业务状态。
5. 不得把 n8n 或 Dify 作为系统核心。ABOS 保留唯一 Workflow/Run/Event/Usage 事实；n8n 只允许受控 connector adapter；Dify 只允许 AI subflow adapter。

## 二、先完整阅读

必须先逐字阅读：

1. `<ai-workflow-root>/routing/GLOBAL_AGENT_ROUTING.md`
2. `docs/CODEX-PROJECT-HANDBOOK.md`
3. `docs/README.md`
4. `docs/USER-HANDBOOK.md`
5. `docs/OPERATOR-RUNBOOK.md`
6. `docs/MODULE-AGENT-DEV-GUIDE.md`
7. `docs/implementation/agentic-business-os-workbench-v1/` 全部文件
8. `docs/implementation/project-logic-chain-v3/` 的状态、事实源和逻辑链
9. `docs/implementation/agentic-business-os-domain-packs-v2/` 本目录全部文件
10. 最近至少 20 个 commits，以及 Module Registry、Capability Registry、Graph/Loop、Agent runtime、workitems/taskboard、recognition task、usage、Web AppShell/页面/测试源码。

阅读完成后先建立并持续维护：

- `IMPLEMENTATION-LIST.md`：每个任务的状态、依赖、验收、证据；
- `EXECUTION-LOG.md`：append-only 时间线；
- `ISSUES.md`：使用本任务书 Bug 编号；
- `DECISIONS.md`：架构决定和替代方案；
- `ACCEPTANCE.md`：机器/浏览器/人工验收；
- `STATUS.md`：唯一当前 Gate。

## 三、安全与 Git 边界

- 开始先记录 HEAD、branch、worktree、tracked/untracked、服务、进程、DB integrity、migration、production、训练进程；
- 用户未跟踪的数据集、模型、SAM、micro-gold、quality 和训练资产禁止删除、覆盖、移动、暂存；禁止 `git add -A`；
- 小步 TDD、小步 commit；禁止 reset/checkout 用户改动；
- 不 merge、不 push、不 deploy；
- 不启动任何 YOLO/SAM/classifier/QLoRA 训练；不切换 production；除非用户另行明确授权；
- 服务 restart 只能精确、安全、可恢复，且必须证明未影响训练/production。

## 四、执行方法：Graph+Loop，不得重复返工

每个任务按循环执行：

`读取事实 → 浏览器/接口复现 → 红测试 → 根因 → 最小实现 → 单测 → 集成 → 浏览器 → 对账 → 证据 → commit → 更新日志`

不得先改 CSS 再猜问题；不得为了通过测试修改断言；不得把 mock/smoke 写成完成。发现本任务书与现场冲突时，以现场证据为准，先在 DECISIONS/ISSUES 披露，再做兼容修订。

## 五、Phase A：先修复现有连续性与 UI（硬阻断）

逐项关闭 `ABOSV2-P0-001`～`P0-004`、`P1-005`～`P1-007`：

1. 统一 current task projection；旧 250 只保留历史，不出现在主页、主管、任务板 current 计数；
2. 修复“快速目标”：文本服务端落 goal draft，打开主管后可见，确认后形成计划/命令；刷新可恢复；
3. 为识别任务补统一详情：task/work/run/trace、tier/profile、输入输出、错误、证据、usage、父子任务、下一动作；
4. 1024 和 768 下主管默认不遮挡；导航有可理解标签/tooltip；表格转 card/detail；
5. Service Tier 若未真正路由不同模型/计算/SLA/价格，UI 必须禁用或明确未启用，不得继续伪装可售卖；
6. 新增真实浏览器和跨层 continuity 测试，不能只做源码字符串断言。

Phase A 未通过，不得开始新 Domain 页面。

## 六、Phase B：统一 Work/Event/Usage Foundation

按 `01-UNIFIED-WORK-EVENT-USAGE-CONTROL-PLANE.md` 实现版本化 schema/domain service：

- BusinessRunV1、WorkItemV2、EventEnvelopeV1、UsageEventV2、EvidenceBundleV1；
- Transactional Outbox、current projection、幂等、乐观锁、pause/resume/retry/cancel/dead-letter；
- tenant/customer/project/correlation/causation/parent/subject 全字段；
- 旧 review/recognition/training/agent command 以兼容投影接入，不删除历史；
- current projection 可从事件重建并 hash/count 对账；
- 所有 Web/API/Agent 入口共用 command gateway。

必须实跑一条识别：

`快速目标或上传 → command → workflow run → recognition node → recognition domain record → event/evidence/usage → current task/timeline`

报告所有 ID，证明全链一致。若识别失败，也必须在同一 run 中展示错误和恢复。

## 七、Phase C：智能 Workflow Studio MVP

按 `02-WORKFLOW-STUDIO-AND-N8N-DIFY.md` 完成：

- canonical WorkflowDefinition/Version/Node/Edge/Trigger/Variable/Policy；
- 节点至少支持 trigger、domain command/query、condition、transform、agent、model、human approval、wait、loop、parallel/join、subflow、connector、end；
- draft/lint/simulate/shadow/approve/publish/deprecate；
- runtime checkpoint、retry、pause/resume/cancel、dead-letter；
- 节点库从已注册 Capability JSON Schema 动态生成；
- Workflow Studio 位于工作流模块内，包含搭建、模板、运行、待办批准、连接器、Agent/模型、证据用量；
- Workflow Agent 可用自然语言生成 draft patch，但只能预览/模拟，发布和高风险运行必须人工批准；
- 建立 `WorkflowExecutorAdapter`；Native 完整实现，n8n/Dify 只做边界清晰的 adapter PoC。若许可证、依赖或网络不满足，诚实标记 blocked，不得复制第三方源代码伪装完成。

首个模板使用真实照片识别链贯通。只保存画布 JSON 不算完成。

## 八、Phase D：IAM 与主数据

先实现账号开设、用户/服务账号/Agent 身份、内置与自定义角色、permission bundle、tenant/customer/project scope、批准矩阵和审计。

实现共享 SKU 库、客户库、项目库，支持 SKU 新旧包装、别名、客户显示名和有效期。它们是 Master Data Pack，不得只写在问卷表中。

必须用两个本地测试客户证明数据、任务、Usage、报表和 Agent 查询相互隔离；测试数据明确标记 test fixture，不得混入生产数据。

## 九、Phase E：问卷纵向切片

完成：SKU库/客户库/项目库引用、单选、多选、填空、打分、跳题、拍照绑定、自动评分、问卷版本、发布、分配、填写、入库、后台修正、报表输入。

约束：

- 跳题是可验证 DAG，检测循环/不可达/冲突；
- 已发布问卷不可原地修改；
- 后台改答案必须 correction event + 原因 + 审计 + 重算版本；
- 拍照题保存位置/时间/设备/质量证据；
- 模型输出是 suggestion，人工接受/拒绝/修改后才进入 final answer；
- 识别反馈和最终答案进入问卷报表与模型评估链，但不得自动成为训练真值。

用一份包含全部首批题型的真实样板问卷 E2E 验收。

## 十、Phase F：BI、位置外勤和财务

不要同时铺三套空页面。按纵向切片依次完成：

### BI

semantic model、metric/dimension、ReportSpec、dashboard/widget、筛选/拆分/追踪、报告版本、异常/追问/反馈/评价。Analytics Agent 从自然语言生成受权限约束的草稿和预览，不允许任意 SQL；批准后发布。实跑“异常 → 追问任务 → 回答 → 报告刷新”。

### 位置与外勤

员工、地址库、地理编码候选、经纬度确认、地图、VRP 路线、约束/成本、多项目合并、电子围栏、地图区块派发、门头必拍和可选自拍接口。低置信度地址不自动派发；人脸比对默认不自动触发。实跑“任务 → 路线 → 到店 → 问卷/照片 → 差旅费”。

### 财务

contract/subscription/rate card/meter/usage/invoice/settlement/adjustment。支持按月、按照片/区域、按 token 及混合阶梯；按客户/项目拆分。账单必须从 immutable Usage 生成并下钻到 run/node/证据；不得临时扫描业务表凑金额。

## 十一、模块与 Agent 插拔验收

升级 Manifest/Capability 集成契约：commands/queries/events 的 JSON Schema、UI component key、权限、billing meter、健康、依赖必须交叉验证。注册模块后应在受控 UI slot、Workflow 节点库、Agent tool registry 和 OpenAPI 中同步出现；任何一环缺失 fail-closed。

新增 Workflow/IAM/Survey/Analytics/FieldOps/Finance Agent。每个 Agent 独立 identity、allowlist、数据 scope、预算、记忆 ACL；Supervisor 只规划/委派/追踪，不借用管理员身份直接写业务表。

## 十二、UI 硬验收

使用真实浏览器在 1440×900、1280×800、1024×768、768×1024 逐个测试：首页快速目标、主管对话、工作流搭建/运行、账号角色、问卷填写与拍照、BI 报告与异常、地图路线、费用明细、识别任务详情。

每个视口必须：关键按钮可见、无抽屉遮挡、无假图表、无横向丢失、键盘可操作、console 无 error。留下截图和 DOM/API 对账证据；`partial` 不能过 Gate。

## 十三、质量与自我挑战

完成每个 Phase 后主动做一次反方审查：

- 是否又产生第二事实源？
- 是否 UI 写了成功但后台没 run/event/usage？
- 是否 Agent 绕过权限或人工批准？
- 是否 customer/project scope 缺失？
- 是否失败后只能重来而不能恢复？
- 是否 planned/smoke/mock 被包装成完成？
- 是否账单数字无法追到业务证据？
- 是否第三方引擎一停，业务历史就不可用？

发现问题必须重新打开 Issue，不得用文案规避。

## 十四、最终验证

- fresh hermetic tests；host_mps 单独执行并单独统计；
- TypeScript typecheck、production build；
- SQLite integrity、migration 幂等、事件投影重建；
- OpenAPI/Module/Capability/Agent/Workflow schema 对账；
- 权限越界、CSRF/SSRF、注入、secret、rate limit；
- API/workflow p50/p95、队列积压、并发、恢复；
- 服务健康和冷启动；
- production 未切换、训练未启动、用户资产未触碰声明。

最后更新 `docs/USER-HANDBOOK.md`、`docs/OPERATOR-RUNBOOK.md`、`docs/MODULE-AGENT-DEV-GUIDE.md` 和 `docs/CODEX-PROJECT-HANDBOOK.md`。用户手册必须按角色写清从登录到完成任务的操作，不得只讲架构。

## 十五、最终报告

严格按 `05-IMPLEMENTATION-GRAPH-GATES-ACCEPTANCE.md` 的最终报告格式，逐项给出 before/after、真实命令、数据库/API/浏览器证据、commit 和路径。当前最多只能写 `READY_FOR_USER_ACCEPTANCE`；没有用户验收不得写 `COMPLETE/PRODUCTION_READY`。
