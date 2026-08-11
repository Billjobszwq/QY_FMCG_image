# DECISIONS

所有决定均为本轮冻结约束。变更必须追加新决定，不覆盖历史。

| ID | 决定 |
|---|---|
| D-001 | 产品是 Agentic Business OS，不是识别系统，也不是传统 SaaS 菜单集合。识别只是首个 Domain Pack。 |
| D-002 | 首页是真正的总控 Dashboard；主管工作台是跨页面工具，不得遮挡主内容，也不得代替首页。 |
| D-003 | WorkItemV2、BusinessRunV1、EventEnvelopeV1、EvidenceBundleV1、UsageEventV2 继续作为统一控制面；禁止再建第四套 Taskboard/首页任务真相。 |
| D-004 | 日历、日程、进度、活动日志均从统一控制面和业务事实投影；用户私人日程可有专表，但必须产生事件和审计。 |
| D-005 | 所有关键动作必须同时支持 Agent 路径和人工路径。Agent 失败、停用或模型不可用时，人工仍可完成业务。 |
| D-006 | Workflow 主画布采用 MIT 许可的 React Flow；ABOS 原生保存 canonical graph。Node-RED 可作为 Apache-2.0 可选执行适配器，不接管权限、客户、审计和计费。 |
| D-007 | 不嵌入 n8n/Dify 作为商业产品核心：n8n Sustainable Use License 对白标/客户嵌入有限制，Dify 许可证对多租户和前端有附加条件。 |
| D-008 | Agent 是版本化业务实体，必须可配置 soul、system prompt、模型、工具、Skill、知识库、记忆、预算和审批规则；配置修改可回滚。 |
| D-009 | Prompt、Skill、知识库、Agent 定义彼此独立、版本化、可测试；Prompt 不是 Skill，知识文件不是长期记忆。 |
| D-010 | 不允许用户 Prompt 或 Workflow 节点执行任意 SQL、任意 shell、任意 Python 或注入 HTML/JS。所有能力从 allowlist Capability Registry 暴露。 |
| D-011 | 生产默认识别模型按用户授权切到 `best/sku_v4_best.pt`，但先走 shadow、回归、性能和回滚验证。其他现有模型只以明确的 experimental/local profile 上线，不能伪装 production-ready。 |
| D-012 | “模型上线”指本机运行时可加载、可选择、可诊断、有真实结果和明确状态；不等于通过商业准确率门。 |
| D-013 | 自主训练工作台必须包含数据集选择、标注入口、快照、参数、算力预检、队列、日志、指标、制品、评估、比较、停止和发布计划；批准与运行分离。 |
| D-014 | 全局主数据导入必须同时提供 CSV 和 XLSX 模板；模板有版本、字段说明、样例、dry-run、逐行错误和幂等键。 |
| D-015 | 地理编码使用 Provider SPI。中国地址优先接高德/腾讯等经授权 Provider；无 Key 时允许导入经纬度并诚实提示配置，不伪造坐标。 |
| D-016 | 地图使用 MapLibre 类开源前端与可配置瓦片源；瓦片、地理编码和路线服务的许可证/Key 独立管理。 |
| D-017 | BI 只允许注册数据集、语义指标、受限公式 DSL 和参数化查询；自然语言只生成 draft，发布前必须人工预览。 |
| D-018 | “系统与开发者”拆为面向全员的“帮助与文档”和仅管理员可见的“系统管理/开发者”；不再把内部状态页当产品模块。 |
| D-019 | 财务本轮只做客户级存储、照片识别、模型计算、Token 等 Usage 日志与可核对汇总，不扩张完整会计系统。 |
| D-020 | 实施 Agent 连续执行全部任务。阶段门失败时自动诊断、修复、重跑并写日志；只有破坏性操作、缺少 Secret/外部授权、真实重训练或无法安全推断时才向用户提问。 |

