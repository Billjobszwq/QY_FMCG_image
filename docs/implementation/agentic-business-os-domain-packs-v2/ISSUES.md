# ISSUES · Domain Packs V2

> 使用任务书 Bug 编号（ABOSV2-*）。状态只允许：CONFIRMED_OPEN /
> PARTIALLY_CLOSED / CLOSED_WITH_EVIDENCE / NOT_REPRODUCED / NOT_TESTED / SUPERSEDED。
> 关闭必须满足 00 文档第 5 节的适用证据层。

| ID | 严重度 | 状态 | 摘要 | 根因（初步） | 关闭证据 |
|---|---:|---|---|---|---|
| ABOSV2-P0-001 | P0 | CONFIRMED_OPEN | 主页/主管读取旧 WorkItems，旧 250 审核复活为当前待办 | `workitems.py` 重新聚合 active 审核队列，未消费 supersession/current projection；Home/Supervisor 不读 taskboard | — |
| ABOSV2-P0-002 | P0 | CONFIRMED_OPEN | 快速目标 → 交给主管丢失输入 | Home.tsx 只导航 `?focus=chat`；Supervisor 不消费目标文本；无服务端 goal draft | — |
| ABOSV2-P0-003 | P0 | CONFIRMED_OPEN | 识别/Graph/Agent/Usage 无统一 run | recognition_tasks.py 直调 adapter，无 BusinessRun/Outbox/证据/计量 | — |
| ABOSV2-P0-004 | P0 | CONFIRMED_OPEN | Service Tier 只是元数据，不改变模型/成本 | 所有档位调用同一 `adapter.recognize(conf)` | — |
| ABOSV2-P1-001 | P1 | CONFIRMED_OPEN | Workflow 页面不是搭建器 | GraphDefinition 无 edge/条件/变量/触发器；build.py 硬注册两个 Graph | Phase C 关闭 |
| ABOSV2-P1-002 | P1 | CONFIRMED_OPEN | Manifest 与 Capability 两套注册表 | `project()` 未投影执行契约；10 模块仅 4 capability | Phase C/Z 关闭 |
| ABOSV2-P1-003 | P1 | CONFIRMED_OPEN | App.tsx 手写路由，模块不可真正插拔 | Registry 只驱动导航不驱动页面装载 | Phase C/Z 关闭 |
| ABOSV2-P1-004 | P1 | CONFIRMED_OPEN | 主管 Agent 是关键词路由器 | supervisor.py if/elif；delegation 只是回执 | Phase B/C 关闭 |
| ABOSV2-P1-005 | P1 | CONFIRMED_OPEN | 识别任务页无详情/证据/用量入口 | 表格无 task_id/trace/tier/错误/证据列，无可点击行 | — |
| ABOSV2-P1-006 | P1 | CONFIRMED_OPEN | 1024/768 主管抽屉遮挡主内容；导航无标签 | ≥1024 默认打开 + max-width:1024 fixed overlay 冲突 | — |
| ABOSV2-P1-007 | P1 | CONFIRMED_OPEN | 测试只有源码字符串断言，无连续性覆盖 | 缺 UI→command→run→event→usage→projection 跨层测试 | — |
| ABOSV2-P2-001 | P2 | CONFIRMED_OPEN | 主管便签 localStorage | 未服务端持久化 | 后续 |
| ABOSV2-P2-002 | P2 | CONFIRMED_OPEN | Agent event stream 为轮询 GET | 无 SSE/cursor | 后续 |
| ABOSV2-P2-003 | P2 | CONFIRMED_OPEN | Profile disabled card 平铺过载 | — | 后续 |
| ABOSV2-P2-004 | P2 | CONFIRMED_OPEN | `abos status` 无权限环境误报 DOWN | 未区分 UNKNOWN/DOWN | 后续 |
| ABOSV2-P2-005 | P2 | CONFIRMED_OPEN | WCAG AA/四视口/rate limit/trace 对账未完成 | 原 Gate 过早 | 后续 |
