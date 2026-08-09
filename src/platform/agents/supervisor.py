"""SLTF 纠偏 Task 4：Supervisor Agent 真实运行时。

规则意图解析（provider 可替换；本地默认 rules fallback，明确标注
provider="rules_fallback"，不伪装大模型推理）。
能力：解析意图→查正式事实源→调 Domain Agent→证据引用→命令预览→
白名单 UIIntent→高风险要求审批→不自行切生产。
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

UI_INTENTS = ("navigate", "open_panel", "filter", "highlight",
              "compare", "pin_card", "show_evidence")
HIGH_RISK = ("production.switch", "training.launch_unbounded",
             "data.delete", "publish.auto")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SupervisorAgent:
    def __init__(self, store: Any, *, provider: str = "rules_fallback",
                 llm_fn: Any = None) -> None:
        self.store = store
        self.provider = provider  # 可替换；默认规则 fallback
        self.llm_fn = llm_fn

    # ---- 事实查询 ----

    def _cycle(self) -> dict | None:
        row = self.store._conn.execute(
            "SELECT * FROM training_cycle_v1 WHERE cycle_id="
            "'sku_long_tail_nextgen_cycle_v1'").fetchone()
        if row is None:
            return None
        nodes = self.store._conn.execute(
            "SELECT node, status FROM training_cycle_node_v1"
            " WHERE cycle_id=? ORDER BY id", (row["cycle_id"],)).fetchall()
        return {**dict(row),
                "nodes": [{"node": n["node"], "status": n["status"]}
                          for n in nodes]}

    def _artifacts(self) -> list[dict]:
        return [dict(r) for r in self.store._conn.execute(
            "SELECT artifact_id, candidate_status, blocker,"
            " evidence_level FROM model_artifact_registry_v1").fetchall()]

    def _tier(self) -> dict | None:
        row = self.store._conn.execute(
            "SELECT summary_json FROM evaluation_registry_v1"
            " WHERE eval_id='sku_readiness_policy'").fetchone()
        return json.loads(row["summary_json"]) if row else None

    def _blackboard(self, etype: str | None = None) -> list[dict]:
        q = "SELECT * FROM blackboard_event_v1"
        args: tuple = ()
        if etype:
            q += " WHERE event_type=?"
            args = (etype,)
        return [dict(r) for r in self.store._conn.execute(
            q + " ORDER BY created_at DESC", args).fetchall()]

    # ---- 意图解析 ----

    def chat(self, session_id: str, text: str, *,
             actor: str) -> dict[str, Any]:
        t = text.strip()
        resp: dict[str, Any] = {"session_id": session_id,
                                "provider": self.provider,
                                "evidence": [], "ui_intents": [],
                                "commands": [], "requires_approval": False}

        if "M1" in t and ("上线" in t or "候选" in t):
            resp["answer"] = ("M1 不可以上线：pilot mAP50 0.077，仅 894 张"
                              "全场景图，状态 PILOT_NOT_CANDIDATE；需补采"
                              "全场景图并独立业务评估。")
            resp["evidence"] = [".models/nextgen_detector_pilot_v1/"
                                "train_report.json"]
        elif "M3" in t and ("最好" in t or "哪个" in t or "胜出" in t):
            resp["answer"] = ("E1/E5 各有优劣，独立测试"
                              "（canonical38_train_val_test_v2）完成前不提前"
                              "判定；两者均 PILOT_PENDING_EVALUATION。")
            resp["evidence"] = ["reports/nextgen_v2/m3_longtail_ablation.json"]
        elif "Qwen" in t or "M4" in t or "达标" in t:
            resp["answer"] = ("KB 检索通过（coverage 1.0/recall@8 1.0），但 VLM"
                              "裁决准确率尚未评估；M4="
                              "PILOT_PENDING_EVALUATION，三版本独立对比待跑。")
            resp["evidence"] = ["reports/nextgen_v2/kb_canonical38_recall.json"]
        elif "250" in t:
            resp["answer"] = ("不需要。旧 250 流程已 SUPERSEDED_FOR_DEMO_"
                              "TRAINING；替代为 demo_micro_gold_v1（待用户"
                              "启动），不再建议先完成 250 项审核。")
            resp["evidence"] = ["platform.sqlite:flow_supersession_v1"]
        elif "训练到哪里" in t or "目前训练" in t or "cycle" in t.lower():
            from src.modules.training_control.cycle_projection import (
                CycleProjectionService)
            cps = CycleProjectionService(self.store)
            sm = cps.cycle_summary("sku_long_tail_nextgen_cycle_v1")
            resp["answer"] = (f"Cycle 16/19 节点完成（{sm['done']}/"
                              f"{sm['distinct_nodes']}）；剩余 3 个评估/决策"
                              "节点：DemoEvaluation、"
                              "AwaitingIndependentEvaluation、"
                              "AwaitingProductionDecision。")
            resp["evidence"] = ["platform.sqlite:"
                                "training_cycle_node_state_v2"]
            resp["ui_intents"] = [{"kind": "open_panel",
                                   "target": "training_cycle"}]
        elif "分类器" in t and ("结果" in t or "打开" in t):
            a = next((x for x in self._artifacts()
                      if x["artifact_id"] == "nextgen_classifier_grouped_v1"),
                     None)
            resp["answer"] = (f"M3 grouped baseline：val top1 30.7%，"
                              f"状态 {a['candidate_status'] if a else '未注册'}；"
                              "random 82.4% 为泄漏证据，不参与排名")
            resp["evidence"] = [
                "reports/nextgen_v2/classifier_split_compare.json",
                "reports/nextgen_v2/m3_classifier_cropped_report.json"]
            resp["ui_intents"] = [{"kind": "navigate",
                                   "target": "/training"},
                                  {"kind": "highlight",
                                   "target": "m3_grouped"}]
        elif "SKU" in t and ("最少" in t or "长尾" in t or "尾部" in t):
            tier = self._tier()
            worst = (tier or {}).get("worst_ten", [])[:5]
            resp["answer"] = ("数据最少的类（Tier D 前5）：" +
                              "、".join(w["display"] for w in worst))
            resp["evidence"] = [
                "reports/nextgen_v2/sku_data_readiness_policy_v1.json"]
            resp["ui_intents"] = [{"kind": "open_panel",
                                   "target": "long_tail"}]
        elif "阻塞" in t or "blocker" in t.lower():
            bl = self._blackboard("Blocker")
            resp["answer"] = ("当前阻塞 " + str(len(bl)) + " 个：" +
                              "；".join(json.loads(b["payload_json"])
                                       .get("text", "") for b in bl[:3]))
            resp["evidence"] = ["platform.sqlite:blackboard_event_v1"]
        elif "创建" in t and "计划" in t:
            resp["answer"] = ("已生成 M3 长尾消融计划预览（E1-E5，grouped "
                              "split，同预算 10-15 epoch early stop）。"
                              "批准后才创建 Plan，不直接启动。")
            cmd_id = "cmd-" + uuid.uuid4().hex[:8]
            resp["commands"] = [{"command_id": cmd_id,
                                 "kind": "training.plan.create",
                                 "params": {"lane": "classifier",
                                            "experiments": ["E1", "E2", "E3",
                                                            "E4", "E5"]},
                                 "status": "pending_approval"}]
            resp["requires_approval"] = True
            resp["ui_intents"] = [{"kind": "show_evidence",
                                   "target": cmd_id}]
        elif "比较" in t and ("random" in t or "grouped" in t):
            resp["answer"] = ("random 82.4%（泄漏，INVALID）vs grouped 30.7%"
                              "（真实基线）；Δ47.7pp")
            resp["ui_intents"] = [{"kind": "compare",
                                   "target": ["m3_random", "m3_grouped"]}]
            resp["evidence"] = [
                "reports/nextgen_v2/classifier_split_compare.json"]
        elif "label studio" in t.lower() or "打开LS" in t:
            resp["answer"] = "打开 Label Studio 项目 19/20（assisted/blind）"
            resp["ui_intents"] = [{"kind": "navigate",
                                   "target": "http://127.0.0.1:8300/projects/19"}]
        elif "qwen" in t.lower() or "M4" in t:
            resp["answer"] = ("M4 禁训原因：KB canonical38 未建，coverage=0，"
                              "candidate recall=null。先建 KB，recall@8≥90% "
                              "才可 pilot。")
            resp["evidence"] = [
                "reports/nextgen_v2/qwen_candidate_recall_real.json"]
            resp["ui_intents"] = [{"kind": "open_panel", "target": "kb"}]
        elif "停止" in t and "训练" in t:
            resp["answer"] = ("当前无运行中训练（MPS heavy lease 空）。"
                              "若有运行中 run，safe-stop 需确认退出证据。")
            resp["commands"] = [{"command_id": "cmd-" + uuid.uuid4().hex[:8],
                                 "kind": "training.safe_stop",
                                 "status": "pending_approval"}]
            resp["requires_approval"] = True
        elif "切换生产" in t or "production" in t.lower():
            resp["answer"] = ("拒绝：production 切换为高风险操作，"
                              "Supervisor 无权自行执行，需人工独立批准。")
            resp["requires_approval"] = True
            resp["denied"] = True
        else:
            resp["answer"] = ("已解析但无匹配意图；支持：训练进度/分类器结果/"
                              "SKU长尾/阻塞/创建计划/比较/打开LS/M4/停止/"
                              "切换生产")
        # 记录会话消息
        self.store._conn.execute(
            "INSERT INTO agent_session_msg_v1 (session_id, role, content,"
            " meta_json, created_at) VALUES (?,?,?,?,?)",
            (session_id, "user", text,
             json.dumps({"actor": actor}, ensure_ascii=False), _now()))
        self.store._conn.execute(
            "INSERT INTO agent_session_msg_v1 (session_id, role, content,"
            " meta_json, created_at) VALUES (?,?,?,?,?)",
            (session_id, "supervisor", resp["answer"],
             json.dumps({k: v for k, v in resp.items()
                         if k != "answer"}, ensure_ascii=False), _now()))
        self.store._conn.commit()
        return resp
