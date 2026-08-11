# ISSUES · Domain Packs V2

> 使用任务书 Bug 编号（ABOSV2-*）。状态只允许：CONFIRMED_OPEN /
> PARTIALLY_CLOSED / CLOSED_WITH_EVIDENCE / NOT_REPRODUCED / NOT_TESTED / SUPERSEDED。
> 关闭必须满足 00 文档第 5 节的适用证据层。

| ID | 严重度 | 状态 | 摘要 | 根因（初步） | 关闭证据 |
|---|---:|---|---|---|---|
| ABOSV2-P0-001 | P0 | CLOSED_WITH_EVIDENCE | 主页/主管读取旧 WorkItems，旧 250 审核复活为当前待办 | `workitems.py` 重新聚合 active 审核队列，未消费 supersession/current projection | commit `4af64f2d`：migration 031 supersession 账本 + projection=current/history/all；现场 current=2、superseded=254 入 history；红测试 7 项 + 浏览器四视口 |
| ABOSV2-P0-002 | P0 | CLOSED_WITH_EVIDENCE | 快速目标 → 交给主管丢失输入 | Home.tsx 只导航 `?focus=chat`；无服务端 goal draft | commit `79b3a534`：migration 032 goal_draft_v1 + goals API；浏览器验证输入→主管→刷新恢复（abosv2_goal_* 截图） |
| ABOSV2-P0-003 | P0 | CLOSED_WITH_EVIDENCE | 识别/Graph/Agent/Usage 无统一 run | recognition_tasks.py 直调 adapter，无 BusinessRun/Outbox/证据/计量 | commit `13106320`：统一控制平面 + 实跱全链 ID 对账（run/work/corr/task/trace/evidence 一致，reconcile consistent=true）；失败 run 同一链恢复 |
| ABOSV2-P0-004 | P0 | CLOSED_WITH_EVIDENCE | Service Tier 只是元数据，不改变模型/成本 | 所有档位调用同一 `adapter.recognize(conf)` | commit `15a39325`：fast/high/extreme 禁用并标“未启用”+ 契约守卫测试；浏览器截图 abosv2_tier_honest_1440.png |
| ABOSV2-P1-001 | P1 | CLOSED_WITH_EVIDENCE | Workflow 页面不是搭建器 | GraphDefinition 无 edge/条件/变量/触发器；build.py 硬注册两个 Graph | commit `aa7ba378`：canonical 定义 + 生命周期 + 15 节点 + Studio 七页签；实跱模板贯通 |
| ABOSV2-P1-002 | P1 | PARTIALLY_CLOSED | Manifest 与 Capability 两套注册表 | `project()` 未投影执行契约；10 模块仅 4 capability | 节点库已同源消费 Capability Registry + Gateway 命令（fail-closed）；Manifest 全量交叉验证（UI slot/meter/health）留待 Z-1 |
| ABOSV2-P1-003 | P1 | CONFIRMED_OPEN | App.tsx 手写路由，模块不可真正插拔 | Registry 只驱动导航不驱动页面装载 | Z-1 关闭（ModuleUIRegistry + slot renderer） |
| ABOSV2-P1-004 | P1 | CONFIRMED_OPEN | 主管 Agent 是关键词路由器 | supervisor.py if/elif；delegation 只是回执 | Workflow Agent 已受控（draft-only）；主管工具化规划留待后续 |
| ABOSV2-P1-005 | P1 | CLOSED_WITH_EVIDENCE | 识别任务页无详情/证据/用量入口 | 表格无 task_id/trace/tier/错误/证据列，无可点击行 | commit `15a39325`：详情 API + DetailDrawer；截图 abosv2_task_detail_1440.png |
| ABOSV2-P1-006 | P1 | CLOSED_WITH_EVIDENCE | 1024/768 主管抽屉遮挡主内容；导航无标签 | ≥1024 默认打开 + max-width:1024 fixed overlay 冲突 | commit `15a39325`：阈值 1440 + 导航 title/aria-label + 表格转 card；截图 abosv2_home_1024.png / abosv2_nav_768.png / abosv2_tasks_768.png |
| ABOSV2-P1-007 | P1 | CLOSED_WITH_EVIDENCE | 测试只有源码字符串断言，无连续性覆盖 | 缺 UI→command→run→event→usage→projection 跨层测试 | commit `15a39325`：test_abos_v2_continuity.py 真实跨层链 + 浏览器验收；事件/usage 环待 Phase B 补全 |
| ABOSV2-P1-008 | P1 | CLOSED_WITH_EVIDENCE | 回归：旧兼容规则隐藏新壳 topbar | styles.css `.topbar{display:none}` 后加载覆盖 shell.css | commit `15a39325`：删除规则；浏览器复验 abosv2_topbar_fix_1440.png |
| ABOSV2-P2-001 | P2 | CONFIRMED_OPEN | 主管便签 localStorage | 未服务端持久化 | 后续 |
| ABOSV2-P2-002 | P2 | CONFIRMED_OPEN | Agent event stream 为轮询 GET | 无 SSE/cursor | 后续 |
| ABOSV2-P2-003 | P2 | CONFIRMED_OPEN | Profile disabled card 平铺过载 | — | 后续 |
| ABOSV2-P2-004 | P2 | CONFIRMED_OPEN | `abos status` 无权限环境误报 DOWN | 未区分 UNKNOWN/DOWN | 后续 |
| ABOSV2-P2-005 | P2 | CONFIRMED_OPEN | WCAG AA/四视口/rate limit/trace 对账未完成 | 原 Gate 过早 | 后续 |
