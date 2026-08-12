# 02-DOMAIN-SCOPE-MATRIX · 全 Domain scope 覆盖矩阵

迁移 `051_execution_scope_v1` 为下列表追加
`data_scope TEXT NOT NULL DEFAULT 'operational'` 与
`test_run_id TEXT NOT NULL DEFAULT ''`（已有列的表不重复加）：

| Domain | 表 | scope 来源 |
|---|---|---|
| 主数据 | md_customer_v1（已有）、md_project_v1、md_sku_v1、md_sku_alias_v1、geo_employee_v1、geo_address_v1 | 创建入参/Test Run |
| 外勤 | field_task_v1、field_visit_evidence_v1、route_plan_v1、geofence_v1、geofence_event_v1、user_calendar_v1、travel_cost_v1 | 父 customer/test_run |
| 问卷 | survey_definition_v1、survey_assignment_v1、survey_response_v1、survey_media_v1、survey_answer_correction_v1 | 父 survey/assignment |
| Workflow | workflow_definition_v1、workflow_node_execution_v1、workflow_timer_v1、workflow_branch_v1、workflow_dead_letter_v1（approval 以 work_item status=approval 表达，已有 scope） | 父 Run |
| Run/Work | business_run_v1（已有）、work_item_v2（已有）、event_envelope_v1、outbox_v1 | ScopeResolver |
| Agent | agent_run_v1、agent_session_v1、agent_session_msg_v1、agent_command_v1 | 父 Run |
| 识别 | recognition_task | 父 Run/command |
| 证据/用量 | usage_event_v2、evidence_bundle_v1、usage_attribution_v1 | 来源 Run（fail-closed） |
| BI | bi_metric_v1、bi_report_spec_v1、bi_dashboard_v1、bi_anomaly_v1、bi_followup_answer_v1 | 创建上下文 |
| 财务 | fin_rate_card_v1、fin_contract_v1、fin_invoice_v1、fin_invoice_line_v1、fin_adjustment_v1 | 父 customer（Usage 聚合必须按 scope 分账） |

查询口径（ScopedQuery 默认）：

- 首页/日历/最近/活动/Agent 事实查询/BI/财务/全局搜索 →
  `COALESCE(data_scope,'operational')='operational'`；
- fixture 仅"测试与证据中心"可见（显式 scope=uat_fixture + 权限）；
- 所有 API 返回对象带 `data_scope` 字段标识。
