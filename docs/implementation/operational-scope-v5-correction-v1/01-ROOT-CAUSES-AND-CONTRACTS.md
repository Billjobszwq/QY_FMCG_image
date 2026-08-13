# 01-ROOT-CAUSES-AND-CONTRACTS — 根因与修复契约（实现基准）

所有实现代理以本文件的契约为基准。契约变更必须先改本文件并记入 DECISIONS.md。

## 根因总表

| ID | 缺陷 | 根因（file:line） |
|---|---|---|
| RC-1 | quarantine 写逃逸 | import_center.py `_guard_active`:577-583 不拦 data_scope=quarantine；commit 状态门接受 'committed'(:754) 允许重放；reconcile 脚本隔离时不设 visibility='history' |
| RC-2 | 首次密码持久化 | receipts 明文写入 commit_json(:796,800)；batch_dto receipts 原样透传(:1071-1073)；无递归 secret 扫描 |
| RC-3 | Gate 自比较/证据无绑定 | osv5_gate_evaluate.py:116-118 recorded=current 同源；四份证据文件均无代码/DB 绑定字段；实时路径只比 HEAD+db_fingerprint |
| RC-4 | 隔离区无出口 | 无裁决表/API/状态机；405 证据在 app.log:18450-18454 |
| RC-5 | 17 批次无血缘 | scope 关联写入路径晚于历史批次；osv5_reconcile 判定未物化；UI 对空关联显示“全局” |
| RC-6 | parallel timeout 竞态 | parallel.py `_finish_branch`:242-268 无条件 UPDATE；6 处 SELECT-then-UPDATE/无条件写；worker 迟到回写无守卫 |
| RC-7 | 报告漂移 | 数字手工录入；gate_negative_tests.json 手工静态化；osv5_gate_evaluate.py 覆写 UAT report.json |
| RC-8 | 导航滚动残留 | HashRouter 无 scroll reset/focus 管理；window 为滚动容器，滚动位置被钳制继承 |
| RC-9 | 全量 1 failed | test_asset_draft_publish_and_kb_search 全量态竞态（单跑通过），与 RC-6 同族时序问题 |

---

## C-1 作用域守卫契约（P0-1，详见 02-IMPORT-SECURITY.md）

1. **单一强制点**：`ImportCenter._assert_batch_writable(b)`（新函数），在 `dry_run()`、`commit()` 的最前部（_must 之后、任何写入之前）调用；同时 `replay`/任何内部重放路径必须经过同一函数。直接调用 service 同样被拦。
2. **拦截条件**：`data_scope in ('quarantine','archived')` 或 `visibility=='history'` → raise `ImportError_`，稳定错误码 `IMPORT_BATCH_WRITE_BLOCKED`，HTTP **409**；detail 格式 `IMPORT_BATCH_WRITE_BLOCKED: <原因>`。已终态历史批次重放同码。
3. **错误码稳定性**：错误码字符串进测试断言；API 层不得吞码改 500。
4. **dry-run 禁写**：quarantine 批次 dry-run 同样 409（它会覆写原批次 dry_run_json 证据）。只读分析走裁决证据（C-3 adjudication evidence，追加式、独立表）。
5. **UI**：`data_scope in (quarantine, archived)` 或 `visibility=='history'` 的批次详情不渲染 dry-run/提交按钮；渲染裁决操作区。
6. **并发/伪造/重启负例**：双线程并发 commit 只有一个结果且必为 409；前端参数伪造 data_scope 无效（守卫读 DB 行而非请求体）；重启后（新 ImportCenter 实例）仍 409。
7. **参数化**：红/绿测试必须参数化覆盖全部 14 个 template_id（至少 customers_v1/users_v1/projects_v1/stores_addresses_v1/skus_v1/employees_v1 六类实跑，其余以 registry 遍历断言守卫调用点）。
8. **Gate 负例**：`quarantine_execution_escape`——负例运行器对 quarantine 批次调 commit：期望 409；并 DB 级断言“任何 quarantine 批次产生 operational 对象”→ gate=BLOCKED_BY_IMPORT_SECURITY。
9. **QA 重放对账**：对 imp-bf333d101db6 追加 `QA_REPLAY_DETECTED` 证据（evidence_bundle_v1 kind='qa_replay_detection'，supersedes 指向 evid-dca91a51476a 的重放语义 + 引用 audit_id 437 与 app.log 行号），不改写任何历史行。

## C-2 首次密码零持久化契约（P0-2，详见 02-IMPORT-SECURITY.md）

