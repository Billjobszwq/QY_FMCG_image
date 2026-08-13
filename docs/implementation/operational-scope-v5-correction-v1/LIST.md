# LIST — 工作项清单（wave/依赖/状态）

| Wave | 项 | 契约 | 触碰文件域 | 状态 |
|---|---|---|---|---|
| W1-a | parallel timeout 竞态修复 + 100 轮压力测试 | C-5 | src/platform/workflow/parallel.py, tests/platform/test_uatcc_parallel_engine.py(+新 stress 文件) | 进行中 |
| W1-b | kb search 全量态竞态（test_asset_draft_publish_and_kb_search）定位与修复 | C-5/RC-9 | tests/platform/test_abos_v3_agent_runtime.py, src/platform/agents/* | 进行中 |
| W1-c | 导航滚动/焦点/读屏修复 | C-7 | web/src/App.tsx, main.tsx, shell.css, 新 ScrollManager | 进行中 |
| W2-a | quarantine 写逃逸红→绿（服务守卫/409/UI/参数化/并发/重启） | C-1 | src/platform/import_center.py, api/import_api.py, web/src/pages/ImportCenter.tsx, tests | 待 W1 |
| W2-a2 | QA_REPLAY_DETECTED 证据入账 | C-1.9 | scripts + evidence/audit 追加 | 随 W2-a |
| W2-b | 首次密码零持久化红→绿（脱敏/递归扫描/清洗/契约测试） | C-2 | import_center.py, iam/auth, 新迁移, tests | 待 W2-a |
| W3 | 隔离区裁决状态机（迁移/API/CAS/双人审批/UI） | C-3 | 新迁移 060, import_center.py, api, web ImportCenter, tests | 待 W2 |
| W4 | 17 批血缘回填 + 未绑定/待裁决显示 + Gate completeness | C-4 | 新脚本, gate_evaluator.py, web 显示, scope_backfill_audit_v1 | 待 W3 |
| W5 | Gate 证据新鲜度（绑定块/去自比较/test_report 生成器/实时路径增强/负例） | C-6 | osv5_gate_evaluate.py, gate_evaluator.py, uatv7_rehearsal.py, osv5_browser_evidence.py, osv5_gate_negative.py, 新 osv51_test_report.py | 待 W4 |
| W6 | 报告 SSOT + machine_facts + 全量验收 + 证据链重生成 + FINAL-REPORT + handbook | C-8 | scripts/osv51_machine_facts.py, 本轮 docs, CODEX-PROJECT-HANDBOOK.md | 待 W5 |

验收门槛见 01 文件“实施顺序与提交纪律”与任务书第十节。
