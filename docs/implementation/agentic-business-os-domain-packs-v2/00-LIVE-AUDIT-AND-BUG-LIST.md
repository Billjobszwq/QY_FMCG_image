# 现场审计与 Bug 清单

审计时间：2026-08-11。审计方式包括 Git/SQLite/API/源码、完整 hermetic 测试、TypeScript 检查以及 1440/1024/768 浏览器操作。测试通过不等于业务连续性通过。

## 1. 现场状态

- Git：HEAD `e5c4236d`，分支 `feat/nextgen-training-cycle-v2`，tracked 工作树干净；用户未跟踪训练/数据资产未触碰。
- SQLite：`.platform/platform.sqlite`，`integrity_check=ok`，现场 63 张表。
- 服务：8091、8092、8300、8400 均能启动并健康；production 仍为 `prod_20260805_v5_r1`。
- 测试：hermetic `1173 passed, 1 skipped, 6 deselected`；前端 typecheck/build 通过。
- 运行事实：识别任务 11 条、Graph Runs 8 条、Agent Commands 5 条、Usage Event 1 条；这些数量不应被解释为已完成统一链路。

## 2. 阻断级问题

### ABOSV2-P0-001：主页读取旧任务源，旧 250 项重新成为“当前待办”

复现：主页显示“今日待办（100）”，但 `/api/v1/workitems?limit=500` 实际包含 256 项，其中 250 项为已经不再作为当前演示门禁的 `rq_v2` 人工审核；较新的 `/api/v1/taskboard` 则保存 Micro-Gold V2 与候选评估状态。

根因：

- [Home.tsx](../../../web/src/pages/Home.tsx) 第 27 行使用 `fetchWorkItems()`；第 32 行虽然调用 `fetchTaskboard()`，但结果直接丢弃；
- [SupervisorWorkspace.tsx](../../../web/src/platform/SupervisorWorkspace.tsx) 第 126–137 行也只读 WorkItems；
- [workitems.py](../../../src/platform/api/workitems.py) 第 38–63 行把活动审核队列重新聚合为待办，没有消费 supersession/current projection；
- 默认分页上限 100，使首页卡片标题与真实总数再次不一致。

影响：主管、用户和训练控制面看到不同“下一步”，系统无法连续推进。

修复原则：建立统一 `WorkItemProjectionV2`；旧队列只能作为历史事件存在；主页、主管、任务板、模块首页和 API 全部读取同一 current projection。

### ABOSV2-P0-002：“快速目标 → 交给主管”丢失用户输入

复现：在首页输入“打开识别任务”并点击“交给主管”，右侧会切到对话页，但输入内容没有进入主管输入框，也没有发送或生成草稿。

根因：[Home.tsx](../../../web/src/pages/Home.tsx) 第 57–71 行只导航到 `/home?focus=chat`；[SupervisorWorkspace.tsx](../../../web/src/platform/SupervisorWorkspace.tsx) 第 99–107 行只消费 `focus`，没有消费目标文本或共享 command draft。

修复原则：目标先落服务端 `goal_draft/work_item`，再通过 `goal_id` 打开主管；不得把业务内容塞入 URL，也不得只存在 React/localStorage 状态。

### ABOSV2-P0-003：识别、Graph、Agent 与计费断链

现状：11 条识别任务没有对应 11 条 Graph Run 或 Usage Event；`recognition_task` 缺少 `work_id/parent_run_id/correlation_id/causation_id/customer_id/evidence_bundle_id/usage_id`。

根因：[recognition_tasks.py](../../../src/platform/api/recognition_tasks.py) 第 99–168 行直接调用 adapter 并写识别任务；没有统一 Workflow Runtime、Outbox、证据或计量步骤。Agent 命令文案声称“计入计费”，但执行钩子只返回 task/trace。

影响：无法回答“这个任务从哪里来、现在在哪个节点、花了多少钱、下一步是谁、失败后如何恢复”。

修复原则：所有入口先创建 `BusinessRun/WorkItem`，识别只是一个 domain command node；成功、失败、人工复核、计费均写入同一事件链。

### ABOSV2-P0-004：服务档位目前只是元数据，不控制模型与成本

证据：[recognition_tasks.py](../../../src/platform/api/recognition_tasks.py) 第 122–140 行校验 `service_tier` 后，无论档位都调用相同 `adapter.recognize(data, conf=conf)`。

影响：低/中/高/极高在 UI 中可选，但没有真实算力、模型、SLA、准确率或价格差异。

修复原则：在 Profile Resolver/Orchestrator 中把档位解析为不可变执行计划和 rate card；未具备真实差异前，UI 必须标记“未启用”，不得售卖。

## 3. 高优先级问题

### ABOSV2-P1-001：Workflow 页面不是工作流搭建器

