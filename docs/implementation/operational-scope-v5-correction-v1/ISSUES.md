# ISSUES — operational-scope-v5-correction-v1

| ID | 级别 | 标题 | 状态 | 契约 |
|---|---|---|---|---|
| OSV51-001 | P0 | quarantine 批次可执行 dry-run/commit 写逃逸（imp-bf333d101db6 已被重放） | OPEN | C-1 |
| OSV51-002 | P0 | users_v1 initial_password_once 明文持久化于 commit_json 并被 GET 反复返回 | OPEN | C-2 |
| OSV51-003 | P0 | Gate 证据自比较 + 四份证据无代码/DB 绑定（静态 READY 与实时 STALE 并存） | OPEN | C-6 |
| OSV51-004 | P1 | 隔离区无人工裁决状态机/API（裁决端点 405） | OPEN | C-3 |
| OSV51-005 | P1 | 17 个历史批次缺 import_batch_customer_scope_v1 关联却被显示为“全局” | OPEN | C-4 |
| OSV51-006 | P1 | TestParallelEngine.test_branch_timeout 全量态竞态（timeout 被 finalize 覆盖为 cancelled） | OPEN | C-5 |
| OSV51-007 | P1 | 报告漂移：42vs52 checks、125vs126 registry、UAT namespace/batch ID 过期、“首次23/23”失实 | OPEN | C-8 |
| OSV51-008 | P1 | 全量 hermetic 实测 1 failed（test_asset_draft_publish_and_kb_search 全量态竞态），静态 test_report 声称 0 failed | OPEN | C-5/C-8 |
| OSV51-009 | P2 | 路由切换滚动位置残留（y=2124→≈1504），无焦点/读屏播报 | OPEN | C-7 |
| OSV51-010 | P2 | 浏览器证据 4 张 Import 视图截图字节相同（采集路径缺陷） | OPEN | C-6 附录 |
| OSV51-011 | P2 | imp-bf333d101db6 QA 重放未入账（需 QA_REPLAY_DETECTED 证据与 supersedes 关系） | OPEN | C-1.9 |
| OSV51-012 | P2 | AGENTS.md 不存在于仓库（阅读清单无法满足，已用 handbook 替代并记录） | WONTFIX（记录） | 00-LIVE-AUDIT §2 |
