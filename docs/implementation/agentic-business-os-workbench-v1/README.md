# Agentic Business OS Workbench V1

> 当前最新的界面、平台壳层、Agent 运行时和识别首域实施入口。

本目录用于纠正近期把平台再次做成“SKU 识别系统”和“第三方 UI 复刻品”的偏差。目标不是继续增加演示卡片，而是交付一套可运行、可理解、可扩展、可由 Agent 操作的智能业务操作系统工作台，并把图像识别作为第一个真正打通的 Domain Pack。

## 唯一推荐阅读顺序

1. `00-CURRENT-STATE-AND-UI-AUDIT.md`
2. `01-PRODUCT-POSITIONING-AND-PLATFORM-ARCHITECTURE.md`
3. `02-WORKBENCH-INFORMATION-ARCHITECTURE-AND-UX.md`
4. `03-RECOGNITION-FIRST-DOMAIN-E2E-PLAN.md`
5. `04-AGENT-MODULE-API-DATA-CONTRACTS.md`
6. `05-IMPLEMENTATION-GRAPH-LOOP-AND-GATES.md`
7. `06-VERIFICATION-AND-ACCEPTANCE.md`
8. `07-SYSTEM-MANUAL-REQUIREMENTS.md`
9. `AGENT-EXECUTION-PROMPT.md`

执行 Agent 还必须完整阅读：

- `docs/superpowers/specs/2026-08-04-fmcg-vision-saas-platform-design.md`
- `docs/superpowers/specs/2026-08-04-location-field-operations-design.md`
- `docs/implementation/project-logic-chain-v3/`
- `docs/implementation/micro-gold-v2-leakage-rebuild/`
- `docs/CODEX-PROJECT-HANDBOOK.md`
- `docs/USER-HANDBOOK.md`

## 本轮边界

- 可以修改平台、Web、Agent、模块注册、识别链路、测试和文档。
- 不允许重新训练模型，除非用户另行明确授权。
- 不允许自动切换 production、删除历史资产、清理受保护目录、merge、push 或 deploy。
- 现有最好生产模型先作为兼容适配器继续使用；新架构不得绑定具体模型权重路径。
- 所有模块必须接入同一个 Graph+Loop Kernel、Module Registry、Data Foundation、Agent Runtime、Audit 和 API Gateway。
