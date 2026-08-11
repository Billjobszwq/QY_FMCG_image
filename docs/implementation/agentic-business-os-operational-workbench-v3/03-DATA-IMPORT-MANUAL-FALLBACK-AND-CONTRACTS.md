# 数据导入、人工备援与统一契约

## 1. Import Center

所有模块共用一个 Import Center，不得每页各写一套上传逻辑。

### 必须提供的模板

| 模板 ID | 内容 |
|---|---|
| `customers_v1` | 客户、状态、账期、标签 |
| `projects_v1` | 客户、项目、周期、负责人、预算 |
| `skus_v1` | canonical SKU、名称、品牌、容量、包装版本、别名 |
| `stores_addresses_v1` | 门店、标准地址、区域、经纬度、坐标系、时间窗 |
| `employees_v1` | 员工、技能、班次、起终点、费用规则 |
| `users_v1` | 用户、显示名、状态 |
| `roles_permissions_v1` | 角色、权限、数据范围、审批能力 |
| `memberships_v1` | 用户、角色、客户、项目范围 |
| `survey_definition_v1` | 问卷基本信息、版本、页面 |
| `survey_questions_v1` | 题目、题型、选项、校验、分值、照片绑定 |
| `survey_logic_v1` | 条件、运算符、值、跳转目标 |
| `route_constraints_v1` | 员工/项目/区域/时间窗/容量/费用约束 |
| `usage_rate_cards_v1` | Usage 类型、单位、价格、生效区间 |
| `knowledge_documents_v1` | KB 名称、客户范围、文件/URL、版本、有效期 |

每个模板同时提供 `.csv` 和 `.xlsx`；模板第一页/README 包含字段类型、是否必填、枚举、样例、幂等键和错误示例。

### 导入状态机

```text
uploaded → parsed → mapped → validated → dry_run_passed
        → awaiting_approval → committed → reconciled
失败：parse_failed / validation_failed / partial_failed / compensated
```

- 上传后先预览，不直接写业务表；
- 逐行显示新增、更新、跳过、冲突和错误；
- 用户修正映射或下载错误行；
- 提交使用 batch id 和 row idempotency key；
- 允许安全补偿，不使用无审计的物理删除；
- 原文件、模板版本、actor、hash、结果和错误报告进入 Evidence。

## 2. 人工和 Agent 双通道

每项能力都满足以下矩阵：

| 能力 | 人工入口 | Agent 入口 | 共同事实 |
|---|---|---|---|
| 导入客户/地址 | Import Center | 生成映射/修复建议 | ImportBatch + Evidence |
| 创建问卷 | Builder | 生成 draft | SurveyDefinition version |
| 规划路线 | Planner | 建议规则/路线 | RoutePlan version |
| 图片识别 | Recognition Workbench | Command Preview | RecognitionTask/Run |
| 建 BI | Dashboard Builder | 生成指标/图表 draft | Metric/ReportSpec version |
| 建工作流 | Visual Studio | 生成 graph draft | WorkflowDefinition version |
| 配置 Agent | Agent Center | 自检/建议 | AgentDefinition version |
| 角色权限 | IAM Console | 解释/模拟 | Role/Permission/Audit |

任何 Agent 失败都返回人工入口 URL 和已保存草稿 ID，而不是让用户重新开始。

## 3. 统一业务主线

一次真实业务必须保留以下关联：

```text
tenant_id → customer_id → project_id
  → goal_id → workflow_definition_id → business_run_id
  → work_id / schedule_id / field_task_id / survey_assignment_id
  → response_id / photo_asset_id / recognition_task_id
  → evidence_id / usage_event_id / report_id
```

规则：

- ID 在入口创建，后续传递，不按名称猜测关联；
- 客户/项目范围贯穿 API、Agent、Workflow 和 BI；
- Correlation ID 贯穿父子 run；
- 当前状态由统一投影产生，历史由事件/attempt 保留；
- 页面不能用 localStorage 作为业务事实源；
- 所有写 API 支持幂等键、权限、审计和错误码；
- 所有列表支持分页、过滤、排序和客户/项目范围；
- 所有详情提供证据、事件、Usage 和相关对象链接。

## 4. 首页、日历、日志和进度投影

- **待办**：WorkItemV2 current projection；
- **日历**：WorkItem due date、field schedule、survey window、workflow timer、report schedule 和用户日程的统一读取模型；
- **活动日志**：EventEnvelope + Audit 的业务友好投影；
- **进度**：项目里程碑和 WorkItem 状态聚合；
- **系统日志**：仅管理员查看服务日志索引，与业务活动分开；
- **历史**：superseded/completed/failed 通过历史过滤查看，不再混入当前待办。

同一 work 在首页、主管、任务板、日历和项目详情必须返回相同状态、负责人、截止时间和 blocker。

## 5. API 与 Module Contract

每个 live Module Manifest 至少声明并通过：

- primary/secondary routes；
- read/write commands；
- queries/events；
- Agent owner；
- data products；
- import templates；
- manual entry routes；
- health checks；
- permission scopes；
- billing/usage units；
- minimum E2E probe。

只有 API、UI、Agent command、人工入口、health 和 minimum E2E 同时通过才是 `live`；缺任一项为 `degraded`，纯规格为 `planned`。

## 6. 错误和恢复

- 成功状态不得残留当前 error；旧错误写 attempt/event；
- 失败必须提供 retry、resume、manual takeover 或 compensate 中至少一种；
- 429 明确重试时间；外部 Provider 故障使用 circuit breaker 并展示人工方式；
- 模型不可用时不得返回空成功；
- 导入、地理编码、训练和长工作流使用后台 Job，可重启恢复；
- 页面刷新后草稿、进度和错误仍存在。

