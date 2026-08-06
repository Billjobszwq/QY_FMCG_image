"""VLM-012：S0–S5 级联编排服务（Graph+Loop v2 是唯一 Orchestrator）。

红线：
- 复用平台内核 LoopEngine/GraphV2：状态、checkpoint、人工门、决策轨迹
  全部经 PlatformStore 持久化，可跨进程恢复；
- 客户档位（fast/standard/deep/expert）快照随 run 冻结；预算耗尽、
  SLA 过期、未知商品、VLM 不可用一律转人工，不得静默接受；
- raw confidence 不参与路由：只有 decide_risk 校准结果可跨模型路由；
- billing 账本按 (node, round) 幂等计费；idempotency_key 重复提交
  返回同一 run，不重复计费；
- 轨迹记录 policy version/risk/budget before-after/SLA/模型/证据 ID，
  不记录密钥与 prompt 内客户敏感数据。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from src.modules.fmcg.adapters.qwen3vl_mlx import (
    QwenAdapterError,
    QwenHttpError,
    QwenTransportError,
)
from src.modules.fmcg.cascade.contracts import DECISIONS
from src.modules.fmcg.cascade.graph import CASCADE_GRAPH
from src.modules.fmcg.cascade.manifest import (
    CAP_DETECT,
    CAP_FAST_SKU,
    CAP_HUMAN,
    CAP_QUALITY,
    CAP_QWEN,
    CAP_RETRIEVE,
    CAP_SAM,
    CAP_SCENE,
)
from src.modules.fmcg.cascade.policy import (
    budget_exhausted_decision,
    policy_for,
    policy_snapshot,
)
from src.modules.fmcg.cascade.risk import bootstrap_rule_v1, decide_risk
from src.platform.data.store import PlatformStore
from src.platform.kernel.loop import LoopEngine
from src.platform.model_runtime import ModelBusy

# 与 src/platform/kernel/loop.py 的 _SHARED/_STATE 常量保持同一键
SHARED_KEY = "__loop_shared__"
STATE_KEY = "__loop_state__"

_QWEN_ERRORS = (QwenAdapterError, QwenHttpError, QwenTransportError,
                ModelBusy)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CascadeService:
    """FMCG 级联编排：API/Web/Agent 共用同一 RecognitionTask/GraphRun。"""

    def __init__(self, store: PlatformStore,
                 adapters: Mapping[str, Any],
                 *, calibrator: Any = None) -> None:
        self.store = store
        self.adapters = dict(adapters)
        self._calibrator = calibrator or bootstrap_rule_v1()
        self._engine = LoopEngine(store)

    # ---------- 生命周期 ----------

    def submit(self, asset_ref: dict[str, Any], *, tier: str,
               idempotency_key: str | None = None,
               queue_deadline_at: datetime | None = None) -> dict[str, Any]:
        """提交识别任务：同一 idempotency_key 幂等返回同一 run。"""
        for k in ("asset_id", "sha256", "image_width", "image_height"):
            if not asset_ref.get(k):
                raise ValueError(f"asset_ref 缺少 {k}（fail-closed）")
        policy = policy_for(tier)
        if idempotency_key is not None:
            existing = self.store.find_run_by_idempotency_key(idempotency_key)
            if existing is not None:
                return existing  # 幂等：不重跑、不重复计费
        deadline = queue_deadline_at or (
            _utcnow() + timedelta(hours=policy.queue_sla_hours))
        run = self._engine.start_run(
            CASCADE_GRAPH,
            {"asset": asset_ref, "tier": tier,
             "queue_deadline_at": deadline.isoformat()},
            idempotency_key=idempotency_key)
        self.store.save_checkpoint(run["run_id"], node_name=SHARED_KEY,
                                   payload={
            "policy_snapshot": policy_snapshot(policy),
            "queue_deadline_at": deadline.isoformat(),
            "budget": {"regions_used": 0, "vlm_tokens_used": 0,
                       "budget_exhausted": False},
            "billing": [], "final": None, "resolution": None,
            "region": None, "signals": {}, "candidate_set": None,
            "qwen": None, "human_reason": None, "last_risk": None,
        })
        return self._engine.execute(
            run["run_id"], self._handlers(policy), self._routers())

    def resume(self, run_id: str,
               resolution: dict[str, Any] | None = None, *,
               approved: bool = True, actor: str = "human") -> dict[str, Any]:
        """人工裁决后恢复（跨进程：任何持同一 store 的新实例均可）。"""
        if not approved:
            return self._engine.approve_human_gate(
                run_id, approved=False, actor=actor)
        shared = self.store.load_checkpoint(run_id, SHARED_KEY) or {}
        if resolution is not None:
            decision = resolution.get("decision")
            if decision not in DECISIONS:
                raise ValueError(
                    f"人工裁决 decision 非法: {decision!r}（合法 {DECISIONS}）")
            if decision == "accepted" and (
                    not resolution.get("sku_id")
                    or not resolution.get("evidence_ids")):
                raise ValueError("人工 accepted 必须携带 sku_id 与证据 ID")
            shared["resolution"] = dict(resolution)
            self.store.save_checkpoint(run_id, node_name=SHARED_KEY,
                                       payload=shared)
        self._engine.approve_human_gate(run_id, approved=True, actor=actor)
        run = self.store.get_run(run_id)
        policy = policy_for(json.loads(run["input_json"])["tier"])
        return self._engine.execute(
            run_id, self._handlers(policy), self._routers())

    # ---------- 视图 ----------

    def result(self, run_id: str) -> dict[str, Any] | None:
        run = self.store.get_run(run_id)
        if run is None or not run.get("output_json"):
            return None
        outputs = json.loads(run["output_json"])
        return outputs.get("finalize")

    def trail(self, run_id: str) -> list[dict[str, Any]]:
        """决策轨迹：内核 trail + 各节点 policy/risk/budget/SLA/证据明细。"""
        state = self.store.load_checkpoint(run_id, STATE_KEY) or {}
        outputs = state.get("outputs", {})
        merged = []
        for t in state.get("trail", []):
            detail = outputs.get(t["node"], {}).get("trail", {})
            merged.append({**t, "detail": detail})
        return merged

    def billing(self, run_id: str) -> list[dict[str, Any]]:
        shared = self.store.load_checkpoint(run_id, SHARED_KEY) or {}
        return list(shared.get("billing", []))

    def sla_hours(self, tier: str) -> float:
        """队列业务 SLA（12/48h）：供 Web/API 展示剩余 SLA，非推理 timeout。"""
        return policy_for(tier).queue_sla_hours

    # ---------- handlers ----------

    def _handlers(self, policy: Any) -> dict[str, Any]:
        return {
            "quality": self._h_quality,
            "scene": self._h_scene,
            "detect": self._h_detect,
            "classify_fast": self._h_classify,
            "risk_s1": self._h_risk("S1"),
            "segment": self._h_segment,
            "reclassify": self._h_reclassify,
            "risk_s2": self._h_risk("S2"),
            "retrieve": self._h_retrieve,
            "risk_s3": self._h_risk("S3"),
            "vlm_rerank": self._h_vlm,
            "risk_s4": self._h_risk_s4,
            "human_review": self._h_human,
            "finalize": self._h_finalize,
        }

    @staticmethod
    def _routers() -> dict[str, Any]:
        by_route = lambda output, state: output.get("route")  # noqa: E731
        return {node: by_route for node in
                ("quality", "detect", "risk_s1", "risk_s2", "risk_s3",
                 "vlm_rerank", "risk_s4")}

    # -- 工具 --

    def _bill(self, ctx, capability: str) -> None:
        shared = ctx.shared_get("billing") or []
        key = f"{ctx.node_name.split('#')[0]}#r{ctx.round}"
        if any(e["key"] == key for e in shared):
            return  # 幂等：同一 attempt 不重复计费
        shared.append({"key": key, "node": key.split("#")[0],
                       "round": ctx.round, "capability": capability,
                       "billed_at": _utcnow().isoformat()})
        ctx.shared_set("billing", shared)

    def _budget(self, ctx) -> dict[str, Any]:
        return ctx.shared_get("budget") or {}

    def _trail_meta(self, ctx, *, model: str, risk: float | None = None,
                    evidence_ids: list[str] | None = None,
                    reasons: list[str] | None = None,
                    budget_before: dict | None = None) -> dict[str, Any]:
        snap = ctx.shared_get("policy_snapshot") or {}
        return {
            "policy_version": snap.get("policy_version"),
            "tier": snap.get("tier"),
            "risk": risk,
            "budget_before": budget_before or self._budget(ctx),
            "budget_after": self._budget(ctx),
            "sla_hours": (snap.get("policy") or {}).get("queue_sla_hours"),
            "queue_deadline_at": ctx.shared_get("queue_deadline_at"),
            "model": model,
            "evidence_ids": list(evidence_ids or []),
            "reasons": list(reasons or []),
        }

    def _set_final(self, ctx, *, decision: str, sku_id: str | None,
                   evidence_ids: list[str], reason: str, stage: str,
                   package_version_id: str | None = None) -> None:
        ctx.shared_set("final", {
            "decision": decision, "sku_id": sku_id,
            "package_version_id": package_version_id,
            "evidence_ids": list(evidence_ids),
            "reason": reason, "stage": stage,
        })

    def _sla_expired(self, ctx) -> bool:
        dl = ctx.shared_get("queue_deadline_at")
        if not dl:
            return False
        return _utcnow() > datetime.fromisoformat(dl)

    # -- 节点实现 --

    def _h_quality(self, ctx):
        self._bill(ctx, CAP_QUALITY)
        asset = ctx.run_input["asset"]
        out = self.adapters[CAP_QUALITY].assess(asset)
        verdict = out.get("verdict")
        ev = out.get("evidence") or {}
        evidence_ids = [f"quality:{ev.get('sha256', '')}"]
        if verdict in ("pass", "warn"):
            route = "scene"
        else:  # manual_review/reject：不得进入识别
            route = "blocked"
            self._set_final(ctx, decision="needs_review", sku_id=None,
                            evidence_ids=evidence_ids,
                            reason=f"quality_{verdict}", stage="S0")
        return {"route": route, "verdict": verdict,
                "trail": self._trail_meta(ctx, model="quality-rules",
                                          evidence_ids=evidence_ids,
                                          reasons=[f"verdict={verdict}"])}

    def _h_scene(self, ctx):
        self._bill(ctx, CAP_SCENE)
        out = self.adapters[CAP_SCENE].classify(ctx.run_input["asset"])
        return {"route": "detect", "scene": out.get("scene"),
                "trail": self._trail_meta(
                    ctx, model=f"scene:{out.get('source')}",
                    reasons=[f"scene={out.get('scene')}"])}

    def _h_detect(self, ctx):
        self._bill(ctx, CAP_DETECT)
        before = self._budget(ctx)
        out = self.adapters[CAP_DETECT].detect(ctx.run_input["asset"])
        regions = list(out.get("regions") or [])
        snap = ctx.shared_get("policy_snapshot") or {}
        max_regions = (snap.get("budget") or {}).get("max_regions", 16)
        if len(regions) > max_regions:
            budget = self._budget(ctx)
            budget["budget_exhausted"] = True
            ctx.shared_set("budget", budget)
            regions = regions[:max_regions]
        budget = self._budget(ctx)
        budget["regions_used"] += len(regions)
        ctx.shared_set("budget", budget)
        if not regions:
            self._set_final(ctx, decision="needs_review", sku_id=None,
                            evidence_ids=[], reason="no_product_detected",
                            stage="S1")
            return {"route": "no_product",
                    "trail": self._trail_meta(ctx, model=out.get("model_id", ""),
                                              budget_before=before,
                                              reasons=["no_product"])}
        ctx.shared_set("region", regions[0])
        return {"route": "classify", "regions": len(regions),
                "trail": self._trail_meta(
                    ctx, model=f"{out.get('model_id')}:{out.get('model_version')}",
                    budget_before=before,
                    reasons=[f"regions={len(regions)}"])}

    def _h_classify(self, ctx, *, slot: str = CAP_FAST_SKU) -> dict:
        self._bill(ctx, CAP_FAST_SKU)
        region = ctx.shared_get("region")
        out = self.adapters[slot].classify(region)
        ctx.shared_set("signals", dict(out.get("signals") or {}))
        ctx.shared_set("top_sku", out.get("top_sku"))
        ctx.shared_set("classify_evidence", list(out.get("evidence_ids") or []))
        return {"route": "risk",
                "trail": self._trail_meta(
                    ctx, model=f"{out.get('model_id')}:{out.get('model_version')}",
                    evidence_ids=list(out.get("evidence_ids") or []),
                    reasons=[f"top_sku={out.get('top_sku')}"])}

    def _h_reclassify(self, ctx):
        return self._h_classify(ctx, slot="reclassify")

    def _h_risk(self, stage: str):
        def handler(ctx):
            budget = self._budget(ctx)
            if self._sla_expired(ctx):
                ctx.shared_set("human_reason", "sla_expired")
                ctx.shared_set("last_risk", 1.0)
                self.store.append_audit(
                    actor="cascade", action="cascade.sla_expired",
                    subject_type="run", subject_id=ctx.run_id,
                    detail={"stage": stage})
                return {"route": "human", "stage": stage, "sla_expired": True,
                        "trail": self._trail_meta(
                            ctx, model="risk-router", risk=1.0,
                            reasons=["sla_expired"])}
            if budget.get("budget_exhausted"):
                rd = budget_exhausted_decision(
                    policy_for(ctx.run_input["tier"]),
                    reason="regions_budget_exhausted")
                ctx.shared_set("human_reason", "budget_exhausted")
            else:
                rd = decide_risk(stage=stage,
                                 signals=ctx.shared_get("signals") or {},
                                 calibrator=self._calibrator,
                                 policy=policy_for(ctx.run_input["tier"]))
            ctx.shared_set("last_risk", rd.risk)
            if rd.route == "accept":
                self._set_final(
                    ctx, decision="accepted",
                    sku_id=ctx.shared_get("top_sku"),
                    evidence_ids=ctx.shared_get("classify_evidence") or [],
                    reason=f"accept_at_{stage}", stage=stage)
            elif rd.route in ("human", "budget_exhausted"):
                ctx.shared_set("human_reason",
                               ctx.shared_get("human_reason")
                               or f"risk_human_at_{stage}")
            return {"route": rd.route, "stage": stage, "risk": rd.risk,
                    "next_stage": rd.next_stage,
                    "trail": self._trail_meta(
                        ctx, model=f"risk:{rd.calibrator_version}",
                        risk=rd.risk, reasons=list(rd.reasons))}
        return handler

    def _h_segment(self, ctx):
        self._bill(ctx, CAP_SAM)
        region = ctx.shared_get("region")
        out = self.adapters[CAP_SAM].refine(ctx.run_input["asset"],
                                            region["box_px"])
        ctx.shared_set("sam", out)
        ev = out.get("evidence") or {}
        return {"route": "reclassify",
                "trail": self._trail_meta(
                    ctx, model="sam-refine",
                    evidence_ids=[f"sam:{ev.get('sha256', '')}"],
                    reasons=["segmented"])}

    def _h_retrieve(self, ctx):
        self._bill(ctx, CAP_RETRIEVE)
        region = ctx.shared_get("region")
        out = self.adapters[CAP_RETRIEVE].retrieve(
            region_id=region["region_id"],
            signals=ctx.shared_get("signals") or {})
        ctx.shared_set("candidate_set", out)
        ctx.shared_set("signals", dict(out.get("signals") or {}))
        return {"route": "risk",
                "trail": self._trail_meta(
                    ctx, model=f"retrieve:{out.get('retrieval_version')}",
                    evidence_ids=[f"cs:{region['region_id']}"],
                    reasons=[f"candidates={len(out.get('candidates') or [])}"])}

    def _h_vlm(self, ctx):
        self._bill(ctx, CAP_QWEN)
        snap = ctx.shared_get("policy_snapshot") or {}
        max_tokens = (snap.get("budget") or {}).get(
            "max_vlm_input_tokens", 1024)
        budget = self._budget(ctx)
        if budget.get("vlm_tokens_used", 0) >= max_tokens:
            ctx.shared_set("human_reason", "budget_exhausted")
            return {"route": "budget_exhausted",
                    "trail": self._trail_meta(
                        ctx, model="qwen3-vl:4b",
                        reasons=["vlm_token_budget_exhausted"])}
        cs = ctx.shared_get("candidate_set") or {}
        region = ctx.shared_get("region") or {}
        context = {"asset_sha": ctx.run_input["asset"]["sha256"],
                   "region": region,
                   "registry_version": cs.get("registry_version")}
        try:
            res = self.adapters[CAP_QWEN].rerank(
                context, candidates=cs.get("candidates"), run_id=ctx.run_id)
        except _QWEN_ERRORS as e:
            ctx.shared_set("human_reason", "vlm_unavailable")
            return {"route": "vlm_unavailable",
                    "trail": self._trail_meta(
                        ctx, model="qwen3-vl:4b",
                        reasons=[f"vlm_unavailable:{type(e).__name__}"])}
        usage = res.usage or {}
        budget["vlm_tokens_used"] += int(usage.get("input_tokens", 0)) \
            + int(usage.get("output_tokens", 0))
        ctx.shared_set("budget", budget)
        ctx.shared_set("qwen", {"decision": res.decision,
                                "sku_id": res.sku_id,
                                "package_version_id": res.package_version_id,
                                "abstain_reason": res.abstain_reason})
        route = {"accepted": "accepted",
                 "new_package": "new_package"}.get(res.decision, "unknown")
        if route == "unknown":
            ctx.shared_set("human_reason", "unknown_sku")
        return {"route": route, "decision": res.decision,
                "trail": self._trail_meta(
                    ctx, model="qwen3-vl:4b",
                    reasons=[f"qwen_decision={res.decision}"])}

    def _h_risk_s4(self, ctx):
        qwen = ctx.shared_get("qwen") or {}
        decision = qwen.get("decision")
        if decision == "accepted":
            signals = {"top1": 0.95, "margin": 0.9, "entropy": 0.1}
        elif decision == "new_package":
            signals = {"top1": 0.9, "margin": 0.7, "entropy": 0.2}
        else:  # unknown/needs_review：低置信，交由人工
            signals = {"top1": 0.35, "margin": 0.1, "entropy": 1.5}
        rd = decide_risk(stage="S4", signals=signals,
                         calibrator=self._calibrator,
                         policy=policy_for(ctx.run_input["tier"]))
        ctx.shared_set("last_risk", rd.risk)
        if rd.route == "accept":
            final_decision = ("new_package" if decision == "new_package"
                              else "accepted")
            self._set_final(
                ctx, decision=final_decision, sku_id=qwen.get("sku_id"),
                package_version_id=qwen.get("package_version_id"),
                evidence_ids=[f"qwen:{ctx.run_id}"],
                reason=f"qwen_{decision}_at_S4", stage="S4")
        else:
            ctx.shared_set("human_reason",
                           ctx.shared_get("human_reason") or "risk_human_at_S4")
        return {"route": rd.route, "stage": "S4", "risk": rd.risk,
                "trail": self._trail_meta(
                    ctx, model=f"risk:{rd.calibrator_version}",
                    risk=rd.risk, reasons=list(rd.reasons))}

    def _h_human(self, ctx):
        self._bill(ctx, CAP_HUMAN)
        resolution = ctx.shared_get("resolution")
        if resolution:  # 人工已裁决：登记终局并放行
            d = resolution["decision"]
            self._set_final(ctx, decision=d,
                            sku_id=resolution.get("sku_id"),
                            evidence_ids=resolution.get("evidence_ids") or [],
                            reason="human_resolution", stage="S5")
            return {"route": "finalize", "resolved": True,
                    "trail": self._trail_meta(
                        ctx, model="human-review",
                        evidence_ids=resolution.get("evidence_ids") or [],
                        reasons=[f"human_decision={d}"])}
        reason = ctx.shared_get("human_reason") or "risk_human"
        handoff = self.adapters[CAP_HUMAN].handoff(
            run_id=ctx.run_id, stage="S5", reason=reason,
            policy_version=(ctx.shared_get("policy_snapshot") or {}).get(
                "policy_version", ""),
            risk=ctx.shared_get("last_risk"))
        ctx.shared_set("handoff", handoff)
        ctx.request_human(f"{reason}: S5 人工审核（人工裁决前不得自动接受）")

    def _h_finalize(self, ctx):
        final = ctx.shared_get("final")
        if not final:
            raise RuntimeError("finalize 缺少终局决策（fail-closed）")
        snap = ctx.shared_get("policy_snapshot") or {}
        policy = snap.get("policy") or {}
        return {
            **final,
            "policy_version": snap.get("policy_version"),
            "tier": snap.get("tier"),
            "risk": ctx.shared_get("last_risk"),
            "budget": self._budget(ctx),
            "sla_hours": policy.get("queue_sla_hours"),
            "queue_deadline_at": ctx.shared_get("queue_deadline_at"),
            "trail": self._trail_meta(ctx, model="finalize"),
        }
