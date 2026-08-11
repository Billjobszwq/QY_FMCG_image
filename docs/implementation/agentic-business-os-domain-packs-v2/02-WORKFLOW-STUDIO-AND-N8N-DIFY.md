# 智能工作流 Studio 与 n8n / Dify 选型

## 1. 最终决定

采用“ABOS 原生控制平面 + 可插拔执行器”方案：

| 能力 | 归属 |
|---|---|
| 工作流定义、版本、权限、审批、状态、事件、证据、计费 | ABOS 唯一事实源 |
| 用户可视化搭建界面 | ABOS Workflow Studio |
| 内部模块/Agent/模型节点 | ABOS Native Runtime |
| 外部 SaaS 连接器和轻量自动化 | 可选 n8n Adapter |
| AI/RAG/LLM 应用子流程 | 可选 Dify Adapter |
| 客户身份、凭据、数据权限 | ABOS Vault + Policy，不下放给第三方 UI |

不把任何第三方 workflow ID 当成业务主键；只作为 `deployment_ref`。

## 2. 为什么不直接采用 n8n 作为核心

n8n 擅长连接器、Webhook、定时和可视化自动化，也支持自托管和自定义节点，适合做外部系统适配层。[n8n 官方文档](https://docs.n8n.io/)

但官方许可说明：为客户托管 workflows/credentials，以及把 n8n 白标嵌入产品，分别涉及 Enterprise 或 Embed 商业许可。这个项目目标是多客户商业系统，直接嵌入会带来许可、凭据隔离和产品控制权风险。[n8n 许可用例说明](https://support.n8n.io/article/can-i-use-your-license-for-my-use-case)

此外，n8n 官方安全审计明确涉及 Code、文件系统、社区节点和未保护 Webhook 等风险节点；这些能力不应直接暴露给商业客户。[n8n 安全审计](https://docs.n8n.io/hosting/securing/security-audit/)

结论：n8n 可以作为受限的 connector worker，但不得成为 ABOS 的权限、任务或计费事实源。是否启用须先完成商业许可确认。

## 3. 为什么不直接采用 Dify 作为核心

Dify 擅长 LLM workflow、Agent、RAG、模型管理，其插件体系包含 Tool、Model、Agent Strategy、Datasource 和 Trigger，适合快速实现 AI 子流程。[Dify 插件类型](https://docs.dify.ai/en/develop-plugin/getting-started/choose-plugin-type)

但它与本项目已有 Supervisor/Domain Agent/Graph+Loop 高度重叠；若把 Dify 作为主流程，会再次分裂会话、工具权限、运行日志、token 计量和客户作用域。其许可证还对多租户使用 Dify 源码及前端标识作出额外限制，商业嵌入必须单独评估。[Dify 官方许可证](https://github.com/langgenius/dify/blob/main/LICENSE)

结论：Dify 只作为 `AIWorkflowProvider`，用于可替换的 RAG/LLM 子流程；ABOS 保存输入输出 schema、运行引用、token、证据和批准状态。

## 4. WorkflowDefinitionV1

工作流定义必须支持：

- metadata：id/name/version/tenant scope/owner/status/tags；
- trigger：manual/API/webhook/schedule/domain event/data change；
- variables：输入、输出、secret reference、default、validation；
- nodes：类型、capability version、input mapping、output schema、policy；
- edges：source port、target port、condition、priority；
- runtime policy：timeout/retry/backoff/idempotency/concurrency/budget；
- approval policy：哪些节点需要谁批准；
- observability：evidence、meter、SLA、trace sampling；
- compatibility：依赖模块和最低版本。

定义发布后不可原地修改；修改必须生成新版本。

## 5. 节点类型

MVP 必须先支持：

1. Trigger；
2. Domain Command；
3. Domain Query；
4. Condition/Switch；
5. Transform（受限表达式，不允许任意 Python/JS）；
6. Agent Invoke；
7. Model Invoke；
8. Human Task/Approval；
9. Wait/Timer；
10. Loop/Iteration；
11. Parallel/Join；
12. Subflow；
13. Webhook/Connector；
14. End。

节点面板只能来自已发布 Capability Schema，不允许用户输入本地 `.pt` 路径、SQL、shell 或任意 HTML。

## 6. Workflow Studio 页面

放在一级“工作流”下，二级菜单至少为：

- 工作流搭建；
- 模板库；
- 运行中心；
- 待办与批准；
- 连接器；
- Agent 与模型；
- 证据与用量。

搭建页布局：左侧节点库、中间画布、右侧属性/输入输出/权限/计费抽屉、底部验证与模拟结果。主管 Agent 以“共同搭建者”出现，接受自然语言后只能：生成 draft patch、解释差异、预测成本、模拟；用户批准后才能发布或运行。

## 7. 生命周期

`draft → linted → simulated → shadow → approved → published → deprecated`

必须具备：

- schema/依赖/权限/循环终止/预算 lint；
- 使用样板数据的 dry-run；
- 节点级输入输出预览和敏感字段遮蔽；
- 版本 diff 与回滚到旧发布版本；
- pause/resume/cancel/retry/compensate；
- checkpoint、dead-letter 和人工恢复；
- 每个节点的耗时、成本、证据、错误和父子关系。

## 8. Adapter SPI

统一接口建议：

```text
validate(definition, policy_context) -> ValidationReport
deploy(definition_version) -> DeploymentRef
start(run_context, inputs, idempotency_key) -> ExecutionRef
poll_or_subscribe(execution_ref, cursor) -> ExecutionEvents
pause/resume/cancel(execution_ref)
collect_usage(execution_ref) -> UsageEvents
collect_evidence(execution_ref) -> EvidenceRefs
```

Native/n8n/Dify 都实现此接口。外部引擎返回的状态先规范化为 ABOS 状态，再写 EventEnvelope；禁止前端直接读第三方运行库。

## 9. 首批贯通模板

实施时必须用四条真实业务模板证明系统“动起来”：

1. 照片上传 → 质量过滤 → 识别 → 低置信度人工复核 → 结果入库 → usage；
2. 问卷拍照题 → 识别建议 → 人工确认 → 评分 → 问卷报表；
3. 外勤任务 → 地址校验 → 路线规划 → 到店围栏 → 问卷/拍照 → 差旅费；
4. 数据异常 → BI Agent 解释 → 创建追问任务 → 回答回写 → 报告刷新。

只画画布或只保存 JSON 均不算通过，必须产生同一 Work/Run/Event/Usage 时间线。
