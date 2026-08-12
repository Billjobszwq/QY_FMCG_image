"""SI3 T3：全表 Scope Registry（指令第五节）。

对当前数据库**全部**表逐张分类登记；机器事实源即本文件。
02-TABLE-SCOPE-REGISTRY.md 为人读投影，`registry_coverage()` 强制
与 sqlite_master 一致：任何业务表未登记 → Gate 阻断
（BLOCKED_BY_SCOPE_REGISTRY）。

分类：
- scoped_business_object  可变业务对象（自身 scope 列或父链推导）
- immutable_ledger        不可变账本（append-only；effective scope
                          经 attribution ledger / 父链推导）
- global_configuration    全局配置（不参与 scope 扫描）
- reference_registry      引用注册表（定义/制品/指标目录）
- derived_projection      派生投影（可重建；重建必须按 effective 过滤）
- cache_runtime           运行时缓存/会话/租约/旧内核态
- audit_only              审计/归属账本（只读，全量保留）

每表登记字段：pk / tenant-customer-project 列 / scope_cols（直接列）
或 derive（有效 scope 推导路径）/ parent（父对象与关联键）/
op_rule（operational 查询规则）/ archive_rule（fixture 归档规则）/
immutable（不可变规则）/ gate（Gate 扫描规则）。
"""
from __future__ import annotations

from typing import Any

CATEGORIES = ("scoped_business_object", "immutable_ledger",
              "global_configuration", "reference_registry",
              "derived_projection", "cache_runtime", "audit_only")

_OP_EFF = "effective-operational（自身列 ⊕ 父链 ⊕ attribution）"
_ARCHIVE = "归档随 test_run_id 结构化（data_scope=uat_fixture）"
_NOOP_ARCHIVE = "不适用（非业务对象）"


def _e(cat: str, *, pk: str = "", customer: str = "", project: str = "",
       scope: str = "", derive: str = "", parent: str = "",
       op: str = _OP_EFF, archive: str = _ARCHIVE,
       immutable: bool = False, gate: str = "leak_scan") -> dict:
    return {"category": cat, "pk": pk, "tenant_col": "tenant_id",
            "customer_col": customer, "project_col": project,
            "scope_cols": scope, "derive": derive, "parent": parent,
            "op_rule": op, "archive_rule": archive,
            "immutable": immutable, "gate": gate}


