# 可视化 Workflow 与 Agent Runtime 决策

## 1. 选型结论

采用“ABOS 原生工作流 + React Flow 画布 + 可选 Node-RED Adapter”：

- **React Flow**：MIT 许可，提供拖拽、缩放、连线、选择、删除、自定义节点和子流程能力，作为 ABOS Web 的画布组件；
- **ABOS Workflow Runtime**：现有 GraphDefinition、BusinessRun、WorkItem、Event、Evidence、Usage 继续是唯一事实源；
- **Node-RED**：Apache-2.0，可在未来作为本机 connector executor；不作为本轮硬依赖，也不保存客户权限和计费真相；
- **n8n**：不嵌入。官方 Sustainable Use License 对白标、面向客户托管和嵌入有商业限制；
- **Dify**：不嵌入。其修改版 Apache 许可对多租户和前端标识有附加条件。

参考：

- React Flow 官方说明其库为 MIT：<https://reactflow.dev/>；
- Node-RED 官方仓库为 Apache-2.0：<https://github.com/node-red/node-red>；
- n8n 官方许可说明：<https://docs.n8n.io/sustainable-use-license/>；
- Dify 官方 LICENSE：<https://github.com/langgenius/dify/blob/main/LICENSE>。

## 2. Workflow Studio 必须具备的工作面

### 画布

- 左侧 Node Palette：触发器、数据、条件、转换、循环、并行、汇合、等待、人工批准、Agent、模型、识别、问卷、BI、地理、财务、通知、子流程、结束；
- 中央 React Flow 画布：拖拽、连线、框选、复制、撤销/重做、对齐、缩放、MiniMap、自动布局；
- 右侧 Inspector：输入、输出、变量、凭据引用、重试、超时、成本、权限、失败分支和人工接管；
- 顶部工具栏：保存、lint、模拟、测试运行、批准、发布、新版本、导入/导出和运行历史；
- 底部运行面板：当前节点、日志、输入输出、耗时、Usage、证据和重试。

JSON 只能作为“高级源码视图”，不能作为默认编辑器。

### Canonical Graph Contract

每个节点至少包含：

```json
{
  "node_id": "stable-id",
  "node_type": "capability|agent|condition|loop|parallel|join|wait|approval|subflow",
  "capability_id": "optional.registry.command",
  "config": {},
  "input_schema": {},
  "output_schema": {},
  "policy": {
    "timeout_seconds": 60,
    "retry": 2,
    "approval": "none|before|after",
    "on_error": "stop|continue|branch|human"
  },
  "ui": {"x": 0, "y": 0, "color": "module-accent"}
}
```

UI 坐标不参与运行 hash；业务定义、版本和策略参与 hash。发布版不可原地编辑。

## 3. Runtime 必须从“同步样板”升级

- `wait`：持久化 timer，进程重启后仍能恢复；
- `parallel`：真正并发提交相互独立分支，受资源租约和最大并发限制；
- `join`：等待指定分支完成，支持 all/any/quorum，记录缺失分支；
- `loop`：有最大次数、分页、断点、幂等键和失败策略；
- `human_approval`：暂停 run，生成同一 WorkItem 主线的批准事项，批准后从 checkpoint 恢复；
- `agent`：调用节点指定的 Agent，不得固定调用 Supervisor；
- `model`：从 Model/Profile Registry 选择，不接受任意磁盘路径；
- `capability`：由 Gateway 调用注册命令，继承 IAM、客户范围、审计、Usage 和 Evidence；
- `subflow`：父子 run、correlation 和取消传播可追踪；
- dead letter：可以人工重试、跳过、补偿或终止，不删除历史。

## 4. Agent Definition

每个 Agent 是独立、版本化的定义：

```text
Identity
  agent_id / name / domain / owner / status / version
Behavior
  soul / system_prompt_version / response_contract / escalation_policy
Runtime
  provider / model / temperature / context_budget / cost_budget / timeout
Capabilities
  tool_allowlist / command_allowlist / delegated_agents / forbidden_actions
Knowledge
  knowledge_bases / retrieval_policy / citation_required
Memory
  L0-turn / L1-session / L2-project / L3-customer / L4-methodology ACL+retention
Governance
  approval_policy / data_scope / audit / test_suite / rollback_version
```

### Agent 工作台

- Agent 列表和真实 health；
- 详情：职责、状态、模型、工具、知识、记忆、预算、最近运行；
- 编辑仅生成 draft；支持 diff、测试会话、红队测试、批准、发布和回滚；
- Soul 与 Prompt 分栏：Soul 定义长期身份和价值边界，Prompt 定义具体指令；
- Tool/Skill/KB 通过选择器绑定，不允许把 Secret 写进 Prompt；
- 每次 Agent 回答显示 provider、model、prompt version、KB citations、tools、usage、trace 和降级状态。

## 5. Supervisor 的真实工具循环

Supervisor 不再只做关键词 `if/else`。一次对话采用：

1. 识别当前用户、客户/项目上下文和当前页面对象；
2. 从 Capability/Agent/Skill/KB Registry 检索可用动作；
3. 生成有界计划；
4. 只读工具可以直接执行；
5. 写入/高成本/外部动作生成 Command Preview；
6. 用户批准后执行；
7. 结果写 Run/Event/Evidence/Usage；
8. 失败时解释、重试或转人工；
9. 更新经授权的记忆和进度。

本地 LLM/兼容 Provider 不可用时，规则 fallback 只能回答固定状态和导航，页面必须显示 `degraded_rules_fallback`，不得伪装智能规划成功。

## 6. Skill、Prompt、知识库与记忆

- **Skill**：一项可复用工作方法，包含输入/输出、前置条件、步骤、工具、验收和风险；
- **Prompt**：Agent 某版本的指令文本，可引用 Skill，不包含数据库真相；
- **知识库**：可检索文档和结构化知识，有来源、客户范围、版本和失效时间；
- **记忆**：运行中沉淀的上下文，受 ACL、生命周期、supersedes 和人工清除控制；
- **黑板**：跨 Agent 的任务/发现/决定/阻断事件，追加式、可订阅，不作为业务主表替代品。

用户必须能在 Web 中创建 draft、测试、发布和停用这些对象。Agent 可以建议创建，但不能绕过人工批准自动扩大权限。

## 7. 人工备援

每个 Agent Command 在对应业务模块必须有人工按钮；每个 Workflow Run 必须能暂停、接管、修改输入的补偿副本、重试或终止。Agent 故障不能导致问卷、外勤、识别、BI 或导入永久卡死。

