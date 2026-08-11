"""ABOSV3 T4：真实 Agent Runtime（工具循环 + 版本化定义 + health probe）。

设计（02-WORKFLOW-AGENT-RUNTIME-DECISION.md §4-6）：
- Agent 是版本化实体：soul（长期身份/价值边界）与 system prompt
  （具体指令）分栏；工具 allowlist、预算、审批、记忆 ACL 随定义版本化；
- 工具目录有界（bounded tool catalog）：只读工具直接执行；
  低风险写（draft 创建）执行并留痕；高风险写生成 Command Preview
  待人工批准；不存在 allowlist 之外的工具；
- 每次 invoke 写 agent_run_v1 + EventEnvelope + Usage + Evidence；
- health 是有界探针（定义已发布 + 事实查询可执行），不是
  "Manifest 存在即健康"；
- LLM Provider SPI：本地/远端 LLM 不可用时明确
  degraded_rules_fallback，不伪装智能规划成功。
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any

HIGH_RISK_TOOLS = frozenset({"recognition.create.preview",
                             "production.switch"})

_SEVEN_AGENTS = {
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


def _new_id(prefix: str) -> str:
    return f"{prefix}-" + uuid.uuid4().hex[:12]


class AgentRuntimeError(Exception):
    pass


class AgentRuntime:
    def __init__(self, store: Any, *, workflow=None, analytics=None,
                 gateway=None, iam=None) -> None:
        self.store = store
        self.workflow = workflow
        self.analytics = analytics
        self.gateway = gateway
        self.iam = iam
        self._seed_definitions()

    # ---------- 版本化定义 ----------

    def _seed_definitions(self) -> None:
        conn = self.store._conn
        for aid, cfg in _SEVEN_AGENTS.items():
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

    def get_definition(self, agent_id: str,
                       version: int | None = None) -> dict | None:
        if version is None:
            row = self.store._conn.execute(
                "SELECT * FROM agent_definition_v1 WHERE agent_id=?"
                " ORDER BY version DESC LIMIT 1", (agent_id,)).fetchone()
        else:
            row = self.store._conn.execute(
                "SELECT * FROM agent_definition_v1 WHERE agent_id=?"
                " AND version=?", (agent_id, version)).fetchone()
        return self._def_to_dict(row) if row else None

    def get_published_definition(self, agent_id: str) -> dict | None:
        row = self.store._conn.execute(
            "SELECT * FROM agent_definition_v1 WHERE agent_id=?"
            " AND status='published' ORDER BY version DESC LIMIT 1",
            (agent_id,)).fetchone()
        return self._def_to_dict(row) if row else None

    @staticmethod
    def _def_to_dict(row) -> dict:
        d = dict(row)
        d["soul"] = json.loads(d["soul_json"])
        d["budget"] = json.loads(d["budget_json"])
        d["approval"] = json.loads(d["approval_json"])
        d["tool_allowlist"] = json.loads(d["tool_allowlist_json"])
        d["memory_acl"] = json.loads(d["memory_acl_json"])
        return d

    def list_definitions(self) -> list[dict]:
        rows = self.store._conn.execute(
            "SELECT agent_id, max(version) v FROM agent_definition_v1"
            " GROUP BY agent_id ORDER BY agent_id").fetchall()
        return [self.get_definition(r["agent_id"], r["v"]) for r in rows]

    def save_draft(self, agent_id: str, *, actor: str,
                   soul: dict | None = None, system_prompt: str | None = None,
                   tool_allowlist: list | None = None,
                   budget: dict | None = None,
                   approval: dict | None = None,
                   provider: str | None = None,
                   model: str | None = None) -> dict:
        """编辑只生成 draft；发布/回滚走 lifecycle。"""
        cur = self.get_definition(agent_id)
        if cur is None and agent_id not in _SEVEN_AGENTS:
            raise AgentRuntimeError(f"未知 Agent: {agent_id}")
        base = cur or {"version": 0, "soul": {}, "system_prompt": "",
                       "tool_allowlist": [], "budget": {}, "approval": {},
                       "provider": "rules_tool_loop", "model": ""}
        version = base["version"] + 1
        self.store._conn.execute(
            "INSERT INTO agent_definition_v1 (agent_id, version, status,"
            " soul_json, system_prompt, provider, model, budget_json,"
            " approval_json, tool_allowlist_json, memory_acl_json,"
            " created_by, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (agent_id, version, "draft",
             json.dumps(soul if soul is not None else base["soul"],
                        ensure_ascii=False),
             system_prompt if system_prompt is not None
             else base["system_prompt"],
             provider or base["provider"], model or base["model"],
             json.dumps(budget if budget is not None else base["budget"]),
             json.dumps(approval if approval is not None
                        else base["approval"]),
             json.dumps(tool_allowlist if tool_allowlist is not None
                        else base["tool_allowlist"]),
             json.dumps(base.get("memory_acl", {})),
             actor, _now(), _now()))
        self.store._conn.commit()
        return self.get_definition(agent_id, version)

    def publish(self, agent_id: str, version: int, *, actor: str) -> dict:
        d = self.get_definition(agent_id, version)
        if d is None:
            raise AgentRuntimeError("定义不存在")
        if d["status"] != "draft":
            raise AgentRuntimeError("只有 draft 可发布")
        conn = self.store._conn
        # 旧 published 版本降为 superseded（可回滚）
        conn.execute(
            "UPDATE agent_definition_v1 SET status='superseded'"
            " WHERE agent_id=? AND status='published'", (agent_id,))
        conn.execute(
            "UPDATE agent_definition_v1 SET status='published',"
            " updated_at=? WHERE agent_id=? AND version=?",
            (_now(), agent_id, version))
        conn.commit()
        self._audit(actor, "agent.definition.published",
                    f"{agent_id}@v{version}")
        return self.get_definition(agent_id, version)

    def rollback(self, agent_id: str, *, actor: str) -> dict:
        """回滚：把最近的 superseded 版本重新发布，现行版本降为 draft。"""
        conn = self.store._conn
        old = conn.execute(
            "SELECT version FROM agent_definition_v1 WHERE agent_id=?"
            " AND status='superseded' ORDER BY version DESC LIMIT 1",
            (agent_id,)).fetchone()
        cur = conn.execute(
            "SELECT version FROM agent_definition_v1 WHERE agent_id=?"
            " AND status='published' ORDER BY version DESC LIMIT 1",
            (agent_id,)).fetchone()
        if old is None:
            raise AgentRuntimeError("没有可回滚的历史版本")
        if cur is not None:
            conn.execute(
                "UPDATE agent_definition_v1 SET status='draft'"
                " WHERE agent_id=? AND version=?",
                (agent_id, cur["version"]))
        conn.execute(
            "UPDATE agent_definition_v1 SET status='published'"
            " WHERE agent_id=? AND version=?",
            (agent_id, old["version"]))
        conn.commit()
        self._audit(actor, "agent.definition.rollback",
                    f"{agent_id}→v{old['version']}")
        return self.get_definition(agent_id, old["version"])

    def _audit(self, actor: str, action: str, resource: str) -> None:
        try:
            self.store._conn.execute(
                "INSERT INTO iam_audit_event_v1 (occurred_at, actor_id,"
                " action, resource, detail_json, customer_id)"
                " VALUES (?,?,?,?,?,?)",
                (_now(), actor, action, resource, "{}", ""))
            self.store._conn.commit()
        except Exception:
            pass

    # ---------- 有界工具目录 ----------

    def tool_catalog(self, agent_id: str) -> list[dict]:
        d = self.get_published_definition(agent_id) or self.get_definition(
            agent_id)
        allow = d["tool_allowlist"] if d else []
        out = []
        for tid, meta in TOOL_META.items():
            if tid in allow:
                out.append({"tool_id": tid, **meta})
        return out

    def _exec_tool(self, tool_id: str, params: dict, *,
                   actor: str, customer_id: str) -> dict:
        conn = self.store._conn
        if tool_id == "work.progress.query":
            proj = self.store.rebuild_work_projection()
            by_status: dict[str, int] = {}
            for it in proj["items"]:
                by_status[it["status"]] = by_status.get(
                    it["status"], 0) + 1
            return {"work_total": len(proj["items"]),
                    "by_status": by_status,
                    "top": [{"title": i.get("title"),
                             "status": i["status"]}
                            for i in proj["items"][:5]]}
        if tool_id == "master.skus.summary":
            rows = conn.execute(
                "SELECT count(*) c FROM md_sku_v1").fetchall()
            total = rows[0]["c"]
            per_cust = conn.execute(
                "SELECT customer_id, count(*) c FROM md_project_v1"
                " GROUP BY customer_id").fetchall()
            fewest = None
            custs = conn.execute(
                "SELECT customer_id FROM md_customer_v1").fetchall()
            counts = {c["customer_id"]: 0 for c in custs}
            # SKU 是客户级主数据（本轮无 customer 列）：以项目数辅助
            for r in per_cust:
                counts.setdefault(r["customer_id"], 0)
            if counts:
                fewest = sorted(counts.items(), key=lambda x: x[1])[0]
            return {"sku_total": total,
                    "fewest_customer": ({"customer_id": fewest[0],
                                         "project_count": fewest[1]}
                                        if fewest else None)}
        if tool_id == "master.data.summary":
            def _c(table: str) -> int:
                try:
                    return conn.execute(
                        f"SELECT count(*) c FROM {table}"
                        ).fetchone()["c"]
                except Exception:
                    return 0
            return {"customers": _c("md_customer_v1"),
                    "projects": _c("md_project_v1"),
                    "skus": _c("md_sku_v1"),
                    "addresses": _c("geo_address_v1"),
                    "employees": _c("geo_employee_v1")}
        if tool_id == "survey.list":
            rows = conn.execute(
                "SELECT survey_id, name, status, version FROM"
                " survey_definition_v1 ORDER BY created_at DESC"
                " LIMIT 10").fetchall()
            return {"surveys": [dict(r) for r in rows],
                    "ui_intent": {"kind": "navigate",
                                  "target": "/survey/design"}}
        if tool_id == "survey.responses.summary":
            rows = conn.execute(
                "SELECT status, count(*) c FROM survey_response_v1"
                " GROUP BY status").fetchall()
            return {r["status"]: r["c"] for r in rows}
        if tool_id == "geo.addresses.missing_coords":
            rows = conn.execute(
                "SELECT address_id, customer_id, raw, status FROM"
                " geo_address_v1 WHERE status != 'confirmed'"
                " ORDER BY created_at DESC LIMIT 20").fetchall()
            return {"missing": [dict(r) for r in rows],
                    "count": len(rows),
                    "ui_intent": {"kind": "navigate",
                                  "target": "/geo/addresses"}}
        if tool_id == "geo.tasks.summary":
            rows = conn.execute(
                "SELECT status, count(*) c FROM field_task_v1"
                " GROUP BY status").fetchall()
            return {r["status"]: r["c"] for r in rows}
        if tool_id == "usage.query":
            where, params_q = "", []
            if customer_id:
                where, params_q = "WHERE customer_id=?", [customer_id]
            rows = conn.execute(
                f"SELECT unit, sum(quantity) q, count(*) n FROM"
                f" usage_event_v2 {where} GROUP BY unit",
                params_q).fetchall()
            return {"customer_id": customer_id or "*",
                    "by_unit": [{"unit": r["unit"],
                                 "quantity": r["q"], "events": r["n"]}
                                for r in rows],
                    "ui_intent": {"kind": "navigate",
                                  "target": "/finance/invoices"}}
        if tool_id == "modelops.artifacts.query":
            rows = conn.execute(
                "SELECT artifact_id, candidate_status, blocker FROM"
                " model_artifact_registry_v1").fetchall()
            return {"artifacts": [dict(r) for r in rows]}
        if tool_id == "analytics.metrics.list":
            rows = conn.execute(
                "SELECT metric_id, name FROM bi_metric_v1").fetchall()
            return {"metrics": [dict(r) for r in rows]}
        if tool_id == "kb.search":
            kw = str(params.get("query", "")).strip()
            rows = conn.execute(
                "SELECT asset_id, name, substr(content, 1, 160) snippet"
                " FROM agent_asset_v1 WHERE kind='kb' AND"
                " status='published'").fetchall()

            def hit(r) -> bool:
                if not kw:
                    return True
                # 双向子串：意图句包含文档名，或文档名/内容包含关键词
                return (kw in r["name"] or r["name"] in kw
                        or kw in r["snippet"]
                        or any(w in r["name"] or w in r["snippet"]
                               for w in kw.replace("：", " ").split()
                               if len(w) >= 2))

            return {"hits": [dict(r) for r in rows if hit(r)][:5]}
        # ---- 写工具 ----
        if tool_id == "workflow.draft.create":
            if self.workflow is None:
                raise AgentRuntimeError("Workflow 服务未装配")
            name = str(params.get("name") or "Agent 草稿工作流")[:40]
            spec = {"trigger": {"type": "manual"}, "variables": {},
                    "nodes": [{"id": "start", "type": "trigger"},
                              {"id": "end", "type": "end"}],
                    "edges": [{"from": "start", "to": "end"}],
                    "policy": {"approval_required_for_publish": True}}
            d = self.workflow.create_draft(name=name, spec=spec,
                                           actor=actor)
            return {"draft_definition_id": d["definition_id"],
                    "status": d["status"],
                    "note": "仅 draft；发布必须人工批准",
                    "ui_intent": {"kind": "navigate",
                                  "target": "/workflow/studio"}}
        if tool_id == "analytics.report.draft":
            if self.analytics is None:
                raise AgentRuntimeError("Analytics 服务未装配")
            metrics = params.get("metrics") or ["recognition.tasks"]
            draft = self.analytics.create_report_spec(
                name=str(params.get("name") or "Agent 草稿报表")[:40],
                metrics=metrics,
                customer_id=customer_id or "local", actor=actor,
                note="Agent 生成 draft；发布必须人工批准")
            return {"draft_spec_id": draft["spec_id"],
                    "status": draft["status"],
                    "ui_intent": {"kind": "navigate",
                                  "target": "/analytics/reports"}}
        if tool_id == "recognition.create.preview":
            return {"requires_approval": True,
                    "command": {"kind": "vision.recognition.create",
                                "params": {
                                    "recognition_profile_id":
                                    params.get("recognition_profile_id",
                                               "production_legacy"),
                                    "service_tier": "standard",
                                    "source": "agent"},
                                "impact": "创建识别任务并计量",
                                "cost_estimate":
                                "recognition_photo + model_compute_ms",
                                "rollback": "任务留痕，不删除历史"}}
        raise AgentRuntimeError(f"未注册的工具: {tool_id}（fail-closed）")

    # ---------- invoke：真实工具循环 ----------

    def invoke(self, agent_id: str, text: str, *, actor: str,
               session_id: str = "", customer_id: str = "",
               project_id: str = "") -> dict:
        d = self.get_published_definition(agent_id)
        degraded = False
        if d is None:
            d = self.get_definition(agent_id)
            degraded = True
        if d is None:
            raise AgentRuntimeError(f"Agent 无定义（拒绝运行）: {agent_id}")
        run_id = _new_id("arun")
        t0 = time.time()
        self.store._conn.execute(
            "INSERT INTO agent_run_v1 (run_id, agent_id, session_id,"
            " intent, status, actor, customer_id, project_id, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (run_id, agent_id, session_id, text[:400], "running",
             actor, customer_id, project_id, _now()))
        self.store._conn.commit()

        tools = self._plan(d, text)
        trace: list[dict] = []
        resp: dict[str, Any] = {
            "agent": agent_id, "run_id": run_id,
            "provider": d["provider"],
            "degraded": degraded,
            "message": "", "evidence_refs": [], "ui_intents": [],
            "command_previews": [], "delegations": [],
            "memory_updates": [], "tool_trace": trace,
            "requires_approval": False,
            "trace_id": "tr-" + uuid.uuid4().hex[:12]}
        allow = set(d["tool_allowlist"])
        max_calls = int(d["budget"].get("max_tool_calls_per_turn", 4))
        summaries: list[str] = []
        for tool_id, params in tools[:max_calls]:
            if tool_id not in allow:
                trace.append({"tool": tool_id, "status": "denied",
                              "reason": "不在 allowlist（fail-closed）"})
                continue
            try:
                out = self._exec_tool(tool_id, params, actor=actor,
                                      customer_id=customer_id)
                trace.append({"tool": tool_id, "status": "ok",
                              "elapsed_ms": round(
                                  (time.time() - t0) * 1000, 1)})
                kind = TOOL_META.get(tool_id, {}).get("kind")
                if kind == "write_approval":
                    cmd = out.get("command") or {}
                    cmd_id = "cmd-" + uuid.uuid4().hex[:8]
                    self.store._conn.execute(
                        "INSERT INTO agent_command_v1 (command_id,"
                        " kind, params_json, status, created_by,"
                        " created_at) VALUES (?,?,?,?,?,?)",
                        (cmd_id, cmd.get("kind", ""),
                         json.dumps(cmd.get("params", {})),
                         "pending_approval", actor, _now()))
                    self.store._conn.commit()
                    resp["command_previews"].append({
                        "command_id": cmd_id, **cmd,
                        "idempotency_key": "agent-" + uuid.uuid4().hex[:8],
                        "status": "pending_approval"})
                    resp["requires_approval"] = True
                    summaries.append(f"已生成待批准命令 {cmd_id}")
                else:
                    if kind == "write_draft":
                        summaries.append(
                            f"{tool_id} 已创建 draft"
                            f"（{json.dumps({k: v for k, v in out.items() if k in ('draft_definition_id', 'draft_spec_id')}, ensure_ascii=False)}）")
                    else:
                        summaries.append(
                            f"{tool_id}：" + json.dumps(
                                out, ensure_ascii=False)[:220])
                    ui = out.get("ui_intent")
                    if ui:
                        resp["ui_intents"].append(ui)
                resp["evidence_refs"].append(
                    {"kind": "tool", "ref": f"{tool_id}@{run_id}"})
            except Exception as e:
                trace.append({"tool": tool_id, "status": "error",
                              "error": str(e)[:200]})
                summaries.append(f"{tool_id} 失败：{str(e)[:120]}")

        if not tools:
            resp["message"] = (
                f"（{agent_id}）未匹配到 allowlist 内的工具意图。"
                "可用工具：" + "、".join(allow) if allow else
                "该 Agent 暂无工具。")
        else:
            resp["message"] = "\n".join(summaries)
        if degraded:
            resp["provider"] = "degraded_rules_fallback"
            resp["message"] = ("（定义未发布，降级运行）" + resp["message"])

        # LLM 合成（可选）：不可用时诚实保持规则输出
        llm = self._llm_compose(d, text, resp["message"])
        if llm:
            resp["message"] = llm
            resp["provider"] = "llm+tool_loop"

        # 写 Run/Event/Evidence/Usage
        self.store._conn.execute(
            "UPDATE agent_run_v1 SET status='succeeded',"
            " tool_trace_json=?, provider=?, ended_at=?"
            " WHERE run_id=?",
            (json.dumps(trace, ensure_ascii=False), resp["provider"],
             _now(), run_id))
        self.store._conn.commit()
        try:
            self.store.emit_event(
                event_id=_new_id("evt"), event_type="agent.invoked",
                actor_type="agent", actor_id=agent_id,
                subject_type="agent_run", subject_id=run_id,
                payload={"intent": text[:200],
                         "tools": [t[0] for t in tools]})
            self.store.insert_usage_event_v2(
                usage_id=_new_id("usage"), unit="agent_call",
                quantity=1, capability=f"agent.{agent_id}.invoke",
                customer_id=customer_id, project_id=project_id,
                source_evidence=f"agent_run:{run_id}")
            self.store.insert_evidence_bundle(
                evidence_id=_new_id("evid"), kind="agent_run",
                source_uri=f"agent_run:{run_id}",
                content_type="application/json",
                producer=f"agent:{agent_id}",
                config_version=f"def@v{d['version']}")
        except Exception:
            pass
        return resp

    def _plan(self, definition: dict, text: str
              ) -> list[tuple[str, dict]]:
        """有界规划：按关键词把意图映射到 allowlist 工具。
        （LLM 可用时由 _llm_compose 润色；工具选择本身是确定性的，
        保证 allowlist 之外永不执行。）"""
        t = text
        plans: list[tuple[str, dict]] = []
        rules = (
            (("进度", "做到哪", "项目状态"), "work.progress.query", {}),
            (("SKU", "sku", "最少"), "master.skus.summary", {}),
            (("主数据", "客户数", "数据质量"), "master.data.summary", {}),
            (("问卷", "survey"), "survey.list", {}),
            (("响应", "填写"), "survey.responses.summary", {}),
            (("坐标", "地理编码", "缺坐标"), "geo.addresses.missing_coords",
             {}),
            (("外勤任务", "到店"), "geo.tasks.summary", {}),
            (("usage", "Usage", "用量", "花了多少"), "usage.query", {}),
            (("候选", "制品", "模型状态"), "modelops.artifacts.query", {}),
            (("指标",), "analytics.metrics.list", {}),
            (("知识", "文档", "手册"), "kb.search",
             {"query": t[:40]}),
            (("工作流", "workflow", "流程"), "workflow.draft.create",
             {"name": "Agent 草稿：" + t[:20]}),
            (("报表", "BI", "仪表盘"), "analytics.report.draft",
             {"name": "Agent 草稿：" + t[:20]}),
            (("识别", "recognize"), "recognition.create.preview", {}),
        )
        allow = set(definition["tool_allowlist"])
        for kws, tool_id, params in rules:
            if tool_id not in allow:
                continue
            if any(k in t for k in kws):
                plans.append((tool_id, dict(params)))
        return plans

    def _llm_compose(self, definition: dict, text: str,
                     tool_output: str) -> str | None:
        """Provider SPI：LLM 只用于把工具结果合成自然语言；
        失败/未配置 → None（保持规则输出，诚实降级）。"""
        import os
        key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not key or not tool_output:
            return None
        import urllib.request
        body = {"model": os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
                "messages": [
                    {"role": "system",
                     "content": definition["system_prompt"]
                     + "\nSoul: " + json.dumps(definition["soul"],
                                                ensure_ascii=False)
                     + "\n只基于下面的工具事实回答，不编造。"},
                    {"role": "user",
                     "content": f"用户：{text}\n工具事实：{tool_output}"}],
                "temperature": 0.3}
        req = urllib.request.Request(
            "https://api.deepseek.com/chat/completions",
            data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(
                    r.read())["choices"][0]["message"]["content"]
        except Exception:
            return None

    # ---------- health：有界探针 ----------

    def health(self, agent_id: str) -> dict:
        checks: list[dict] = []
        d = self.get_published_definition(agent_id)
        if d is None:
            checks.append({"check": "definition_published", "ok": False,
                           "reason": "无已发布定义"})
            return {"agent": agent_id, "healthy": False,
                    "status": "unhealthy", "checks": checks}
        checks.append({"check": "definition_published", "ok": True,
                       "version": d["version"]})
        # 探针 1：事实查询可执行（有界：只读 + 快速）
        t0 = time.time()
        try:
            self._exec_tool("work.progress.query", {}, actor="health",
                            customer_id="")
            checks.append({"check": "fact_query", "ok": True,
                           "elapsed_ms": round(
                               (time.time() - t0) * 1000, 1)})
        except Exception as e:
            checks.append({"check": "fact_query", "ok": False,
                           "reason": str(e)[:120]})
        # 探针 2：allowlist 工具均在目录内
        unknown = [t for t in d["tool_allowlist"] if t not in TOOL_META]
        checks.append({"check": "tool_allowlist_valid",
                       "ok": not unknown, "unknown": unknown})
        healthy = all(c["ok"] for c in checks)
        return {"agent": agent_id, "healthy": healthy,
                "status": "healthy" if healthy else "degraded",
                "definition_version": d["version"], "checks": checks}

    # ---------- 资产（Skill/Prompt/KB）与记忆 ----------

    def save_asset(self, *, kind: str, name: str, content: str,
                   actor: str, asset_id: str | None = None,
                   customer_id: str = "", meta: dict | None = None
                   ) -> dict:
        if kind not in ("skill", "prompt", "kb"):
            raise AgentRuntimeError(f"资产类型不支持: {kind}")
        aid = asset_id or _new_id(kind)
        row = self.store._conn.execute(
            "SELECT max(version) v FROM agent_asset_v1 WHERE asset_id=?",
            (aid,)).fetchone()
        version = (row["v"] or 0) + 1
        self.store._conn.execute(
            "INSERT INTO agent_asset_v1 (asset_id, version, kind, name,"
            " content, meta_json, status, customer_id, created_by,"
            " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (aid, version, kind, name, content,
             json.dumps(meta or {}, ensure_ascii=False), "draft",
             customer_id, actor, _now(), _now()))
        self.store._conn.commit()
        return self.get_asset(aid, version)

    def get_asset(self, asset_id: str,
                  version: int | None = None) -> dict | None:
        if version is None:
            row = self.store._conn.execute(
                "SELECT * FROM agent_asset_v1 WHERE asset_id=?"
                " ORDER BY version DESC LIMIT 1", (asset_id,)).fetchone()
        else:
            row = self.store._conn.execute(
                "SELECT * FROM agent_asset_v1 WHERE asset_id=? AND"
                " version=?", (asset_id, version)).fetchone()
        return dict(row) if row else None

    def list_assets(self, *, kind: str = "") -> list[dict]:
        if kind:
            rows = self.store._conn.execute(
                "SELECT asset_id, max(version) v FROM agent_asset_v1"
                " WHERE kind=? GROUP BY asset_id", (kind,)).fetchall()
        else:
            rows = self.store._conn.execute(
                "SELECT asset_id, max(version) v FROM agent_asset_v1"
                " GROUP BY asset_id").fetchall()
        return [self.get_asset(r["asset_id"], r["v"]) for r in rows]

    def publish_asset(self, asset_id: str, *, actor: str) -> dict:
        a = self.get_asset(asset_id)
        if a is None:
            raise AgentRuntimeError("资产不存在")
        if a["status"] != "draft":
            raise AgentRuntimeError("只有 draft 可发布")
        self.store._conn.execute(
            "UPDATE agent_asset_v1 SET status='published', updated_at=?"
            " WHERE asset_id=? AND version=?",
            (_now(), asset_id, a["version"]))
        self.store._conn.commit()
        self._audit(actor, f"agent.{a['kind']}.published",
                    f"{asset_id}@v{a['version']}")
        return self.get_asset(asset_id, a["version"])

    def remember(self, *, agent_id: str, content: str, level: str = "L1",
                 actor: str, acl: dict | None = None,
                 supersedes: str | None = None) -> dict:
        if level not in ("L0", "L1", "L2", "L3", "L4"):
            raise AgentRuntimeError("记忆层级必须为 L0-L4")
        mid = _new_id("mem")
        self.store._conn.execute(
            "INSERT INTO agent_memory_v1 (memory_id, agent_id, level,"
            " content, acl_json, supersedes, created_by, created_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (mid, agent_id, level, content,
             json.dumps(acl or {}, ensure_ascii=False), supersedes,
             actor, _now()))
        self.store._conn.commit()
        return {"memory_id": mid, "level": level}

    def list_memories(self, agent_id: str, *,
                      include_cleared: bool = False) -> list[dict]:
        where = "WHERE agent_id=?"
        if not include_cleared:
            where += " AND status='active'"
        rows = self.store._conn.execute(
            f"SELECT * FROM agent_memory_v1 {where}"
            " ORDER BY created_at DESC LIMIT 200",
            (agent_id,)).fetchall()
        return [dict(r) for r in rows]

    def clear_memory(self, memory_id: str, *, actor: str) -> None:
        """人工清除记忆（ACL 控制；留痕不物理删除内容行的事实）。"""
        n = self.store._conn.execute(
            "UPDATE agent_memory_v1 SET status='cleared'"
            " WHERE memory_id=?", (memory_id,))
        if n.rowcount != 1:
            raise AgentRuntimeError("记忆不存在")
        self.store._conn.commit()
        self._audit(actor, "agent.memory.cleared", memory_id)


# 工具元数据（kind: read / write_draft / write_approval）
TOOL_META: dict[str, dict] = {
    "work.progress.query": {"kind": "read",
                            "description": "查询当前工作投影与进度"},
    "master.skus.summary": {"kind": "read",
                            "description": "SKU 汇总与最少 SKU 客户"},
    "master.data.summary": {"kind": "read",
                            "description": "主数据数量汇总"},
    "survey.list": {"kind": "read", "description": "问卷定义列表"},
    "survey.responses.summary": {"kind": "read",
                                 "description": "问卷响应状态汇总"},
    "geo.addresses.missing_coords": {
        "kind": "read", "description": "查询缺坐标（未确认）地址"},
    "geo.tasks.summary": {"kind": "read",
                          "description": "外勤任务状态汇总"},
    "usage.query": {"kind": "read",
                    "description": "按客户查询 Usage 用量"},
    "modelops.artifacts.query": {"kind": "read",
                                 "description": "模型制品与候选状态"},
    "analytics.metrics.list": {"kind": "read",
                               "description": "已注册指标列表"},
    "kb.search": {"kind": "read", "description": "知识库检索"},
    "workflow.draft.create": {
        "kind": "write_draft",
        "description": "创建工作流 draft（发布必须人工批准）"},
    "analytics.report.draft": {
        "kind": "write_draft",
        "description": "创建 BI 报表 draft（发布必须人工批准）"},
    "recognition.create.preview": {
        "kind": "write_approval",
        "description": "生成识别命令预览（需人工批准后执行）"},
}