SCOPE_REGISTRY: dict[str, dict[str, Any]] = {
    # ---------- 主数据 ----------
    "md_customer_v1": _e("scoped_business_object", pk="customer_id",
                         customer="customer_id",
                         scope="data_scope/test_run_id",
                         derive="is_test_fixture=1 → fixture",
                         op="list 默认排除 fixture（include_fixture 显式）",
                         gate="leak_scan+registry"),
    "md_project_v1": _e("scoped_business_object", pk="project_id",
                        customer="customer_id", project="project_id",
                        scope="data_scope/test_run_id",
                        parent="md_customer_v1.customer_id",
                        gate="leak_scan+parent_edge"),
    "md_sku_v1": _e("scoped_business_object", pk="sku_id",
                    customer="", scope="data_scope/test_run_id",
                    op=_OP_EFF, gate="leak_scan"),
    "md_sku_alias_v1": _e("scoped_business_object", pk="alias_id",
                          scope="经 md_sku_v1 推导",
                          parent="md_sku_v1.sku_id",
                          derive="sku 父链", gate="parent_edge"),

    # ---------- 运行域（控制平面） ----------
    "business_run_v1": _e("scoped_business_object", pk="run_id",
                          customer="customer_id", project="project_id",
                          scope="data_scope/test_run_id",
                          parent="business_run_v1.parent_run_id",
                          gate="leak_scan+parent_edge+terminal"),
    "work_item_v2": _e("scoped_business_object", pk="work_id",
                       customer="customer_id", project="project_id",
                       scope="data_scope/visibility",
                       derive="父链 run_id→business_run_v1",
                       parent="business_run_v1.run_id",
                       gate="leak_scan+parent_edge+terminal"),
    "work_item_supersession_v1": _e("derived_projection", pk="id",
                                    derive="随 work_item_v2",
                                    op="重建时按 effective 过滤",
                                    gate="projection"),
    "task_state_projection_v1": _e("derived_projection", pk="id",
                                   derive="随 work 投影",
                                   op="重建时按 effective 过滤",
                                   gate="projection"),
    "goal_draft_v1": _e("scoped_business_object", pk="goal_id",
                        customer="customer_id",
                        scope="经发起 run 推导",
                        derive="goal→run 父链", gate="parent_edge"),
    "flow_supersession_v1": _e("derived_projection", pk="id",
                               derive="随 workflow_definition_v1",
                               gate="projection"),

    # ---------- 工作流 ----------
    "workflow_definition_v1": _e("scoped_business_object",
                                 pk="definition_id",
                                 scope="data_scope/test_run_id",
                                 gate="leak_scan"),
    "workflow_node_execution_v1": _e(
        "scoped_business_object", pk="exec_id",
        scope="data_scope/test_run_id",
        derive="父链 run_id→business_run_v1",
        parent="business_run_v1.run_id",
        gate="leak_scan+parent_edge+terminal"),
    "workflow_timer_v1": _e("scoped_business_object", pk="timer_id",
                            scope="data_scope/test_run_id",
                            parent="business_run_v1.run_id",
                            derive="父链 run_id",
                            gate="leak_scan+parent_edge+terminal"),
    "workflow_branch_v1": _e("scoped_business_object", pk="branch_id",
                             scope="data_scope/test_run_id",
                             parent="business_run_v1.run_id",
                             derive="父链 run_id",
                             gate="leak_scan+parent_edge+terminal"),
    "workflow_dead_letter_v1": _e("immutable_ledger", pk="dead_letter_id",
                                  derive="父链 run_id→business_run_v1",
                                  parent="business_run_v1.run_id",
                                  immutable=True,
                                  gate="parent_edge+attribution"),

    # ---------- Agent ----------
    "agent_definition_v1": _e("reference_registry", pk="agent_id",
                              op="全局定义；运行实例按 run scope",
                              archive=_NOOP_ARCHIVE, gate="registry"),
    "agent_manifest_v1": _e("reference_registry", pk="agent_id",
                            archive=_NOOP_ARCHIVE, gate="registry"),
    "agent_asset_v1": _e("reference_registry", pk="asset_id",
                         archive=_NOOP_ARCHIVE, gate="registry"),
    "agent_session_v1": _e("cache_runtime", pk="session_id",
                           archive=_NOOP_ARCHIVE, gate="none"),
    "agent_session_msg_v1": _e("cache_runtime", pk="message_id",
                               archive=_NOOP_ARCHIVE, gate="none"),
    "agent_run_v1": _e("scoped_business_object", pk="run_id",
                       customer="customer_id", project="project_id",
                       scope="data_scope/test_run_id",
                       parent="business_run_v1.run_id(business_run_id)",
                       derive="父链 business_run_id",
                       gate="leak_scan+parent_edge"),
    "agent_command_v1": _e("scoped_business_object", pk="command_id",
                           derive="父链 agent_run/business_run",
                           parent="agent_run_v1.run_id",
                           gate="parent_edge"),
    "agent_memory_v1": _e("cache_runtime", pk="memory_id",
                          archive=_NOOP_ARCHIVE, gate="none"),
    "memory_entry_v1": _e("cache_runtime", pk="entry_id",
                          archive=_NOOP_ARCHIVE, gate="none"),
    "blackboard_event_v1": _e("immutable_ledger", pk="seq",
                              derive="父链 run_id",
                              immutable=True, gate="attribution"),

    # ---------- 问卷 ----------
    "survey_definition_v1": _e("scoped_business_object", pk="survey_id",
                               scope="data_scope/test_run_id",
                               derive="父链 assignment/response",
                               gate="leak_scan"),
    "survey_assignment_v1": _e("scoped_business_object",
                               pk="assignment_id",
                               customer="customer_id",
                               scope="data_scope/test_run_id",
                               parent="survey_definition_v1.survey_id",
                               gate="leak_scan+parent_edge"),
    "survey_response_v1": _e("scoped_business_object", pk="response_id",
                             customer="customer_id",
                             scope="data_scope/test_run_id",
                             parent="survey_assignment_v1.assignment_id",
                             gate="leak_scan+parent_edge"),
    "survey_media_v1": _e("scoped_business_object", pk="media_id",
                          scope="data_scope/test_run_id",
                          parent="survey_response_v1.response_id",
                          derive="父链 response→assignment",
                          gate="leak_scan+parent_edge"),
    "survey_answer_correction_v1": _e(
        "scoped_business_object", pk="correction_id",
        derive="父链 response_id→survey_response_v1",
        parent="survey_response_v1.response_id",
        gate="parent_edge"),

    # ---------- 地理外勤 ----------
    "geo_address_v1": _e("scoped_business_object", pk="address_id",
                         customer="customer_id",
                         scope="data_scope/test_run_id",
                         gate="leak_scan"),
    "geo_employee_v1": _e("scoped_business_object", pk="employee_id",
                          customer="customer_id",
                          scope="data_scope/test_run_id",
                          gate="leak_scan"),
    "geofence_v1": _e("scoped_business_object", pk="fence_id",
                      customer="customer_id",
                      scope="data_scope/test_run_id",
                      gate="leak_scan"),
    "geofence_event_v1": _e("scoped_business_object", pk="event_id",
                            customer="customer_id",
                            scope="data_scope/test_run_id",
                            derive="父链 fence/task",
                            gate="leak_scan+parent_edge"),
    "field_task_v1": _e("scoped_business_object", pk="task_id",
                        customer="customer_id",
                        scope="data_scope/test_run_id",
                        parent="md_customer_v1.customer_id",
                        gate="leak_scan+parent_edge"),
    "field_visit_evidence_v1": _e("immutable_ledger", pk="evidence_id",
                                  derive="父链 task_id→field_task_v1",
                                  parent="field_task_v1.task_id",
                                  immutable=True, gate="parent_edge"),
    "route_plan_v1": _e("scoped_business_object", pk="plan_id",
                        customer="customer_id",
                        scope="data_scope/test_run_id",
                        gate="leak_scan"),
    "route_constraint_preset_v1": _e("reference_registry", pk="preset_id",
                                     archive=_NOOP_ARCHIVE,
                                     gate="registry"),
    "travel_cost_v1": _e("scoped_business_object", pk="cost_id",
                         customer="customer_id",
                         derive="父链 task/plan",
                         gate="parent_edge"),
    "user_calendar_v1": _e("scoped_business_object", pk="event_id",
                           customer="customer_id",
                           scope="data_scope/test_run_id",
                           gate="leak_scan"),
    "user_note_v1": _e("scoped_business_object", pk="note_id",
                       op="actor 私有；无 fixture 风险",
                       archive=_NOOP_ARCHIVE, gate="none"),

    # ---------- 识别 ----------
    "recognition_task": _e("scoped_business_object", pk="task_id",
                           project="project_id",
                           scope="data_scope/test_run_id",
                           parent="business_run_v1.run_id",
                           derive="父链 run_id",
                           gate="leak_scan+parent_edge"),
    "recognition_profile_v1": _e("reference_registry", pk="profile_id",
                                 archive=_NOOP_ARCHIVE, gate="registry"),
    "recognition_profile_def_v1": _e("reference_registry",
                                     pk="profile_id",
                                     archive=_NOOP_ARCHIVE,
                                     gate="registry"),
    "cascade_usage": _e("immutable_ledger", pk="id",
                        derive="历史级联用量；经 run 父链",
                        immutable=True, gate="attribution"),

    # ---------- BI ----------
    "bi_metric_v1": _e("reference_registry", pk="metric_id",
                       archive=_NOOP_ARCHIVE, gate="registry"),
    "bi_report_spec_v1": _e("scoped_business_object", pk="spec_id",
                            customer="customer_id",
                            scope="data_scope/test_run_id",
                            derive="Agent 工具透传 ctx",
                            gate="leak_scan"),
    "bi_dashboard_v1": _e("scoped_business_object", pk="dashboard_id",
                          customer="customer_id",
                          scope="data_scope/test_run_id",
                          gate="leak_scan"),
    "bi_anomaly_v1": _e("scoped_business_object", pk="anomaly_id",
                        scope="data_scope/test_run_id",
                        derive="父链 report/metric",
                        gate="leak_scan"),
    "bi_followup_answer_v1": _e("scoped_business_object",
                                pk="answer_id",
                                derive="父链 anomaly→report",
                                parent="bi_anomaly_v1.anomaly_id",
                                gate="parent_edge"),

    # ---------- Usage / 财务 ----------
    "usage_event_v2": _e("immutable_ledger", pk="usage_id",
                         customer="customer_id", project="project_id",
                         scope="data_scope/test_run_id",
                         derive="父链 run_id/customer + attribution",
                         parent="business_run_v1.run_id",
                         immutable=True,
                         op="summary/rows/export/budget 用 effective 口径",
                         gate="leak_scan+parent_edge+attribution"),
    "usage_event": _e("immutable_ledger", pk="usage_id",
                      derive="legacy；经 attribution",
                      immutable=True, gate="attribution"),
    "usage_attribution_v1": _e("audit_only", pk="attribution_id",
                               immutable=True, gate="none"),
    "fin_rate_card_v1": _e("reference_registry", pk="rate_card_id",
                           archive=_NOOP_ARCHIVE, gate="registry"),
    "fin_contract_v1": _e("scoped_business_object", pk="contract_id",
                          customer="customer_id",
                          gate="parent_edge"),
    "fin_invoice_v1": _e("scoped_business_object", pk="invoice_id",
                         customer="customer_id",
                         derive="经 usage effective（排除 fixture）",
                         op="生成时排除 effective fixture usage",
                         gate="finance_scan"),
    "fin_invoice_line_v1": _e("scoped_business_object", pk="line_id",
                              derive="父链 invoice→usage",
                              parent="fin_invoice_v1.invoice_id",
                              gate="parent_edge"),
    "fin_adjustment_v1": _e("immutable_ledger", pk="adjustment_id",
                            customer="customer_id", immutable=True,
                            gate="parent_edge"),

    # ---------- 事件 / 证据 ----------
    "event_envelope_v1": _e("immutable_ledger", pk="seq",
                            derive="经 run_id 父链（活动日志过滤）",
                            immutable=True, gate="watermark"),
    "outbox_v1": _e("immutable_ledger", pk="event_id",
                    derive="随事件", immutable=True, gate="watermark"),
    "evidence_bundle_v1": _e("immutable_ledger", pk="evidence_id",
                             scope="data_scope/test_run_id",
                             derive="父链 run_id + attribution",
                             parent="business_run_v1.run_id",
                             immutable=True,
                             gate="leak_scan+parent_edge+attribution"),
    "evidence_bundle": _e("immutable_ledger", pk="evidence_id",
                          derive="legacy；经 attribution",
                          immutable=True, gate="attribution"),
    "webhook_event": _e("immutable_ledger", pk="event_id",
                        immutable=True, gate="none"),

    # ---------- IAM ----------
    "iam_principal_v1": _e("global_configuration", pk="username",
                           archive=_NOOP_ARCHIVE, gate="registry"),
    "iam_role_v1": _e("global_configuration", pk="role_id",
                      archive=_NOOP_ARCHIVE, gate="registry"),
    "iam_role_permission_v1": _e("global_configuration", pk="id",
                                 archive=_NOOP_ARCHIVE, gate="registry"),
    "iam_permission_bundle_v1": _e("global_configuration",
                                   pk="bundle_id",
                                   archive=_NOOP_ARCHIVE,
                                   gate="registry"),
    "iam_membership_v1": _e("global_configuration", pk="id",
                            customer="customer_id",
                            archive=_NOOP_ARCHIVE, gate="registry"),
    "iam_approval_matrix_v1": _e("global_configuration", pk="id",
                                 archive=_NOOP_ARCHIVE, gate="registry"),
    "iam_audit_event_v1": _e("audit_only", pk="seq", immutable=True,
                             gate="none"),
    "audit_event": _e("audit_only", pk="seq", immutable=True,
                      gate="none"),
    "auth_sessions": _e("cache_runtime", pk="session_id",
                        archive=_NOOP_ARCHIVE, gate="none"),
    "share_token": _e("cache_runtime", pk="token",
                      archive=_NOOP_ARCHIVE, gate="none"),

    # ---------- 测试治理 ----------
    "uat_test_run_v1": _e("reference_registry", pk="test_run_id",
                          op="Test Run registry（fail-closed 校验源）",
                          archive="归档置 status=archived",
                          gate="registry+no_open_context"),
    "scope_backfill_audit_v1": _e("audit_only", pk="id",
                                  immutable=True, gate="none"),
    "scope_attribution_ledger_v1": _e("audit_only",
                                      pk="attribution_id",
                                      immutable=True,
                                      op="effective_scope 推导依据",
                                      gate="attribution"),

    # ---------- 配置 / 限流 ----------
    "platform_flag": _e("global_configuration", pk="flag_key",
                        archive=_NOOP_ARCHIVE, gate="registry"),
    "rate_limit_v1": _e("global_configuration", pk="id",
                        archive=_NOOP_ARCHIVE, gate="none"),
    "rate_limit_rule_v1": _e("global_configuration", pk="rule_id",
                             archive=_NOOP_ARCHIVE, gate="registry"),
    "schema_migrations": _e("global_configuration", pk="id",
                            immutable=True, archive=_NOOP_ARCHIVE,
                            gate="migration_hash"),
    "sqlite_sequence": _e("global_configuration", pk="name",
                          archive=_NOOP_ARCHIVE, gate="none"),

    # ---------- 运行时 / 旧内核 ----------
    "job": _e("cache_runtime", pk="job_id", archive=_NOOP_ARCHIVE,
              gate="none"),
    "job_attempt": _e("cache_runtime", pk="attempt_id",
                      archive=_NOOP_ARCHIVE, gate="none"),
    "checkpoint": _e("cache_runtime", pk="checkpoint_id",
                     archive=_NOOP_ARCHIVE, gate="none"),
    "graph_run": _e("cache_runtime", pk="run_id",
                    archive=_NOOP_ARCHIVE, gate="none"),
    "node_execution": _e("cache_runtime", pk="exec_id",
                         archive=_NOOP_ARCHIVE, gate="none"),
    "model_lease": _e("cache_runtime", pk="lease_id",
                      archive=_NOOP_ARCHIVE, gate="none"),
    "model_residency": _e("cache_runtime", pk="model_id",
                          archive=_NOOP_ARCHIVE, gate="none"),
    "resource_lease_v1": _e("cache_runtime", pk="lease_id",
                            archive=_NOOP_ARCHIVE, gate="none"),
    "import_batch_v1": _e("scoped_business_object", pk="batch_id",
                          customer="customer_id",
                          scope="data_scope/test_run_id",
                          gate="leak_scan"),

    # ---------- 训练 / 模型治理（非业务运营投影） ----------
    "training_run": _e("scoped_business_object", pk="run_id",
                       op="治理域；scope=system", gate="registry"),
    "training_run_v2": _e("scoped_business_object", pk="run_id",
                          op="治理域；scope=system", gate="registry"),
    "training_plan_v2": _e("scoped_business_object", pk="plan_id",
                           op="治理域", gate="registry"),
    "training_event_v1": _e("immutable_ledger", pk="seq",
                            immutable=True, gate="none"),
    "training_cycle_v1": _e("scoped_business_object", pk="cycle_id",
                            op="治理域", gate="registry"),
    "training_cycle_node_v1": _e("scoped_business_object", pk="node_id",
                                 derive="父链 cycle", gate="parent_edge"),
    "training_cycle_node_state_v2": _e("immutable_ledger", pk="id",
                                       immutable=True, gate="none"),
    "training_cycle_event_v1": _e("immutable_ledger", pk="seq",
                                  immutable=True, gate="none"),
    "training_artifact_v1": _e("reference_registry", pk="artifact_id",
                               archive=_NOOP_ARCHIVE, gate="registry"),
    "training_artifact_v2": _e("reference_registry", pk="artifact_id",
                               archive=_NOOP_ARCHIVE, gate="registry"),
    "training_run_supersession_v1": _e("derived_projection", pk="id",
                                       gate="none"),
    "nextgen_plan_v1": _e("scoped_business_object", pk="plan_id",
                          op="治理域", gate="registry"),
    "nextgen_plan_approval_v1": _e("audit_only", pk="approval_id",
                                   immutable=True, gate="none"),
    "nextgen_run_attempt_v1": _e("immutable_ledger", pk="attempt_id",
                                 immutable=True, gate="none"),
    "dataset_snapshot": _e("reference_registry", pk="snapshot_id",
                           archive=_NOOP_ARCHIVE, gate="registry"),
    "dataset_snapshot_registry_v1": _e("reference_registry",
                                       pk="snapshot_id",
                                       archive=_NOOP_ARCHIVE,
                                       gate="registry"),
    "evaluation_registry_v1": _e("reference_registry", pk="eval_id",
                                 archive=_NOOP_ARCHIVE, gate="registry"),
    "model_artifact_registry_v1": _e("reference_registry",
                                     pk="artifact_id",
                                     archive=_NOOP_ARCHIVE,
                                     gate="registry"),
    "legacy_model_registry_v1": _e("reference_registry", pk="model_id",
                                   archive=_NOOP_ARCHIVE,
                                   gate="registry"),
    "sam_lineage_v1": _e("reference_registry", pk="lineage_id",
                         archive=_NOOP_ARCHIVE, gate="registry"),
    "source_asset_inventory_v1": _e("reference_registry", pk="asset_id",
                                    archive=_NOOP_ARCHIVE,
                                    gate="registry"),
    "resource_benchmark_v1": _e("reference_registry", pk="benchmark_id",
                                archive=_NOOP_ARCHIVE, gate="registry"),
    "asset": _e("reference_registry", pk="asset_id",
                archive=_NOOP_ARCHIVE, gate="registry"),
    "labeling_batch": _e("reference_registry", pk="batch_id",
                         archive=_NOOP_ARCHIVE, gate="registry"),
    "knowledge_document_v1": _e("reference_registry", pk="doc_id",
                                archive=_NOOP_ARCHIVE, gate="registry"),

    # ---------- 审核 / 质量 / gold ----------
    "review_task_v1": _e("scoped_business_object", pk="task_id",
                         op="治理域（标注审核）", gate="registry"),
    "review_queue_ledger_v1": _e("immutable_ledger", pk="seq",
                                 immutable=True, gate="none"),
    "review_queue_invalidation_v1": _e("immutable_ledger", pk="seq",
                                       immutable=True, gate="none"),
    "review_event_v1": _e("immutable_ledger", pk="seq", immutable=True,
                          gate="none"),
    "quality_decision_v1": _e("audit_only", pk="decision_id",
                              immutable=True, gate="none"),
    "quality_gold_v1": _e("reference_registry", pk="gold_id",
                          archive=_NOOP_ARCHIVE, gate="registry"),
    "quality_human_v1": _e("audit_only", pk="human_id", immutable=True,
                           gate="none"),
    "gold_region_v1": _e("reference_registry", pk="region_id",
                         archive=_NOOP_ARCHIVE, gate="registry"),
    "package_decision": _e("derived_projection", pk="id", gate="none"),
    "package_supersede": _e("derived_projection", pk="id", gate="none"),
}


