# 02 · Import IAM 与隐私（OSV5 T3）

端点权限（IAMService.authorize + visible_customers）：
- GET templates/download：登录即可。
- POST upload：模板矩阵 scope + 全部涉及客户授权（fail-closed 整批）。
- GET batches：scope 检查；默认 effective operational ∩ 调用者
  客户作用域 ∩ 允许全局；view=mine|history|quarantine；
  include_fixture=1 仅 platform_admin/owner/auditor。
- GET batches/{id}：批次作用域授权 → 显式 DTO（无原始 payload）。
- POST dry-run/commit：同 upload 权限 + 批次 scope 一致性。
- GET errors.csv / preview：批次作用域；preview 仅创建者或
  data.import.audit，脱敏 + ≤50 行。

DTO 白名单：batch_id/template_id/filename/actor/status/row_count/
data_scope/test_run_id/customer_scopes/created_at/updated_at/
dry_run_summary/error_count/commit_summary。
新 scope：finance.manage、data.import.audit（bundle 注册 v1）。
