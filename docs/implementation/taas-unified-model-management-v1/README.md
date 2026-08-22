# TaaS 统一模型管理 V1

本目录定义 TaaS 的系统级统一模型管理模块。它在现有平台上统一管理本地模型与外部模型连接，为系统能力、业务模块和 Agent 分配模型，并复用现有 IAM、Scope、Agent Definition、Usage、审批、CAS、审计、模型驻留和 Research RAG，不建立平行运行平台。

## 当前状态

- 设计状态：`APPROVED`
- 实施状态：`NOT_STARTED`
- 代码状态：本目录仅包含开发规范与执行提示词；尚未修改业务代码。
- Git：未 stage、未 commit、未 push。
- 生产：未切换模型、未应用新迁移、未部署、未训练。

## 目标

1. 新建与“智能识别”等并列的系统级“模型管理”一级模块。
2. 统一配置本地 OMLX、OpenAI、OpenAI-compatible 和 Anthropic 连接。
3. 为系统能力、模块、租户/客户/项目和 Agent Definition 分配模型。
4. API Key 全链路加密、只写不读、按租户隔离，生产变更强制 maker/checker。
5. 记录账号级模型请求、Token、延迟、错误、成本与配额，并提供运行监控。
6. 先用本地 OMLX 的 `Qwen3-Embedding-0.6B-8bit` 跑通 Research RAG dense/hybrid 与 paraphrase Gate。

## 文档索引

- [00-LIVE-BASELINE-AND-SCOPE.md](00-LIVE-BASELINE-AND-SCOPE.md)：现场基线、边界与非目标。
- [01-ARCHITECTURE-AND-DATA-CONTRACTS.md](01-ARCHITECTURE-AND-DATA-CONTRACTS.md)：模块边界、事实源、绑定解析和数据契约。
- [02-API-PROVIDER-AND-SECURITY.md](02-API-PROVIDER-AND-SECURITY.md)：API、Provider Adapter、密钥与 Endpoint 安全。
- [03-USAGE-MONITORING-AND-RELEASE.md](03-USAGE-MONITORING-AND-RELEASE.md)：账号级计量、预算、监控、上线与回滚。
- [04-UI-INTERACTION-SPEC.md](04-UI-INTERACTION-SPEC.md)：与现有 TaaS 桌面兼容的 UI 规范。
- [05-IMPLEMENTATION-PLAN-AND-GATES.md](05-IMPLEMENTATION-PLAN-AND-GATES.md)：TDD 实施顺序、文件责任和验收 Gate。
- [DECISIONS.md](DECISIONS.md)：已批准的不可逆设计决策。
- [STATUS.md](STATUS.md)：任务状态与证据槽位。
- [AGENT-EXECUTION-PROMPT.md](AGENT-EXECUTION-PROMPT.md)：下一轮可直接复制执行的完整提示词。

## 执行纪律

- 新迁移从 `072` 开始，只能纯追加；禁止改写 `001–071`。
- live 数据库在文档基线时仍为 `068`，不得因为构造 `PlatformStore` 而隐式升级。
- 先测试、后实现；任何安全、作用域、计量或索引身份失败均 fail-closed。
- 未获明确授权不得删除文件、commit、push、部署、训练或切换 production。
- 不得把测试 Fake Provider、词法结果或静态 UI 当作真实模型验收证据。
