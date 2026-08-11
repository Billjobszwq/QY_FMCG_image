"""ABOS T6：Supervisor Agent 真实运行时（重写）。

原则：
- 平台定位唯一：智能业务操作系统（Graph+Loop 内核 + Domain Pack）；
  识别只是首个 Domain Pack，不再以单一识别工具自居。
- 不硬编码过期业务事实：所有状态类答案经 Query Tool 从 store/注册表/
  运行态实时读取；查不到就诚实说查不到。
- 统一响应契约：message/evidence_refs/ui_intents/command_previews/
  tasks/delegations/memory_updates/requires_approval/trace_id
  （保留 answer/commands 兼容字段一个版本）。
- UIIntent 白名单执行，禁 HTML/JS 注入。
- 高风险（production.switch/删除/发布/财务终结）一律拒绝或要求人工
  独立批准；LLM 不可用时明确降级，不伪装智能回答。
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .kernel import UI_INTENT_KINDS, validate_ui_intent

UI_INTENTS = tuple(sorted(UI_INTENT_KINDS))
HIGH_RISK = ("production.switch", "training.launch_unbounded",
             "data.delete", "publish.auto", "finance.finalize")

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _trace_id() -> str:
    return "tr-" + uuid.uuid4().hex[:12]


# ---- DeepSeek LLM provider（规则未命中时兜底；不可用时明确降级）----

_SYSTEM_PROMPT = (
    "你是 Agentic Business OS（智能业务操作系统）的主管 Agent。平台以 "
    "Graph+Loop 为执行内核，图像识别只是第一个 Domain Pack。基于以下"
    "平台实时状态回答，简洁、诚实、可执行；不确定就说不确定；"
    "涉及生产切换/发布/删除/财务终结一律要求人工批准。\n")


def _deepseek_answer(text: str, context: str) -> str | None:
    import os
    import urllib.request
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
    if not key:
        return None
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT + context},
            {"role": "user", "content": text}],
        "temperature": 0.3,
    }
    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.loads(r.read())
        return d["choices"][0]["message"]["content"]
    except Exception:
        return None


class QueryTool:
    """Supervisor 的事实查询层：只读 store/注册表/运行态，不写数据。"""

    def __init__(self, store: Any) -> None:
        self.store = store

    def _safe(self, fn, default):
        try:
            return fn()
        except Exception:
            return default

    def cycle_summary(self) -> dict | None:
        def _q():
            from src.platform.projection import CycleProjectionService
            return CycleProjectionService(self.store).cycle_summary(
                "sku_long_tail_nextgen_cycle_v1")
        return self._safe(_q, None)

    def artifacts(self) -> list[dict]:
        def _q():
            return [dict(r) for r in self.store._conn.execute(
                "SELECT artifact_id, candidate_status, blocker,"
                " evidence_level FROM model_artifact_registry_v1").fetchall()]
        return self._safe(_q, [])

    def blockers(self) -> list[dict]:
        def _q():
            return [dict(r) for r in self.store._conn.execute(
                "SELECT payload_json, created_at FROM blackboard_event_v1"
                " WHERE event_type='Blocker' ORDER BY created_at DESC"
                " LIMIT 10").fetchall()]
        return self._safe(_q, [])

    def recognition_tasks(self) -> dict:
        def _q():
            total = self.store._conn.execute(
                "SELECT COUNT(*) c FROM recognition_task").fetchone()["c"]
            last = self.store._conn.execute(
                "SELECT task_id, status, entry, sku_count, created_at"
                " FROM recognition_task ORDER BY id DESC LIMIT 1").fetchone()
            return {"total": total, "last": dict(last) if last else None}
        return self._safe(_q, {"total": 0, "last": None})

    def pending_commands(self) -> int:
        def _q():
            return self.store._conn.execute(
                "SELECT COUNT(*) c FROM agent_command_v1"
                " WHERE status='pending_approval'").fetchone()["c"]
        return self._safe(_q, 0)

    def training_process(self) -> str:
        """无训练进程核验（只读 ps，不启停任何进程）。"""
        import subprocess
        try:
            out = subprocess.run(
                ["ps", "aux"], capture_output=True, text=True,
                timeout=5).stdout
            marks = ("ultralytics", "train_v1", "qlora", "finetune_qwen",
                     "mlx_lm")
            hits = [ln.split()[1] for ln in out.splitlines()
                    if any(m in ln for m in marks) and "grep" not in ln]
            return ("有疑似训练进程: " + ",".join(hits)) if hits \
                else "当前无训练进程（MPS/MLX 空闲）"
        except Exception:
            return "训练进程状态查询失败"

    def production(self) -> dict:
        f = _REPO_ROOT / ".models" / "bundles" / "CURRENT.json"
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            return {"bundle_id": d.get("bundle_id"),
                    "previous": d.get("previous"), "found": True}
        except Exception:
            return {"bundle_id": None, "found": False}

    def micro_gold_v2_project(self) -> int | None:
        f = _REPO_ROOT / ".micro_gold_v2" / "ls_project.json"
        try:
            return json.loads(f.read_text(encoding="utf-8"))["project_id"]
        except Exception:
            return None

    def sample_photo(self) -> str | None:
        """仓库内合法样板照片（演示验收用；不进训练/金标准）。"""
        d = _REPO_ROOT / "bad_samples"
        try:
            for f in sorted(d.iterdir()):
                if f.suffix.lower() in (".jpg", ".jpeg", ".png"):
                    return str(f.relative_to(_REPO_ROOT))
        except Exception:
            pass
        return None

    def platform_context(self) -> str:
        cyc = self.cycle_summary()
        prod = self.production()
        rec = self.recognition_tasks()
        cyc_txt = ("—" if not cyc else
                   f"{cyc.get('done')}/{cyc.get('distinct_nodes')}")
        return (f"cycle={cyc_txt}; "
                f"artifacts={len(self.artifacts())}; "
                f"识别任务={rec['total']}; 待批命令={self.pending_commands()}; "
                f"production={prod.get('bundle_id') or '未知'}（未切换）")


def _intent(kind: str, target: Any) -> dict:
    it = {"kind": kind, "target": target}
    validate_ui_intent(it)   # fail-closed：非法 intent 直接抛错
    return it


class SupervisorAgent:
    def __init__(self, store: Any, *, provider: str = "rules_fallback",
                 llm_fn: Any = None) -> None:
        self.store = store
        self.provider = provider
        self.llm_fn = llm_fn
        self.q = QueryTool(store)

    # ---- 统一响应构造 ----

    def _resp(self, session_id: str) -> dict[str, Any]:
        return {"session_id": session_id,
                "provider": self.provider,
                "message": "",
                "evidence_refs": [],
                "ui_intents": [],
                "command_previews": [],
                "tasks": [],
                "delegations": [],
                "memory_updates": [],
                "requires_approval": False,
                "trace_id": _trace_id()}

    def _delegate(self, resp: dict, agent_id: str, action: str,
                  result: Any) -> None:
        resp["delegations"].append({
            "agent_id": agent_id, "action": action,
            "status": "ok", "receipt": result, "at": _now()})

    # ---- 领域回答（全部走 Query Tool 实时事实）----

    def chat(self, session_id: str, text: str, *,
             actor: str) -> dict[str, Any]:
        t = text.strip()
        resp = self._resp(session_id)
        q = self.q

        if "切换生产" in t or "切生产" in t or (
                "production" in t.lower() and "切换" in t):
            resp["message"] = ("拒绝：production 切换为高风险操作，"
                               "Supervisor 无权自行执行，需人工独立批准。")
            resp["requires_approval"] = True
            resp["denied"] = True
        elif "删除" in t and ("数据" in t or "资产" in t):
            resp["message"] = ("拒绝：删除数据/资产属于高风险操作，"
                               "需人工独立批准并明确删除目标。")
            resp["requires_approval"] = True
            resp["denied"] = True
        elif ("识别" in t and ("照片" in t or "这批" in t or "任务" in t
                               and "创建" in t)) or "发起识别" in t:
            # 委派 Recognition Agent：生成命令预览，批准后走统一 API
            cmd_id = "cmd-" + uuid.uuid4().hex[:8]
            resp["message"] = (
                "已委派 Recognition Agent 生成识别命令预览：批准后将经 "
                "POST /api/v1/vision/recognition-tasks 创建统一任务"
                "（同一 Profile/Service/证据链）。")
            resp["command_previews"].append({
                "command_id": cmd_id,
                "kind": "vision.recognition.create",
                "params": {"recognition_profile_id": "production_legacy",
                           "service_tier": "standard", "source": "agent",
                           "image_path": q.sample_photo()},
                "impact": "创建识别任务并计入任务历史/计费",
                "cost_estimate": "按 recognition_call 计量",
                "idempotency_key": "agent-" + uuid.uuid4().hex[:8],
                "rollback": "任务可查询/标记，不删除历史",
                "status": "pending_approval"})
            resp["requires_approval"] = True
            resp["ui_intents"].append(_intent("navigate", "/vision/tasks"))
            self._delegate(resp, "recognition_agent",
                           "vision.recognition.create.preview", cmd_id)
        elif "训练" in t and ("进程" in t or "正在" in t or "运行" in t):
            resp["message"] = q.training_process() + "；本轮只评估不训练。"
            resp["evidence_refs"].append({"kind": "host",
                                          "ref": "ps aux（只读）"})
        elif "训练到哪里" in t or "cycle" in t.lower() or "目前训练" in t:
            sm = q.cycle_summary()
            if sm:
                resp["message"] = (
                    f"Cycle {sm['done']}/{sm['distinct_nodes']} 节点完成；"
                    "详情见训练控制面。")
                resp["evidence_refs"].append(
                    {"kind": "db", "ref": "training_cycle_node_state_v2"})
            else:
                resp["message"] = "未查询到训练 cycle 记录。"
            resp["ui_intents"].append(_intent("navigate", "/vision/models"))
        elif "候选" in t and ("哪些" in t or "模型" in t):
            arts = q.artifacts()
            if arts:
                resp["message"] = ("候选模型 " + str(len(arts)) + " 个：" +
                                   "；".join(f"{a['artifact_id']}="
                                             f"{a['candidate_status']}"
                                             for a in arts[:6]))
                resp["evidence_refs"].append(
                    {"kind": "db", "ref": "model_artifact_registry_v1"})
            else:
                resp["message"] = "未查询到已注册候选模型。"
        elif "micro-gold" in t and ("新项目" in t or "ID" in t
                                     or "id" in t):
            pid = q.micro_gold_v2_project()
            resp["message"] = (f"micro-gold v2 有效项目 ID={pid}"
                               if pid else
                               "micro-gold v2 项目信息未导入（无本地记录）。")
            resp["evidence_refs"].append(
                {"kind": "file", "ref": ".micro_gold_v2/ls_project.json"})
        elif "阻塞" in t or "blocker" in t.lower():
            bl = q.blockers()
            resp["message"] = ("当前阻塞 " + str(len(bl)) + " 个" +
                               ("：" + "；".join(
                                   json.loads(b["payload_json"]).get(
                                       "text", "") for b in bl[:3])
                                if bl else "（无）"))
            resp["evidence_refs"].append(
                {"kind": "db", "ref": "blackboard_event_v1"})
        elif "识别任务" in t or "任务历史" in t:
            rec = q.recognition_tasks()
            last = rec["last"]
            resp["message"] = (
                f"识别任务共 {rec['total']} 条" +
                (f"；最近一条 {last['task_id'][:8]}… 状态="
                 f"{last['status']}（{last['entry']}，SKU "
                 f"{last['sku_count']}）" if last else "（暂无）"))
            resp["evidence_refs"].append(
                {"kind": "db", "ref": "recognition_task"})
            resp["ui_intents"].append(_intent("navigate", "/vision/tasks"))
        elif "打开" in t or "跳转" in t:
            target = self._nav_target(t)
            resp["message"] = f"已打开 {target}"
            resp["ui_intents"].append(_intent("navigate", target))
        elif "这里能做什么" in t or "帮助" in t or "怎么用" in t:
            resp["message"] = (
                "这是 Agentic Business OS 主管工作台：我可以汇总待办/审批/"
                "运行/异常，委派领域 Agent 创建识别任务（需批准），并用 "
                "UIIntent 打开对应页面。识别入口在“智能识别”模块。")
            resp["ui_intents"].append(_intent("navigate", "/vision/recognize"))
        else:
            llm = _deepseek_answer(t, q.platform_context())
            if llm:
                resp["message"] = llm
                resp["provider"] = "deepseek"
            else:
                resp["message"] = (
                    "（LLM 暂不可用，已降级为规则回答）可问：识别任务/"
                    "候选模型/训练进度/阻塞/打开某页面/切换生产（将被拒绝）")
                resp["provider"] = "rules_fallback"

        self._persist(session_id, text, actor, resp)
        # 兼容字段（一个版本后移除）
        resp["answer"] = resp["message"]
        resp["commands"] = resp["command_previews"]
        resp["evidence"] = [e.get("ref", str(e))
                            for e in resp["evidence_refs"]]
        return resp

    @staticmethod
    def _nav_target(t: str) -> str:
        table = (("识别", "/vision/recognize"),
                 ("任务", "/vision/tasks"),
                 ("标注", "/vision/annotation"),
                 ("数据集", "/vision/datasets"),
                 ("模型", "/vision/models"), ("训练", "/vision/models"),
                 ("证据", "/vision/evidence"),
                 ("资产", "/data/assets"), ("数据", "/data/assets"),
                 ("状态", "/status"), ("系统", "/status"),
                 ("工作流", "/workflow/runs"),
                 ("run", "/workflow/runs"))
        for kw, route in table:
            if kw in t.lower():
                return route
        return "/"

    def _persist(self, session_id: str, text: str, actor: str,
                 resp: dict) -> None:
        self.store._conn.execute(
            "INSERT INTO agent_session_msg_v1 (session_id, role, content,"
            " meta_json, created_at) VALUES (?,?,?,?,?)",
            (session_id, "user", text,
             json.dumps({"actor": actor}, ensure_ascii=False), _now()))
        meta = {k: v for k, v in resp.items()
                if k not in ("message", "answer")}
        self.store._conn.execute(
            "INSERT INTO agent_session_msg_v1 (session_id, role, content,"
            " meta_json, created_at) VALUES (?,?,?,?,?)",
            (session_id, "supervisor", resp["message"],
             json.dumps(meta, ensure_ascii=False, default=str), _now()))
        self.store._conn.commit()
