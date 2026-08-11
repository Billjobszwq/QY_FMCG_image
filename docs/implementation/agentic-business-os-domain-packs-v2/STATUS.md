# STATUS / DECISIONS / ISSUES

更新时间：2026-08-11。

## 当前状态

`FOUNDATION_CONTINUITY_REPAIR_REQUIRED`

不是 `READY_FOR_NEXT_DOMAIN_PACK`。代码测试通过，但真实浏览器和数据对账发现任务事实源、快速目标、Graph/识别/计费、响应式 UI 与任务详情尚未闭合。

## 已冻结决定

- D-001：平台核心是 Agentic Graph+Loop，不是识别系统或传统 SaaS。
- D-002：ABOS 原生保存 workflow、run、event、evidence、usage 唯一事实。
- D-003：n8n 仅可作为可选 connector executor，启用前完成 Embed/Enterprise 许可评估。
- D-004：Dify 仅可作为可选 AI subflow provider，不接管客户、权限、会话、任务和计费。
- D-005：先统一 Work/Event/Usage，再新增 Domain Pack。
- D-006：IAM 与 Master Data 先于问卷/BI/外勤/财务。
- D-007：模型识别结果进入问卷时只能是 suggestion，人工 final 才是业务答案。
- D-008：所有计费来自 immutable Usage Ledger，不能从页面计数临时反推。
- D-009：第三方引擎和模块都通过 Adapter SPI，可插拔但不能绕过 Policy。

## 当前未关闭问题

- P0：旧 250 审核重新进入当前主页；
- P0：快速目标内容丢失；
- P0：Recognition/Graph/Agent/Usage 无统一 run；
- P0：服务档位未改变执行；
- P1：Workflow 仅运行查看器；
- P1：Manifest 与 Capability/Route 不是真正一体化；
- P1：主管 Agent 不是工具规划执行器；
- P1：识别任务无详情/证据/费用入口；
- P1：1024/768 页面被主管抽屉遮挡；
- P1：连续性 E2E 和四视口测试缺失；
- P2：便签 localStorage、event polling、profile 信息过载；
- 业务：问卷、BI、Geo/Field、Finance、IAM 仍为 planned，禁止以导航入口计为完成。

## 本轮未做

未修改业务代码、数据库或 UI；未启动训练；未切换 production；未 merge/push/deploy；未删除或暂存用户资产。