1. **一次性交付**：`initial_password_once` 仅出现在 POST /commit 的当次 HTTP 响应体。
2. **落库脱敏**：commit_json/dry_run_json 中 receipts 的敏感键在 `_update_batch` 前经 `redact_secrets()` 递归替换为 `"[REDACTED]"`（保留键与非敏感字段如 username、stats）。
3. **DTO 递归扫描**：`batch_dto` 输出前递归扫描 dict/list，secret 键名集合 = {password, initial_password_once, password_once, token, api_key, apikey, secret, credential, private_key}（大小写不敏感、含子串匹配规则表）→ 值替换 `[REDACTED]`。errors.csv、preview、history/quarantine 列表同源同策略。
4. **哈希存储**：iam_principal_v1 仅存 PBKDF2 哈希（现状已满足，保持）；初始密码熵提升到 ≥128bit（token_hex(16)）。
5. **清洗脚本/迁移**：新迁移或幂等脚本递归扫描现存所有批次 JSON 列；发现敏感键 → 原位安全清除（不打印原值，日志只记 batch_id+键路径+sha256 前 8 位指纹）+ 追加审计（iam.audit `import.secret.scrubbed`）。
6. **契约测试**：临时 DB 真跑 users_v1 upload→dry-run→commit→GET→restart(新 store/新 ImportCenter)→GET，断言：commit 响应含明文一次；其后一切表面（DB JSON 列、GET、列表、errors.csv、evidence、audit、event）无明文。
7. **Gate 负例**：`recursive_secret_scan`——对全部批次 JSON 列 + DTO 输出递归扫描；发现 password/token/api_key/secret 等键携带非 `[REDACTED]` 值 → BLOCKED_BY_IMPORT_SECURITY。

## C-3 隔离区裁决状态机契约（P1，详见 03-QUARANTINE-STATE-MACHINE.md）

状态集：`quarantined → retained_for_evidence | bound_to_test_run | soft_discarded | release_requested → release_approved | superseded_by_new_batch`（release_requested 可被拒绝回 quarantined）。
1. **存储**：新迁移 `060_quarantine_adjudication_v1`：`quarantine_adjudication_v1`（batch_id PK, state, version, requested_by, requested_at, approved_by, approved_at, target_test_run_id, revision_batch_id, reason）+ 追加式 `quarantine_adjudication_evidence_v1`（只读分析产物，INSERT 触发器禁 UPDATE/DELETE）。原 import_batch_v1 行与证据不可修改（soft_discard 只改裁决表 state，不动批次行）。
2. **API**：`POST /api/v1/import/batches/{id}/adjudication`，body {action, reason, target_test_run_id?}；action ∈ retain/bind_test_run/soft_discard/request_release/approve_release/reject_release。权限：platform 角色或 `data.import.audit`；审计事件 `import.quarantine.<action>`（追加）。
3. **release_to_operational**：双人审批（approve_release 的 actor ≠ request_release 的 actor，否则 409 `ADJUDICATION_SAME_ACTOR`）；批准后**创建新批次 revision**（新 batch_id，data_scope=operational 或绑定 test_run，supersedes=原批次），原批次 adjudication.state=superseded_by_new_batch；禁止把原 quarantine 行原地改成 operational。
4. **CAS/幂等**：所有状态转换 `UPDATE ... WHERE batch_id=? AND version=?`；rowcount=0 → 409 `ADJUDICATION_VERSION_CONFLICT`；同状态重复提交返回当前状态 200（幂等）。
5. **UI**：quarantine 详情渲染裁决按钮组（按当前 state 与权限显隐）；三个现有批次可安全查看与裁决。
6. **负例**：无权限 403；跨客户 403；直接 URL 访问他人客户批次 403/404 fail-closed；并发双批准仅一个成功；申请人自批 409。

## C-4 客户血缘回填契约（P1）

1. **回填源**：`batch.test_run_id` → `uat_test_run_v1`（唯一行）→ `customer_ids_json` 单一客户；以 md_customer_v1.test_run_id、对象表（md_project_v1/geo_address_v1）、iam_audit import.committed 交叉印证。禁止名称模糊匹配。
2. **物化**：向 `import_batch_customer_scope_v1` 追加 17 批关联行（scope_source='backfill_osv51'，authorization_decision='granted'），UNIQUE(batch_id,customer_id) 防重（新迁移加唯一索引）；逐批写入 `scope_backfill_audit_v1`，detail_json **必须含 batch_id**。
3. **不可确定者**：3 个 quarantine 批次不写关联行；UI/API 显示“未绑定/待裁决”，禁止显示“全局”。
4. **单一关联源**：新函数 `ImportCenter.batch_customer_associations(batch_id)`（读 import_batch_customer_scope_v1）被 history 列表、quarantine 列表、detail DTO、authorize_batch、BI/审计查询共同使用；废除任何各自为政的拼接。
5. **守恒校验**：回填脚本输出 before/after 逐批次审计表 + 守恒等式（关联行数增量 == 17×1，其余表不变），落盘 `.eval/scope_v5/lineage_backfill_audit.json`。
6. **Gate**：新检查 `import_batch_association_complete`——history/quarantine/current 每个批次要么 ≥1 关联行、要么 data_scope=quarantine（合法未绑定）；其余缺失 → BLOCKED_BY_IMPORT_SCOPE_LINEAGE。

## C-5 并行工作流终态契约（P1）

