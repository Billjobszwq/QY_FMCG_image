# ISSUES

## P0：必须先关闭

| ID | 问题 | 验收 |
|---|---|---|
| ABOSV3-P0-001 | 工作流发出 `workflow.succeeded`，投影器只识别 `run.succeeded`，已完成 WorkItem 被重建成 todo | 同一 run 的 DB/API/UI/reconcile 均为 done；从事件清空重建后仍一致 |
| ABOSV3-P0-002 | 首页 WorkItems、WorkItemV2、Taskboard 是平行真相 | 首页、主管、日历、任务板、进度使用同一 current projection；历史单独查询 |
| ABOSV3-P0-003 | succeeded run 可能残留上次失败 error | 当前状态无旧 error；失败证据仍存在事件/attempt 中 |
| ABOSV3-P0-004 | BI 版本列表把不同版本重复投影为 latest | v1/v2 分别显示、可下钻、可比较；旧版不可被覆盖 |
| ABOSV3-P0-005 | 没有可完成真实工作的首页和总控 Dashboard | 首页包含待办、日历、日程、进度、活动、资源、Agent 提醒，点击均进入真实对象 |
| ABOSV3-P0-006 | Supervisor 主要是关键词规则，多数 Domain Agent invoke 只返回 `ok=true` | Supervisor 能基于工具目录检索、规划、委派、预览、批准执行并返回证据；不可用时诚实降级 |
| ABOSV3-P0-007 | 工作流不是可视化搭建器，wait/parallel/join/agent 仍是假实现 | 拖拽画布完成真实 E2E；定时、并行汇合、人工批准、Agent/模型/数据节点均有真实运行证据 |

## P1：本轮必须关闭

| ID | 问题 | 验收 |
|---|---|---|
| ABOSV3-P1-001 | 主管工作台遮挡、信息层级和版式不适合长期使用 | 1440/1280/1024/768 四视口；无横向溢出、无主操作遮挡；键盘可用 |
| ABOSV3-P1-002 | 数据与资产定位不清 | 形成数据量、存储、吞吐、资源、队列、数据质量、资产血缘综合运营中心 |
| ABOSV3-P1-003 | 问卷只有样板，没有从零创建/增删改/配置/预览/发布 | 用户从空白建立问卷，配置所有首批题型、跳题、评分和照片绑定并完成一次响应 |
| ABOSV3-P1-004 | 外勤没有真实地址导入、地理编码按钮、规则、地图 | 下载模板→dry-run→导入→地理编码→地图→规则→路线→任务分配完整通过 |
| ABOSV3-P1-005 | 智能识别模型状态难懂，训练无输入输出，标注入口缺失 | V4 best 默认可用；其余 profile 状态真实；识别/标注/数据集/训练/模型/发布形成闭环 |
| ABOSV3-P1-006 | BI 没有可操作工作台和计算逻辑配置 | 注册数据集、创建指标/公式/维度、拖拽图表、发布 Dashboard、异常追问全部可操作 |
| ABOSV3-P1-007 | Agent 无 soul/prompt/知识库/Skill/工具/模型配置工作台 | 主管及 Domain Agent 可查看、复制版本、编辑 draft、测试、批准、发布、回滚 |
| ABOSV3-P1-008 | 账号权限不能由用户自定义 | 角色 CRUD、权限矩阵、范围、审批、模拟检查和审计可用；禁止删除最后管理员 |
| ABOSV3-P1-009 | 客户与主数据不能完整自定义 | 客户/项目/SKU/门店/员工 CRUD、导入、合并、停用、版本和审计可用 |
| ABOSV3-P1-010 | 财务范围不符合当前阶段 | 按客户查看 storage/photo/model/token usage 日志、趋势、证据和导出；不伪装完整会计 |
| ABOSV3-P1-011 | 系统与开发者页面含义不清 | 全员“帮助与文档”+管理员“系统管理/开发者”分离，手册可搜索、API 可浏览 |
| ABOSV3-P1-012 | 全局缺 CSV/XLSX 模板下载与统一导入体验 | 所有主数据/问卷/地址/角色批量入口使用同一个 Import Center 契约 |
| ABOSV3-P1-013 | 人工路径被 Agent 概念遮蔽 | 每个 Agent Command 都能在对应模块由人工预览、执行、撤销或补救 |
| ABOSV3-P1-014 | 模块 manifest 标 live 但缺健康检查和真实 capability | live 必须同时满足 API、UI、Agent command、health 和最小 E2E；否则 degraded |
| ABOSV3-P1-015 | IAM 多客户可见性只取第一个 customer | 用户在获授权的多个客户间切换/汇总，越权仍 403 |
| ABOSV3-P1-016 | rate limit 未实现 | 登录、Agent invoke、URL 导入、批量导入、识别和高成本查询有按主体/租户限制与审计 |

## P2：不得阻断真实 UAT，但必须登记

- 便签服务端同步与跨浏览器恢复；
- 事件由 polling 升级 SSE/WebSocket；
- 地图离线缓存和国产坐标系转换；
- BI 导出 PDF/PPT、定时发送；
- Node-RED 可选执行 Adapter；
- 完整 WCAG AA 审计和移动端原生适配。

