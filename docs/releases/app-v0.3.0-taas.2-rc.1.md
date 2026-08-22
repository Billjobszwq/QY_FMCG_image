# app-v0.3.0-taas.2-rc.1

## 版本定位

本标签冻结 TaaS Research RAG、Agent/Memory/Governance 和统一模型管理 V1
完成后的本地候选基线，供下一轮安全加固、可重复浏览器 Gate 和人工 UAT
继续开发与回退。

这是候选版本，不是生产发布、不是 `ACCEPTED`，也不表示已经完成真实
人工 UAT。

- 基线分支：`codex/taas-agent-operation-v1`
- 上一代码 HEAD：`5bbbf89861cc658fdfbb4a7b5b3ad9967e4b6610`
- 上一应用标签：`app-v0.3.0-taas.1`
- 冻结对象：本标签所指向的提交

## 主要内容

- Agent Definition 单一事实源及 Manifest 投影。
- Policy、Alert、Pause、maker/checker、CAS 和审计治理。
- Source/Document/Chunk/Span 不可变证据链。
- L1/L2/L3 Memory 与 Knowledge/Skill 生命周期。
- ACL-first 联邦检索、Research Graph、Claim/Citation/Synthesizer。
- 独立系统级“模型管理”模块：Connection、Catalog、Binding、Resolver、
  SecretStore、EndpointPolicy、OpenAI-compatible、Anthropic 和本地 OMLX。
- 账号级模型调用账本、诚实计量单位、预算、限流、成本、告警和回滚。
- 本地 `Qwen3-Embedding-0.6B-8bit` 的真实 dense/hybrid Research RAG 链路。
- 统一模型管理五页签 UI、权限投影和旧 `/vision/models` 兼容路由。

## Fresh 验证结果

- Python 全量：`2242 passed, 6 skipped, 6 deselected, 0 failed`，
  4 个既有 warning，433.52 秒。
- 前端：5 个测试文件、34 项测试全部通过；ESLint 通过；
  `tsc -b && vite build` 成功，526 modules transformed。
- 旧 web 树：`tsc --noEmit` 通过。
- 真实 OMLX/RAG 证据：13/13 measured Gate PASS；
  `paraphrase.recall_at_10=1.0`；ACL/injection/forbidden 均为 0。
- live DB：SHA-256
  `2306a030cf1128a36d2432e9fe78ca623ac0925f73710dc428630d05a806f109`；
  integrity `ok`；仍为 68 条迁移，最大
  `068_cognition_research_report_v1`。
- 069–074 未应用于 live；072–074 只在显式临时副本演练。

## 版本资产边界

- 纳入：源码、前后端、测试、固定评测夹具、迁移脚本、对账/QA/诊断工具
  和实施文档。
- 排除：`.claude/`、`runtime/` 机器证据、数据库、备份、训练数据、模型
  权重、用户数据、本地依赖与构建产物。实施状态、执行日志和验收结论的
  Markdown 文档作为候选版开发记录纳入。
- 未 stage/commit 任何 API Key、KEK、密文、模型文件或业务数据。
- 本次只创建本地提交与注释标签；未 push、未合并、未部署、未切换生产。

## 发布卫生审计说明

候选 staged tree 的扩展名、二进制、私钥、GitHub/AWS 凭据、嵌入式认证
URI 与受保护目录均已检查。没有发现未知真实凭据、数据库、模型或业务
资产。

现有严格 clean-release 审计器报告 19 个已分类 finding：

- 3 个前序版本已跟踪的前端应用图标，被通用 PNG 禁止规则命中；
- 5 个本轮新增的合成 Cognition JSONL 金标准，被通用 JSONL 禁止规则命中；
- 1 个 EndpointPolicy 测试中的假 `userinfo` URL，被凭据模式规则命中；
- 其余为实施文档中的执行状态、日志或本机绝对路径。

这些内容仅允许进入本地候选快照。后续如需 push、PR 或正式 clean release，
必须重新决定文档证据边界、为安全的合成夹具/应用图标建立精确 allowlist，
并要求审计器返回零个未解释 finding。

## 已知阻断与下一轮入口

1. 六个既有 OMLX 构建/评测脚本仍包含本地凭据默认值。它们不是本轮
   新增 diff，但仍存在于历史 tracked tree；下一轮必须移除默认值、缺失
   环境变量时 fail-closed，并增加全 tracked tree 的凭据回归扫描。
2. `@playwright/test` 尚未纳入前端开发依赖，模型管理 E2E 规格未按计划
   自动执行；规格中的员工上下文隔离和角色覆盖也需要修正。
3. VLM/OCR/Embedding 独立 CLI 仍保留可观测的 legacy env 通道，待受管
   连接齐备后迁移。
4. 默认 pytest 包含本机 OMLX integration，验收报告应把 hermetic 回归与
   host-local integration 分开报告。

上述问题未闭环前，本标签保持 `rc.1`，不得升级为正式发布或
`ACCEPTED`。
