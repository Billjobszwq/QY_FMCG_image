"""联邦查询网关（Task 8）：CognitiveQueryGateway。

不变量（02 §1/§7/§8.2）：
- 缺上下文 fail-closed；
- tenant/customer/project/data_scope/test_run/permission/effective-time
  过滤全部发生在候选评分**之前**（pre-retrieval filter）；
- 不返回 total_count/facets 等可泄露残留计数；
- embedding/reranker 不可用 → 显式 degraded，不返回假向量结果；
- 每个知识候选携带可定位 evidence span。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from ..context import CognitiveContext
from ..contracts import (
    CognitiveQueryRequest,
    EvidenceSpan,
    RetrievalCandidate,
    SearchResult,
)
from ..errors import CognitionValidationError
from ..repository import CognitionRepository
from .fusion import dedup_by_document, reciprocal_rank_fusion
from .lexical import score_bm25, tokenize
from .vector import cosine, encode_queries, provider_identity

# M7 冻结检索参数：hybrid 中“仅稠密”候选的强语义阈值（归一化余弦）。
# 低于该阈值且无词法佐证的稠密命中视为噪声：防止稠密腿“恒返回
# top-k”破坏 ACL/注入/弃权负例的零命中合同。变更该值 = 检索身份变更，
# 必须走新索引版本 + 金标准复评（01 §7 / DEC-M007）。
DENSE_HYBRID_STRONG_SIM = 0.60


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


class CognitiveQueryGateway:
    def __init__(self, store: Any, *, catalog: Any,
                 vector_provider: Any = None,
                 reranker: Any = None) -> None:
        self.store = store
        self.repo = CognitionRepository(store)
        self.catalog = catalog
        self.vector_provider = vector_provider
        self.reranker = reranker

    # ---------- ACL 前置过滤 ----------

    @staticmethod
    def _unit_visible(unit: dict[str, Any], ctx: CognitiveContext,
                      as_of: datetime) -> bool:
        if unit.get("tenant_id", "local") != ctx.tenant_id:
            return False
        if unit.get("data_scope", "operational") != ctx.data_scope:
            return False
        if unit.get("test_run_id", "") != ctx.test_run_id:
            return False
        uc = unit.get("customer_id", "")
        if uc and uc != ctx.customer_id:
            return False
        if not ctx.customer_id and uc:
            return False  # 平台级上下文只见平台级（customer=''）内容
        # project 维度：项目级内容仅同项目可见；平台级（project=''）
        # 对所有项目可见；指定项目的上下文不见其他项目内容。
        up = unit.get("project_id", "")
        if up and up != ctx.project_id:
            return False
        if not ctx.project_id and up:
            return False
        tags = set(unit.get("permission_tags") or [])
        if not tags & set(ctx.permission_tags):
            return False
        frm = _parse_ts(unit.get("effective_from"))
        to = _parse_ts(unit.get("effective_to"))
        if frm is not None and as_of < frm:
            return False
        if to is not None and as_of >= to:
            return False
        if unit.get("status", "published") != "published":
            return False
        return True

    def _knowledge_currently_published(self, knowledge_id: str,
                                       version: str) -> bool:
        """查询时以 DB 当前状态复核（索引 artifact 冻结的是 build 时刻
        快照；revoked/superseded 后不得再命中，评审 #G6-2）。"""
        row = self.store._conn.execute(
            "SELECT status FROM knowledge_item_version WHERE"
            " knowledge_id=? AND version=?",
            (knowledge_id, str(version))).fetchone()
        return row is not None and row["status"] == "published"

    # ---------- knowledge 检索 ----------

    def _search_knowledge(self, req: CognitiveQueryRequest,
                          ctx: CognitiveContext,
                          trace: dict[str, Any],
                          snap_ids: list[str]) -> tuple[
                              list[RetrievalCandidate], bool]:
        build = self.catalog.active("knowledge")
        if build is None:
            trace["knowledge"] = "no_active_index（fail-closed 空结果）"
            return [], False
        artifact = self.catalog.load_artifact(build)
        snap_ids.append(build["index_snapshot_id"])
        units: dict[str, dict] = artifact["units"]
        as_of = ctx.as_of
        allowed = {cid for cid, u in units.items()
                   if self._unit_visible(u, ctx, as_of)}
        # 不记录全局语料计数（02 §8.2：计数/facet/存在性同样受权限约束，
        # 经 trace 泄露全局规模构成跨租户存在性 oracle，评审 #G6-6）。
        # 以 DB 当前状态复核知识仍为 published（索引 artifact 冻结 build
        # 时刻快照；revoke/supersede 后不得再命中，评审 #G6-2）。
        allowed = {cid for cid in allowed
                   if self._knowledge_currently_published(
                       units[cid]["knowledge_id"],
                       units[cid]["knowledge_version"])}

        # ---- 词法 leg ----
        postings = artifact["postings"]
        df = {t: len(p) for t, p in postings.items()}
        lex_scores = score_bm25(postings, df, len(units),
                                tokenize(req.query), allowed)
        lex_ranked = sorted(lex_scores.items(),
                            key=lambda kv: kv[1], reverse=True)[:40]

        # ---- 稠密 leg（可用才计算；否则诚实 degraded） ----
        dense_ranked: list[tuple[str, float]] = []
        degraded = False
        vectors = artifact.get("vectors") or {}
        if self.vector_provider is not None:
            if not self.vector_provider.available():
                degraded = True
            elif vectors:
                # R2-05：build/query provider identity 必须完全一致；
                # 不同模型/版本/维度/归一化的向量不可比较（fail-closed，
                # 不计算 cosine，不返回看似正常的 hybrid）。
                q_ident = provider_identity(self.vector_provider)
                b_ident = artifact.get("vector_identity")
                if b_ident is None:
                    identity_ok = q_ident["provider_id"] == "legacy"
                else:
                    identity_ok = q_ident == b_ident
                if not identity_ok:
                    degraded = True
                    trace["provider_mismatch"] = {
                        "index": b_ident, "query": q_ident}
                else:
                    qvec = encode_queries(self.vector_provider,
                                          [req.query])[0]
                    ds: dict[str, float] = {}
                    for cid in allowed:
                        v = vectors.get(cid)
                        if v is not None:
                            ds[cid] = cosine(qvec, v)
                    # M7 冻结合同：dense 候选必须有词法佐证，或相似度
                    # 达到强语义阈值；否则视为噪声丢弃（防"恒返回
                    # top-k"破坏负例/弃权/注入/ACL 零命中契约）。
                    ds = {cid: s for cid, s in ds.items()
                          if cid in lex_scores
                          or s >= DENSE_HYBRID_STRONG_SIM}
                    dense_ranked = sorted(ds.items(),
                                          key=lambda kv: kv[1],
                                          reverse=True)[:40]
            else:
                degraded = True  # provider 可用但索引无向量
        elif vectors:
            degraded = True  # 索引带向量但网关未配 provider

        legs = [lex_ranked]
        if dense_ranked:
            legs.append(dense_ranked)
        fused = reciprocal_rank_fusion(legs)
        ordered = sorted(fused.items(), key=lambda kv: kv[1],
                         reverse=True)

        hits: list[dict[str, Any]] = []
        for cid, fscore in ordered:
            u = units[cid]
            hits.append({
                "chunk_id": cid,
                "document_key": u["knowledge_id"],
                "fusion": fscore,
                "lexical": lex_scores.get(cid),
                "dense": dict(dense_ranked).get(cid),
                "rerank": None,
                "unit": u,
            })
        hits = dedup_by_document(hits, max_per_document=2)
        # rerank 端口：可用时对 top-20 重排并把 rerank 分记入 trace；
        # 不可用则跳过（不伪造 rerank 分）。
        if self.reranker is not None and self.reranker.available():
            top = hits[:20]
            scores = self.reranker.rerank(
                req.query, [{"text": h["unit"]["text"]} for h in top])
            for h, rs in zip(top, scores):
                h["rerank"] = rs
            top.sort(key=lambda h: h["rerank"], reverse=True)
            rest = hits[20:]
            hits = top + rest
            trace["reranked"] = len(top)
        hits = hits[:req.top_k]

        out: list[RetrievalCandidate] = []
        for h in hits:
            u = h["unit"]
            text = u["text"]
            quote_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
            span = EvidenceSpan(
                span_id=h["chunk_id"], chunk_id=h["chunk_id"],
                quote_start=0, quote_end=len(text),
                quote_hash=quote_hash, normalized_quote=text[:200],
                locator={"knowledge_id": u["knowledge_id"],
                         "document_id": u["document_id"],
                         "document_version": u["document_version"],
                         "chunk_id": h["chunk_id"],
                         "char_start": u.get("char_start", 0),
                         "char_end": u.get("char_end", len(text))})
            breakdown = {"fusion": round(h["fusion"], 6)}
            breakdown["lexical"] = (round(h["lexical"], 6)
                                    if h["lexical"] is not None else None)
            breakdown["dense"] = (round(h["dense"], 6)
                                  if h["dense"] is not None else None)
            breakdown["rerank"] = (round(h["rerank"], 6)
                                   if h.get("rerank") is not None
                                   else None)
            out.append(RetrievalCandidate(
                target_kind="knowledge",
                target_id=u["knowledge_id"],
                version=str(u["knowledge_version"]),
                score_breakdown=breakdown,
                summary=u.get("summary") or u.get("title", ""),
                spans=(span,),
                index_snapshot_id=build["index_snapshot_id"]))
        return out, degraded

    # ---------- skill / memory 检索（各自 lifecycle filter） ----------

    @staticmethod
    def _row_visible(row: dict[str, Any], ctx: CognitiveContext,
                     *, require_tags: bool = True) -> bool:
        if row.get("tenant_id", "local") != ctx.tenant_id:
            return False
        if row.get("data_scope", "operational") != ctx.data_scope:
            return False
        if row.get("test_run_id", "") != ctx.test_run_id:
            return False
        uc = row.get("customer_id", "")
        if uc and uc != ctx.customer_id:
            return False
        if not ctx.customer_id and uc:
            return False
        # project 维度（评审 #G6-1）：项目级内容仅同项目可见。
        up = row.get("project_id", "")
        if up and up != ctx.project_id:
            return False
        if not ctx.project_id and up:
            return False
        if not require_tags:
            # L3 方法论表无 permission_tags 列（064 schema 未含）：
            # 以 tenant/data_scope/customer/project 隔离为准，发布已经
            # 人工审批门（publish_l3），不再叠加 tag 交集检查。
            return True
        tags = set(json.loads(row.get("permission_tags_json") or "[]"))
        return bool(tags & set(ctx.permission_tags))

    @staticmethod
    def _token_overlap_score(query_tokens: list[str], text: str) -> float:
        tt = set(tokenize(text))
        if not query_tokens:
            return 0.0
        return sum(1.0 for t in query_tokens if t in tt) / len(
            query_tokens)

    def _search_skill(self, req: CognitiveQueryRequest,
                      ctx: CognitiveContext,
                      trace: dict[str, Any]) -> list[RetrievalCandidate]:
        # lifecycle filter：仅 published 的 skill 可被发现
        rows = [r for r in self.repo.list_skills_by_status("published")
                if self._row_visible(r, ctx)]
        trace["skill_rows_allowed"] = len(rows)
        qtoks = tokenize(req.query)
        scored = []
        for r in rows:
            text = " ".join([r["name"], r["description"],
                             r["applicable_scenarios_json"]])
            s = self._token_overlap_score(qtoks, text)
            if s > 0:
                scored.append((s, r))
        scored.sort(key=lambda x: x[0], reverse=True)
        out = []
        for s, r in scored[:req.top_k]:
            out.append(RetrievalCandidate(
                target_kind="skill", target_id=r["skill_id"],
                version=str(r["version"]),
                score_breakdown={"lexical": round(s, 6),
                                 "dense": None, "fusion": round(s, 6)},
                summary=r["description"] or r["name"], spans=(),
                index_snapshot_id=""))
        return out

    def _search_memory(self, req: CognitiveQueryRequest,
                       ctx: CognitiveContext, kind: str,
                       trace: dict[str, Any]) -> list[RetrievalCandidate]:
        # lifecycle filter：仅 published 的 L2/L3 可被检索
        if kind == "memory_l2":
            rows = [r for r in self.repo.list_l2(status="published")
                    if self._row_visible(r, ctx)]
            text_of = lambda r: " ".join([r["solution"], r["result"],  # noqa: E731
                                          r["issues_json"]])
        else:
            # L3 表无 permission_tags 列 → require_tags=False（见 _row_visible）
            rows = [r for r in self.repo.list_l3(status="published")
                    if self._row_visible(r, ctx, require_tags=False)]
            text_of = lambda r: " ".join([r["statement"],  # noqa: E731
                                          r["trigger_conditions_json"]])
        id_field = "episode_id" if kind == "memory_l2" else "methodology_id"
        trace[f"{kind}_rows_allowed"] = len(rows)
        qtoks = tokenize(req.query)
        scored = []
        for r in rows:
            s = self._token_overlap_score(qtoks, text_of(r))
            if s > 0:
                scored.append((s, r))
        scored.sort(key=lambda x: x[0], reverse=True)
        out = []
        for s, r in scored[:req.top_k]:
            out.append(RetrievalCandidate(
                target_kind=kind, target_id=r[id_field],
                version=str(r.get("version", 1)),
                score_breakdown={"lexical": round(s, 6),
                                 "dense": None, "fusion": round(s, 6)},
                summary=(r.get("solution") or r.get("statement")
                         or "")[:200], spans=(), index_snapshot_id=""))
        return out

    # ---------- 统一入口 ----------

    def search(self, req: CognitiveQueryRequest,
               ctx: CognitiveContext | None,
               *, max_per_document: int = 2) -> SearchResult:
        if ctx is None:
            raise CognitionValidationError(
                "缺 CognitiveContext（fail-closed，不得无上下文检索）")
        trace: dict[str, Any] = {"query": req.query,
                                 "target_kinds": list(req.target_kinds)}
        snap_ids: list[str] = []
        candidates: list[RetrievalCandidate] = []
        degraded = False
        if "knowledge" in req.target_kinds:
            kc, kd = self._search_knowledge(req, ctx, trace, snap_ids)
            candidates.extend(kc)
            degraded = degraded or kd
        if "skill" in req.target_kinds:
            candidates.extend(self._search_skill(req, ctx, trace))
        if "memory_l2" in req.target_kinds:
            candidates.extend(self._search_memory(req, ctx, "memory_l2",
                                                  trace))
        if "memory_l3" in req.target_kinds:
            candidates.extend(self._search_memory(req, ctx, "memory_l3",
                                                  trace))
        return SearchResult(
            query=req.query, candidates=tuple(candidates),
            degraded=degraded, index_snapshot_ids=tuple(snap_ids),
            policy_decision={"pre_filtered": True, "fail_closed": True},
            retrieval_trace=trace)
