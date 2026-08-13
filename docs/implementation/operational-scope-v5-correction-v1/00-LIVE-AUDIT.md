# 00-LIVE-AUDIT — Operational Scope V5.1 独立审计复核（as-of 2026-08-13 开工时点）

本文件是开工时点的实况审计快照（before-state），后续状态以 STATUS.md / EXECUTION-LOG.md 为准。

## 0. 环境基线

| 项 | 值 |
|---|---|
| branch / HEAD | feat/nextgen-training-cycle-v2 / 8e31708d584459fb38fedefe21b070bede36db57 |
| 服务 | app/recognize/monitor/label_studio 全 UP（bin/abos status） |
| production | prod_v4_best_r1（CURRENT.json，previous=prod_20260805_v5_r1） |
| 训练进程 | 0 |
| DB 备份 | .platform/backups/platform_pre_osv51_correction_20260813T162315.sqlite（integrity ok；原库 integrity ok） |
| 静态 Gate | .eval/scope_v5/gate.json = READY_FOR_REAL_DATA_UAT（52 checks，evaluated_at 2026-08-13T14:14:35+0800，绑定 HEAD 8e31708d） |
| 实时 Gate | 任务声明 STALE_GATE_EVIDENCE；浏览器证据采集时 gate_observed=STALE_GATE_EVIDENCE（browser_evidence.json）。静态文件与实时端点口径差异本身就是缺陷（见 §3） |

## 1. 已确认缺陷（独立审计 + 本轮复核）

### P0-1 quarantine 写逃逸（CONFIRMED，活体证据）
- 服务层无 data_scope 守卫：`ImportCenter._guard_active`（src/platform/import_center.py:577-583）只拦 `visibility=='history'` 与 `data_scope=='archived'`；quarantine 批次 `visibility='current'` 全部放行 dry-run/commit。
- 活体证据：imp-bf333d101db6（stores_addresses_v1，quarantine，archived_at=2026-08-13T05:28:36Z）在 **2026-08-13T08:07:41Z 被重放 commit**：
  - iam_audit_event_v1 第二条 `import.committed`（audit_id=437，inserted:0/skipped:1）；
  - import_batch_v1.updated_at=08:07:41.416302Z，commit_json 被从 inserted:1 覆写为 skipped:1；
  - .platform/logs/app.log 两次 `POST /api/v1/import/batches/imp-bf333d101db6/commit`（行 7001、18504）；
  - 新增 evid-dca91a51476a（source_uri=import_batch:imp-bf333d101db6）。
  - 未新增 operational 对象（地址已存在被幂等跳过）——这是运气，不是守卫。
- UI：ImportCenter.tsx:213-222 对任意批次渲染 dry-run/提交按钮。
- 裁决端点不存在：app.log 行 18450-18454 对 /adjudicate、/resolve、/bind、/delete、/archive 的 OPTIONS 探测全部 405。

### P0-2 首次密码持久化（CONFIRMED，代码路径）
- `_commit_row` users_v1（import_center.py:912-921）生成 `Init-`+token_hex(4)（仅 32bit），回执 `initial_password_once` 明文进入 receipts → commit_json（:796, :800-801, _update_batch :1208/1215）落库并永久存活。
- `batch_dto`（:1071-1073）receipts 原样透传 → GET 详情/四视图列表反复返回明文。
- 泄漏面：commit_json 静态存储、GET 详情、operational/mine/history/quarantine 列表、前端缓存展示（ImportCenter.tsx:244-249 文案“仅显示一次”为假）。
- Gate 检查 import_batch_raw_payload_redacted 只查 DTO key 名单，不查内容 → 绿灯下泄漏。

### P0-3 Gate 证据新鲜度自比较（CONFIRMED）
- scripts/osv5_gate_evaluate.py:116-118 把当前 head/tree/migration 同时作为 recorded 与 current 传入 → 三项绑定检查恒真。
- uatv7/report.json、test_report.json、browser_evidence.json 均无 source_commit/tree/migration/db 绑定字段；证据→Gate→代码链在证据端断裂。
- test_report.json 手写、无生成器、无 HEAD 绑定；实时路径只比 HEAD+db_fingerprint，不比 tree/migration/worktree/证据文件 hash。
- 本轮全量实测 1 failed（见 §4），而 test_report.json 声称 0 failed —— 静态证据已失真。

### P1-1 隔离区无裁决状态机
- quarantine 仅由 data_scope 表达；status 仍是 committed/validation_failed；无裁决 API（405 证据如上）、无状态迁移、无双人审批、无 CAS。

