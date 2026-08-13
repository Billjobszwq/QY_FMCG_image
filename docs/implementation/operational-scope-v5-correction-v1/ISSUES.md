# ISSUES — operational-scope-v5-correction-v1

| ID | 级别 | 标题 | 状态 | 契约 | 关闭证据 |
|---|---|---|---|---|---|
| OSV51-001 | P0 | quarantine 批次写逃逸（imp-bf333d101db6 已被重放） | CLOSED | C-1 | 守卫 52 测试绿 + 负例 13/14/16 + 提交 3c786897/3ec5cbd9 |
| OSV51-002 | P0 | users_v1 initial_password_once 明文持久化 | CLOSED | C-2 | 10 测试绿 + 负例 15 + scrub 0 命中 + 提交 30f0c17f |
| OSV51-003 | P0 | Gate 证据自比较/无绑定（静态 READY 与实时 STALE 并存） | CLOSED | C-6 | binding 块 + 去自比较 + 实时复核 + 负例 17-21 + 提交 0d759fe6 |
| OSV51-004 | P1 | 隔离区无裁决状态机（405） | CLOSED | C-3 | 15 测试绿 + 迁移 060 + API/UI + 提交 cc5600f4 |
| OSV51-005 | P1 | 17 批缺客户血缘却显示“全局” | CLOSED | C-4 | 9 测试绿 + 12→29 关联行 + Gate completeness + 提交 78964124 |
| OSV51-006 | P1 | test_branch_timeout 全量竞态 | CLOSED | C-5 | 确定性测试 + 100 轮压力零漂移 + 提交 c6af1d10 |
| OSV51-007 | P1 | 报告漂移（42vs52/125vs126/namespace/“首次23/23”） | CLOSED | C-8 | machine_facts.py + V5 更正附录 + 提交 5c166d66 |
| OSV51-008 | P1 | 全量 hermetic 实测失败而 test_report 声称 0 failed | CLOSED | C-5/C-8 | test_report 机器生成（binding + failed 诚实计数）+ kb flake 修复 185511b1；收尾全量重跑见 machine_facts |
| OSV51-009 | P2 | 路由切换滚动残留 | CLOSED | C-7 | ScrollManager + typecheck/build + 四视口浏览器断言（05-BROWSER-UAT） |
| OSV51-010 | P2 | 四视图截图字节相同 | CLOSED | C-6 | 采集修复 + browser_import_views_distinct Gate 检查 |
| OSV51-011 | P2 | QA 重放未入账 | CLOSED | C-1.9 | QA_REPLAY_DETECTED evidence+audit（幂等；live DB 已入账） |
| OSV51-012 | P2 | AGENTS.md 不存在 | WONTFIX | — | 记录于 00-LIVE-AUDIT §2（以 handbook + 本轮文档为入口） |
| OSV51-013 | P2 | store.py set_business_run_status 残留 SELECT-then-UPDATE（无 workflow 终态写入经此路径） | OPEN（低风险，下轮） | C-5 备注 | understand/parallel-engine.md + W1-a concerns |
