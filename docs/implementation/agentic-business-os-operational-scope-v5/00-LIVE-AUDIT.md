# 00-LIVE-AUDIT · Operational Scope V5（开工现场，独立复现）

审计时间：2026-08-13（UTC+8）；审计人：agent（OSV5）。
证据文件：`.eval/scope_v5/before/before_audit_v5.json`（由
`scripts/scope_audit_v5_before.py` 只读生成，防覆盖）。

## 1. 基线核对（指令第一节 vs 现场）

| 项 | 指令预期 | 现场实测 | 差异 |
|---|---|---|---|
| branch | feat/nextgen-training-cycle-v2 | 同 | 无 |
| HEAD | 6ec99985b4… | 6ec99985 | 无 |
| production | prod_v4_best_r1 | 同 | 无 |
| 8091/8092/8300/8400 | UP | 四服务 UP | 无 |
| 训练进程 | 无 | 无 | 无 |
| SQLite integrity | ok | ok | 无 |
| 机器 Gate | 错误显示 READY_FOR_REAL_DATA_UAT | 实测 READY（34 检查） | 无 |
| evaluator_version | 3.0.0 | 3.0.0 | 无 |
| import_batch_v1 | 20 条 | 20 条 | 无 |
| 20 条全 operational 且属历史 UAT | 是 | operational=20，uat_semantic=20 | 无 |
| BI import.batches_v1=20 | 是 | data-products rows=20 | 无 |

## 2. 独立复现的问题（全部结构化证据，非名称推断）

### P0-001 历史 UAT 导入批次污染运营面（OSV5-001）
SQL（指令原文）：total=20 / operational=20 / uat_semantic=20。
- GET /api/v1/import/batches → count=20（默认全量返回）；
- GET /api/v1/analytics/data-products → import.batches_v1 rows=20；
- GET /api/v1/control/gate → READY_FOR_REAL_DATA_UAT（错误放行）。

### P0-002 创建链无作用域（OSV5-002）
`ImportCenter.upload()` 签名无 ExecutionContext/test_run_id；
`_save_batch()` INSERT 不含 data_scope/test_run_id；全部批次依赖
DB 默认 operational。UAT V6 ids 30 键中无 import_batch——旧报告
"导入归档闭环"无端到端证据。

### P0-003 Import API 跨角色/跨客户越权（OSV5-003）
`import_api.py` 全部端点仅 `require_principal`（登录检查），无
permission/客户作用域校验；read_only 可 list/detail/dry-run/commit。
红测试在临时库复现（tests/platform/test_osv5_import_scope.py）。

### P0-004 详情原始 payload 泄漏（OSV5-004）
详情响应返回 mapping_json/dry_run_json/error_report_json/
commit_json（before 证据：returns_*_json 全 true，mapping_json
含原始导入行）。仅 `b.pop("mapping")` 不构成脱敏。

### P0-005 Registry 非唯一事实源（OSV5-005）
SCOPE_REGISTRY=125 项；scope.py `_SCOPED_TABLES`=23 项；
test_data.py `_SCOPED_DOMAIN_TABLES`=18 项；Gate 另有硬编码 SQL；
import_batch_v1 已登记但未进 scanner（不在 _SCOPED_TABLES）也未进
archiver（不在 _SCOPED_DOMAIN_TABLES）。

### P0-006 Registry 假语义（OSV5-006）
schema 对账：35 个不存在的 pk 声明；5 个不存在的 customer_col
（含 import_batch_v1.customer_id）；115 张表被 `_e()` 默认
tenant_col=tenant_id 但列不存在。registry_coverage 只比表名。

### P1-001 Import Center 浏览器假阴性（OSV5-007）
页面不显示 filename/data_scope/test_run_id（批次列仅截断 id），
fixture_token_count=0 不证明隔离。

### P1-002 归档/测试中心未覆盖 import_batch_v1（OSV5-008）
archive_namespace 无 import 分支；center_summary count_tables
无 import batches。

### P1-003 Gate data-products 只核客户（OSV5-009）
data_products_effective_basis 仅比对 md_customer_v1。

### P1-004 Gate/报告版本漂移（OSV5-010）
文档称 Gate 3.1；代码与证据 evaluator_version=3.0.0。

### P2-001 过期 session 滞留（OSV5-011）
auth_sessions 仅在访问时惰性删除；无有界清理。bill 为锁定平台
身份，不得当 orphan 清理。

### P2-002 旧审计器漂移（OSV5-012）
scripts/scope_audit_v4.py 仍写"import_batch_v1 无 scope 列"，与
迁移 058 后 schema 不符。

## 3. 备份（红线一.1）

- 文件：`.platform/backups/platform_pre_scope_v5_20260813T124408.sqlite`
- 备份库 sha256：`f1f92091f1b2001b0cd6f338f7a74d988b63e4ecce3fec66f03f98ea8c53b284`
- 源库 sha256：`694ce1d71a88c00503ee22ac934730ccfb6aed8173a0951730016ce2aba29a01`（WAL 在途，hash 不同属预期）
- 双向 integrity_check：源库 ok / 备份库 ok