### P1-2 17 个历史批次无客户血缘
- import_batch_customer_scope_v1 仅 12 行（全部属于 uatv7 三个批次×4 关联）；其余 26 个批次中 17 个 uat_fixture 历史批次（8×uat_fixture_v3、6×uatv2、3×uatv3）零关联行，却被 UI 呈现为“全局”。
- osv5_reconcile 在 scope_backfill_audit_v1（ids 66-83）已做出 17 条“唯一 Test Run 客户集”判定，但从未物化到 import_batch_customer_scope_v1，且审计行 detail_json 不含 batch_id。
- 17 批全部可确定性绑定（batch.test_run_id → uat_test_run_v1 唯一行 → 单一客户；md_customer/对象表/iam 审计交叉印证）。3 个 quarantine 批次候选 Test Run 数=0 → 必须保持未绑定/待裁决。

### P1-3 并行工作流 timeout 竞态（CONFIRMED）
- `_finish_branch`（src/platform/workflow/parallel.py:242-268）无条件 UPDATE，可把 timeout 覆盖为 completed/cancelled；共 6 处竞态点（详见 understand/parallel-engine.md）。

### P1-4 报告漂移（CONFIRMED）
- 42 vs 52 Gate checks（V5 EXECUTION-LOG T6 与 FINAL-REPORT §31/§51 写 42；gate.json 实际 52）；
- Registry 125 vs 运行时 126（scope_registry.json 追加 md_customer_v1 后 13 份报告未同步）；
- osv5_gate_evaluate.py 每次重评会覆写 uatv7/report.json 的 namespace/batch IDs → 13 份报告引用过期 ID；
- “首次 23/23” 与 kh463m 运行史（首次 jiv6d6 20/23 失败、jiv6d6 重跑 23/23 但报告被覆盖丢失）不一致。
- 根因：gate_negative_tests.json 手工静态化、数字手工录入、evaluator 覆写 UAT 记录。

### P2-1 导航滚动不回归顶部（CONFIRMED）
- web/src 全库仅一处 scrollTo（SupervisorWorkspace 聊天框）；HashRouter 路由切换无滚动重置、无焦点管理；y=2124 → 新页面被浏览器钳制到 ≈1504。

## 2. 附加发现（本轮实测）

- 全量 hermetic pytest 实测 **1 failed / 1478 passed**：`tests/platform/test_abos_v3_agent_runtime.py::TestLifecycleAssetsMemory::test_asset_draft_publish_and_kb_search`（单独重跑通过 → 全量态时序/状态竞态，与 test_branch_timeout 同类问题）。静态 test_report.json 的“0 failed”不成立。
- 浏览器证据中 4 张 Import Center 视图截图字节完全相同（sha256 c01b52d6…，各 241865 字节）却声称不同行数 —— 采集路径缺陷，视图分离仅由 DOM 数字证明。
- md_customer_v1 无任何 operational 客户；uat-cust-a/uat-cust-b is_test_fixture=0 但 data_scope=uat_fixture（分类不一致，登记在 ISSUES）。
- AGENTS.md 不存在（find maxdepth 3 为空）——阅读清单第 2 项无法满足，以 CODEX-PROJECT-HANDBOOK.md + 本轮文档替代并记录。

## 3. 静态 Gate 与实时 Gate 不一致的对账

静态 gate.json 生成于 14:14:35（HEAD 提交后 20 秒），此后：
1. 独立 QA 于 08:07:41Z（gate 生成前）已造成 quarantine 重放——静态 Gate 的 import 血缘检查未覆盖“quarantine 批次可写”这一维度；
2. 实时端点 /api/v1/control/gate 以 mtime 最新 gate.json 为基准只做 HEAD+db_fingerprint freshness 复评；浏览器证据采集时（14:00 左右）gate_observed=STALE 说明当时已有 DB/HEAD 漂移；
3. 本轮任何代码提交都会使 HEAD ≠ source_commit → 实时 Gate 立即 STALE_GATE_EVIDENCE（任务声明的当前实时状态即由此而来）。

结论：静态 READY 与实时 STALE 并存的根因是“证据不绑定生成时代码状态 + evaluator 覆写证据 + 实时路径只比两项”。修复契约见 04-EVIDENCE-FRESHNESS.md。

## 4. 开工前证据索引

- BEFORE-STATE.md（HEAD/工作树/服务/进程/CURRENT/迁移/Gate/批次数量/导入作用域）
- before-snapshots/{gate,uatv7_report,test_report,browser_evidence,gate_negative_tests}.json
- 全量 pytest 基线：/tmp/osv51_full_pytest_run1.log（1 failed, 1478 passed, 263s）
- understand/*.md（10 路阅读报告：handbook/runbooks/scope-governance/gate-evidence/import-pipeline/parallel-engine/iam-users-import/frontend/registry-reports/db-lineage）
