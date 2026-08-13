# ISSUES · Operational Scope V5

| ID | 级别 | 状态 | 摘要 | 证据 |
|---|---|---|---|---|
| OSV5-001 | P0 | OPEN | 历史 20 条 UAT 导入批次全部 operational 污染运营面/BI/Gate | .eval/scope_v5/before/before_audit_v5.json |
| OSV5-002 | P0 | OPEN | 导入创建链无 ExecutionContext/test_run_id（UAT V6 未经 Import Center） | 同上（签名静态事实） |
| OSV5-003 | P0 | OPEN | Import API 跨角色/跨客户越权（read_only 可 dry-run/commit） | tests/platform/test_osv5_import_scope.py |
| OSV5-004 | P0 | OPEN | 详情接口返回原始 mapping_json 等 4 类 payload，无 DTO | before_audit_v5.json p0004 |
| OSV5-005 | P0 | OPEN | Registry 非可执行唯一事实源（125/23/18 三套平行清单） | before_audit_v5.json p0005 |
| OSV5-006 | P0 | OPEN | Registry 假语义：35 假 pk/5 假 customer_col/115 假 tenant_col | before_audit_v5.json p0006 |
| OSV5-007 | P1 | OPEN | Import Center 浏览器验收假阴性（不显示 filename/scope/test_run） | ImportCenter.tsx 静态事实 |
| OSV5-008 | P1 | OPEN | archive_namespace/测试中心未覆盖 import_batch_v1 | test_data.py 静态事实 |
| OSV5-009 | P1 | OPEN | Gate data_products_effective_basis 只核 md_customer_v1 | gate_evaluator.py |
| OSV5-010 | P1 | OPEN | Gate 版本漂移：文档 3.1 vs 代码/证据 3.0.0 | before_audit_v5.json p1004 |
| OSV5-011 | P2 | OPEN | 过期 session 仅惰性删除，无有界清理（bill 为锁定身份不得误删） | auth.py principal() |
| OSV5-012 | P2 | OPEN | scope_audit_v4.py 与迁移 058 后 schema 漂移 | scripts/scope_audit_v4.py |