1. **终态优先级**：timeout/failed/completed/cancelled 均不可降级；竞争写入按“先到且合法者赢，后到者无条件放弃”。
2. **条件 UPDATE**：所有终态写入改为 `UPDATE business_run_v1 SET status=?, end_at=? WHERE id=? AND status IN ('running','waiting_timer',...)`（非终态集合），rowcount 判定成败；废除 finalize 的 SELECT-then-UPDATE。`_finish_branch` 同理（branches 终态互不覆盖：`WHERE id=? AND status NOT IN ('timeout','failed','completed','cancelled')`）。
3. **迟到写防护**：worker 完成回写携带 branch 当前状态条件；超时判定后到达的 completed 写入被 rowcount=0 拒绝。
4. **测试确定性**：test_branch_timeout 改为有界等待/状态轮询断言，不依赖 sleep 时序；新增 100 轮压力测试（随机抖动调度，覆盖 all/any/quorum、外部取消、branch timeout、run timeout、重启恢复），断言零漂移。
5. **全量绿**：同族修复覆盖 test_asset_draft_publish_and_kb_search 的全量态竞态（先复现定位根因，再修；不得放宽断言）。

## C-6 Gate 证据新鲜度契约（P0，详见 04-EVIDENCE-FRESHNESS.md）

1. **证据绑定块**：uatv7/report.json、test_report.json、browser_evidence.json、gate_negative_tests.json 每份必须含：`source_commit, code_tree_hash, migration_hash, database_fingerprint, suite_config_hash, started_at, finished_at, command_hash, result_hash`。生成器各自独立计算（在证据生成时刻），禁止由 gate 生成时回填。
2. **Gate 验证**：osv5_gate_evaluate.py 从每份证据读 recorded 绑定，独立计算 current 值并比对；任一不符 → 该检查 false → STALE_GATE_EVIDENCE。**recorded 只允许来自证据文件本身**——消灭自比较。
3. **test_report 机器化**：新脚本 `scripts/osv51_test_report.py` 运行 hermetic pytest（或解析既定运行产物）生成带绑定块的 test_report.json；手写 JSON 作废。
4. **实时路径增强**：/api/v1/control/gate freshness 复评增加 tree hash + migration hash + worktree clean 复核（读时计算，5s 缓存沿用）。
5. **失败必须显形**：全量 1 failed 的当下，任何证据重生成必须记录 failed=1 → gate 必须非 READY；修复并全部重跑后才允许恢复 READY。
6. **负例**：新增 stale 负例——改代码不重跑测试 → STALE；改 DB 不重跑 UAT → STALE；改前端不重跑浏览器证据 → STALE；自比较注入检测（recorded==current 且证据文件缺失绑定块 → BLOCKED_BY_GATE_EVIDENCE）。

## C-7 导航滚动契约（P2）

1. 路由 pathname 变化（POP 除外）→ `window.scrollTo(0,0)` + 聚焦新页面 h1（tabIndex=-1，preventScroll=false），`history.scrollRestoration='manual'`。
2. POP（back/forward）→ 恢复该 history key 保存的滚动位置。
3. aria-live 区域播报页面切换（屏幕阅读器）；键盘焦点落到 h1。
4. 覆盖入口：主导航、二级导航、Supervisor UIIntent navigate、普通链接、重定向。
5. 四视口（1440/1280/1024/768）真实浏览器验收；console 无未解释错误。

## C-8 报告单一事实源契约（P1）

1. **机器事实文件**：新脚本 `scripts/osv51_machine_facts.py` 采集 HEAD/branch/registry 计数/gate check 数/UAT namespace 与 batch IDs/测试计数/服务状态/bundle/训练进程 → `.eval/scope_v5/machine_facts.json`（带生成时刻与绑定块）。
2. **FINAL-REPORT 生成**：本轮 FINAL-REPORT.md 的数字与 ID 全部引用 machine_facts.json，禁止手工录入。
3. **历史报告更正**：V5 轮 13 份漂移报告不改写历史，在其 FINAL-REPORT 追加“V5.1 更正附录”指向本轮证据；OPERATOR-RUNBOOK/USER-HANDBOOK 的 42/125 等口径随本轮最终数字更新。
4. **负例账本去手工化**：gate_negative_tests.json 只允许 osv5_gate_negative.py 生成（含本轮新增负例），禁止手写。

## 实施顺序与提交纪律

波次（依赖序）：
- W1（并行）：C-5 parallel 修复 ｜ C-7 导航滚动 ｜ RC-9 kb 测试竞态定位
- W2（串行）：C-1 quarantine 守卫（红→绿）→ C-2 密码零持久化（红→绿）
- W3：C-3 裁决状态机（依赖 C-1 的守卫与 UI 区域）
- W4：C-4 血缘回填（依赖 C-3 的 quarantine 语义）
- W5：C-6 Gate 新鲜度（在 W2-W4 的新检查之后，一次成型）
- W6：C-8 报告 SSOT + 证据链全量重生成 + 完整验收 + FINAL-REPORT + handbook

每个提交：显式文件清单（禁 git add -A）；红测试先行；禁 merge/push/deploy/训练/切 bundle。
