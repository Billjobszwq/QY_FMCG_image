# 01 · 导入批次作用域模型（OSV5 T2）

批次 = 冻结执行上下文。迁移 059：

- import_batch_v1 增列：visibility TEXT DEFAULT 'current'、
  archived_at TEXT DEFAULT ''、source TEXT DEFAULT 'import_center'、
  correlation_id TEXT DEFAULT ''。（data_scope/test_run_id 已有）
- 新表 import_batch_customer_scope_v1：batch_id, customer_id,
  project_id（可空）, scope_source, authorization_decision,
  created_at；UNIQUE(batch_id, customer_id, COALESCE project '')。

创建规则：
- operational：test_run_id 必空；按模板权限矩阵 + 逐行客户授权；
  任一客户无权 → 整批 403 且不落库。
- UAT：必须显式 test_run_id；ScopeResolver.assert_test_run_current
  fail-closed（archived/不存在 409）；同事务写 data_scope=
  uat_fixture；禁止先 operational 再补写。
- 全局模板：users/roles/memberships→iam.manage；rate card→
  finance.manage；知识库→master.manage；不得因无 customer_id 绕过。
- 提交对象继承批次作用域（同事务）。
- 归档批次不得再次 dry-run/commit（409）；重放幂等。
