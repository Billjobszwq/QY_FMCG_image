"""ABOS T3：Module Manifest V2 唯一目录（只读投影事实源）。

平台品牌/身份 + 九个一级业务模块 + reference.echo 参考模块。
前端导航、模块目录、Agent 关联、API 前缀、权限与计费全部从本目录
投影读取；任何平行常量（App.tsx RAIL / modules_api.MODULES）均禁止。

状态语义：live=真实后端通过；beta=可运行有披露限制；planned=只有
规格和插槽；degraded=依赖异常；disabled=策略关闭。缺依赖自动投影为
degraded，不伪造 live。
"""
from __future__ import annotations

from .registry import (
    CapabilitySpec,
    ModuleManifestV2,
    ModuleRegistry,
    NavRoute,
)

# ---- 平台唯一身份（登录/标题/导航/footer/OpenAPI/Agent prompt 共用）----
PLATFORM_IDENTITY = {
    "product_name": "Agentic Business OS",
    "product_name_zh": "智能业务操作系统",
    "definition": (
        "以 Graph+Loop 为智能执行内核、以模块化 Domain Pack 为业务能力、"
        "以共享数据与证据底座为可信事实源、由主管 Agent 和领域 Agent "
        "协作完成工作的智能业务操作系统。"),
    "tagline": "Graph+Loop 驱动 · Domain Pack 可插拔 · 证据链可信",
    "short": "qy·abos",
    "environment": "local",
    "first_domain_pack": "vision（图像识别/标注/训练）",
}


def _vision() -> ModuleManifestV2:
    return ModuleManifestV2(
        module_id="vision",
        name="智能识别",
        version="1.0.0",
        domain="fmcg_vision",
        status="live",
        theme_token="blue",
        primary_route="/vision",
        navigation=(
            NavRoute(route="/vision/recognize", label="即时识别",
                     description="单图/批量/URL 识别，统一任务与证据",
                     actions=("上传照片", "URL 输入", "批量任务",
                              "选择 Profile", "导出结果")),
            NavRoute(route="/vision/tasks", label="识别任务",
                     description="统一任务历史（Web/API/Agent 同源）",
                     actions=("筛选", "查看详情", "重放幂等键")),
            NavRoute(route="/vision/annotation", label="标注与审核",
                     description="Label Studio 项目、审核队列与金标准",
                     actions=("打开项目", "审核队列", "金标准状态")),
            NavRoute(route="/vision/datasets", label="数据集",
                     description="数据资产、快照与质量门禁",
                     actions=("资产台账", "快照", "质量门禁")),
            NavRoute(route="/vision/models", label="模型与训练",
                     description="候选模型、驻留与训练治理（只读）",
                     actions=("候选状态", "模型驻留", "训练控制")),
            NavRoute(route="/vision/evidence", label="质量与证据",
                     description="质量判定、证据链与 Graph trail",
                     actions=("质量判定", "证据浏览", "Trail")),
        ),
        agents=("recognition_agent", "modelops"),
        capabilities=(
            CapabilitySpec(capability_id="legacy.recognition.v2",
                           kind="recognition",
                           description="cascade 识别（HTTP 代理 8091）"),
            CapabilitySpec(capability_id="legacy.label_studio",
                           kind="labeling",
                           description="Label Studio 代理（HTTP 8300）"),
        ),
        commands=("vision.recognition.create",),
        queries=("vision.recognition.list", "vision.profiles.list"),
        events=("vision.recognition.completed",),
        api_prefix="/api/v1/recognition",
        openapi_tag="vision",
        data_products=("vision.recognition_daily_v1",),
        permission_scopes=("vision.read", "vision.recognize",
                           "vision.annotation.review"),
        ui_slots=("workspace", "evidence_drawer"),
        feature_flags=("vision.url_input", "vision.batch"),
        dependencies=(),
        compatibility={"legacy_api": "/api/v1/recognition/*（adapter 兼容）"},
        billing_units=("recognition_call",),
        health_checks=("recognize", "label_studio"),
    )


