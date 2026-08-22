"""Citation Verifier（Task 10 / G8 / 03 §6）。

逐 Claim 核验引证：
- span 必须真实存在且可回到已发布、当前生效、scope 匹配的来源；
- supported 但 span 失效 → 按重要性给 remove/narrow；
- contradicted → research_more（冲突并列，不静默选边）；
- 高重要性 Claim 若 unsupported/contradicted/span 失效 → gate 失败，
  报告不得发布（02 §6、03 §6）。
verdict 集合：pass / narrow / relabel / remove / research_more。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from ..context import CognitiveContext
from ..repository import CognitionRepository

VERDICTS = ("pass", "narrow", "relabel", "remove", "research_more")


def _parse_ts(v: Any) -> datetime | None:
    if not v:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


class CitationVerifier:
    def __init__(self, store: Any, *, support_verifier: Any = None) -> None:
        self.store = store
        self.repo = CognitionRepository(store)
        if support_verifier is None:
            from .claims import DeterministicClaimSupportVerifier
            support_verifier = DeterministicClaimSupportVerifier()
        self.support = support_verifier

    # ---------- span 文本 / 支持关系持久化 ----------

    def _span_text(self, span_id: str) -> str:
        """span → 原文（chunk text 优先，其次 evidence span 归一 quote）。"""
        row = self.store._conn.execute(
            "SELECT text FROM cognition_chunk_v1 WHERE chunk_id=?",
            (span_id,)).fetchone()
        if row is not None:
            return row["text"] or ""
        sp = self.repo.get_span(span_id)
        return (sp or {}).get("normalized_quote", "") or ""

    def _persist_relation(self, claim_id: str, span_id: str,
                          relation: str, score: float, reason: str
                          ) -> None:
        from .claims import input_hash
        version = f"{self.support.verifier_id}@{self.support.verifier_version}"
        self.store._conn.execute(
            "UPDATE claim_evidence_v1 SET relation=?, verifier_score=?,"
            " verifier_version=? WHERE claim_id=? AND span_id=?",
            (relation, float(score), version, claim_id, span_id))
        self.store._conn.commit()

    # ---------- span 溯源 ----------

    def _span_sources(self, span_id: str) -> list[dict]:
        """span → 全部引用它的已发布 knowledge 条目（评审 #G8-10：
        同一 span 可能被多个条目引用，须逐一核验而非取第一条）。"""
        span = self.repo.get_span(span_id)
        if span is None:
            return []
        rows = self.store._conn.execute(
            "SELECT * FROM knowledge_item_version WHERE status="
            "'published'").fetchall()
        out = []
        for r in rows:
            ids = json.loads(r["source_span_ids_json"] or "[]")
            if span_id in ids:
                d = dict(r)
                d["_span"] = span
                out.append(d)
        return out

    def _span_underlying_source_ok(self, span_id: str) -> bool:
        """span → chunk → document → source：底层 source 被隔离/撤销/
        取代时，其引证不可用（02 §8.1/§8.2，评审 #G6-2）。"""
        chunk_row = self.store._conn.execute(
            "SELECT document_id, document_version FROM cognition_chunk_v1"
            " WHERE chunk_id=?", (span_id,)).fetchone()
        if chunk_row is None:
            return True  # 非 chunk 型 span（如测试 span）不校验底层
        doc_row = self.store._conn.execute(
            "SELECT source_id FROM cognition_document_version_v1 WHERE"
            " document_id=? AND version=?",
            (chunk_row["document_id"],
             chunk_row["document_version"])).fetchone()
        if doc_row is None:
            return True
        src_row = self.store._conn.execute(
            "SELECT status FROM cognition_source_artifact_v1 WHERE"
            " source_id=?", (doc_row["source_id"],)).fetchone()
        if src_row is None:
            return True
        return src_row["status"] not in ("quarantined", "revoked",
                                         "superseded")

    def _check_span(self, span_id: str, ctx: CognitiveContext
                    ) -> tuple[bool, str]:
        sources = self._span_sources(span_id)
        if not sources:
            return False, "span_missing_or_source_unpublished"
        last_reason = "span_missing_or_source_unpublished"
        for src in sources:
            ok, reason = self._check_one_source(src, ctx)
            if ok:
                return True, ""
            last_reason = reason
        return False, last_reason

    def _check_one_source(self, src: dict, ctx: CognitiveContext
                          ) -> tuple[bool, str]:
        # 底层 source 状态（隔离/撤销/取代 → 不可用，评审 #G6-2）
        if not self._span_underlying_source_ok(src["_span"]["span_id"]):
            return False, "underlying_source_unavailable"
        # 时间有效性（temporal validity，03 §6）
        as_of = ctx.as_of
        frm = _parse_ts(src["effective_from"])
        to = _parse_ts(src["effective_to"])
        if frm is not None and as_of < frm:
            return False, "not_yet_effective"
        if to is not None and as_of >= to:
            return False, "expired"
        # scope 有效性（03 §6：tenant/data_scope/test_run/customer/project）
        if src["tenant_id"] != ctx.tenant_id:
            return False, "tenant_mismatch"
        if src["data_scope"] != ctx.data_scope:
            return False, "scope_mismatch"
        if src.get("test_run_id", "") != ctx.test_run_id:
            return False, "test_run_mismatch"
        sc = src["customer_id"]
        if sc and sc != ctx.customer_id:
            return False, "customer_mismatch"
        sp = src.get("project_id", "")
        if sp and sp != ctx.project_id:
            return False, "project_mismatch"
        # 权限标签交集
        tags = set(json.loads(src["permission_tags_json"] or "[]"))
        if not tags & set(ctx.permission_tags):
            return False, "permission_denied"
        return True, ""

    # ---------- 逐 claim 核验 ----------

    def _verify_claim(self, claim: dict, *, ctx: CognitiveContext
                      ) -> dict[str, Any]:
        from .claims import input_hash
        evs = self.store._conn.execute(
            "SELECT * FROM claim_evidence_v1 WHERE claim_id=?",
            (claim["claim_id"],)).fetchall()
        base = {"claim_id": claim["claim_id"],
                "verifier_id": self.support.verifier_id,
                "verifier_version": self.support.verifier_version,
                "input_hash": input_hash(
                    claim["text"], [e["span_id"] for e in evs],
                    self.support.verifier_version)}
        if not evs:
            return {**base, "verdict": "remove",
                    "reason": "无支持引证（unsupported）"}
        # 显式反证（人工/研究流程记录）→ 不静默选边
        if claim["support_status"] == "contradicted" or any(
                e["relation"] == "contradicts" for e in evs):
            return {**base, "verdict": "research_more",
                    "reason": "存在反证/冲突，需补研究或人工裁决"}
        supports, contradicts, weak, invalid = [], [], [], []
        for e in evs:
            ok, reason = self._check_span(e["span_id"], ctx)
            if not ok:
                invalid.append((e["span_id"], reason))
                continue
            # R2-07：span 有效 ≠ 支持。对 Claim 与 span 原文做两层验证
            # （确定性数值/否定/主题 + 有效性），并把结果持久化回账本。
            j = self.support.verify(claim["text"],
                                    self._span_text(e["span_id"]))
            self._persist_relation(claim["claim_id"], e["span_id"],
                                   j.relation, j.score, j.reason)
            if j.relation == "supports":
                supports.append(e["span_id"])
            elif j.relation == "contradicts":
                contradicts.append((e["span_id"], j.reason))
            else:
                weak.append((e["span_id"], j.relation, j.reason))
        if contradicts:
            return {**base, "verdict": "research_more",
                    "reason": f"证据与 Claim 矛盾: {contradicts[:2]}"}
        if supports:
            if invalid:
                v = ("remove" if claim["importance"] == "high"
                     else "narrow")
                return {**base, "verdict": v,
                        "reason": f"部分引证失效: "
                                  f"{[r for _, r in invalid]}",
                        "valid_spans": supports}
            return {**base, "verdict": "pass", "reason": "",
                    "valid_spans": supports}
        if weak:
            # 仅背景/支持不足：高重要性不得发布；低重要性收窄表述
            v = ("research_more" if claim["importance"] == "high"
                 else "narrow")
            return {**base, "verdict": v,
                    "reason": f"引证仅背景/支持不足: {weak[:2]}"}
        return {**base, "verdict": "remove",
                "reason": f"全部引证失效: {[r for _, r in invalid]}"}

    def verify_run(self, research_run_id: str, *, ctx: CognitiveContext
                   ) -> dict[str, Any]:
        if ctx is None:
            from ..errors import CognitionValidationError
            raise CognitionValidationError("缺 CognitiveContext")
        claims = self.store._conn.execute(
            "SELECT * FROM research_claim_v1 WHERE research_run_id=?",
            (research_run_id,)).fetchall()
        verdicts = [self._verify_claim(dict(c), ctx=ctx) for c in claims]
        by_id = {v["claim_id"]: v for v in verdicts}
        gate_ok = True
        blocking = []
        for c in claims:
            c = dict(c)
            v = by_id[c["claim_id"]]
            # 高重要性 + 无有效引证/冲突 → 阻断发布（硬门）
            if c["importance"] == "high" and (
                    c["support_status"] in ("unsupported", "contradicted")
                    or v["verdict"] in ("remove", "research_more")):
                gate_ok = False
                blocking.append(c["claim_id"])
        return {"gate_ok": gate_ok, "blocking_claims": blocking,
                "verdicts": verdicts}
