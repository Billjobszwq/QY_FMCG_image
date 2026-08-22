"""Synthesizer（Task 10 / G8）。

只基于**已核验**的 Claim Graph 生成报告（不直接读原始自由文本）；
高重要性 unsupported/contradicted Claim 未过引证门时拒绝发布；
无有效证据时 abstain（不编造）。报告绑定 corpus/index/model/prompt/
policy snapshot（02 §6/§8.3）。
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from ..context import CognitiveContext
from ..errors import CognitionPolicyError, CognitionValidationError
from ..repository import CognitionRepository
from .citations import CitationVerifier


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Synthesizer:
    def __init__(self, store: Any) -> None:
        self.store = store
        self.repo = CognitionRepository(store)
        self.verifier = CitationVerifier(store)

    def build_report(self, research_run_id: str, *,
                     ctx: CognitiveContext, report_id: str,
                     corpus_snapshot_id: str = "",
                     index_snapshot_ids: list[str] | None = None,
                     model_profile_ids: list[str] | None = None,
                     prompt_version: str = "synthesizer@1",
                     policy_version: str = "policy@1") -> dict[str, Any]:
        """核验引证门并构造报告插入列（不做提交；调用方负责事务）。

        gate 失败抛 CognitionPolicyError（报告不得发布）。R2-04：该
        结果必须随终态 UoW 同事务落账，不得在 succeeded 之前独立提交。
        """
        verification = self.verifier.verify_run(research_run_id, ctx=ctx)
        if not verification["gate_ok"]:
            raise CognitionPolicyError(
                "引证门失败：高重要性 Claim 缺有效引证/存在未裁决冲突，"
                f"报告不得发布（blocking={verification['blocking_claims']}）")
        verdict_by_id = {v["claim_id"]: v
                         for v in verification["verdicts"]}
        claims = self.store._conn.execute(
            "SELECT * FROM research_claim_v1 WHERE research_run_id=?"
            " ORDER BY created_at", (research_run_id,)).fetchall()
        included, citations = [], []
        for c in claims:
            c = dict(c)
            v = verdict_by_id.get(c["claim_id"], {})
            if v.get("verdict") in ("remove", "research_more"):
                continue  # 被移除/待补研究的 Claim 不进入报告
            entry = {"claim_id": c["claim_id"], "text": c["text"],
                     "claim_type": c["claim_type"],
                     "importance": c["importance"],
                     "support_status": c["support_status"],
                     "verdict": v.get("verdict", "pass")}
            included.append(entry)
            for sid in v.get("valid_spans", []):
                citations.append({"claim_id": c["claim_id"],
                                  "span_id": sid,
                                  "relation": "supports"})
        abstain = 1 if not included else 0
        body = {
            "sections": {
                "facts": [e for e in included
                          if e["claim_type"] == "fact"],
                "inferences": [e for e in included
                               if e["claim_type"] == "inference"],
                "recommendations": [e for e in included
                                    if e["claim_type"] == "recommendation"],
                "unknowns": [e for e in included
                             if e["claim_type"] == "unknown"],
            },
            "abstain": bool(abstain),
            "note": ("证据不足，拒绝给出结论（abstain）"
                     if abstain else ""),
        }
        return {"report_id": report_id,
                "research_run_id": research_run_id,
                "abstain": abstain,
                "body": body,
                "claims": included,
                "citations": citations,
                "corpus_snapshot_id": corpus_snapshot_id,
                "index_snapshot_ids": index_snapshot_ids or [],
                "model_profile_ids": model_profile_ids or [],
                "prompt_version": prompt_version,
                "policy_version": policy_version,
                "verification": verification}

    def insert_report(self, conn: Any, rep: dict[str, Any]) -> None:
        """按 build_report 结果写不可变报告行（conn 由调用方事务控制）。"""
        conn.execute(
            "INSERT INTO research_report_v1 (report_id,"
            " research_run_id, abstain, body_json, claims_json,"
            " citations_json, corpus_snapshot_id, index_snapshot_ids_json,"
            " model_profile_ids_json, prompt_version, policy_version,"
            " created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (rep["report_id"], rep["research_run_id"], rep["abstain"],
             json.dumps(rep["body"], ensure_ascii=False),
             json.dumps(rep["claims"], ensure_ascii=False),
             json.dumps(rep["citations"], ensure_ascii=False),
             rep["corpus_snapshot_id"],
             json.dumps(rep["index_snapshot_ids"], ensure_ascii=False),
             json.dumps(rep["model_profile_ids"], ensure_ascii=False),
             rep["prompt_version"], rep["policy_version"], _now()))

    def synthesize(self, research_run_id: str, *, ctx: CognitiveContext,
                   corpus_snapshot_id: str = "",
                   index_snapshot_ids: list[str] | None = None,
                   model_profile_ids: list[str] | None = None,
                   prompt_version: str = "synthesizer@1",
                   policy_version: str = "policy@1") -> dict[str, Any]:
        if ctx is None:
            raise CognitionValidationError("缺 CognitiveContext")
        report_id = "rep-" + uuid.uuid4().hex[:14]
        rep = self.build_report(
            research_run_id, ctx=ctx, report_id=report_id,
            corpus_snapshot_id=corpus_snapshot_id,
            index_snapshot_ids=index_snapshot_ids,
            model_profile_ids=model_profile_ids,
            prompt_version=prompt_version, policy_version=policy_version)
        self.insert_report(self.store._conn, rep)
        self.store._conn.commit()
        return {"report_id": rep["report_id"],
                "research_run_id": research_run_id,
                "abstain": bool(rep["abstain"]), "body": rep["body"],
                "claims": rep["claims"], "citations": rep["citations"],
                "snapshots": {
                    "corpus_snapshot_id": rep["corpus_snapshot_id"],
                    "index_snapshot_ids": rep["index_snapshot_ids"],
                    "model_profile_ids": rep["model_profile_ids"],
                    "prompt_version": rep["prompt_version"],
                    "policy_version": rep["policy_version"]},
                "verification": rep["verification"]}
