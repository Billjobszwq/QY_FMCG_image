# ISSUES · Operational Scope V5

| ID | 级别 | 状态 | 摘要 | 证据 |
|---|---|---|---|---|
| OSV5-001 | P0 | CLOSED | 历史 20 条 UAT 导入批次全部 operational 污染运营面/BI/Gate | 纠偏 17 bind + 3 quarantine（scope_backfill_audit_v1 20 行；operational=0）；.eval/scope_v5/before/before_audit_v5.json |
| OSV5-002 | P0 | CLOSED | 导入创建链无 ExecutionContext/test_run_id | 迁移 059 + upload(test_run_id) 同事务写 uat_fixture；UAT V7 23/23 真实 multipart |
| OSV5-003 | P0 | CLOSED | Import API 跨角色/跨客户越权 | 模板权限矩阵 + authorize_batch + 逐客户 fail-closed；红测试 r09-r14 绿；UAT V7 检查 4/12/13；负例 4/5 |
| OSV5-004 | P0 | CLOSED | 详情接口返回原始 payload | batch_dto 白名单（无 mapping/dry_run/error_report/commit_json）；preview 端点授权+脱敏+50 行上限；r15/r16 绿 |
| OSV5-005 | P0 | CLOSED | Registry 非可执行唯一事实源 | _SCOPED_TABLES/_SCOPED_DOMAIN_TABLES 均 Registry 派生；ARCHIVE_HANDLERS+leak_scan_tables；scope_audit_v5.py 七维 |
| OSV5-006 | P0 | CLOSED | Registry 假语义（35 pk/5 customer_col/115 tenant_col） | 全部修正为真实列/composite:/not_applicable；validate_registry 零错误（r22 绿） |
| OSV5-007 | P1 | CLOSED | Import Center 浏览器假阴性 | 四视图对象级对账（DOM 行==API 计数 + 具体 batch_id）；29/29；OSV5-007 浏览器证据 |
| OSV5-008 | P1 | CLOSED | 归档/测试中心未覆盖 import_batch_v1 | ARCHIVE_HANDLERS import handler（visibility=history）；center count_tables import_batches；r20/r21 绿 |
| OSV5-009 | P1 | CLOSED | Gate data-products 只核客户 | data_products_all_effective_consistent 8 产品逐项对账（禁弱条件） |
| OSV5-010 | P1 | CLOSED | Gate/报告版本漂移 | EVALUATOR_VERSION=3.2.0 单点；gate.json/API/负例/审计器一致；evaluator_version_consistent 检查 |
| OSV5-011 | P2 | CLOSED | 过期 session 仅惰性删除 | purge_expired_sessions（登录触发；只删过期；审计；bill 豁免）；r32 绿 |
| OSV5-012 | P2 | CLOSED | scope_audit_v4.py 漂移 | v4 过期口径标注修正 + scripts/scope_audit_v5.py 七维审计器 |
