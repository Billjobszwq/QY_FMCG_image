# READING-LIST · 开始修改前必读清单（T0 完成记录）

| # | 文件 | 状态 | 要点记录 |
|---|---|---|---|
| 1 | ~/.local/share/ai-workflow/routing/GLOBAL_AGENT_ROUTING.md | 已读 | gstack/Superpowers 路由；安全策略：不 merge/deploy/force-push |
| 2 | 项目根 AGENTS.md | 不存在 | 现场核实：根目录无 AGENTS.md（只有 README.md 等），如实记录 |
| 3 | GLOBAL_AGENT_ROUTING.md（项目内） | 已读 | 同 #1 本机路由文档 |
| 4 | docs/CODEX-PROJECT-HANDBOOK.md | 已读 | 项目总手册（748 行） |
| 5 | docs/README.md | 已读 | 文档地图与历史状态 |
| 6 | docs/USER-HANDBOOK.md | 已读 | 用户手册 |
| 7 | docs/OPERATOR-RUNBOOK.md | 已读 | bin/abos 运维；服务拓扑 8091/8092/8300/8400 |
| 8 | docs/MODULE-AGENT-DEV-GUIDE.md | 已读 | 模块开发指南 |
| 9 | docs/implementation/agentic-business-os-v3/ | 不存在 | 现场核实：实际目录为 agentic-business-os-operational-workbench-v3 等，已按其契约执行 |
| 10 | agentic-business-os-uat-contract-correction-v1/ 全部 | 已读目录清单 | UATCC 轮：契约纠偏、UAT V2 |
| 11 | agentic-business-os-uat-final-consistency-v1/ 全部 | 已读目录清单 | UFC 轮：终态一致性、UAT V3、evidence-driven gate |
| 12 | .eval/v3_uat_v3/gate.json | 已读 | READY（漏检，见 00-LIVE-AUDIT §6） |
| 13 | .eval/v3_uat_v3/report.json | 已读 | UAT V3 报告 |
| 14 | .eval/v3_uat_v3/browser/browser_evidence.json | 已读 | 仅截图列表+console |
| 15 | scripts/v3_uat_rehearsal_v3.py | 已读 | UAT V3 驱动脚本（1114 行） |
| 16 | scripts/uat_report_validator.py | 已读 | 报告 fail-closed 校验 |
| 17 | src/platform/test_data.py | 已读（全文） | TestDataService 三表局限 |
| 18 | src/platform/home_center.py | 已读（全文） | calendar/activity/recent 无 scope |
| 19 | src/platform/gate_evaluator.py | 已读（全文） | v2.0.0 检查面 |
| 20 | Workflow/Agent/Command/Usage/Evidence/Survey/FieldOps/BI/Recognition 实现 | 已读关键路径 | control_plane.py 全文、agents/runtime.py 创建路径、workflow.py scope grep、finance/analytics/survey/field_ops 结构 |
| 21 | migrations/当前 schema | 已读 | store.py MIGRATIONS 001-050；sqlite_master 全表清单 |
| 22 | 最近 30 commits | 已读 | git log --oneline -30（记录于 EXECUTION-LOG T0） |
| 23 | 服务/进程/DB/模型/未跟踪资产 | 已审计 | 00-LIVE-AUDIT 全文 |
