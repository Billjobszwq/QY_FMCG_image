"""VLM-012 TDD：S0–S5 Graph+Loop 级联编排（14 节点 + 四条路由 + 门禁语义）。

四条路径：
1. fast：S0→S1→accepted；
2. standard：S1 高风险→S2→accepted；
3. expert：S2/S3 冲突→S4（Qwen 闭集裁决）→accepted；
4. unknown：S4→S5 waiting_human→跨进程恢复。

同时覆盖：预算耗尽→人工、VLM 不可用→人工、SLA 过期→人工、
idempotency 重试不重复计费、决策轨迹含 policy/risk/budget/SLA/证据。
全部 fake backend，不加载任何真实模型。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.modules.fmcg.adapters.human_review import HumanReviewAdapter
from src.modules.fmcg.adapters.qwen3vl_mlx import (
    QwenTransportError,
    RerankResult,
)
from src.modules.fmcg.cascade.graph import CASCADE_GRAPH, CASCADE_NODES
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
from src.modules.fmcg.cascade.service import CascadeService
from src.platform.data.store import PlatformStore

ASSET = {"asset_id": "A-1", "sha256": "ab" * 32,
         "image_width": 640, "image_height": 480}


# ---------- fake adapters（不加载任何真实模型） ----------

class FakeQuality:
    capability_id = CAP_QUALITY

    def __init__(self, verdict: str = "pass") -> None:
        self._v = verdict

    def assess(self, image_ref: dict) -> dict:
        return {"verdict": self._v, "scores": {},
                "evidence": {"sha256": image_ref["sha256"],
                             "rule_version": "quality-gate.v2"}}


class FakeScene:
    capability_id = CAP_SCENE

    def classify(self, image_ref: dict) -> dict:
        return {"scene": "shelf", "price_tag": "unknown", "source": "model"}


class FakeDetect:
    capability_id = CAP_DETECT

    def __init__(self, n_regions: int = 1) -> None:
        self._n = n_regions

    def detect(self, image_ref: dict) -> dict:
        regions = [
            {"region_id": f"R-{i}", "box_px": [10.0 * i, 10.0, 60.0, 80.0]}
            for i in range(self._n)
        ]
        return {"regions": regions, "model_id": "yolo11n",
                "model_version": "e2-v0"}


class FakeClassify:
    """S1/S2 共用：信号可控，entropy 低才能过校准阈值。"""

    capability_id = CAP_FAST_SKU

    def __init__(self, *, top1: float, sku: str = "SKU-1",
                 entropy: float = 0.1) -> None:
        self._sig = {"top1": top1, "margin": max(0.0, top1 - 0.05),
                     "entropy": entropy}
        self._sku = sku

    def classify(self, region: dict) -> dict:
        return {"signals": dict(self._sig), "top_sku": self._sku,
                "model_id": "resnet50", "model_version": "cls-v0",
                "evidence_ids": [f"ev-{region['region_id']}"]}


class FakeSam:
    capability_id = CAP_SAM

    def refine(self, image_ref: dict, box: list) -> dict:
        return {"crops": {"coarse": list(box), "mask": list(box),
                          "context": list(box)},
                "needs_review": False,
                "evidence": {"sha256": image_ref["sha256"]}}


class FakeRetrieval:
    capability_id = CAP_RETRIEVE

    def __init__(self, *, conflicts: list | None = None) -> None:
        self._conflicts = conflicts or []

    def retrieve(self, *, region_id: str, signals: dict) -> dict:
        return {"candidates": [{"sku_id": "SKU-1", "score": 0.9},
                               {"sku_id": "SKU-2", "score": 0.6}],
                "registry_version": "reg-v1",
                "retrieval_version": "retrieval.v1",
                "signals": {**signals, "retrieval_margin": 0.3,
                            "attribute_conflicts": list(self._conflicts)}}


class FakeQwen:
    capability_id = CAP_QWEN

    def __init__(self, *, decision: str = "accepted", sku: str = "SKU-1",
                 unavailable: bool = False) -> None:
        self._decision = decision
        self._sku = sku
        self._unavailable = unavailable
        self.calls = 0

    def rerank(self, context: dict, *, candidates, run_id: str):
        self.calls += 1
        if self._unavailable:
            raise QwenTransportError("vlm_unavailable: 训练冲突熔断")
        return RerankResult(decision=self._decision, sku_id=self._sku,
                            latency_ms=12.0,
                            usage={"input_tokens": 300, "output_tokens": 20})


def _make_adapters(tmp_path: Path, *, quality="pass", detect_n=1,
                   s1_top1=0.99, s2_top1=0.99, conflicts=None,
                   qwen_decision="accepted", qwen_unavailable=False):
    return {
        CAP_QUALITY: FakeQuality(quality),
        CAP_SCENE: FakeScene(),
        CAP_DETECT: FakeDetect(detect_n),
        CAP_FAST_SKU: FakeClassify(top1=s1_top1),
        "reclassify": FakeClassify(top1=s2_top1),
        CAP_SAM: FakeSam(),
        CAP_RETRIEVE: FakeRetrieval(conflicts=conflicts),
        CAP_QWEN: FakeQwen(decision=qwen_decision,
                           unavailable=qwen_unavailable),
        CAP_HUMAN: HumanReviewAdapter(),
    }


@pytest.fixture()
def store(tmp_path: Path):
    s = PlatformStore(tmp_path / "p.sqlite")
    yield s
    s.close()


def _svc(store, **kw):
    return CascadeService(store, _make_adapters(Path("."), **kw))


# ---------- 图定义（14 节点） ----------

def test_graph_has_exactly_14_nodes() -> None:
    assert CASCADE_NODES == (
        "quality", "scene", "detect", "classify_fast", "risk_s1",
        "segment", "reclassify", "risk_s2", "retrieve", "risk_s3",
        "vlm_rerank", "risk_s4", "human_review", "finalize")
    assert tuple(CASCADE_GRAPH.nodes) == CASCADE_NODES
    assert CASCADE_GRAPH.entry == "quality"


# ---------- 四条路由 ----------

def test_fast_route_s0_s1_accepted(store) -> None:
    svc = _svc(store)
    out = svc.submit(ASSET, tier="fast")
    assert out["status"] == "completed"
    res = svc.result(out["run_id"])
    assert res["decision"] == "accepted"
    assert res["sku_id"] == "SKU-1"
    visited = {t["node"] for t in svc.trail(out["run_id"])}
    assert {"quality", "scene", "detect", "classify_fast", "risk_s1",
            "finalize"} <= visited
    assert "vlm_rerank" not in visited  # fast 档不依赖 VLM


def test_standard_route_escalates_to_s2(store) -> None:
    svc = _svc(store, s1_top1=0.5)  # S1 高风险 → S2
    out = svc.submit(ASSET, tier="standard")
    assert out["status"] == "completed"
    res = svc.result(out["run_id"])
    assert res["decision"] == "accepted"
    visited = {t["node"] for t in svc.trail(out["run_id"])}
    assert {"segment", "reclassify", "risk_s2"} <= visited
    assert "vlm_rerank" not in visited  # standard 档 max_stage=S2


def test_expert_route_conflict_to_s4_vlm(store) -> None:
    svc = _svc(store, s1_top1=0.5, s2_top1=0.6,
               conflicts=["净含量OCR与候选不一致"])
    out = svc.submit(ASSET, tier="expert")
    assert out["status"] == "completed"
    res = svc.result(out["run_id"])
    assert res["decision"] == "accepted"
    assert res["sku_id"] == "SKU-1"
    visited = [t["node"] for t in svc.trail(out["run_id"])]
    assert "vlm_rerank" in visited and "risk_s4" in visited
    # Qwen 只被调用一次（闭集裁决）
    assert svc.adapters[CAP_QWEN].calls == 1


def test_unknown_route_s5_waiting_human_and_cross_process_resume(store) -> None:
    svc = _svc(store, s1_top1=0.5, s2_top1=0.6, qwen_decision="unknown")
    out = svc.submit(ASSET, tier="expert")
    assert out["status"] == "waiting_human"
    run_id = out["run_id"]

    # 跨进程恢复：全新 service 实例（同一 store）接管
    svc2 = CascadeService(store, _make_adapters(Path("."),
                                                s1_top1=0.5, s2_top1=0.6,
                                                qwen_decision="unknown"))
    out2 = svc2.resume(run_id, resolution={"decision": "accepted",
                                           "sku_id": "SKU-9",
                                           "evidence_ids": ["ev-human-1"]},
                       actor="reviewer")
    assert out2["status"] == "completed"
    res = svc2.result(run_id)
    assert res["decision"] == "accepted"
    assert res["sku_id"] == "SKU-9"
    assert any("ev-human-1" in e for e in res["evidence_ids"])


# ---------- 门禁语义 ----------

def test_budget_exhausted_goes_to_human(store) -> None:
    svc = _svc(store, detect_n=99)  # fast 档 max_regions=8
    out = svc.submit(ASSET, tier="fast")
    assert out["status"] == "waiting_human"
    trail = svc.trail(out["run_id"])
    assert any("budget_exhausted" in str(t.get("reason", ""))
               or t.get("label") == "budget_exhausted" for t in trail)


def test_vlm_unavailable_goes_to_human(store) -> None:
    svc = _svc(store, s1_top1=0.5, s2_top1=0.6,
               conflicts=["冲突"], qwen_unavailable=True)
    out = svc.submit(ASSET, tier="expert")
    assert out["status"] == "waiting_human"
    assert svc.adapters[CAP_QWEN].calls == 1  # 失败不无限重试


def test_sla_expired_goes_to_human(store) -> None:
    svc = _svc(store, s1_top1=0.5)
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    out = svc.submit(ASSET, tier="standard", queue_deadline_at=past)
    assert out["status"] == "waiting_human"
    res_trail = str(svc.trail(out["run_id"]))
    assert "sla_expired" in res_trail


def test_idempotent_retry_does_not_double_bill(store) -> None:
    svc = _svc(store)
    r1 = svc.submit(ASSET, tier="fast", idempotency_key="task-001")
    ledger_1 = svc.billing(r1["run_id"])
    assert ledger_1  # 每个节点 attempt 都计费一次
    r2 = svc.submit(ASSET, tier="fast", idempotency_key="task-001")
    assert r2["run_id"] == r1["run_id"]
    assert svc.billing(r1["run_id"]) == ledger_1  # 不重复计费


def test_trail_records_policy_risk_budget_sla_evidence(store) -> None:
    svc = _svc(store)
    out = svc.submit(ASSET, tier="fast")
    res = svc.result(out["run_id"])
    # 决策轨迹不只写 route label：policy/risk/budget/SLA/模型/证据
    assert res["policy_version"] == "cascade-policy.v1"
    assert res["tier"] == "fast"
    assert "risk" in res and "budget" in res
    assert res["sla_hours"] == 12.0
    assert res["evidence_ids"]
    ledger = svc.billing(out["run_id"])
    caps = {e["capability"] for e in ledger}
    assert CAP_QUALITY in caps and CAP_FAST_SKU in caps


def test_quality_manual_review_blocks_entry(store) -> None:
    svc = _svc(store, quality="manual_review")
    out = svc.submit(ASSET, tier="fast")
    assert out["status"] == "completed"
    res = svc.result(out["run_id"])
    assert res["decision"] == "needs_review"
    visited = {t["node"] for t in svc.trail(out["run_id"])}
    assert "detect" not in visited  # 质量门未过不得进入识别


def test_human_reject_is_terminal(store) -> None:
    svc = _svc(store, s1_top1=0.5, s2_top1=0.6, qwen_decision="unknown")
    out = svc.submit(ASSET, tier="expert")
    assert out["status"] == "waiting_human"
    out2 = svc.resume(out["run_id"], approved=False, actor="reviewer")
    assert out2["status"] == "failed"
