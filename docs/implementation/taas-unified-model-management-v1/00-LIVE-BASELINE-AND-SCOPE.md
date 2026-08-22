# 00｜现场基线、范围与约束

## 1. 文档基线

记录时间：2026-08-21（Asia/Shanghai）。

- 工作目录：`/Users/zhangweiqi/Documents/QY/TaaS by Agent Operation`
- 分支：`codex/taas-agent-operation-v1`
- HEAD：`5bbbf89861cc658fdfbb4a7b5b3ad9967e4b6610`
- 工作树：已有 Round 2 未提交修改和新增文件；本任务必须保护这些用户资产。
- live DB：`runtime/platform/platform.sqlite`
- live DB SHA-256：`2306a030cf1128a36d2432e9fe78ca623ac0925f73710dc428630d05a806f109`
- live DB `PRAGMA integrity_check`：`ok`
- live DB 已应用迁移：68，最高为 `068_cognition_research_report_v1`
- 当前工作树代码定义迁移：`001–071`
- OMLX `/health`：`healthy`；当时模型池报告9个模型、0个已加载模型。

上述数据是只读快照。实施开始前必须 fresh 重跑，不得把本文快照当作未来现场事实。

## 2. 已有可复用资产

- `src/platform/cognition/index/providers.py` 已有 OpenAI-compatible Embedding Adapter、Provider Identity 和 env fallback。
- `src/platform/cognition/index/catalog.py`、`gateway.py` 已实现索引身份、build/query mismatch fail-closed。
- `src/platform/agents/runtime.py` 的 Agent Definition 已包含 `provider` 和 `model`，并有 draft/publish/rollback 生命周期。
- `src/platform/governance` 已有 maker/checker、审批账本、告警和 pause。
- `usage_event_v2` 是不可变 Usage 账本，已经有 customer/project/run/capability/model/profile/unit/cost 字段。
- `src/platform/rate_limit.py` 已有按 Capability、主体和 IP 的持久化请求限流。
- `src/platform/api/health.py` 已把 OMLX 纳入健康探针。
- 前端采用 TaaS 桌面、一级模块窗口和 `ModuleWorkbench` 标签，不使用传统后台侧栏。

## 3. 当前缺口

1. Embedding Provider 仍由环境变量装配，UI 不能安全创建、测试、审批和切换。
2. 没有系统级 Connection/Catalog/Binding 事实对象。
3. Anthropic 原生协议没有 Adapter。
4. 当前 Agent LLM 路径仍存在直接读取 DeepSeek 环境变量和直接 HTTP 调用。
5. Usage 只记录 `agent_call`、`research_query` 等粗粒度单位；没有账号级输入/输出/缓存/reasoning Token。
6. 当前限流是请求次数，不是 Token 预算。
7. “模型管理”当前位于智能识别模块，边界错误。
8. `AuthMe` 只含 actor/role；前端需消费已有 `/api/v1/iam/whoami` 的 scopes 才能安全投影模块可见性。

## 4. V1 范围

### 必须实现

- 独立系统模块 `models`。
- Provider：OMLX/OpenAI-compatible、OpenAI模板、Anthropic原生。
- 能力：Embedding、Chat/Reasoning、Vision、OCR Text、OCR Boxes、Rerank目录声明。
- 连接测试、模型发现、人工模型登记、能力探针。
- 系统能力/模块/Agent 的版本化绑定。
- SecretStore、EndpointPolicy、IAM、Scope、maker/checker、CAS、审计。
- 账号级模型 Usage、Token预算、监控和告警。
- 本地 OMLX Embedding真实索引、检索、评测和回滚。
- 当前模型驻留、训练门禁和历史模型页面迁移到新模块，不复制数据源。

### 非目标

- 不重写 Graph+Loop、Agent Runtime、Cognition或训练内核。
- 不把 YOLO/SAM权重训练生命周期改造成外部 API Connection。
- 不实现 Provider 市场、自动购买额度或自动创建外部厂商账号。
- 不允许普通员工配置模型或查看密钥元数据。
- 不在本轮自动切生产、部署、训练、删除旧页面或删除资产。

## 5. 保护约束

- 新迁移从 `072` 开始；禁止修改已定义的 `001–071`。
- 对 live DB 的任何迁移测试必须先做只读预检，再使用 `mktemp -d` 下显式副本。
- 禁止将 API Key 写入 Markdown、测试快照、命令行参数、日志或Git。
- 本地 Provider真实测试通过 SecretStore/环境注入，执行报告只写“configured/failed”，不写凭据。
- 未获授权不得 commit、stage、push、部署或切换 production。
