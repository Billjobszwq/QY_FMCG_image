# 统一工作台信息架构与 UX 规范

## 一、设计原则

1. **任务优先，不是展示优先**：首页先告诉用户今天该做什么、哪里异常、哪些任务在运行。
2. **模块色是识别线索，不是整块涂色**：颜色用于图标、active rail、标题线、图表强调和状态辅助；内容表面保持中性。
3. **三级导航有真实 URL 和状态**：每级都能深链接、刷新恢复、浏览器前进后退。
4. **复杂性渐进披露**：默认展示结论、影响、下一步；模型 hash、策略版本、token、trace 放到证据抽屉。
5. **Agent 与页面协同**：Agent 通过结构化 UIIntent 打开、定位、筛选和置顶，不能注入 HTML，也不能用聊天文字代替真实页面。
6. **所有状态有语义**：loading、empty、success、warning、blocked、failed、stale、permission denied 都有一致组件和下一步。

## 二、桌面工作台布局

```text
┌─────────────────────────────────────────────────────────────────────────┐
│ 品牌/租户/项目   全局搜索与命令    当前运行  通知  帮助  用户          │
├──────────────┬────────────────────────────────────┬─────────────────────┤
│ 一级模块导航 │ 二级功能导航 + 三级工具栏          │ 主管 Agent / 证据   │
│ 图标+名称    │ 页面标题、状态、主内容、任务结果   │ 待办/命令/审批/聊天 │
│ active 色条  │                                    │ 可收起、可置顶      │
└──────────────┴────────────────────────────────────┴─────────────────────┘
```

- 左侧一级导航建议 224px 展开 / 72px 收起；禁止 92px 高饱和大色块堆叠。
- 顶栏固定，展示租户、客户、项目和环境；不能把 production 名称硬编码在 footer。
- 右侧主管工作台采用之前确认的“黄色便签/任务板”语言，但只作为强调区域，不让整站变黄。
- 主内容最大宽度根据页面类型变化：表格/画布全宽，表单 960–1200px，阅读型文档 800px。

## 三、三级菜单定义

### 一级：业务域

由 `ModuleManifestV2.navigation.primary` 注册，代表稳定的业务边界。例如“智能识别”“位置与外勤”。

### 二级：功能

真实 route，每个功能独立 URL。例如：

- 智能识别 / 即时识别：`/vision/recognize`
- 智能识别 / 识别任务：`/vision/tasks`
- 智能识别 / 标注与审核：`/vision/annotation`
- 智能识别 / 数据集：`/vision/datasets`
- 智能识别 / 模型与训练：`/vision/models`
- 智能识别 / 质量与证据：`/vision/evidence`

禁止多个标签指向同一路由，也禁止用组件内部默认 state 伪装路由。

### 三级：具体操作

位于页面工具栏、分段控件、步骤条或详情抽屉。例如“上传照片、URL 输入、批量任务、导出结果”。三级操作必须：

- 有可见 label、权限和 disabled 原因；
- 有快捷键和 focus 状态；
- 高风险动作先预览，再人工批准；
- 操作完成后提供结果、证据和下一步，不只弹 toast。

## 四、模块色系

建立语义 token，不允许页面直接散落十六进制：

| 模块 | accent | soft surface | 使用范围 |
|---|---|---|---|
| 主管工作台 | violet | violet-50 | Agent、跨域任务、审批 |
| 数据与资产 | amber | amber-50 | 数据、血缘、质量 |
| 调研与问卷 | cyan | cyan-50 | 问卷、样本、回收 |
| 位置与外勤 | emerald | emerald-50 | 地址、地图、路线、围栏 |
| 智能识别 | blue | blue-50 | 识别、标注、模型 |
| 分析与 BI | indigo | indigo-50 | 指标、报表、洞察 |
| 工作流与 Agent | purple | purple-50 | Graph、Run、Agent |
| 财务与结算 | rose | rose-50 | 对账、成本、账单 |
| 系统与开发者 | slate | slate-50 | 健康、权限、API |

状态色独立于模块色：绿色只表示成功，黄色只表示警告，红色只表示错误，灰色表示停用。不能用模块绿色误导为“健康”。所有文字与背景满足 WCAG AA。

## 五、设计系统最低组件集

- AppShell、TopBar、PrimaryNav、SecondaryNav、PageHeader、ActionBar；
- Button、IconButton、Link、Input、Select、Combobox、Upload、DateRange；
- Card、MetricCard、DataTable、EmptyState、ErrorState、Skeleton、Banner；
- StatusBadge、Progress、Stepper、Tabs、Drawer、Dialog、Toast；
- EvidenceDrawer、RunTimeline、ApprovalCard、AgentMessage、CommandPreview；
- ImageViewer、BoundingBoxOverlay、RegionInspector；
- MapCanvas、ChartFrame、QueryResult（先提供插槽，不伪造数据）。

组件必须有 Storybook 或等价组件实验页，覆盖正常、hover、focus、disabled、loading、error、长文本、空数据和窄屏。

## 六、首页 / 主管工作台

首页不是品牌宣传拼贴，必须包含：

1. 今日待办：可认领、可跳转、含截止时间和 blocker；
2. 需要我批准：命令预览、影响范围、成本、回滚方式；
3. 正在运行：Graph Run、识别任务、训练任务、数据导入；
4. 异常与告警：按严重度和责任 Agent 聚合；
5. 最近完成：结果、证据、耗时和费用；
6. 固定笔记：用户与主管 Agent 共同维护，不与事实状态混为一谈；
7. 快速目标输入：“帮我分析……”“创建一次……”，由主管 Agent 拆解；
8. 模块健康：只显示真实 registered/live/degraded 状态。

主管 Agent 的回答必须能生成：

- 文本解释；
- 证据引用；
- UIIntent；
- 可批准命令；
- 新 Task/Graph Run；
- 对应领域 Agent 的调用回执。

## 七、人类友好硬要求

- 页面主标题使用用户任务语言，不用内部代码名作主标题；
- 每个页面首屏只有一个主操作；
- 不让用户理解 Gate、bundle、checkpoint 后才能完成普通操作；
- 技术字段放“查看技术证据”抽屉；
- 表格支持排序、筛选、列显示、分页、空状态和导出；
- 表单错误靠近字段，保留用户输入；
- 长任务异步化，可离开页面，完成后通知；
- destructive/high-risk 操作必须展示影响、权限和恢复方式；
- 1440、1280、1024、768 宽度无水平遮挡；移动端至少可查看和审批；
- 支持键盘导航、Esc 关闭、focus trap、`prefers-reduced-motion`；
- 跑马灯默认移除；巨型 footer 和巨幅展示标题仅允许营销页，不进入操作工作台。

## 八、反 AI-slop 验收

以下任一存在都不得通过：

- 不同页面各自定义一套 card/button/table；
- 大面积彩虹渐变、无意义图标、夸张空白或装饰跑马灯；
- 用硬编码数字、截图或静态数组冒充实时数据；
- 同一按钮在不同页面颜色、尺寸、语义不一致；
- 所有模块都长得一样，只替换标题和颜色；
- “Agent 可以做”但没有结构化命令、权限、审计和失败反馈；
- 页面可见但 URL、刷新、API、权限或真实操作断裂。
