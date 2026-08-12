# READING LIST（V3 开工阅读记录）

实施 Agent：Lingma（本轮接管）。逐项记录已读与结论。

| # | 文件 | 状态 | 结论/用途 |
|---|---|---|---|
| 1 | `~/.local/share/ai-workflow/routing/GLOBAL_AGENT_ROUTING.md` | 已读 | 先 report-only 后实施；TDD；验证后才声明完成；安全策略（不 merge/push/deploy） |
| 2 | `~/.codex/AGENTS.md`（全局 AGENTS.md） | 已读 | 全局工作流层指引；安全边界同上 |
| 3 | `docs/CODEX-PROJECT-HANDBOOK.md` | 已读（全文 722 行） | 接续锚点、权限边界、训练红线、Bug 七层证据、易失忆事实 19 条 |
| 4 | `docs/README.md` | 已读 | 文档地图；当前唯一实施入口=本目录 |
| 5 | `docs/USER-HANDBOOK.md` | 已读 | 五角色操作流；凭据 bill（锁定）；planned/degraded/disabled 语义 |
| 6 | `docs/OPERATOR-RUNBOOK.md` | 已读 | bin/abos 栈控制；对账端点；故障矩阵 |
| 7 | `docs/MODULE-AGENT-DEV-GUIDE.md` | 已读 | ModuleManifestV2 单一事实源；ABOSV2 接入契约（命令网关/IAM scope/UI 镜像/Agent 白名单/Usage） |
| 8 | `agentic-business-os-domain-packs-v2/` 全部 14 份 | 已读 | V2 控制平面/工作流/IAM/问卷/BI/外勤/财务契约与证据；P0-001..004 历史 |
| 9 | 本目录 00–05 + README/STATUS/ISSUES/DECISIONS/IMPLEMENTATION-LIST/EXECUTION-LOG | 已读 | 本轮任务书：T0–T12、G0–G8、60 项报告、READY_FOR_REAL_DATA_UAT |
| 10 | `AGENT-EXECUTION-PROMPT.md` | 已读 | 最高优先级任务书；连续执行；Gate 为内部质量控制 |
| 11 | 代码：`src/platform/*`（control_plane/workflow/analytics/survey/field_ops/finance/iam/standard_profile/import_center/home_center/agents.runtime 等）、`src/modules/training_control/profiles.py`、`web/src/*` | 已读 | 定位全部 P0 根因与新工作台接入点 |
| 12 | 最近 30 commits（`git log --oneline -30`） | 已读 | V2 Phase A–F + T9 + 凭据锁定链 |
| 13 | 现场核验：HEAD `47c01c43`、branch `feat/nextgen-training-cycle-v2`、四服务 UP、DB integrity ok、107 表、迁移 040、production `prod_20260805_v5_r1`、`best/sku_v4_best.pt` sha256 `84bf9936…5554975`（133,135,871 B） | 已核验 | 开工基线与备份 `.platform/backups/platform_pre_v3_20260812_030918.sqlite`（integrity ok） |