# --------------------------------------------------------------------
# SI4 T5：对象生命周期语义层（防分类逃逸，指令第十节）。
# “表已登记”≠“UAT 数据不会进入运营平面”：每张表还必须声明
# UAT 可创建性/provenance/归档/登录授权/计费/BI/浏览器暴露面。
# --------------------------------------------------------------------

LIFECYCLE_KEYS = ("uat_creatable", "provenance", "archive_rule",
                  "login_impact", "billing_impact", "bi_impact",
                  "browser_surface")

_DEFAULT_LIFECYCLE_BY_CATEGORY = {
    "scoped_business_object": {
        "uat_creatable": "yes",
        "provenance": "data_scope/test_run_id 列（同事务写入）",
        "archive_rule": "archive_namespace 按 test_run_id 结构化归档",
        "login_impact": "none", "billing_impact": "via usage 父链",
        "bi_impact": "计入 data-products effective 口径",
        "browser_surface": "运营列表默认排除 fixture"},
    "immutable_ledger": {
        "uat_creatable": "yes",
        "provenance": "自身 scope 列 ⊕ attribution ledger ⊕ 父链",
        "archive_rule": "不改原行；attribution 追加式绑定",
        "login_impact": "none",
        "billing_impact": "effective 口径排除 fixture 后才可计费",
        "bi_impact": "usage effective 计数",
        "browser_surface": "仅测试中心可下钻 fixture 账本"},
    "global_configuration": {
        "uat_creatable": "restricted",
        "provenance": "创建者/来源必须可追踪（created_by/audit）",
        "archive_rule": "UAT 创建的配置必须可归档且不参与运营执行",
        "login_impact": "按表声明", "billing_impact": "按表声明",
        "bi_impact": "按表声明",
        "browser_surface": "运营页默认不暴露 UAT 配置"},
    "reference_registry": {
        "uat_creatable": "restricted",
        "provenance": "data_scope/test_run_id/status（迁移 058 起）",
        "archive_rule": "UAT 创建的引用对象归档后不进运营目录",
        "login_impact": "none", "billing_impact": "按表声明",
        "bi_impact": "metric/dashboard 不进运营 BI",
        "browser_surface": "运营目录默认排除 fixture"},
    "derived_projection": {
        "uat_creatable": "derived", "provenance": "随源表",
        "archive_rule": "重建时按 effective 口径过滤",
        "login_impact": "none", "billing_impact": "none",
        "bi_impact": "none", "browser_surface": "同源表"},
    "cache_runtime": {
        "uat_creatable": "runtime", "provenance": "actor 关联",
        "archive_rule": "Test Run 归档时失效/清理（运行时态）",
        "login_impact": "会话失效", "billing_impact": "none",
        "bi_impact": "none", "browser_surface": "不暴露"},
    "audit_only": {
        "uat_creatable": "append-only", "provenance": "actor/detail 自带",
        "archive_rule": "不归档不删除（审计面）",
        "login_impact": "登录拒绝写审计", "billing_impact": "none",
        "bi_impact": "none", "browser_surface": "仅审计/测试中心"},
}

