"""单一 Agent Definition 事实源（Task 3）。

AgentDefinitionVersion 是 Agent 的唯一事实源；Manifest 是只读投影
（见 manifest_projection.py）。`AGENT_SEEDS` 是原 runtime._SEVEN_AGENTS
的版本化迁移：内容不变，所有权收敛到本模块，禁止在多处复制 seed。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

AGENT_SEEDS: dict[str, dict[str, Any]] = {
    "supervisor": {
        "soul": {"identity": "主管 Agent：规划、委派、追踪、升级",
                 "values": ["不借用管理员身份", "高风险必须人工批准",
                            "诚实降级，不伪装成功"]},
        "prompt": "你是主管 Agent。优先从工具目录检索可用动作，生成有界"
                  "计划；只读工具直接执行，写入动作生成命令预览待批准；"
                  "结果写 Run/Event/Evidence/Usage。",
        "tools": ["work.progress.query", "master.skus.summary",
                  "survey.list", "geo.addresses.missing_coords",
                  "usage.query", "workflow.draft.create",
                  "analytics.report.draft", "recognition.create.preview",
                  "kb.search"],
    },
    "modelops": {
        "soul": {"identity": "ModelOps Agent：模型/制品/训练治理",
                 "values": ["生产切换必须人工批准", "弱模型不自动晋级"]},
        "prompt": "你负责模型制品与训练控制面事实查询；发布与生产切换"
                  "永远生成待批准命令。",
        "tools": ["modelops.artifacts.query", "work.progress.query"],
    },
    "data_steward": {
        "soul": {"identity": "Data Steward：主数据与数据质量 steward",
                 "values": ["主数据变更留审计", "不删除历史"]},
        "prompt": "你负责客户/项目/SKU/地址等主数据事实与数据质量查询。",
        "tools": ["master.skus.summary", "master.data.summary",
                  "geo.addresses.missing_coords"],
    },
    "survey_agent": {
        "soul": {"identity": "Survey Agent：问卷域助手",
                 "values": ["模型输出只是 suggestion，人工才是 final"]},
        "prompt": "你负责问卷定义/分配/响应事实查询与打开问卷页面。",
        "tools": ["survey.list", "survey.responses.summary"],
    },
    "analytics_agent": {
        "soul": {"identity": "Analytics Agent：BI 语义层助手",
                 "values": ["禁止任意 SQL", "发布必须人工批准"]},
        "prompt": "你把业务问题映射到已注册指标并生成报表 draft；"
                  "发布由人工批准。",
        "tools": ["analytics.report.draft", "analytics.metrics.list"],
    },
    "fieldops_agent": {
        "soul": {"identity": "FieldOps Agent：位置与外勤助手",
                 "values": ["低置信地址不自动派发",
                            "人脸比对需显式授权"]},
        "prompt": "你负责地址/坐标/任务/路线事实查询。",
        "tools": ["geo.addresses.missing_coords", "geo.tasks.summary"],
    },
    "finance_agent": {
        "soul": {"identity": "Finance Agent：Usage 与账单助手",
                 "values": ["账单只来自 immutable Usage",
                            "结算后不原地改写"]},
        "prompt": "你负责客户 Usage/账单事实查询与导出建议。",
        "tools": ["usage.query"],
    },
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentDefinitionService:
    """版本化 Agent 定义的 seed/查询服务（发布/回滚仍走 AgentRuntime
    lifecycle，避免双写路径）。"""

    def __init__(self, store: Any) -> None:
        self.store = store

    def ensure_seed_definitions(self) -> None:
        """幂等 seed：只为不存在的 agent_id 插入 v1 published 定义。"""
        conn = self.store._conn
        for aid, cfg in AGENT_SEEDS.items():
            if conn.execute(
                    "SELECT 1 FROM agent_definition_v1 WHERE agent_id=?",
                    (aid,)).fetchone():
                continue
            conn.execute(
                "INSERT INTO agent_definition_v1 (agent_id, version,"
                " status, soul_json, system_prompt, provider, model,"
                " budget_json, approval_json, tool_allowlist_json,"
                " memory_acl_json, created_by, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (aid, 1, "published",
                 json.dumps(cfg["soul"], ensure_ascii=False),
                 cfg["prompt"], "rules_tool_loop", "",
                 json.dumps({"max_tool_calls_per_turn": 4}),
                 json.dumps({"high_risk_requires_approval": True}),
                 json.dumps(cfg["tools"]),
                 json.dumps({"levels": ["L0", "L1", "L2"]}),
                 "system", _now(), _now()))
        conn.commit()

    def latest_definition(self, agent_id: str) -> dict | None:
        row = self.store._conn.execute(
            "SELECT * FROM agent_definition_v1 WHERE agent_id=?"
            " ORDER BY version DESC LIMIT 1", (agent_id,)).fetchone()
        return dict(row) if row else None

    def published_definition(self, agent_id: str) -> dict | None:
        row = self.store._conn.execute(
            "SELECT * FROM agent_definition_v1 WHERE agent_id=?"
            " AND status='published' ORDER BY version DESC LIMIT 1",
            (agent_id,)).fetchone()
        return dict(row) if row else None


def canonical_agent_report(store: Any) -> list[dict[str, Any]]:
    """12 个内置 Agent 的迁移报告（Task 3 检查项）。

    - 有 published 定义 → definition_status=published，healthy=True；
    - 仅有 draft/superseded 定义 → 该状态，healthy=False；
    - 只有 Manifest 声明 → declared（不得伪装 healthy/published）。
    """
    from .kernel import _BUILTIN

    svc = AgentDefinitionService(store)
    out: list[dict[str, Any]] = []
    for m in _BUILTIN:
        latest = svc.latest_definition(m.agent_id)
        published = (latest is not None
                     and latest["status"] == "published")
        status = (latest["status"] if latest is not None else "declared")
        manifest = store._conn.execute(
            "SELECT 1 FROM agent_manifest_v1 WHERE agent_id=?",
            (m.agent_id,)).fetchone()
        out.append({
            "agent_id": m.agent_id,
            "definition_status": status,
            "version": latest["version"] if latest else None,
            "healthy": published,
            "manifest_present": manifest is not None,
        })
    return out
