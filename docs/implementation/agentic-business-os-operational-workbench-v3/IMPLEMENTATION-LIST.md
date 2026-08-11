# IMPLEMENTATION LIST

状态只允许：`NOT_STARTED`、`IN_PROGRESS`、`VERIFIED_LOCAL`、`BLOCKED_EXTERNAL`。每次 commit 后更新本表和 `EXECUTION-LOG.md`。

| Task | 工作 | 初始状态 | 完成证据 |
|---|---|---|---|
| T0 | 现场审计、备份、14 项 before 浏览器证据、P0/P1 红测试 | NOT_STARTED | audit + screenshots + red test log |
| T1 | Work/Run/Event/Taskboard/Calendar/BI 版本统一与状态修复 | NOT_STARTED | projection rebuild + DB/API/UI reconciliation |
| T2 | 首页 Dashboard、日历、日程、进度、活动和主管布局 | NOT_STARTED | 四视口 E2E + persistent data |
| T3 | Import Center、CSV/XLSX 模板、客户主数据、IAM 自定义 | NOT_STARTED | download→dry-run→commit→audit E2E |
| T4 | Agent Definition、Soul、Prompt、Skill、KB、Memory、工具运行时 | NOT_STARTED | real agent tool traces + version rollback |
| T5 | React Flow 可视化 Workflow 和真实异步 Runtime | NOT_STARTED | visual graph E2E + restart recovery |
| T6 | 从空白自定义问卷 Builder、逻辑、评分、照片绑定 | NOT_STARTED | blank→publish→response E2E |
| T7 | 地址导入、地理编码、规则、地图、路线和围栏 | NOT_STARTED | address→map→route→field E2E |
| T8 | V4 best 切换、其他模型本机 Profile、标注/数据集/训练中心 | NOT_STARTED | rollback-tested switch + runtime/profile/training UI |
| T9 | BI 数据集、指标、公式、图表、Dashboard 和异常追问 | NOT_STARTED | user-built dashboard + version correctness |
| T10 | 客户级 storage/photo/model/token Usage 与财务日志 | NOT_STARTED | usage drilldown + CSV export |
| T11 | 帮助文档、系统管理、全局 UX、无障碍和错误状态 | NOT_STARTED | searchable docs + browser QA |
| T12 | UAT fixture 全链、性能、安全、冷启动、对账和文档收口 | NOT_STARTED | G0–G8 + final report |