现有 `GraphDefinition` 只有 name/version/顺序节点；没有 edge、port、条件、变量、触发器、重试、并行、人工节点和发布状态。[build.py](../../../src/composition/build.py) 第 54–65 行仅硬注册两个 Graph；Agent approval hook 第 188–226 行仅支持 `vision.recognition.create`。

结论：当前页面是 Graph Run 查看器和固定启动器，不满足“模块自由组合”。

### ABOSV2-P1-002：Module Manifest 与可执行 Capability 是两套注册表

`ModuleManifestV2` 声明 commands/queries/events，但 `project()` 没有投影这些执行契约；运行时另有 `CapabilityRegistry`。现场 10 个模块只有 4 个 capability，planned 模块均为 0。

影响：注册模块可以出现在导航中，但不代表节点可以被 Workflow/Agent 调用。

修复原则：模块发布必须同时通过 Manifest、Capability Adapter、JSON Schema、权限、计费、健康检查、UI slot 的交叉验证。

### ABOSV2-P1-003：路由仍由 App 手写，不能真正插拔

[App.tsx](../../../web/src/App.tsx) 第 215–299 行逐条硬编码业务路由。Registry 驱动了导航，但没有驱动页面装载；新模块仍需修改中央 App。

修复原则：建立受控 `ModuleUIRegistry` 与 slot renderer；Manifest 只引用已注册组件 key，禁止任意远程代码和 HTML 注入。

### ABOSV2-P1-004：主管 Agent 还不是全局主管

[supervisor.py](../../../src/platform/agents/supervisor.py) 第 220–341 行是关键词 `if/elif` 路由；`tasks` 和 `memory_updates` 默认保持空；所谓 delegation 是回执对象，不是独立 Agent 执行。Agent health 主要验证 manifest 存在。

修复原则：主管只负责任务规划、委派、审批、状态追踪和异常升级；领域工具必须来自 Capability Registry；每次工具调用落 run/node/event/evidence/usage。

### ABOSV2-P1-005：识别任务页面无法查看它承诺的证据

页面文案称“按 trace_id 可查证据”，但表格没有 task_id、trace_id、tier、project/customer、错误详情、结果详情、证据链接、usage 或可点击行。[Vision.tsx](../../../web/src/pages/Vision.tsx) 第 308–329 行可复核。

修复原则：统一任务详情抽屉必须显示时间线、当前节点、输入/输出摘要、错误、证据、成本、父子任务和允许动作。

### ABOSV2-P1-006：1024/768 响应式布局遮挡主操作区

`SupervisorWorkspace` 在宽度 `>=1024` 默认打开；CSS 在 `max-width:1024` 又把 side panel 改为 fixed overlay，恰好在 1024 自动遮住主内容。768 时一级导航只剩色点和图标，无可见标签，主管抽屉占据约一半屏幕。

修复原则：

- ≥1440 可选 dock；1024–1439 默认收起且不覆盖主表；<1024 使用全屏临时抽屉；
- 侧栏收起时必须提供 tooltip、aria-label 和当前模块名称；
- 表格在 1024/768 自动转 card/detail，而不是简单压缩列。

### ABOSV2-P1-007：测试覆盖结构存在但没有覆盖连续性

现有契约测试大量是静态字符串断言，不能发现：目标丢失、旧待办复活、识别无计费、抽屉遮挡、任务无详情、模块无执行适配器。

必须新增跨层测试：UI 操作 → command → workflow run → node → domain record → event → usage → evidence → projection → UI timeline。

## 4. 中低优先级

- ABOSV2-P2-001：主管便签仍存在 localStorage，跨浏览器/设备不一致。
- ABOSV2-P2-002：Agent event stream 实为轮询 GET，不是可恢复的 SSE/WebSocket event cursor。
- ABOSV2-P2-003：识别 Profile 大量 disabled card 直接平铺，用户难以理解默认选择和不可用原因。
- ABOSV2-P2-004：`bin/abos status` 在无进程查看权限环境中把“无法判断”报告为 DOWN，应区分 UNKNOWN 与 DOWN。
- ABOSV2-P2-005：完整 WCAG AA、精确四视口、rate limit、trace 自动对账仍未完成，原 Gate `READY_FOR_NEXT_DOMAIN_PACK` 过早。

## 5. Gate 纠正

当前 Gate 应从 `READY_FOR_NEXT_DOMAIN_PACK` 回退为：

`FOUNDATION_CONTINUITY_REPAIR_REQUIRED`

只有 P0-001～P0-004、P1-005～P1-007 通过真实浏览器与账本对账，才允许进入 Workflow Studio MVP；业务 Domain Pack 只能在统一 IAM/MDM 和 Work/Event/Usage 底座通过后开始。
