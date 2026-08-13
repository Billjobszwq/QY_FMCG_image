# 02-IMPORT-SECURITY — 导入安全契约实现说明（C-1 / C-2）

## 1. 作用域守卫（W2-a）

**强制点**：`ImportCenter._assert_batch_writable(b)`，dry_run()/commit() 最前部调用；读 DB 行而非请求参数。
拦截条件与错误：

| 条件 | 结果 |
|---|---|
| data_scope ∈ {quarantine, archived} | ImportError_ `IMPORT_BATCH_WRITE_BLOCKED` → HTTP 409 |
| visibility == 'history' | 同上（原 _guard_active 语义并入） |
| 其余 | 放行原流程 |

覆盖的攻击面（全部进红测试 tests/platform/test_osv51_quarantine_guard.py）：
1. 直接 service 调用（绕过 API）；
2. POST /commit、/dry-run（API 层）；
3. 双线程并发 commit（都 409、零写入）；
4. 伪造前端参数改 data_scope（无效）；
5. 重启后重试（新 ImportCenter/store 实例仍 409）；
6. 14 个 template_id 参数化；
7. operational 批次回归不受影响。

**Gate**：负例 `quarantine_execution_escape`（osv5_gate_negative.py）+ 检查 `quarantine_no_operational_writes`（gate_evaluator.py，block=BLOCKED_BY_IMPORT_SECURITY）。

**QA 重放对账（OSV51-011）**：scripts/osv51_record_qa_replay.py 幂等追加：
- evidence_bundle_v1：kind='qa_replay_detection'，source_uri='import_batch:imp-bf333d101db6'，supersedes 语义指向 evid-dca91a51476a（重放产物）；
- scope_backfill_audit_v1：actor='osv51_correction'，rule='QA_REPLAY_DETECTED'，detail_json 含 batch_id、重放时刻 2026-08-13T08:07:41Z、audit_id≈437、commit_json 覆写事实（inserted:1→skipped:1）、app.log 证据位、对账结论（无新增 operational 对象；历史行不回写）。
历史 commit_json 保持重放后的现值不回写（D-07）。

## 2. 首次密码零持久化（W2-b）

**数据流目标态**：
```
users_v1 commit → iam.create_principal(password=temp_pw)   # DB 仅 PBKDF2 哈希
              → receipts（内存）含 initial_password_once
              → _update_batch 前 redact_secrets(recipes) → commit_json 落库为 [REDACTED]
              → POST /commit 响应体 = 未脱敏 receipts（仅此一次）
GET/列表/errors.csv/preview → batch_dto → 递归 secret 扫描兜底 → [REDACTED]
```

**secret 键集合（大小写不敏感）**：password、initial_password_once、password_once、passwd、token、api_key、apikey、secret、credential、private_key。
**递归扫描**：dict/list 任意深度；命中键 → 值替换 `[REDACTED]`（保留键，便于前端展示“已脱敏”）。
**熵**：Init- 前缀 + token_hex(16)（≥128bit）。
**清洗**：幂等脚本/迁移扫描现存全部批次 JSON 列（commit/dry_run/error/mapping）；发现即原位清除 + iam.audit `import.secret.scrubbed`（只记 batch_id、键路径、值指纹 sha256[:8]，绝不打印原值）。
**契约测试**（临时 DB）：users_v1 upload→dry-run→commit→GET→restart（新 store）→GET；断言除 commit 当次响应外一切表面无明文，且该密码登录仍有效（哈希可用）。
**Gate**：负例 `recursive_secret_scan`（扫描全部批次 JSON 列与 DTO 输出；发现非 [REDACTED] 敏感值 → BLOCKED_BY_IMPORT_SECURITY）。
**前端**：ImportCenter.tsx 首次密码展示仅在 commit 响应后的当次会话内存；详情重读不再出现明文（后端已脱敏，前端文案改为“初始密码仅在提交成功时显示一次”）。
