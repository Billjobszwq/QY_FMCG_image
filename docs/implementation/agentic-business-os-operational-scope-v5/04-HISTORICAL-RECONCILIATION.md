# 04 · 历史 20 条纠偏（OSV5 T5）

scripts/scope_reconcile_imports_v5.py：
- plan_reconciliation(conn)：只读；逐批结构化证据：
  1) mapping_json 客户 ↔ uat_test_run_v1.customer_ids_json；
  2) commit receipts 业务对象 ↔ Test Run；
  3) 导入对象自身 data_scope/test_run_id；
  4) 创建时间 ↔ Test Run 时间窗；5) audit/evidence 关联。
  文件名/UAT 前缀仅辅助诊断（不作为唯一依据）。
- 唯一确定 → decision=bind（uat_fixture + test_run_id）；
  否则 → decision=quarantine（data_scope='quarantine'）。
- apply_reconciliation：幂等、before/after hash、逐批写入
  scope_backfill_audit_v1、不删行、不覆盖不可变证据。