def build_default_module_registry() -> ModuleRegistry:
    """九一级业务模块 + reference.echo；冲突 fail-closed。"""
    reg = ModuleRegistry()
    reg.register(ModuleManifestV2(
        module_id="home", name="主管工作台", version="1.0.0",
        domain="supervisor", status="live", theme_token="violet",
        primary_route="/",
        navigation=(
            NavRoute(route="/home", label="今日工作",
                     description="待办/审批/运行/异常/完成/笔记",
                     actions=("认领待办", "审批命令", "快速目标")),
        ),
        agents=("supervisor", "workbench"),
        commands=("graph.decompose", "command.preview"),
        queries=("workitems.list", "blackboard.recent"),
        api_prefix="/api/v1",
        openapi_tag="home",
        permission_scopes=("home.read",),
        ui_slots=("taskboard", "drawer"),
        billing_units=("call",),
        health_checks=(),
    ))
    reg.register(ModuleManifestV2(
        module_id="data", name="数据与资产", version="1.0.0",
        domain="data", status="live", theme_token="amber",
        primary_route="/data",
        navigation=(
            NavRoute(route="/data/assets", label="资产台账",
                     description="source_asset_inventory 真实台账",
                     actions=("筛选", "查看血缘", "导出")),
            NavRoute(route="/data/quality", label="数据质量",
                     description="质量门禁与判定",
                     actions=("门禁状态", "判定历史")),
        ),
        agents=("data_steward",),
        commands=("data.correction.propose",),
        queries=("data.lineage.query", "assets.list"),
        api_prefix="/api/v1/assets",
        openapi_tag="data",
        data_products=("data.asset_inventory_v1",),
        permission_scopes=("data.read",),
        billing_units=("query",),
        health_checks=(),
    ))
    reg.register(ModuleManifestV2(
        module_id="survey", name="调研与问卷", version="1.0.0",
        domain="survey", status="live", theme_token="cyan",
        primary_route="/survey",
        navigation=(
            NavRoute(route="/survey/design", label="问卷设计",
                     description="题型/跳题 DAG/评分规则/版本/发布",
                     actions=("创建草稿", "lint", "发布", "新版本")),
            NavRoute(route="/survey/field", label="分配与填写",
                     description="分配/作答/拍照证据/识别建议人工终审",
                     actions=("分配", "填写", "提交", "修正")),
            NavRoute(route="/survey/report", label="报表输入",
                     description="final 答案与评分聚合（BI 只读消费）",
                     actions=("查看报表",)),
        ),
        api_prefix="/api/v1/survey", openapi_tag="survey",
        data_products=("survey.responses_v1",),
        permission_scopes=("survey.read", "survey.manage"),
        billing_units=("response",),
        agents=("survey_agent",),
    ))
    reg.register(ModuleManifestV2(
        module_id="geo", name="位置与外勤", version="1.0.0",
        domain="geo_field", status="live", theme_token="emerald",
        primary_route="/geo",
        navigation=(
            NavRoute(route="/geo/addresses", label="地址与地理编码",
                     description="候选经纬度/置信度；低置信度必须人工确认",
                     actions=("添加地址", "人工确认")),
            NavRoute(route="/geo/field", label="任务与路线",
                     description="外勤任务/VRP 路线/约束/成本/派发",
                     actions=("建任务", "规划路线", "派发")),
            NavRoute(route="/geo/visit", label="围栏与到店",
                     description="围栏事件/门头必拍/差旅费；人脸默认关闭",
                     actions=("建围栏", "到店", "完成")),
        ),
        api_prefix="/api/v1/geo", openapi_tag="geo",
        data_products=("geo.store_index_v1",),
        permission_scopes=("geo.read",), billing_units=("task",),
        agents=("fieldops_agent",),
    ))
    reg.register(_vision())
    reg.register(ModuleManifestV2(
        module_id="analytics", name="分析与 BI", version="1.0.0",
        domain="analytics", status="live", theme_token="indigo",
        primary_route="/analytics",
        navigation=(
            NavRoute(route="/analytics/reports", label="报表与仪表盘",
                     description="注册制指标报表；版本化；发布须人工批准",
                     actions=("新建报表", "评估", "发布")),
            NavRoute(route="/analytics/anomalies", label="异常与追问",
                     description="异常规则→追问任务→回答→报表刷新",
                     actions=("检查异常", "回答")),
            NavRoute(route="/analytics/semantics", label="指标语义层",
                     description="Metric/维度注册表（禁任意 SQL）",
                     actions=("查看指标",)),
        ),
        api_prefix="/api/v1/analytics", openapi_tag="analytics",
        data_products=("analytics.kpi_daily_v1",),
        permission_scopes=("analytics.read",), billing_units=("query",),
        agents=("analytics_agent",),
    ))
    reg.register(ModuleManifestV2(
        module_id="workflow", name="工作流与 Agent", version="1.1.0",
        domain="workflow", status="live", theme_token="purple",
        primary_route="/workflow",
        navigation=(
            NavRoute(route="/workflow/studio", label="工作流搭建",
                     description="定义/画布/生命周期/Workflow Agent 草稿",
                     actions=("创建 draft", "lint", "模拟", "批准", "发布")),
            NavRoute(route="/workflow/templates", label="模板库",
                     description="首批贯通模板（实例化为 draft）",
                     actions=("实例化",)),
            NavRoute(route="/workflow/runs", label="运行中心",
                     description="运行/checkpoint/重试/取消/人工批准",
                     actions=("运行", "pause", "resume", "retry", "批准")),
            NavRoute(route="/workflow/approvals", label="待办与批准",
                     description="统一 current 投影的人工事项",
                     actions=("查看",)),
            NavRoute(route="/workflow/connectors", label="连接器",
                     description="n8n/Dify 边界 adapter（许可未确认则 blocked）",
                     actions=("查看状态",)),
            NavRoute(route="/workflow/agents", label="Agent 与模型",
                     description="Agent Manifest、可调用节点与健康",
                     actions=("查看 Manifest", "调用", "健康")),
            NavRoute(route="/workflow/evidence", label="证据与用量",
                     description="事件↔投影↔outbox 对账与 current 投影",
                     actions=("对账",)),
        ),
        commands=("agent.invoke",),
        queries=("runs.list", "agents.list"),
        api_prefix="/api/v1/runs", openapi_tag="workflow",
        permission_scopes=("workflow.read",), billing_units=("run",),
        health_checks=(),
        agents=("workflow_agent",),
    ))
    reg.register(ModuleManifestV2(
        module_id="iam", name="账号与权限", version="1.0.0",
        domain="iam", status="live", theme_token="teal",
        primary_route="/iam",
        navigation=(
            NavRoute(route="/iam/accounts", label="账号与角色",
                     description="用户/服务账号/Agent 身份、角色与成员作用域",
                     actions=("开设账号", "授权", "查看成员")),
            NavRoute(route="/iam/audit", label="审计与批准矩阵",
                     description="append-only 审计事件与高风险动作批准矩阵",
                     actions=("查看审计", "批准检查")),
        ),
        commands=("iam.principal.create", "iam.grant"),
        queries=("iam.principals.list", "iam.audit.list"),
        api_prefix="/api/v1/iam", openapi_tag="iam",
        permission_scopes=("iam.read", "iam.manage"),
        billing_units=(),
        agents=("iam_agent",),
    ))
    reg.register(ModuleManifestV2(
        module_id="master", name="客户与主数据", version="1.0.0",
        domain="master", status="live", theme_token="gold",
        primary_route="/master",
        navigation=(
            NavRoute(route="/master/customers", label="客户库",
                     description="客户/组织/保留策略；test fixture 显式标记",
                     actions=("新建客户", "隔离概览")),
            NavRoute(route="/master/projects", label="项目库",
                     description="项目↔客户/SKU 范围/预算",
                     actions=("新建项目",)),
            NavRoute(route="/master/skus", label="SKU 库",
                     description="别名/客户显示名/有效期/新旧包装",
                     actions=("新建 SKU", "supersede", "别名")),
        ),
        commands=("master.customer.create", "master.sku.create"),
        queries=("master.customers.list", "master.skus.list"),
        api_prefix="/api/v1/master", openapi_tag="master",
        data_products=("master.customers_v1", "master.skus_v1"),
        permission_scopes=("master.read", "master.manage"),
        billing_units=(),
    ))
    reg.register(ModuleManifestV2(
        module_id="finance", name="财务与结算", version="1.0.0",
        domain="finance", status="live", theme_token="rose",
        primary_route="/finance",
        navigation=(
            NavRoute(route="/finance/contracts", label="合同与价目卡",
                     description="contract/rate card 版本化；价格变更限平台角色",
                     actions=("新建合同", "新版本价目")),
            NavRoute(route="/finance/invoices", label="账单与结算",
                     description="仅从 immutable Usage 生成；可下钻 run/node/证据",
                     actions=("生成账单", "开票", "调整", "结算")),
        ),
        api_prefix="/api/v1/finance", openapi_tag="finance",
        data_products=("usage.cost_ledger_v1",),
        permission_scopes=("finance.read",), billing_units=("token",),
        agents=("finance_agent",),
    ))
    reg.register(ModuleManifestV2(
        module_id="system", name="系统与开发者", version="1.0.0",
        domain="system", status="live", theme_token="slate",
        primary_route="/status",
        navigation=(
            NavRoute(route="/status", label="系统状态",
                     description="服务健康、模块注册表、API 文档",
                     actions=("健康检查", "模块目录", "OpenAPI")),
        ),
        agents=("system_agent",),
        capabilities=(
            CapabilitySpec(capability_id="legacy.training.monitor",
                           kind="monitor",
                           description="训练监控只读（HTTP 8092）"),
        ),
        queries=("system.health", "modules.list"),
        api_prefix="/api/v1/platform", openapi_tag="system",
        permission_scopes=("system.read",), billing_units=("call",),
        health_checks=("monitor",),
    ))
    # reference.echo：非识别参考模块，证明内核不绑 FMCG（可注册/导航/调用）
    reg.register(ModuleManifestV2(
        module_id="reference.echo", name="参考模块 Echo", version="1.0.0",
        domain="reference", status="live", theme_token="slate",
        primary_route="/reference",
        navigation=(
            NavRoute(route="/reference/echo", label="Echo 调用",
                     description="最小非业务模块：注册/调用/卸载示例",
                     actions=("调用 echo",)),
        ),
        capabilities=(
            CapabilitySpec(capability_id="reference.echo", kind="reference",
                           description="平台通用性参考能力（echo）"),
        ),
        commands=("reference.echo",),
        api_prefix="/api/v1/reference", openapi_tag="reference",
        permission_scopes=("reference.read",), billing_units=("call",),
    ))
    return reg
