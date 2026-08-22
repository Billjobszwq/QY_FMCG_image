"""ABOSV2 Z-1：模块集成契约交叉验证（fail-closed）。

注册模块后必须在以下各处同步出现，任何一环缺失即报错：
- Manifest ↔ Agent 清单（声明的 agent 必须已注册）；
- permission_scopes ↔ IAM 版本化 scope 注册表；
- commands ↔ Command Gateway / 平台命令注册表；
- navigation routes ↔ 前端 UI 组件注册表（MODULE_ROUTES）；
- api_prefix ↔ OpenAPI 实际路径。
"""
from __future__ import annotations

from typing import Any

from .iam import SCOPES as IAM_SCOPES

# 平台已实现的命令注册表（Command Gateway + 各域写命令）。
# 模块声明的 commands 必须在此登记，否则集成报告 fail-closed。
PLATFORM_COMMANDS: dict[str, str] = {
    # Command Gateway（统一入口）
    "vision.recognition.create": "control_plane.CommandGateway",
    # Workflow
    "workflow.run": "workflow.WorkflowService.start_run",
    "workflow.publish": "workflow.WorkflowService.publish",
    # IAM
    "iam.principal.create": "iam.IAMService.create_principal",
    "iam.grant": "iam.IAMService.grant",
    # 问卷
    "survey.response.submit": "survey.SurveyService.submit",
    "survey.correction.create": "survey.SurveyService.correct_answer",
    # 外勤
    "geo.task.dispatch": "field_ops.FieldOpsService.dispatch_task",
    "geo.task.complete": "field_ops.FieldOpsService.complete_task",
    # 财务
    "finance.invoice.generate": "finance.FinanceService.generate_invoice",
    "finance.invoice.adjust": "finance.FinanceService.adjust_invoice",
    # Agent/目标
    "agent.invoke": "agents.SupervisorAgent.chat",
    "goal.draft.create": "goals.create_goal_draft",
    # 主数据
    "master.customer.create": "iam.MasterDataService.create_customer",
    "master.sku.create": "iam.MasterDataService.create_sku",
    # 参考模块
    "reference.echo": "modules.reference_echo.echo",
    # Agent 命令预览（supervisor 实际能力）
    "command.preview": "agents.SupervisorAgent.command_preview",
}

# UI 组件注册表镜像（与 web/src/platform/ui_registry.ts 的 MODULE_ROUTES
# 严格一致；由契约测试双向校验，缺失即 fail-closed）。
UI_ROUTES_MIRROR: tuple[str, ...] = (
    "/home",
    "/vision/recognize", "/vision/tasks", "/vision/annotation",
    "/vision/datasets", "/vision/evidence",
    "/models/connections", "/models/catalog", "/models/bindings",
    "/models/governance", "/models/local",
    "/data/import", "/data/assets", "/data/quality",
    "/workflow/studio", "/workflow/templates", "/workflow/runs",
    "/workflow/approvals", "/workflow/connectors", "/workflow/agents",
    "/workflow/evidence",
    "/iam/accounts", "/iam/audit",
    "/master/customers", "/master/projects", "/master/skus",
    "/survey/design", "/survey/field", "/survey/report",
    "/analytics/reports", "/analytics/anomalies", "/analytics/semantics",
    "/geo/addresses", "/geo/field", "/geo/visit",
    "/finance/contracts", "/finance/invoices",
    "/help",
    "/status", "/reference/echo",
)


def integration_report(module_registry: Any, *,
                       agent_ids: set[str],
                       ui_routes: set[str] | None = None,
                       openapi_paths: list[str],
                       gateway_commands: set[str] | None = None,
                       agent_command_schemas: set[str] | None = None,
                       ) -> dict:
    """对全部注册模块做交叉验证；返回 {ok, modules:[...]}。"""
    if ui_routes is None:
        ui_routes = set(UI_ROUTES_MIRROR)
    cmds = dict(PLATFORM_COMMANDS)
    for c in (gateway_commands or set()):
        cmds.setdefault(c, "control_plane.CommandGateway")
    for c in (agent_command_schemas or set()):
        cmds.setdefault(c, "agents.tool_registry")
    modules_out = []
    overall_ok = True
    for m in module_registry.project():
        errors: list[str] = []
        warnings: list[str] = []
        mid, status = m["module_id"], m["status"]
        # 1) agents ↔ agent 清单
        for a in m.get("agents", []):
            if a not in agent_ids:
                errors.append(f"声明的 agent 未注册: {a}")
        # 2) permission_scopes ↔ IAM scope 注册表
        for s in m.get("permission_scopes", []):
            if s not in IAM_SCOPES:
                errors.append(f"permission scope 未在 IAM 注册: {s}")
        # 3) commands ↔ 命令注册表
        for c in m.get("commands", []):
            if c not in cmds:
                errors.append(f"声明的 command 未在任何注册表登记: {c}")
        # 4) navigation routes ↔ UI 组件注册表（live 模块 fail-closed）
        for n in m.get("navigation", []):
            if status == "live" and n["route"] not in ui_routes:
                errors.append(
                    f"导航路由缺少 UI 组件注册: {n['route']}")
        # 5) api_prefix ↔ OpenAPI 实际路径
        prefix = m.get("api_prefix") or ""
        if prefix and status == "live":
            if not any(p.startswith(prefix) for p in openapi_paths):
                errors.append(f"OpenAPI 中无 {prefix} 前缀路径")
        # 6) 计费单位与健康检查（警告级）
        if status == "live" and not m.get("billing_units"):
            warnings.append("live 模块未声明 billing_units")
        if status == "live" and not m.get("health_checks"):
            warnings.append("live 模块未声明 health_checks")
        if errors:
            overall_ok = False
        modules_out.append({"module_id": mid, "status": status,
                            "errors": errors, "warnings": warnings})
    return {"ok": overall_ok, "modules": modules_out,
            "checked": {
                "agents": sorted(agent_ids),
                "ui_routes": len(ui_routes),
                "openapi_paths": len(openapi_paths),
                "platform_commands": sorted(cmds),
            }}
