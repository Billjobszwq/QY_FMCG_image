# READING-LIST · Operational Scope V5

开工前完整阅读（指令第二节，29 项）：

| # | 文档/代码 | 状态 | 关键记录 |
|---|---|---|---|
| 1 | ~/.local/share/ai-workflow/routing/GLOBAL_AGENT_ROUTING.md | READ | Graph+Loop、证据优先、诚实边界 |
| 2 | AGENTS.md | READ | 项目红线与提交规则 |
| 3 | docs/CODEX-PROJECT-HANDBOOK.md | READ | V4 九条方法论（含 READY 绑定最终 HEAD+DB fingerprint） |
| 4 | docs/USER-HANDBOOK.md | READ | Import Center 用户口径 |
| 5 | docs/OPERATOR-RUNBOOK.md | READ | 服务启停/Gate 复评流程 |
| 6 | docs/MODULE-AGENT-DEV-GUIDE.md | READ | Domain Pack 接入清单 |
| 7 | docs/implementation/agentic-business-os-operational-scope-v4/（全部） | READ | V4 FINAL-REPORT 47 项；导入闭环宣称无端到端证据（OSV5-002） |
| 8 | docs/implementation/agentic-business-os-scope-integrity-v3/（全部） | READ | Scope Graph V3 契约/ExecutionContext |
| 9 | 最近 50 个 Git commits | READ | 6ec99985 后无新提交（外部 TaaS 已在 V4 审计过） |
| 10 | src/platform/scope_registry.py | READ | 125 项；_e() 默认 tenant_id；coverage 仅表名（OSV5-006） |
| 11 | src/platform/scope.py | READ | _SCOPED_TABLES=23；ScopedQuery/ScopeResolver |
| 12 | src/platform/test_data.py | READ | _SCOPED_DOMAIN_TABLES=18 无 import；count_tables 无 import |
| 13 | src/platform/import_center.py | READ | upload/_save_batch 无 scope；get_batch 返回整行 |
| 14 | src/platform/api/import_api.py | READ | 仅 require_principal；详情 pop("mapping") 后仍回原始 JSON |
| 15 | src/platform/analytics.py | READ | bi_effective_counts 含 import_batch_v1 |
| 16 | src/platform/api/analytics_api.py | READ | data-products 用 effective 口径（import 被污染计入 20） |
| 17 | src/platform/gate_evaluator.py | READ | EVALUATOR_VERSION=3.0.0；无 import 检查；data-products 检查仅客户 |
| 18 | src/platform/iam.py | READ | SCOPES/BUILTIN_ROLES/authorize/visible_customers |
| 19 | src/platform/api/iam_api.py | READ | IAM 端点模式（guard 用法参考） |
| 20 | web/src/pages/ImportCenter.tsx | READ | 批次列无 filename/scope/test_run（OSV5-007） |
| 21 | tests/platform/test_abos_v3_import_center.py | READ | 现有 fixture 模式（build_production_bundle+TestClient） |
| 22 | tests/platform/test_si4_operational_surface.py | READ | V4 红测试模式 |
| 23 | scripts/scope_audit_v4.py | READ | 仍写 import_batch_v1 无 scope 列（OSV5-012） |
| 24 | scripts/uatv6_rehearsal.py | READ | UAT 协议骨架；ids 30 键无 import_batch |
| 25 | scripts/uat_report_validator.py | READ | REQUIRED_UATV6_EXTRA_IDS 协议 |
| 26 | .eval/scope_v4/gate.json | READ | evaluator_version=3.0.0（与文档 3.1 漂移） |
| 27 | .eval/scope_v4/uatv6/report.json | READ | 57/57；无 import 链证据 |
| 28 | .eval/scope_v4/browser/browser_evidence.json | READ | Import 页仅 token 断言（OSV5-007） |
| 29 | 当前数据库 schema/迁移/触发器/Registry 对账 | READ | 迁移至 058；import_batch_v1 有 data_scope/test_run_id 列但无客户关联表；PRAGMA 对账见 before_audit_v5.json |

结论：不得只信报告——V4 的"导入闭环"在创建链、归档链、授权链
三处均无真实端到端证据。
