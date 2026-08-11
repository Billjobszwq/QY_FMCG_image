# Agent、Module、API 与数据契约

## 一、Agent 组织

### Supervisor Agent

职责：目标理解、跨域拆解、任务路由、待办汇总、异常升级、证据汇总和审批协同。它没有全库直写权，也不能自行切生产、发布模型、删除数据或修改财务事实。

### Domain Agent

每个已启用 Domain Pack 注册一个主 Agent，例如：

- Data Agent：资产、血缘、数据质量、数据产品；
- Survey Agent：问卷定义、样本、回收、质量；
- Geo/Field Agent：地址、路线、围栏、区块、任务；
- Recognition Agent：识别任务、标注、数据集、训练、模型；
- Analytics Agent：指标、BI、告警、异常解释；
- Finance Agent：账单、成本、对账、差异；
- Workflow Agent：Graph、Run、策略和自动化；
- System Agent：权限、模块、API、健康、审计。

“一个模块一个 Agent”不是创建八个聊天窗口，而是八个独立 Manifest、权限、工具、数据范围、记忆策略、命令 schema 和健康状态。用户默认与 Supervisor 对话；需要时可切换到领域 Agent。

## 二、Agent 调用契约

统一响应：

```json
{
  "message": "业务语言回答",
  "evidence_refs": [],
  "ui_intents": [],
  "command_previews": [],
  "tasks": [],
  "delegations": [],
  "memory_updates": [],
  "requires_approval": false,
  "trace_id": "..."
}
```

前端必须实际消费并呈现这些字段：

- UIIntent 只允许 `navigate/open_panel/filter/highlight/compare/pin/show_evidence`；
- command preview 展示参数、权限、影响、成本、幂等键、回滚和批准按钮；
- evidence ref 打开证据抽屉；
- delegation 显示调用了哪个领域 Agent、状态和回执；
- 高风险命令必须两阶段 approve，不能因聊天内容直接执行。

## 三、共享黑板与记忆

- Blackboard 是 typed append-only 事件流：Question、Finding、Decision、Task、Blocker、EvidenceRef、PendingCommand、Approval、Resolution、Note；
- 当前卡片由 projection 生成，历史不覆盖；跨 Agent supersede 需要人工或策略授权；
- 记忆分 L0 会话、L1 Run、L2 项目事实、L3 客户授权知识、L4 通用方法论；
- 每条记忆有 scope、tenant/project、ACL、confidence、evidence、valid_from/to、retention、supersedes；
- 向量索引是可重建派生缓存，不是事实源；
- Agent 只能在授权范围读取客户数据，不能把客户事实写进跨客户长期记忆。

## 四、Module Manifest V2

必须扩展现有 `src/platform/registry.py`，不新建平行常量：

```json
{
  "module_id": "vision",
  "version": "1.0.0",
  "name": "智能识别",
  "domain": "fmcg_vision",
  "status": "live",
  "theme_token": "vision",
  "primary_route": "/vision",
  "navigation": [],
  "agents": [],
  "capabilities": [],
  "commands": [],
  "data_products": [],
  "events": [],
  "ui_slots": [],
  "permission_scopes": [],
  "feature_flags": [],
  "dependencies": [],
  "compatibility": {},
  "billing_units": [],
  "health_checks": []
}
```

Registry 启动时完成 schema、重复 ID、route 冲突、capability adapter、dependency、API prefix、permission、Agent scope 和版本兼容校验。失败模块为 degraded/disabled，不能让整个平台启动失败，除非是可信底座核心模块。

## 五、统一 API 原则

- 统一前缀 `/api/v1/<domain>/...`；
- 所有写操作服务端身份 + CSRF/token + permission + idempotency；
- Web 不直接调用 8091/8300/数据库，统一经 8400 Gateway；
- Agent 不直接执行 Python 函数或 SQL，调用领域 Command/Query API；
- App/小程序复用相同 OpenAPI，不单独复制业务规则；
- 响应包含 `trace_id/evidence_refs/version`；
- 错误采用稳定 code + 人类可读 message + retryable + next_action；
- 长任务返回 task/run ID，支持事件流、取消、恢复和重试；
- API 契约生成客户端类型，禁止前端大量 `any`。

## 六、Data Product 契约

跨域查询不直接 join 他域私有表，而由领域注册版本化 Data Product：

- schema/version/owner/description；
- tenant/project/data scope；
- freshness/quality/lineage；
- PII classification/retention；
- query endpoint/cache policy；
- allowed consumers/billing unit。

例如 BI 消费 `vision.recognition_daily_v1`，而不是直接读取模型训练报告；Finance 消费 `usage.cost_ledger_v1`，不读取前端统计。

## 七、为未来客户和模块预留

- 所有事实和 Run 带 tenant/customer/project；本地单租户也不能省略契约；
- 客户定制通过 Graph/Policy/Manifest/Feature Flag/Data Product 组合，不复制整个应用；
- 开源内核与商业 Domain Pack 通过同一签名 Manifest 接入；
- 模块可独立升级、禁用和迁移，历史 Run、账本和证据继续可读；
- 不允许运行时上传任意代码插件；本机阶段模块必须经过代码审查和签名版本注册。
