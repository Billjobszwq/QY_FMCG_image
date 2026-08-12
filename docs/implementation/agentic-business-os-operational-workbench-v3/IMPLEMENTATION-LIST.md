# IMPLEMENTATION LIST

状态只允许：`NOT_STARTED`、`IN_PROGRESS`、`VERIFIED_LOCAL`、`BLOCKED_EXTERNAL`。每次 commit 后更新本表和 `EXECUTION-LOG.md`。

| Task | 工作 | 状态 | 完成证据 |
|---|---|---|---|
| T0 | 现场审计、备份、READING-LIST、before 基线 | VERIFIED_LOCAL | READING-LIST.md；备份 integrity ok；HEAD 47c01c43 |
| T1 | Work/Run/Event/Taskboard/Calendar/BI 版本统一与状态修复 | VERIFIED_LOCAL | a94cdc82；8 红测试绿；reconcile 业务事实对账 |
| T2 | 首页 Dashboard、日历、日程、进度、活动和主管布局 | VERIFIED_LOCAL | 90eaa7e9/d9923cb5；home dashboard API+UI；浏览器 5/5 |
| T3 | Import Center、CSV/XLSX 模板、客户主数据、IAM 自定义 | VERIFIED_LOCAL | 419043d6；14 模板 round-trip；坏 fixture→修复→提交 E2E |
| T4 | Agent Definition、Soul、Prompt、Skill、KB、Memory、工具运行时 | VERIFIED_LOCAL | e2de6a7d；7 Agent 定义/健康探针；8 工具意图实执行 |
| T5 | React Flow 可视化 Workflow 和真实异步 Runtime | VERIFIED_LOCAL | e7b3361c；画布 E2E + timer 重启恢复；浏览器 6/6 |
| T6 | 从空白自定义问卷 Builder、逻辑、评分、照片绑定 | VERIFIED_LOCAL | 37a45c53；空白→发布→响应→计分 E2E |
| T7 | 地址导入、地理编码、规则、地图、路线和围栏 | VERIFIED_LOCAL | 5c634489；SPI 降级+手工坐标+调版 v2+map-data |
| T8 | V4 best 切换、其他模型本机 Profile、标注/数据集/训练中心 | VERIFIED_LOCAL | 1fd048b8；shadow/切换/回滚/再切换；8091 真实推理 |
| T9 | BI 数据集、指标、公式、图表、Dashboard 和异常追问 | VERIFIED_LOCAL | d64a436a；DSL fail-closed+下钻+看板 CRUD |
| T10 | 客户级 storage/photo/model/token Usage 与财务日志 | VERIFIED_LOCAL | bbeaa643；汇总/下钻/CSV；跨客户 403 |
| T11 | 帮助文档、系统管理、全局 UX、无障碍和错误状态 | VERIFIED_LOCAL | 7fd64b66；help 模块；管理员导航过滤；9 页巡检 |
| T12 | UAT fixture 全链、性能、安全、冷启动、对账和文档收口 | VERIFIED_LOCAL | 预演 23/23；restart 四服务 UP；安全快检；本文档收口 |
