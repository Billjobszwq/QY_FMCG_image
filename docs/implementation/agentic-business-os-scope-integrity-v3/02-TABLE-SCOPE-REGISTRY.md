# 02-TABLE-SCOPE-REGISTRY · 全表 Scope 登记（V3）

> 契约：当前数据库**全部**表逐张分类登记；任何业务表未登记 →
> Gate 阻断（`BLOCKED_BY_SCOPE_REGISTRY`）。机器事实源：
> `src/platform/scope_registry.py`（SCOPE_REGISTRY），本文档为其
> 人读投影，二者由测试 `test_registry_matches_db` 强制一致。

## 1. 分类

| 类别 | 语义 | Gate 规则 |
|---|---|---|
| scoped_business_object | 可变业务对象，带（或推导）scope | 泄漏扫描 + 父子边一致性 |
| immutable_ledger | 不可变账本（Usage/Evidence/事件） | 只追加；effective_scope 经 attribution 推导 |
| global_configuration | 全局配置（rate limit/flag/profile） | 不参与 scope 扫描 |
| reference_registry | 引用注册表（模型/SKU 别名/指标定义） | 按 effective 查询过滤 |
| derived_projection | 派生投影（work 投影/task_state） | 重建时必须按 effective 过滤 |
| cache_runtime | 运行时缓存/会话/租约 | 不进 Gate |
| audit_only | 审计/回填审计 | 只读，全量保留 |

## 2. 每表必填字段

主键 / tenant-customer-project 字段 / 直接 scope 字段或有效 scope
推导路径 / 父对象及关联键 / operational 查询规则 / fixture 归档规则 /
不可变规则 / Gate 扫描规则。

## 3. 登记表（随 T-reg 完成逐表填充；覆盖率必须 100%）

初始骨架按域列出必须登记的重点表（完整逐表清单见机器文件
`src/platform/scope_registry.py`）：

- 主数据：md_customer_v1、md_project_v1、md_sku_v1、md_sku_alias_v1
- 运行域：business_run_v1、work_item_v2、work_item_supersession_v1、
  task_state_projection_v1、goal_draft_v1
- 工作流：workflow_definition_v1、workflow_node_execution_v1、
  workflow_timer_v1、workflow_branch_v1、workflow_dead_letter_v1、
  flow_supersession_v1
- Agent：agent_definition_v1、agent_manifest_v1、agent_asset_v1、
  agent_command_v1、agent_session_v1、agent_session_msg_v1、
  agent_run_v1、agent_memory_v1、memory_entry_v1、blackboard_event_v1
- 问卷：survey_definition_v1、survey_assignment_v1、
  survey_response_v1、survey_media_v1、survey_answer_correction_v1
- 地理外勤：geo_address_v1、geo_employee_v1、geofence_v1、
  geofence_event_v1、field_task_v1、field_visit_evidence_v1、
  route_plan_v1、route_constraint_preset_v1、travel_cost_v1、
  user_calendar_v1
- 识别：recognition_task、recognition_profile_v1、
  recognition_profile_def_v1、cascade_usage
- BI：bi_metric_v1、bi_report_spec_v1、bi_dashboard_v1、
  bi_anomaly_v1、bi_followup_answer_v1
- Usage/财务：usage_event_v2、usage_event（legacy）、
  usage_attribution_v1、fin_rate_card_v1、fin_contract_v1、
  fin_invoice_v1、fin_invoice_line_v1、fin_adjustment_v1
- 事件/投影：event_envelope_v1、outbox_v1、evidence_bundle_v1、
  evidence_bundle（legacy）、audit_event、iam_audit_event_v1
- IAM：iam_principal_v1、iam_role_v1、iam_role_permission_v1、
  iam_permission_bundle_v1、iam_membership_v1、
  iam_approval_matrix_v1、auth_sessions、share_token
- 测试治理：uat_test_run_v1、scope_backfill_audit_v1、
  scope_attribution_ledger_v1（V3 新增）
- 训练/模型（治理域，非业务投影）：training_*、model_*、
  dataset_snapshot*、evaluation_registry_v1、legacy_model_registry_v1、
  sam_lineage_v1、nextgen_*、quality_*、gold_region_v1、
  review_*、knowledge_document_v1
- 其他：platform_flag、rate_limit_v1、rate_limit_rule_v1、job、
  job_attempt、user_note_v1、import_batch_v1、source_asset_inventory_v1、
  package_decision、package_supersede、resource_lease_v1、
  resource_benchmark_v1、webhook_event、asset、checkpoint、graph_run、
  node_execution、training_run、schema_migrations、sqlite_sequence

## 4. 覆盖率要求

- `覆盖率 = 已登记表数 / sqlite_master(type='table'，剔除
  sqlite_* 内部表) = 100%`；
- scoped_business_object 表必须给出父对象与推导路径；
- immutable_ledger 表必须给出 attribution 推导规则；
- Gate 3.0 负例包含"未登记新表"阻断。
