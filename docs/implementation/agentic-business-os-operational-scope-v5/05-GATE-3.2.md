# 05 · Gate 3.2（OSV5 T6）

EVALUATOR_VERSION="3.2.0"（代码常量；gate.json/API/Web/文档/
validator/负例统一引用）。

新增检查（18）：import_batch_scope_complete /
import_batch_operational_fixture_zero /
import_batch_unknown_scope_zero / import_batch_api_effective_consistent /
import_batch_bi_effective_consistent /
import_batch_archive_handler_registered /
import_batch_test_center_consistent /
import_batch_cross_tenant_access_denied /
import_batch_raw_payload_redacted / registry_schema_valid /
registry_runtime_scanner_complete / registry_archive_handler_complete /
registry_operational_query_complete / registry_parent_edges_valid /
data_products_all_effective_consistent /
browser_import_current_history_separated /
uat_import_lineage_complete / evaluator_version_consistent。

新阻断状态：BLOCKED_BY_IMPORT_SCOPE_LINEAGE（优先级高于
OPERATIONAL_FIXTURE_SURFACE）。负例 ≥12（指令第八节清单），任一
成立 Gate 非 READY。data_products_all_effective_consistent 逐产品
对账（客户/项目/SKU/问卷/识别/usage/地址/import），禁用
"effective <= physical" 弱条件。
