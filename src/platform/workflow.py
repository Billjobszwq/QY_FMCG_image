"""ABOSV2 Phase C：Workflow Studio MVP 服务层（02 文档契约）。

- canonical WorkflowDefinition/Version/Node/Edge/Trigger/Variable/Policy；
- 生命周期 draft → linted → simulated → approved → published → deprecated；
  发布后不可原地修改（修改生成新版本）；发布必须经人工 approve；
- runtime：checkpoint、retry、pause/resume/cancel、dead-letter、
  human_approval 等待节点；
- 节点库从已注册 Capability 动态生成（fail-closed）；
- WorkflowExecutorAdapter SPI：Native 完整实现；n8n/Dify 为边界清晰的
  adapter，许可未确认前诚实标 blocked，不伪装完成。
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from .agents.supervisor import SupervisorAgent

NODE_TYPES = ("trigger", "command", "query", "condition", "transform",
              "agent", "model", "human_approval", "wait", "loop",
              "parallel", "join", "subflow", "connector", "end")

LIFECYCLE = ("draft", "linted", "simulated", "approved", "published",
             "deprecated")

# 受限 transform：只做路径取值映射，禁止任意表达式/代码
_ALLOWED_OPS = ("eq", "ne", "gt", "ge", "lt", "le", "contains")


class WorkflowError(Exception):
    """生命周期/执行错误（诚实失败）。"""


class WorkflowExecutorBlocked(Exception):
    """外部执行器不可用（许可/依赖/网络未满足），诚实 blocked。"""


def _new_id(prefix: str) -> str:
    return f"{prefix}-" + uuid.uuid4().hex[:12]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _spec_hash(spec: dict) -> str:
    """业务定义/版本/策略参与 hash；UI 坐标不参与（02 文档 §2）。"""

    def strip_ui(obj):
        if isinstance(obj, dict):
            return {k: strip_ui(v) for k, v in obj.items() if k != "ui"}
        if isinstance(obj, list):
            return [strip_ui(x) for x in obj]
        return obj

    return hashlib.sha256(json.dumps(
        strip_ui(spec), sort_keys=True, ensure_ascii=False).encode(
        )).hexdigest()


def _resolve_path(path: str, ctx: dict) -> Any:
    """受限路径解析：$vars.x / $inputs.x / $nodes.<id>.field.sub"""
    if not isinstance(path, str) or not path.startswith("$"):
        return path
    parts = path[1:].split(".")
    cur: Any = ctx
    for p in parts:
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        else:
            return None
    return cur


def _resolve_value(value: Any, ctx: dict) -> Any:
    if isinstance(value, str) and value.startswith("$"):
        return _resolve_path(value, ctx)
    if isinstance(value, dict):
        return {k: _resolve_value(v, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_value(v, ctx) for v in value]
    return value


def _compare(left: Any, op: str, right: Any) -> bool:
    if op not in _ALLOWED_OPS:
        raise WorkflowError(f"不支持的条件操作符: {op}")
    try:
        if op == "eq":
            return left == right
        if op == "ne":
            return left != right
        if op == "contains":
            return right in (left or "")
        return bool({
            "gt": lambda: left > right, "ge": lambda: left >= right,
            "lt": lambda: left < right, "le": lambda: left <= right,
        }[op]())
    except TypeError:
        return False


# ---------- Executor Adapter SPI（02 §8） ----------

class WorkflowExecutorAdapter:
    """统一执行器接口；外部引擎状态须规范化为 ABOS 状态再写事件。"""

    name = "abstract"

    def available(self) -> tuple[bool, str]:
        raise NotImplementedError

    def validate(self, definition: dict) -> list[dict]:
        raise NotImplementedError

    def start(self, run_context: dict, inputs: dict,
              idempotency_key: str | None = None) -> dict:
        raise NotImplementedError

    def pause(self, execution_ref: str) -> dict:
        raise NotImplementedError

    def resume(self, execution_ref: str) -> dict:
        raise NotImplementedError

    def cancel(self, execution_ref: str) -> dict:
        raise NotImplementedError

    def collect_usage(self, execution_ref: str) -> list[dict]:
        raise NotImplementedError

    def collect_evidence(self, execution_ref: str) -> list[dict]:
        raise NotImplementedError


class N8nWorkflowAdapter(WorkflowExecutorAdapter):
    """n8n connector executor（边界 PoC）。许可未确认前诚实 blocked：
    为客户托管 workflows/credentials 与白标嵌入涉及 n8n Enterprise/Embed
    商业许可（docs: 02-WORKFLOW-STUDIO-AND-N8N-DIFY.md §2）。"""

    name = "n8n"

    def available(self) -> tuple[bool, str]:
        return False, ("n8n 商业许可（Enterprise/Embed）未确认；"
                       "启用前必须完成许可评估与凭据隔离设计")

    def validate(self, definition: dict) -> list[dict]:
        return [{"level": "blocked", "code": "license_unverified",
                 "message": self.available()[1]}]

    def start(self, run_context: dict, inputs: dict,
              idempotency_key: str | None = None) -> dict:
        raise WorkflowExecutorBlocked(self.available()[1])

    def pause(self, execution_ref: str) -> dict:
        raise WorkflowExecutorBlocked(self.available()[1])

    def resume(self, execution_ref: str) -> dict:
        raise WorkflowExecutorBlocked(self.available()[1])

    def cancel(self, execution_ref: str) -> dict:
        raise WorkflowExecutorBlocked(self.available()[1])

    def collect_usage(self, execution_ref: str) -> list[dict]:
        return []

    def collect_evidence(self, execution_ref: str) -> list[dict]:
        return []


class DifyWorkflowAdapter(WorkflowExecutorAdapter):
    """Dify AI subflow provider（边界 PoC）。许可证对多租户与前端标识
    有额外限制，未评估前诚实 blocked（02 文档 §3）。"""

    name = "dify"

    def available(self) -> tuple[bool, str]:
        return False, ("Dify 多租户商业许可未评估；Dify 不接管身份/"
                       "权限/会话/计费，仅可作为可替换 AI 子流程")

    def validate(self, definition: dict) -> list[dict]:
        return [{"level": "blocked", "code": "license_unverified",
                 "message": self.available()[1]}]

    def start(self, run_context: dict, inputs: dict,
              idempotency_key: str | None = None) -> dict:
        raise WorkflowExecutorBlocked(self.available()[1])

    def pause(self, execution_ref: str) -> dict:
        raise WorkflowExecutorBlocked(self.available()[1])

    def resume(self, execution_ref: str) -> dict:
        raise WorkflowExecutorBlocked(self.available()[1])

    def cancel(self, execution_ref: str) -> dict:
        raise WorkflowExecutorBlocked(self.available()[1])

    def collect_usage(self, execution_ref: str) -> list[dict]:
        return []

    def collect_evidence(self, execution_ref: str) -> list[dict]:
        return []


CONNECTORS = {"n8n": N8nWorkflowAdapter(), "dify": DifyWorkflowAdapter()}

# 照片识别链首批模板（02 §9-1）
TEMPLATE_RECOGNITION_CHAIN = {
    "template_id": "tpl_recognition_chain_v1",
    "name": "照片识别链（上传→识别→低置信人工复核→入库）",
    "spec": {
        "trigger": {"type": "manual"},
        "variables": {"images": {"type": "list", "default": []},
                      "conf": {"type": "number", "default": 0.25}},
        "nodes": [
            {"id": "start", "type": "trigger"},
            {"id": "recognize", "type": "command",
             "capability": "vision.recognition.create",
             "inputs": {"images": "$vars.images", "conf": "$vars.conf",
                        "recognition_profile_id": "production_legacy",
                        "service_tier": "standard"},
             "policy": {"retry": 1}},
            {"id": "check", "type": "condition",
             "config": {"rules": [
                 {"when": {"path": "$nodes.recognize.status",
                           "op": "eq", "value": "failed"},
                  "to": "review"}],
                 "default": "end"}},
            {"id": "review", "type": "human_approval",
             "config": {"title": "识别失败/低置信人工复核"}},
            {"id": "end", "type": "end"},
        ],
        "edges": [{"from": "start", "to": "recognize"},
                  {"from": "recognize", "to": "check"},
                  {"from": "review", "to": "end"}],
        "policy": {"approval_required_for_publish": True},
    },
}
TEMPLATES = [TEMPLATE_RECOGNITION_CHAIN]


class WorkflowService:
    def __init__(self, store: Any, capability_registry: Any,
                 gateway: Any, agent_runtime: Any = None) -> None:
        self.store = store
        self.caps = capability_registry
        self.gateway = gateway
        # ABOSV3 T5：agent 节点调用指定 Agent（不再固定 Supervisor）
        self.agent_runtime = agent_runtime

    # ---------- 节点库（来自已注册 Capability，fail-closed） ----------

    def node_library(self) -> dict[str, Any]:
        commands = []
        for cap in self.caps.capabilities():
            commands.append({
                "node_type": "model",
                "capability": cap["capability_id"],
                "module": cap["module_id"],
                "kind": cap.get("kind"),
            })
        # 领域命令节点：来自 Command Gateway 已注册命令（fail-closed）
        gateway_cmds = [
            {"node_type": "command", "capability": k,
             "module": "control_plane", "kind": "domain_command"}
            for k in getattr(self.gateway, "SUPPORTED_COMMANDS", ())]
        return {"node_types": list(NODE_TYPES),
                "command_nodes": gateway_cmds + commands,
                "connectors": {
                    name: {"available": ad.available()[0],
                           "reason": ad.available()[1]}
                    for name, ad in CONNECTORS.items()},
                "templates": [{"template_id": t["template_id"],
                               "name": t["name"]} for t in TEMPLATES]}

    # ---------- 生命周期 ----------

    def create_draft(self, *, name: str, spec: dict, actor: str,
                     definition_id: str | None = None,
                     from_template: str | None = None) -> dict:
        if from_template:
            tpl = next((t for t in TEMPLATES
                        if t["template_id"] == from_template), None)
            if tpl is None:
                raise WorkflowError(f"模板不存在: {from_template}")
            spec = json.loads(json.dumps(tpl["spec"]))
            name = name or tpl["name"]
        if not name or not isinstance(spec, dict):
            raise WorkflowError("name/spec 必填")
        def_id = definition_id or "wf-" + uuid.uuid4().hex[:10]
        if self.store.get_workflow_definition(def_id) is not None:
            raise WorkflowError(f"definition 已存在: {def_id}（请用新版本）")
        return self.store.insert_workflow_definition(
            definition_id=def_id, version=1, name=name, spec=spec,
            created_by=actor)

    def update_draft(self, definition_id: str, *, spec: dict | None = None,
                     name: str | None = None, actor: str = "") -> dict:
        d = self._must(definition_id)
        if d["status"] != "draft":
            raise WorkflowError(
                f"只有 draft 可修改（当前 {d['status']}）；"
                "已发布内容必须生成新版本")
        return self.store.update_workflow_definition(
            definition_id, d["version"], spec=spec, name=name)

    def new_version(self, definition_id: str, *, actor: str) -> dict:
        latest = self._must(definition_id)
        spec = json.loads(json.dumps(latest["spec"]))
        return self.store.insert_workflow_definition(
            definition_id=definition_id, version=latest["version"] + 1,
            name=latest["name"], spec=spec, created_by=actor)

    def lint(self, definition_id: str, version: int | None = None) -> dict:
        d = self._must(definition_id, version)
        report = self._lint_spec(d["spec"])
        status = "linted" if not any(
            i["level"] == "error" for i in report) else "draft"
        updated = self.store.update_workflow_definition(
            definition_id, d["version"], lint_report=report,
            status=status if d["status"] == "draft" else None)
        return updated

    def _lint_spec(self, spec: dict) -> list[dict]:
        issues: list[dict] = []
        nodes = spec.get("nodes") or []
        ids = [n.get("id") for n in nodes]
        idset = set(ids)
        if len(ids) != len(idset):
            issues.append({"level": "error", "code": "dup_node_id",
                           "message": "节点 ID 重复"})
        types = {n.get("id"): n.get("type") for n in nodes}
        if not any(t == "trigger" for t in types.values()):
            issues.append({"level": "error", "code": "no_trigger",
                           "message": "缺少 trigger 节点"})
        if sum(1 for t in types.values() if t == "end") != 1:
            issues.append({"level": "error", "code": "end_count",
                           "message": "必须有且只有一个 end 节点"})
        for e in spec.get("edges") or []:
            if e.get("from") not in idset or e.get("to") not in idset:
                issues.append({"level": "error", "code": "edge_unknown",
                               "message": f"边引用未知节点: {e}"})
        # 可达性：从 trigger 出发
        adj: dict[str, list[str]] = {}
        for e in spec.get("edges") or []:
            adj.setdefault(e["from"], []).append(e["to"])
        trig = next((n["id"] for n in nodes if n["type"] == "trigger"), None)
        reachable: set[str] = set()
        if trig:
            stack = [trig]
            while stack:
                cur = stack.pop()
                if cur in reachable:
                    continue
                reachable.add(cur)
                for t in adj.get(cur, []):
                    stack.append(t)
                # condition 的分支与 human_approval 后继也在 edges 中
                node = next((n for n in nodes if n["id"] == cur), {})
                for r in (node.get("config") or {}).get("rules", []) or []:
                    if r.get("to") in idset:
                        stack.append(r["to"])
                if (node.get("config") or {}).get("default") in idset:
                    stack.append(node["config"]["default"])
        for i in ids:
            if i not in reachable:
                issues.append({"level": "error", "code": "unreachable",
                               "message": f"节点不可达: {i}"})
        for n in nodes:
            t = n.get("type")
            if t not in NODE_TYPES:
                issues.append({"level": "error", "code": "unknown_type",
                               "message": f"未知节点类型: {t}"})
            if t in ("command", "model"):
                cap = n.get("capability")
                registered = True
                try:
                    self.caps.get(cap)
                except Exception:
                    registered = False
                if not registered and cap not in getattr(
                        self.gateway, "SUPPORTED_COMMANDS", ()):
                    issues.append({
                        "level": "error", "code": "capability_missing",
                        "message": f"节点 {n.get('id')} 的 capability"
                                   f" 未注册（fail-closed）: {cap}"})
            if t == "transform":
                if not isinstance((n.get("config") or {}).get("map"), dict):
                    issues.append({
                        "level": "error", "code": "transform_map",
                        "message": f"transform {n.get('id')} 需要"
                                   " config.map 映射"})
            if t == "connector":
                cid = (n.get("config") or {}).get("connector_id")
                ad = CONNECTORS.get(cid)
                if ad is None:
                    issues.append({
                        "level": "error", "code": "connector_unknown",
                        "message": f"未知连接器: {cid}"})
                else:
                    ok, reason = ad.available()
                    if not ok:
                        issues.append({
                            "level": "warn", "code": "connector_blocked",
                            "message": f"连接器 {cid} 当前不可用：{reason}"})
            if t == "loop":
                cfg = n.get("config") or {}
                if not cfg.get("items_path") or not cfg.get("body"):
                    issues.append({
                        "level": "error", "code": "loop_config",
                        "message": f"loop {n.get('id')} 需要 items_path"
                                   " 与 body（循环终止必须有界）"})
            if t == "wait":
                cfg = n.get("config") or {}
                try:
                    float(cfg.get("seconds", 0) or 0)
                except (TypeError, ValueError):
                    issues.append({
                        "level": "error", "code": "wait_seconds",
                        "message": f"wait {n.get('id')} 的 seconds"
                                   " 必须为数字"})
            if t == "join":
                cfg = n.get("config") or {}
                if cfg.get("mode", "all") not in ("all", "any",
                                                    "quorum"):
                    issues.append({
                        "level": "error", "code": "join_mode",
                        "message": f"join {n.get('id')} 的 mode 必须为"
                                   " all/any/quorum"})
            if t == "subflow":
                cfg = n.get("config") or {}
                sub = (self.store.get_workflow_definition(
                    cfg.get("definition_id"), cfg.get("version"))
                    if cfg.get("definition_id") else None)
                if sub is None or sub["status"] != "published":
                    issues.append({
                        "level": "error", "code": "subflow_unpublished",
                        "message": f"subflow {n.get('id')} 引用的定义"
                                   " 不存在或未发布"})
        return issues

    def simulate(self, definition_id: str, *, inputs: dict,
                 version: int | None = None, actor: str = "") -> dict:
        d = self._must(definition_id, version)
        if d["status"] not in ("draft", "linted"):
            raise WorkflowError("只有 draft/linted 可模拟")
        report = self._lint_spec(d["spec"])
        if any(i["level"] == "error" for i in report):
            raise WorkflowError("lint 未通过，不得模拟")
        trace = self._execute(d, inputs, actor or "simulator",
                              simulate=True)
        if trace["status"] == "failed":
            raise WorkflowError(f"模拟失败：{trace.get('error')}")
        self.store.update_workflow_definition(
            definition_id, d["version"], status="simulated")
        return trace

    def approve(self, definition_id: str, *, actor: str,
                version: int | None = None) -> dict:
        d = self._must(definition_id, version)
        if d["status"] not in ("linted", "simulated"):
            raise WorkflowError(
                f"只有 linted/simulated 可批准（当前 {d['status']}）")
        return self.store.update_workflow_definition(
            definition_id, d["version"], status="approved")

    def publish(self, definition_id: str, *, actor: str,
                version: int | None = None) -> dict:
        d = self._must(definition_id, version)
        if d["status"] != "approved":
            raise WorkflowError(
                "发布必须先经人工批准（approved）；Agent/自动化不得直接发布")
        return self.store.update_workflow_definition(
            definition_id, d["version"], status="published", published=True)

    def deprecate(self, definition_id: str, *, actor: str,
                  version: int | None = None) -> dict:
        d = self._must(definition_id, version)
        return self.store.update_workflow_definition(
            definition_id, d["version"], status="deprecated")

    def _must(self, definition_id: str,
              version: int | None = None) -> dict:
        d = self.store.get_workflow_definition(definition_id, version)
        if d is None:
            raise WorkflowError(f"workflow 定义不存在: {definition_id}")
        return d

    # ---------- 运行 ----------

    def start_run(self, definition_id: str, *, inputs: dict, actor: str,
                  source: str = "web", version: int | None = None,
                  parent_run_id: str | None = None,
                  correlation_id: str | None = None) -> dict:
        d = self._must(definition_id, version)
        if d["status"] != "published":
            raise WorkflowError(
                f"只有 published 可运行（当前 {d['status']}）")
        corr = correlation_id or "corr-" + uuid.uuid4().hex[:12]
        run = self.store.insert_business_run({
            "run_id": _new_id("run"), "work_id": _new_id("work"),
            "trigger_type": d["spec"].get("trigger", {}).get(
                "type", "manual"),
            "correlation_id": corr, "parent_run_id": parent_run_id,
            "initiator_type": "human", "initiator_id": actor,
            "status": "queued", "command_kind": "workflow.run",
            "params": {"definition_id": definition_id,
                       "version": d["version"]},
            "workflow_definition_id": definition_id,
            "workflow_version": str(d["version"])})
        self.store.insert_work_item_v2({
            "work_id": run["work_id"], "run_id": run["run_id"],
            "status": "running", "owner_type": "system",
            "owner_id": "workflow_runtime",
            "title": f"工作流：{d['name']}",
            "business_summary": f"{definition_id}@v{d['version']}"})
        self.store.emit_event(
            event_id=_new_id("evt"), event_type="workflow.started",
            run_id=run["run_id"], work_id=run["work_id"],
            correlation_id=corr, actor_type="human", actor_id=actor,
            payload={"definition_id": definition_id,
                     "version": d["version"]})
        self.store.set_business_run_status(run["run_id"], "running",
                                           current_node="start")
        trace = self._execute(d, inputs, actor, run_id=run["run_id"],
                              work_id=run["work_id"], corr=corr)
        return {"run": self.store.get_business_run(run["run_id"]),
                "trace": trace}

    def approve_run(self, run_id: str, *, actor: str,
                    decision: str = "approved") -> dict:
        """人工批准等待节点 → 恢复执行（批准是节点，不是旁路）。"""
        run = self.store.get_business_run(run_id)
        if run is None:
            raise WorkflowError(f"run 不存在: {run_id}")
        if run["status"] != "waiting_human":
            raise WorkflowError(f"run 不在等待人工状态: {run['status']}")
        waiting = next((e for e in self.store.list_node_executions(run_id)
                        if e["status"] == "waiting_approval"), None)
        if waiting is None:
            raise WorkflowError("未找到等待批准的节点")
        self.store.emit_event(
            event_id=_new_id("evt"),
            event_type="human_approval.decided",
            run_id=run_id, work_id=run["work_id"],
            correlation_id=run["correlation_id"],
            actor_type="human", actor_id=actor,
            payload={"node_id": waiting["node_id"], "decision": decision})
        if decision != "approved":
            self.store.set_business_run_status(run_id, "cancelled")
            self.store.upsert_node_execution(
                run_id, waiting["node_id"], node_type="human_approval",
                status="skipped", output_data={"decision": decision})
            self.store.set_work_item_v2_status(run["work_id"], "cancelled")
            return self.store.get_business_run(run_id)
        # 恢复：从批准节点的默认后继继续
        d = self._must(run["workflow_definition_id"],
                       int(run["workflow_version"]))
        spec = d["spec"]
        adj = self._adjacency(spec)
        succ = adj.get(waiting["node_id"], [])
        self.store.upsert_node_execution(
            run_id, waiting["node_id"], node_type="human_approval",
            status="succeeded", output_data={"decision": decision})
        self.store.set_business_run_status(run_id, "running")
        ctx = self._restore_ctx(run_id, d)
        trace = self._run_nodes(d, succ, ctx, run_id=run_id,
                                work_id=run["work_id"],
                                corr=run["correlation_id"])
        return self.store.get_business_run(run_id)

    def pause_run(self, run_id: str, *, actor: str) -> dict:
        self.store.set_business_run_status(run_id, "paused")
        return self.store.get_business_run(run_id)

    def resume_run(self, run_id: str, *, actor: str) -> dict:
        run = self.store.get_business_run(run_id)
        if run is None or run["status"] != "paused":
            raise WorkflowError("run 不在 paused 状态")
        d = self._must(run["workflow_definition_id"],
                       int(run["workflow_version"]))
        pending = [e for e in self.store.list_node_executions(run_id)
                   if e["status"] == "pending"]
        self.store.set_business_run_status(run_id, "running")
        if pending:
            ctx = self._restore_ctx(run_id, d)
            self._run_nodes(d, [p["node_id"] for p in pending], ctx,
                            run_id=run_id, work_id=run["work_id"],
                            corr=run["correlation_id"])
        return self.store.get_business_run(run_id)

    def cancel_run(self, run_id: str, *, actor: str) -> dict:
        self.store.set_business_run_status(run_id, "cancelled")
        run = self.store.get_business_run(run_id)
        self.store.set_work_item_v2_status(run["work_id"], "cancelled")
        return run

    def retry_run(self, run_id: str, *, actor: str,
                  inputs: dict | None = None) -> dict:
        """失败 run 从失败节点重试（同一 run，checkpoint 续跑）。"""
        run = self.store.get_business_run(run_id)
        if run is None:
            raise WorkflowError(f"run 不存在: {run_id}")
        if run["status"] != "failed":
            raise WorkflowError(f"只有 failed 可重试: {run['status']}")
        d = self._must(run["workflow_definition_id"],
                       int(run["workflow_version"]))
        failed = [e for e in self.store.list_node_executions(run_id)
                  if e["status"] == "failed"]
        if not failed:
            raise WorkflowError("无失败节点可重试")
        self.store.emit_event(
            event_id=_new_id("evt"), event_type="workflow.retried",
            run_id=run_id, work_id=run["work_id"],
            correlation_id=run["correlation_id"],
            actor_type="human", actor_id=actor,
            payload={"nodes": [f["node_id"] for f in failed]})
        self.store.set_business_run_status(run_id, "running", error="")
        ctx = self._restore_ctx(run_id, d, extra_inputs=inputs)
        self._run_nodes(d, [f["node_id"] for f in failed], ctx,
                        run_id=run_id, work_id=run["work_id"],
                        corr=run["correlation_id"])
        return self.store.get_business_run(run_id)

    # ---------- 持久化 timer（ABOSV3 T5：重启可恢复） ----------

    def resume_due_timers(self) -> list[dict]:
        """扫描到期 pending timer 并恢复执行（启动/轮询均调用）。"""
        fired: list[dict] = []
        rows = self.store._conn.execute(
            "SELECT * FROM workflow_timer_v1 WHERE status='pending'"
            " AND fire_at <= ?", (_now_iso(),)).fetchall()
        for t in rows:
            try:
                self._fire_timer(dict(t))
                fired.append({"timer_id": t["timer_id"],
                              "run_id": t["run_id"]})
            except Exception:
                pass  # 单个 timer 失败不阻断其他
        return fired

    def _fire_timer(self, t: dict) -> None:
        run = self.store.get_business_run(t["run_id"])
        if run is None or run["status"] not in ("waiting_timer",
                                                "running"):
            # run 已取消/完成：timer 标 cancelled，不恢复
            self.store._conn.execute(
                "UPDATE workflow_timer_v1 SET status='cancelled',"
                " fired_at=? WHERE timer_id=?",
                (_now_iso(), t["timer_id"]))
            self.store._conn.commit()
            return
        self.store._conn.execute(
            "UPDATE workflow_timer_v1 SET status='fired', fired_at=?"
            " WHERE timer_id=?", (_now_iso(), t["timer_id"]))
        self.store._conn.commit()
        d = self._must(run["workflow_definition_id"],
                       int(run["workflow_version"]))
        node = next((n for n in d["spec"]["nodes"]
                     if n["id"] == t["node_id"]), None)
        self.store.upsert_node_execution(
            t["run_id"], t["node_id"], node_type="wait",
            status="succeeded",
            output_data={"waited_seconds": t["seconds"],
                         "timer_id": t["timer_id"]})
        self.store.emit_event(
            event_id=_new_id("evt"), event_type="workflow.timer_fired",
            run_id=t["run_id"], work_id=run["work_id"],
            correlation_id=run["correlation_id"],
            actor_type="system", actor_id="workflow_runtime",
            payload={"node": t["node_id"], "timer_id": t["timer_id"]})
        self.store.set_business_run_status(t["run_id"], "running")
        ctx = self._restore_ctx(t["run_id"], d)
        ctx["nodes"][t["node_id"]] = {
            "status": "succeeded",
            "waited_seconds": t["seconds"]}
        succ = [e["to"] for e in (d["spec"].get("edges") or [])
                if e["from"] == t["node_id"]]
        if node and node["type"] == "wait":
            self._run_nodes(d, succ, ctx, run_id=t["run_id"],
                            work_id=run["work_id"],
                            corr=run["correlation_id"])

    def list_timers(self, *, status: str = "") -> list[dict]:
        where = "WHERE status=?" if status else ""
        rows = self.store._conn.execute(
            f"SELECT * FROM workflow_timer_v1 {where}"
            " ORDER BY created_at DESC LIMIT 200",
            (status,) if status else ()).fetchall()
        return [dict(r) for r in rows]

    # ---------- 执行引擎 ----------

    def _adjacency(self, spec: dict) -> dict[str, list[str]]:
        adj: dict[str, list[str]] = {}
        for e in spec.get("edges") or []:
            adj.setdefault(e["from"], []).append(e["to"])
        return adj

    def _execute(self, d: dict, inputs: dict, actor: str, *,
                 simulate: bool = False, run_id: str = "",
                 work_id: str = "", corr: str = "") -> dict:
        spec = d["spec"]
        nodes = {n["id"]: n for n in spec["nodes"]}
        trig = next(n["id"] for n in spec["nodes"]
                    if n["type"] == "trigger")
        vars_ = {k: v.get("default")
                 for k, v in (spec.get("variables") or {}).items()}
        vars_.update(inputs)  # trigger 输入绑定到变量（覆盖默认值）
        ctx = {"vars": vars_, "inputs": dict(inputs), "nodes": {}}
        self.store.upsert_node_execution(
            run_id or "sim", trig, node_type="trigger", status="succeeded",
            input_data=inputs, output_data=dict(inputs)) if run_id else None
        ctx["nodes"][trig] = {"status": "succeeded", **inputs}
        return self._run_nodes(d, self._adjacency(spec).get(trig, []),
                               ctx, simulate=simulate, run_id=run_id,
                               work_id=work_id, corr=corr)

    def _run_nodes(self, d: dict, frontier: list[str], ctx: dict, *,
                   simulate: bool = False, run_id: str = "",
                   work_id: str = "", corr: str = "") -> dict:
        spec = d["spec"]
        nodes = {n["id"]: n for n in spec["nodes"]}
        adj = self._adjacency(spec)
        spec_all_edges = spec.get("edges") or []
        join_requeue: dict[str, int] = {}
        while frontier:
            nid = frontier.pop(0)
            node = nodes.get(nid)
            if node is None:
                raise WorkflowError(f"未知节点: {nid}")
            try:
                out, branch = self._exec_node(
                    d, node, ctx, simulate=simulate, run_id=run_id,
                    work_id=work_id, corr=corr)
            except _WaitingHuman as w:
                return {"status": "waiting_human", "node": nid,
                        "work_item": w.work_id}
            except _WaitingTimer as wt:
                return {"status": "waiting_timer", "node": nid,
                        "timer_id": wt.timer_id}
            except _JoinNotReady as jn:
                # 汇合未满足：重排到 frontier 末尾（有界）
                join_requeue[nid] = join_requeue.get(nid, 0) + 1
                if join_requeue[nid] > 64:
                    return self._fail_node(
                        d, node, ctx,
                        f"join {nid} 无法满足（{jn.arrived}/{jn.need}）",
                        run_id=run_id, work_id=work_id, corr=corr)
                frontier.append(nid)
                continue
            except WorkflowError as e:
                return self._fail_node(d, node, ctx, str(e),
                                       run_id=run_id, work_id=work_id,
                                       corr=corr)
            ctx["nodes"][nid] = {"status": "succeeded", **(
                out if isinstance(out, dict) else {"value": out})}
            if run_id:
                self.store.upsert_node_execution(
                    run_id, nid, node_type=node["type"],
                    status="succeeded",
                    output_data=out if isinstance(out, dict)
                    else {"value": out})
            if node["type"] == "end":
                continue
            # 后继：condition 用 branch；其余用 edges
            if node["type"] == "condition" and branch:
                frontier.insert(0, branch)
                continue
            succ = [e["to"] for e in spec_all_edges
                    if e["from"] == nid]
            if node["type"] == "parallel" and len(succ) > 1:
                frontier = succ + frontier  # 扇出
            else:
                for s in succ:
                    frontier.insert(0, s)
        status = "succeeded"
        if run_id:
            self.store.set_business_run_status(
                run_id, status, current_node="end")
            self.store.emit_event(
                event_id=_new_id("evt"), event_type="workflow.succeeded",
                run_id=run_id, work_id=work_id, correlation_id=corr,
                actor_type="system", actor_id="workflow_runtime",
                payload={})
            self.store.set_work_item_v2_status(work_id, "done")
            self.store.rebuild_work_projection()
        return {"status": status, "nodes": ctx["nodes"]}

    def _fail_node(self, d, node, ctx, error: str, *, run_id: str,
                   work_id: str, corr: str) -> dict:
        policy = node.get("policy") or {}
        max_retry = int(policy.get("retry", 0))
        if run_id:
            row = next((e for e in self.store.list_node_executions(run_id)
                        if e["node_id"] == node["id"]), None)
            attempts = row["attempts"] if row else 0
            self.store.upsert_node_execution(
                run_id, node["id"], node_type=node["type"], status="failed",
                error=error, inc_attempt=True)
            if attempts < max_retry:
                # 自动重试：同 run 内再次执行该节点
                try:
                    out, branch = self._exec_node(
                        d, node, ctx, simulate=False, run_id=run_id,
                        work_id=work_id, corr=corr)
                    ctx["nodes"][node["id"]] = {
                        "status": "succeeded",
                        **(out if isinstance(out, dict)
                           else {"value": out})}
                    succ = [e["to"] for e in (d["spec"].get("edges") or [])
                            if e["from"] == node["id"]]
                    return self._run_nodes(d, succ, ctx, run_id=run_id,
                                           work_id=work_id, corr=corr)
                except Exception as e2:
                    error = str(e2)
            # 重试耗尽 → 死信 + run failed
            self.store.insert_dead_letter(
                run_id, node["id"], reason=error,
                payload={"node": node, "attempts": attempts + 1})
            self.store.upsert_node_execution(
                run_id, node["id"], node_type=node["type"], status="failed",
                error=error)
            self.store.set_business_run_status(
                run_id, "failed", error=error, current_node=node["id"])
            self.store.emit_event(
                event_id=_new_id("evt"), event_type="workflow.failed",
                run_id=run_id, work_id=work_id, correlation_id=corr,
                actor_type="system", actor_id="workflow_runtime",
                payload={"node": node["id"], "error": error})
            self.store.set_work_item_v2_status(
                work_id, "blocked", blockers=[error])
            self.store.rebuild_work_projection()
        return {"status": "failed", "node": node["id"], "error": error}

    def _exec_node(self, d: dict, node: dict, ctx: dict, *,
                   simulate: bool, run_id: str, work_id: str,
                   corr: str) -> tuple[Any, str | None]:
        t = node["type"]
        cfg = node.get("config") or {}
        if run_id:
            self.store.upsert_node_execution(
                run_id, node["id"], node_type=t, status="running",
                input_data=_safe_inputs(node, ctx))
        if t in ("trigger", "end"):
            return {}, None
        if t == "transform":
            mapping = cfg.get("map") or {}
            return {k: _resolve_value(v, ctx) for k, v in mapping.items()}, \
                None
        if t == "condition":
            for r in cfg.get("rules") or []:
                when = r.get("when") or {}
                left = _resolve_path(when.get("path", ""), ctx)
                if _compare(left, when.get("op", "eq"), when.get("value")):
                    return {"matched": r.get("to")}, r.get("to")
            return {"matched": cfg.get("default")}, cfg.get("default")
        if t == "wait":
            # ABOSV3 T5：持久化 timer（进程重启后仍能恢复）；
            # simulate 或 seconds<=0 时即时通过（checkpoint 留痕）。
            seconds = float(cfg.get("seconds", 0) or 0)
            if simulate or seconds <= 0 or not run_id:
                return {"waited_seconds": seconds,
                        "note": ("即时通过" if seconds <= 0
                                 else "模拟：timer 未真实等待")}, None
            fire_at = (datetime.now(timezone.utc)
                       + timedelta(seconds=seconds)).isoformat()
            timer_id = _new_id("tmr")
            self.store._conn.execute(
                "INSERT INTO workflow_timer_v1 (timer_id, run_id,"
                " node_id, fire_at, seconds, status, created_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (timer_id, run_id, node["id"], fire_at, seconds,
                 "pending", _now_iso()))
            self.store._conn.commit()
            self.store.set_business_run_status(
                run_id, "waiting_timer", current_node=node["id"])
            self.store.emit_event(
                event_id=_new_id("evt"),
                event_type="workflow.waiting_timer",
                run_id=run_id, work_id=work_id, correlation_id=corr,
                actor_type="system", actor_id="workflow_runtime",
                payload={"node": node["id"], "timer_id": timer_id,
                         "fire_at": fire_at})
            raise _WaitingTimer(timer_id)
        if t == "agent":
            if simulate:
                return {"message": "[simulate] agent 节点未真实调用"}, None
            agent_id = str(cfg.get("agent_id") or "supervisor")
            prompt = str(cfg.get("prompt", "当前工作流状态？"))
            prompt = _resolve_value(prompt, ctx)
            # ABOSV3：调用节点指定的 Agent（真实工具循环）；
            # runtime 未装配时回退 Supervisor 规则回答（诚实降级）。
            if self.agent_runtime is not None:
                resp = self.agent_runtime.invoke(
                    agent_id, str(prompt), actor="workflow_runtime",
                    session_id=f"workflow:{run_id or 'sim'}")
                return {"agent_id": agent_id,
                        "message": resp.get("message"),
                        "tool_trace": resp.get("tool_trace"),
                        "provider": resp.get("provider")}, None
            sup = SupervisorAgent(self.store)
            resp = sup.chat(session_id=f"workflow:{run_id or 'sim'}",
                            text=str(prompt), actor="workflow_runtime")
            return {"agent_id": "supervisor",
                    "message": resp.get("message"),
                    "trace_id": resp.get("trace_id"),
                    "provider": resp.get("provider")}, None
        if t == "human_approval":
            if simulate:
                return {"decision": "[simulate] auto-approved"}, None
            approval_work = self.store.insert_work_item_v2({
                "work_id": _new_id("work"), "run_id": run_id,
                "status": "approval", "owner_type": "human",
                "owner_id": cfg.get("owner", "admin"),
                "title": cfg.get("title", "人工批准"),
                "business_summary": f"workflow run {run_id}",
                "subject_type": "workflow_run", "subject_id": run_id})
            self.store.upsert_node_execution(
                run_id, node["id"], node_type="human_approval",
                status="waiting_approval",
                output_data={"work_id": approval_work["work_id"]})
            self.store.set_business_run_status(run_id, "waiting_human",
                                               current_node=node["id"])
            self.store.emit_event(
                event_id=_new_id("evt"), event_type="run.waiting_human",
                run_id=run_id, work_id=work_id, correlation_id=corr,
                actor_type="system", actor_id="workflow_runtime",
                payload={"node": node["id"],
                         "approval_work_id": approval_work["work_id"]})
            raise _WaitingHuman(approval_work["work_id"])
        if t == "loop":
            items = _resolve_path(cfg.get("items_path", ""), ctx) or []
            if not isinstance(items, list):
                raise WorkflowError("loop items_path 必须解析为列表")
            body = next((n for n in d["spec"]["nodes"]
                         if n["id"] == cfg.get("body")), None)
            if body is None:
                raise WorkflowError("loop body 节点不存在")
            results = []
            for i, item in enumerate(items):
                ctx["vars"]["loop_item"] = item
                ctx["vars"]["loop_index"] = i
                out, _ = self._exec_node(
                    d, body, ctx, simulate=simulate, run_id=run_id,
                    work_id=work_id, corr=corr)
                results.append(out)
            return {"count": len(results), "results": results}, None
        if t == "parallel":
            # 扣资源租约：max_concurrency 记录在 config（本机单 worker
            # 串行执行分支，不伪造并发吞吐；分支经边扇出）
            return {"note": "扇出由边驱动",
                    "max_concurrency": int(
                        cfg.get("max_concurrency", 1))}, None
        if t == "join":
            # ABOSV3：all/any/quorum 汇合语义：统计已完成前驱分支
            mode = str(cfg.get("mode", "all"))
            quorum = int(cfg.get("quorum", 1))
            preds = [e["from"] for e in (d["spec"].get("edges") or [])
                     if e["to"] == node["id"]]
            done_nodes = ctx.get("nodes", {})
            arrived = [p for p in preds
                       if done_nodes.get(p, {}).get("status")
                       == "succeeded"]
            need = len(preds) if mode == "all" else (
                quorum if mode == "quorum" else 1)
            if len(arrived) < max(need, 1):
                # 未满足 → 重新排到 frontier 末尾（_run_nodes 处理）
                raise _JoinNotReady(len(arrived), max(need, 1))
            return {"joined": sorted(arrived), "mode": mode,
                    "missing": sorted(set(preds) - set(arrived))}, None
        if t == "subflow":
            if simulate:
                return {"[simulate]": "subflow 未真实嵌套执行"}, None
            sub = self.start_run(
                cfg["definition_id"], inputs=ctx.get("inputs", {}),
                actor="workflow_runtime", source="internal",
                version=cfg.get("version"), parent_run_id=run_id,
                correlation_id=corr)
            return {"sub_run_id": sub["run"]["run_id"],
                    "status": sub["run"]["status"]}, None
        if t == "connector":
            ad = CONNECTORS.get(cfg.get("connector_id"))
            if ad is None:
                raise WorkflowError(
                    f"未知连接器: {cfg.get('connector_id')}")
            ok, reason = ad.available()
            if simulate:
                return {"status": ("simulated" if ok
                                   else "simulated_blocked"),
                        "connector": cfg.get("connector_id"),
                        "reason": reason}, None
            if not ok:
                raise WorkflowError(f"连接器不可用（blocked）：{reason}")
            return ad.start({"run_id": run_id}, ctx.get("inputs", {})), None
        if t in ("command", "model"):
            cap = node.get("capability")
            if simulate:
                return {"status": "simulated", "capability": cap,
                        "note": "dry-run：未产生副作用/用量"}, None
            params = _resolve_value(node.get("inputs") or {}, ctx)
            if not isinstance(params, dict):
                raise WorkflowError("command inputs 必须解析为对象")
            out = self.gateway.submit(
                command_kind=cap, params=params, actor="workflow_runtime",
                source="internal", correlation_id=corr,
                tenant_id="local", parent_run_id=run_id or None)
            return {"status": out["status"], "run_id": out["run_id"],
                    "work_id": out["work_id"],
                    "result": out.get("result"),
                    "error": out.get("error")}, None
        raise WorkflowError(f"未实现的节点类型: {t}")

    def _restore_ctx(self, run_id: str, d: dict,
                     extra_inputs: dict | None = None) -> dict:
        """从 checkpoint 恢复执行上下文（可恢复性）。"""
        spec = d["spec"]
        vars_ = {k: v.get("default")
                 for k, v in (spec.get("variables") or {}).items()}
        vars_.update(extra_inputs or {})
        ctx = {"vars": vars_, "inputs": dict(extra_inputs or {}),
               "nodes": {}}
        for e in self.store.list_node_executions(run_id):
            if e["status"] == "succeeded":
                ctx["nodes"][e["node_id"]] = {
                    "status": "succeeded", **e["output"]}
                if not ctx["inputs"]:
                    ctx["inputs"] = e.get("input") or {}
        return ctx

    # ---------- Workflow Agent：自然语言 → draft patch ----------

    def agent_draft(self, text: str, *, actor: str) -> dict:
        """规则化 NL→draft：只能生成 draft，发布必须人工批准。"""
        t = text or ""
        if "识别" in t or "照片" in t or "货架" in t:
            spec = json.loads(json.dumps(
                TEMPLATE_RECOGNITION_CHAIN["spec"]))
            note = "已生成照片识别链 draft：trigger→识别命令→失败人工复核→end"
        else:
            spec = {"trigger": {"type": "manual"}, "variables": {},
                    "nodes": [{"id": "start", "type": "trigger"},
                              {"id": "end", "type": "end"}],
                    "edges": [{"from": "start", "to": "end"}],
                    "policy": {"approval_required_for_publish": True}}
            note = "未识别业务意图：生成最小 draft 骨架，请补充节点"
        draft = self.create_draft(
            name=f"Agent 草稿：{(t or '未命名')[:20]}",
            spec=spec, actor=actor)
        return {"note": note, "draft": draft,
                "requires_human_approval": True,
                "allowed_next": ["lint", "simulate", "approve", "publish"],
                "warning": "Workflow Agent 只能生成/预览/模拟 draft；"
                           "发布与高风险运行必须人工批准"}


class _WaitingHuman(Exception):
    def __init__(self, work_id: str) -> None:
        super().__init__("waiting_human")
        self.work_id = work_id


class _WaitingTimer(Exception):
    def __init__(self, timer_id: str) -> None:
        super().__init__("waiting_timer")
        self.timer_id = timer_id


class _JoinNotReady(Exception):
    def __init__(self, arrived: int, need: int) -> None:
        super().__init__(f"join not ready {arrived}/{need}")
        self.arrived = arrived
        self.need = need


def _safe_inputs(node: dict, ctx: dict) -> dict:
    try:
        raw = _resolve_value(node.get("inputs") or {}, ctx)
        return raw if isinstance(raw, dict) else {"value": str(raw)[:200]}
    except Exception:
        return {}


class NativeWorkflowExecutor(WorkflowExecutorAdapter):
    """Native executor：ABOS 保留唯一 Workflow/Run/Event/Usage 事实。"""

    name = "native"

    def __init__(self, service: WorkflowService) -> None:
        self.service = service

    def available(self) -> tuple[bool, str]:
        return True, "native runtime"

    def validate(self, definition: dict) -> list[dict]:
        return self.service._lint_spec(definition.get("spec") or {})

    def start(self, run_context: dict, inputs: dict,
              idempotency_key: str | None = None) -> dict:
        return self.service.start_run(
            run_context["definition_id"], inputs=inputs,
            actor=run_context.get("actor", "api"),
            version=run_context.get("version"))

    def pause(self, execution_ref: str) -> dict:
        return self.service.pause_run(execution_ref, actor="api")

    def resume(self, execution_ref: str) -> dict:
        return self.service.resume_run(execution_ref, actor="api")

    def cancel(self, execution_ref: str) -> dict:
        return self.service.cancel_run(execution_ref, actor="api")

    def collect_usage(self, execution_ref: str) -> list[dict]:
        return self.service.store.list_usage_events_v2(
            run_id=execution_ref)

    def collect_evidence(self, execution_ref: str) -> list[dict]:
        run = self.service.store.get_business_run(execution_ref)
        if run and run.get("evidence_bundle_id"):
            ev = self.service.store.get_evidence_bundle(
                run["evidence_bundle_id"])
            return [ev] if ev else []
        return []