_SPECIFIC_LIFECYCLE = {
    "iam_principal_v1": {
        "uat_creatable": "yes（受信 test_run 路径）",
        "provenance": "data_scope/test_run_id/origin/visibility 列",
        "archive_rule": "Test Run 归档同事务：disabled+history",
        "login_impact": "归档身份拒绝登录（IDENTITY_ARCHIVED）",
        "billing_impact": "none", "bi_impact": "none",
        "browser_surface": "运营账号页默认排除 fixture"},
    "iam_membership_v1": {
        "uat_creatable": "yes（继承 principal provenance）",
        "provenance": "data_scope/test_run_id/visibility 列",
        "archive_rule": "Test Run 归档同事务：visibility=history",
        "login_impact": "归档 membership 不参与授权/权限矩阵",
        "billing_impact": "none", "bi_impact": "none",
        "browser_surface": "运营授权页默认排除 fixture"},
    "auth_sessions": {
        "uat_creatable": "runtime", "provenance": "actor 关联",
        "archive_rule": "Test Run 归档时全部注销（安全失效）",
        "login_impact": "会话失效后不得继续鉴权",
        "billing_impact": "none", "bi_impact": "none",
        "browser_surface": "不暴露"},
    "bi_metric_v1": {
        "uat_creatable": "yes（受信 test_run 路径）",
        "provenance": "data_scope/test_run_id/status/created_by 列",
        "archive_rule": "Test Run 归档：status=archived",
        "login_impact": "none",
        "billing_impact": "none",
        "bi_impact": "不进运营指标目录/看板/异常规则/Agent 分析",
        "browser_surface": "运营 BI 页默认排除 fixture"},
    "bi_dashboard_v1": {
        "uat_creatable": "yes（受信 test_run 路径）",
        "provenance": "data_scope/test_run_id 列",
        "archive_rule": "archive_namespace 按 test_run_id 归档",
        "login_impact": "none", "billing_impact": "none",
        "bi_impact": "不进运营看板列表",
        "browser_surface": "运营 BI 页默认排除 fixture"},
    "import_batch_v1": {
        "uat_creatable": "yes",
        "provenance": "data_scope/test_run_id 列（迁移 058）",
        "archive_rule": "archive_namespace 按 test_run_id 归档",
        "login_impact": "none",
        "billing_impact": "none",
        "bi_impact": "data-products effective 计数",
        "browser_surface": "运营导入页默认排除 fixture"},
    "fin_rate_card_v1": {
        "uat_creatable": "restricted（平台配置）",
        "provenance": "created_by/audit",
        "archive_rule": "UAT 创建的价目卡不得参与运营计费",
        "login_impact": "none",
        "billing_impact": "计费必须只用 operational 价目卡",
        "bi_impact": "none", "browser_surface": "财务页"},
    "agent_definition_v1": {
        "uat_creatable": "restricted（平台种子）",
        "provenance": "created_by",
        "archive_rule": "UAT 不得创建持久 Agent 定义",
        "login_impact": "none", "billing_impact": "none",
        "bi_impact": "Agent BI 工具继承调用方 scope",
        "browser_surface": "Agent 中心"},
    "platform_flag": {
        "uat_creatable": "restricted（平台配置）",
        "provenance": "创建审计",
        "archive_rule": "UAT 创建的特性开关不得参与运营执行",
        "login_impact": "none", "billing_impact": "none",
        "bi_impact": "none", "browser_surface": "系统管理"},
}

for _t, _e in SCOPE_REGISTRY.items():
    _base = dict(_DEFAULT_LIFECYCLE_BY_CATEGORY[_e["category"]])
    _base.update(_SPECIFIC_LIFECYCLE.get(_t, {}))
    for _k, _v in _base.items():
        _e.setdefault(_k, _v)


def registry_coverage(conn) -> dict[str, Any]:
    """覆盖率对账：sqlite_master 全表必须 100% 登记（剔除 sqlite_*
    内部表）；返回 missing/unknown/coverage。fail-fast（异常上抛）。"""
    # sqlite_sequence 仅在 autoincrement 触发后存在，属系统可选表。
    optional = {"sqlite_sequence"}
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name"
        " NOT LIKE 'sqlite_%'").fetchall()}
    registered = set(SCOPE_REGISTRY) - optional
    missing = sorted(tables - registered)
    unknown = sorted(registered - tables)
    total = len(tables)
    covered = len(tables & registered)
    return {"missing": missing, "unknown": unknown,
            "total_tables": total, "covered": covered,
            "coverage": (round(covered / total * 100, 2)
                         if total else 100.0)}
