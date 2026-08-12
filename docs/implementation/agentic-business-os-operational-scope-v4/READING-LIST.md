# READING-LIST · Operational Scope V4

| # | 文件 | 状态 | 用途 |
|---|---|---|---|
| 1 | ~/.local/share/ai-workflow/routing/GLOBAL_AGENT_ROUTING.md | 已读（SI3 轮完整阅读） | 全局工作流/安全策略 |
| 2 | 项目根 AGENTS.md / GLOBAL_AGENT_ROUTING.md | find 验证不存在 | 以全局 routing 为准 |
| 3 | docs/CODEX-PROJECT-HANDBOOK.md | 已读（含 SI3 收口节） | 项目方法论/假阳性教训 |
| 4 | docs/USER-HANDBOOK.md | 已读 | 角色与操作流 |
| 5 | docs/OPERATOR-RUNBOOK.md | 已读 | bin/abos/服务拓扑/健康探针语义 |
| 6 | docs/MODULE-AGENT-DEV-GUIDE.md | 已读 | Domain Pack 扩展规范 |
| 7 | docs/implementation/agentic-business-os-uat-scope-isolation-v2/ | 已读（SI3 轮） | SI2 契约与遗留 |
| 8 | docs/implementation/agentic-business-os-scope-integrity-v3/ | 已读（本轮作者文档） | V3 契约/审计/回填/Gate 3.0 |
| 9 | .eval/scope_v3/gate.json | 已读 | 旧 READY（已 STALE）绑定 78f2e990 |
| 10 | .eval/scope_v3/uatv5/report.json | 已读 | UAT V5 48/48，ids 24/24 |
| 11 | .eval/scope_v3/browser/browser_evidence.json | 已读 | 12/12 但覆盖面不足（P1-003） |
| 12 | .gstack/qa-reports/qa-report-127-0-0-1-2026-08-13.md | 已读 | 独立 QA：ISSUE-001…005 |
| 13 | src/platform/scope.py | 已读 | ExecutionContext/Resolver/Policy/ScopedQuery |
| 14 | src/platform/scope_registry.py | 已读 | 123 表物理登记（待语义升级） |
| 15 | src/platform/test_data.py | 已读 | Test Run 上下文/归档（缺 IAM/BI 收敛） |
| 16 | src/platform/gate_evaluator.py | 已读 | Gate 3.0（待 3.1） |
| 17 | src/platform/home_center.py | 已读 | 首页 effective 口径 |
| 18 | src/platform/iam.py（IAMService/MasterDataService） | 已读 | principal/membership/login 逻辑 |
| 19 | src/platform/analytics.py + api/analytics_api.py | 已读 | metric/data-products（物理计数根因） |
| 20 | src/platform/finance.py + api/finance_api.py | 已读 | invoice/contracts |
| 21 | src/platform/api/usage_api.py | 已读 | _EFFECTIVE_OP 口径 |
| 22 | src/platform/workflow.py / agents/runtime.py / control_plane.py | 已读 | Run/scope 透传 |
| 23 | web/src/pages/{BIWorkbench,Finance,UsageWorkbench,Geo,IamMaster,SystemStatus}.tsx、platform/SupervisorWorkspace.tsx | 已读 | 默认值/浮层/列表 |
| 24 | 最近 40+ commits | 已读 | 含外部 TaaS 6 commits 审计 |
| 25 | schema_migrations 001–056 + 全表 PRAGMA | 已读（审计器） | 缺 scope 列发现（metric/dashboard/import_batch） |
| 26 | 服务/进程/CURRENT/未跟踪资产 | 已核 | abos status + CURRENT.json |
