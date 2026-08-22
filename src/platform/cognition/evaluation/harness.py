"""评测 harness（Task 12；R2-08 扩展）：构建语料 → 建索引 → 跑金标准
→ 分层指标（retrieval/reader/citation/generation/research/system/safety）。

供 scripts/eval_research_rag.py 与 tests 共用（确定性、可复现）。
防污染：gold fixture 只作为输入与哈希绑定，provider/检索代码不读取
gold 内容做特化。
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..composition import build_cognition_services  # noqa: F401  (re-export)
from ..context import CognitiveContext
from ..knowledge.service import APPROVAL_KIND_PUBLISH, KnowledgeService
from ..memory.service import (
    APPROVAL_KIND_L2 as MEM_L2_PUBLISH,
    APPROVAL_KIND_L3 as MEM_L3_PUBLISH,
)
from ..skills.service import APPROVAL_KIND_PUBLISH as SKILL_PUBLISH
from ..sources.service import SourceService
from .dataset import GoldQuery, gold_content_hash

FIXTURE_ROOT = Path(__file__).resolve().parents[4] / "tests" / \
    "fixtures" / "cognition"

EVAL_AS_OF = datetime(2026, 8, 20, 12, 0, 0, tzinfo=timezone.utc)

TRAVEL_MD = "# 差旅报销制度\n\n## 限额\n\n高铁二等座全额报销；机票经济舱上限 2000 元。\n"
LEAVE_MD = "# 年假制度\n\n## 年假\n\n入职满一年年假 5 天。\n"
CONFIDENTIAL_MD = "# 客户A专属制度\n\n客户A专属机密代号 ZEBRA-9981。\n"

CORPUS = {
    "kb-travel": ("policies/travel.md", TRAVEL_MD),
    "kb-leave": ("policies/leave.md", LEAVE_MD),
}
CUSTOMER_CORPUS = {
    "kb-confidential": ("policies/confidential.md", CONFIDENTIAL_MD,
                        "cust-a"),
}

# 平台级补充语料（从 fixture 文件加载，fail-closed）：
# kid -> (corpus 相对路径, customer_id)
KNOWLEDGE_FILES = {
    "kb-org": ("corpus/multi_hop_org.md", ""),
    "kb-cs-a": ("corpus/conflict_policy_a.md", ""),
    "kb-cs-b": ("corpus/conflict_policy_b.md", ""),
}


def _ctx(action: str, *, customer_id: str = "",
         as_of: datetime | None = None) -> CognitiveContext:
    return CognitiveContext(
        principal_id="eval", tenant_id="local", customer_id=customer_id,
        project_id="", test_run_id="", data_scope="operational",
        action=action, permission_tags=("public", "internal"),
        purpose="evaluation", correlation_id="", parent_run_id=None,
        as_of=as_of or EVAL_AS_OF)


def _require_fixture(rel: str) -> Path:
    p = FIXTURE_ROOT / rel
    if not p.exists():
        raise FileNotFoundError(f"评测 fixture 缺失（fail-closed）: {p}")
    return p


def _policy_versions() -> list[dict[str, Any]]:
    """解析 policy_versions.md 为多个带有效期的知识条目。"""
    p = _require_fixture("corpus/policy_versions.md")
    entries: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.startswith("=== id:"):
            meta: dict[str, str] = {}
            for part in line.strip("= ").split("|"):
                k, _, v = part.strip().partition(":")
                meta[k.strip()] = v.strip()
            cur = {"kid": meta["id"],
                   "effective_from": meta.get("effective_from") or None,
                   "effective_to": meta.get("effective_to") or None,
                   "lines": []}
            entries.append(cur)
        elif cur is not None:
            cur["lines"].append(line)
    for e in entries:
        e["text"] = "\n".join(e["lines"]).strip() + "\n"
    return entries


def _publish_knowledge(stack, store, *, kid: str, uri: str, text: str,
                       customer_id: str, effective_from: str,
                       effective_to: str | None) -> None:
    from ...governance.policy_service import PolicyService
    policy = PolicyService(store)
    ctx = CognitiveContext(
        principal_id="eval", tenant_id="local", customer_id=customer_id,
        project_id="", test_run_id="", data_scope="operational",
        action="cognition.sources.ingest",
        permission_tags=("public", "internal"), purpose="evaluation",
        correlation_id="", parent_run_id=None, as_of=EVAL_AS_OF)
    res = stack.sources.ingest(ctx, source_type="file", original_uri=uri,
                               media_type="text/markdown",
                               content=text.encode("utf-8"),
                               permission_tags=("public",),
                               trust_tier="authoritative")
    span_ids = [c["chunk_id"] for c in res["chunks"]]
    stack.knowledge.draft(ctx, knowledge_id=kid, knowledge_type="policy",
                          title=kid, body=text, summary=kid, owner="hr",
                          effective_from=effective_from,
                          effective_to=effective_to,
                          permission_tags=("public",),
                          source_span_ids=span_ids)
    ap = policy.request_generic_approval(
        kind=APPROVAL_KIND_PUBLISH, subject_ref=f"{kid}@v1",
        requested_by="eval-ingest")
    policy.decide_approval(ap["approval_id"], actor="human-eval",
                           decision="approved")
    stack.knowledge.publish(ctx, kid, 1, approver="human-eval",
                            approval_id=ap["approval_id"])


def _ingest_skills(stack, store) -> dict[str, str]:
    """从 skills.jsonl 发布 skill；返回 skill_id→skill_id 映射。"""
    from ...governance.policy_service import PolicyService
    policy = PolicyService(store)
    p = _require_fixture("skills.jsonl")
    out: dict[str, str] = {}
    ctx = _ctx("cognition.sources.ingest")
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        d = json.loads(line)
        sid = d["skill_id"]
        stack.skills.draft(
            ctx, skill_id=sid, name=d["name"],
            description=d["description"], skill_type=d["skill_type"],
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            execution_ref=f"scripts/skills/{sid}.py",
            tool_scopes=[], risk_level=d["risk_level"],
            applicable_scenarios=d["applicable_scenarios"],
            forbidden_scenarios=d["forbidden_scenarios"],
            source_refs=[], evaluation_ref="eval:skill@1",
            permission_tags=("public",))
        stack.skills.validate(ctx, sid, 1, actor="eval-ingest")
        ap = policy.request_generic_approval(
            kind=SKILL_PUBLISH, subject_ref=f"{sid}@v1",
            requested_by="eval-ingest")
        policy.decide_approval(ap["approval_id"], actor="human-eval",
                               decision="approved")
        stack.skills.publish(ctx, sid, 1, approver="human-eval",
                             approval_id=ap["approval_id"])
        out[sid] = sid
    return out


def _ingest_memory(stack, store) -> dict[str, str]:
    """从 l2_cases.jsonl / l3_methods.jsonl 发布 L2/L3；返回 hint→id。"""
    from ...governance.policy_service import PolicyService
    policy = PolicyService(store)
    id_map: dict[str, str] = {}
    ctx = _ctx("cognition.sources.ingest")
    actor = "memory_consolidator"
    # L2：每个 case 先落一条 L1，再 consolidate 为 candidate，发布
    l2p = _require_fixture("l2_cases.jsonl")
    episode_ids: list[str] = []
    for i, line in enumerate(l2p.read_text(encoding="utf-8").splitlines()):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        d = json.loads(line)
        l1_id = stack.memory.append_l1(
            ctx, task_id=d["task_id"], run_id=f"run-eval-{i}",
            node_id="eval", actor_id="eval", actor_kind="system",
            event_type="case.observed",
            payload={"solution": d["solution"], "result": d["result"]},
            permission_tags=("public",))
        ep = stack.memory.consolidate_l1_to_l2(
            ctx, actor_role="consolidator", actor=actor,
            task_id=d["task_id"],
            period_start="2026-01-01T00:00:00+00:00",
            period_end="2026-06-30T00:00:00+00:00",
            l1_ids=[l1_id], entities=d.get("entities"),
            solution=d["solution"], result=d["result"],
            issues=d.get("issues"), confidence=0.6)
        eid = ep["episode_id"]
        episode_ids.append(eid)
        ap = policy.request_generic_approval(
            kind=MEM_L2_PUBLISH, subject_ref=f"l2:{eid}",
            requested_by="eval-ingest")
        policy.decide_approval(ap["approval_id"], actor="human-eval",
                               decision="approved")
        stack.memory.publish_l2(eid, approver="human-eval",
                                approval_id=ap["approval_id"])
        id_map[d["episode_id_hint"]] = eid
    # L3：由已发布 L2（≥MIN_INDEPENDENT_EVENTS）提炼方法论并发布
    l3p = _require_fixture("l3_methods.jsonl")
    for line in l3p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        d = json.loads(line)
        m = stack.memory.propose_l3(
            ctx, actor_role="consolidator", actor=actor,
            statement=d["statement"], source_l2_ids=episode_ids,
            trigger_conditions=d.get("trigger_conditions"),
            scope=d.get("scope"), confidence=d.get("confidence", 0.6))
        mid, mver = m["methodology_id"], m["version"]
        ap = policy.request_generic_approval(
            kind=MEM_L3_PUBLISH, subject_ref=f"l3:{mid}@v{mver}",
            requested_by="eval-ingest")
        policy.decide_approval(ap["approval_id"], actor="human-eval",
                               decision="approved")
        stack.memory.publish_l3(mid, mver, approver="human-eval",
                                approval_id=ap["approval_id"])
        id_map[d["methodology_id_hint"]] = mid
    return id_map


def build_corpus(stack, store) -> dict[str, Any]:
    """摄取+发布全部语料（知识/skill/L2/L3），建索引并激活。

    返回 snapshot + id_map（gold expect_ref → 真实 id）+ provider 身份。
    """
    for kid, (uri, text) in CORPUS.items():
        _publish_knowledge(stack, store, kid=kid, uri=uri, text=text,
                           customer_id="",
                           effective_from="2026-01-01T00:00:00+00:00",
                           effective_to=None)
    for kid, (uri, text, cust) in CUSTOMER_CORPUS.items():
        _publish_knowledge(stack, store, kid=kid, uri=uri, text=text,
                           customer_id=cust,
                           effective_from="2026-01-01T00:00:00+00:00",
                           effective_to=None)
    # 带有效期的时间语料（temporal）
    for e in _policy_versions():
        _publish_knowledge(stack, store, kid=e["kid"],
                           uri=f"policies/{e['kid']}.md", text=e["text"],
                           customer_id="",
                           effective_from=e["effective_from"],
                           effective_to=e["effective_to"])
    # 其余平台级知识语料（multi-hop/conflict）
    for kid, (rel, cust) in KNOWLEDGE_FILES.items():
        text = _require_fixture(rel).read_text(encoding="utf-8")
        _publish_knowledge(stack, store, kid=kid, uri=rel, text=text,
                           customer_id=cust,
                           effective_from="2026-01-01T00:00:00+00:00",
                           effective_to=None)
    # skill / L2 / L3
    skill_map = _ingest_skills(stack, store)
    mem_map = _ingest_memory(stack, store)
    id_map = {**skill_map, **mem_map}

    snap = stack.sources.build_corpus_snapshot(
        _ctx("cognition.research.start"))
    b = stack.catalog.build(_ctx("cognition.index.build"),
                            target_kind="knowledge",
                            corpus_snapshot_id=snap["corpus_snapshot_id"])
    stack.catalog.activate(_ctx("cognition.index.activate"),
                           target_kind="knowledge",
                           index_snapshot_id=b["index_snapshot_id"])
    from ..index.vector import provider_identity
    return {"corpus_snapshot_id": snap["corpus_snapshot_id"],
            "index_snapshot_id": b["index_snapshot_id"],
            "source_manifest_hash": b["source_manifest_hash"],
            "provider_identity": provider_identity(
                getattr(stack.gateway, "vector_provider", None)),
            "id_map": id_map}


def _resolve_expected(g: GoldQuery, id_map: dict[str, str]) -> list[str]:
    ids = list(g.expect_knowledge_ids) + list(g.expect_target_ids)
    if g.extra.get("expect_ref"):
        ref = g.extra["expect_ref"]
        if ref not in id_map:
            raise KeyError(f"gold expect_ref 无法解析（fail-closed）: {ref}")
        ids.append(id_map[ref])
    return ids


def _resolve_forbidden(g: GoldQuery, id_map: dict[str, str]) -> set[str]:
    out: set[str] = set()
    for f in g.forbidden_source_ids:
        out.add(id_map.get(f, f))
    return out


def _parse_as_of(g: GoldQuery) -> datetime:
    if not g.as_of:
        return EVAL_AS_OF
    d = datetime.fromisoformat(g.as_of.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def run_gold_evaluation(stack, store, gold: list[GoldQuery],
                        snapshot: dict[str, Any],
                        gold_path: str | Path | None = None) -> dict:
    """跑金标准样本 → 分层指标报告。"""
    from ..contracts import CognitiveQueryRequest
    from .citations import run_citation_gold
    from .retrieval import percentile

    id_map = snapshot.get("id_map", {})
    samples: list[Any] = []
    acl_leaks: list[dict] = []
    forbidden_hits = 0
    latencies: list[float] = []
    conflict_results: list[bool] = []

    for g in gold:
        expected = _resolve_expected(g, id_map)
        forbidden = _resolve_forbidden(g, id_map)
        if g.expect_empty_for_customer is not None:
            query_customer = g.expect_empty_for_customer
        elif g.scope.get("customer_id"):
            query_customer = g.scope["customer_id"]
        elif g.extra.get("extra_customer"):
            query_customer = g.extra["extra_customer"]
        else:
            query_customer = ""
        ctx = CognitiveContext(
            principal_id="eval", tenant_id="local",
            customer_id=query_customer, project_id="",
            test_run_id="", data_scope="operational",
            action="cognition.knowledge.search",
            permission_tags=("public", "internal"), purpose="eval",
            correlation_id="", parent_run_id=None,
            as_of=_parse_as_of(g))
        req = CognitiveQueryRequest(query=g.query,
                                    target_kinds=tuple(g.target_kinds),
                                    mode=g.mode, top_k=10)
        t0 = time.perf_counter()
        result = stack.gateway.search(req, ctx)
        latencies.append((time.perf_counter() - t0) * 1000.0)
        retrieved_ids = [c.target_id for c in result.candidates]
        retrieved_quotes = [sp["normalized_quote"]
                            for c in result.candidates
                            for sp in (s.to_dict() for s in c.spans)]
        abstained = (not result.candidates)
        s = compute_sample(g, expected, retrieved_ids, retrieved_quotes,
                           abstained)
        # forbidden source 命中（temporal/expired/negative 负例）
        if forbidden & set(retrieved_ids):
            s.forbidden_hit = True
            forbidden_hits += len(forbidden & set(retrieved_ids))
        # 冲突判定正确性
        if g.expect_conflict is not None:
            found = _detect_conflict(result)
            s.conflict_correct = (found == g.expect_conflict)
            conflict_results.append(s.conflict_correct)
        samples.append(s)
        if s.leaked:
            acl_leaks.append({"query_id": g.id,
                              "leaked_ids": retrieved_ids})

    injection_hits = _run_injection_negative(stack, store)
    reader = _reader_metrics(stack, store, samples)
    research = _research_metrics(stack, store, snapshot)
    system = _system_metrics(stack, store, snapshot, latencies, samples)
    citation_gold = run_citation_gold(store)

    report = assemble(samples, id_map, acl_leaks, injection_hits,
                      forbidden_hits, snapshot, reader, research, system,
                      citation_gold, conflict_results, gold_path,
                      latencies)
    return report


def _detect_conflict(result) -> bool:
    """对检索命中做互斥数值冲突检测（critic 同源逻辑）。"""
    from ..research.critic import detect_conflicts
    evidence: dict[str, list[dict]] = {}
    for c in result.candidates:
        spans = [{"span_id": s.span_id,
                  "quote": s.normalized_quote,
                  "target_id": c.target_id}
                 for s in c.spans]
        evidence.setdefault(c.target_id, []).extend(spans)
    return bool(detect_conflicts(evidence))


from .report import EvalSampleResult, assemble_report  # noqa: E402
from .retrieval import (  # noqa: E402
    mrr, ndcg_at_k, percentile, recall_at_k, span_recall)


def compute_sample(gold, expected, retrieved_ids, retrieved_quotes,
                   abstained) -> EvalSampleResult:
    s = EvalSampleResult(gold_id=gold.id, cls=gold.cls,
                         retrieved_ids=retrieved_ids,
                         retrieved_quotes=retrieved_quotes,
                         abstained=abstained)
    if gold.expect_abstain and not expected:
        s.abstain_correct = abstained
        return s
    if gold.expect_empty_for_customer is not None:
        s.leaked = len(retrieved_ids) > 0
        s.abstain_correct = not s.leaked
        return s
    if not expected:
        # 无期望 target 的非 abstain 样本（如纯冲突样本）只记 abstain
        s.abstain_correct = not abstained
        return s
    s.is_retrieval_sample = True
    s.recall_at_5 = recall_at_k(retrieved_ids, expected, 5)
    s.recall_at_10 = recall_at_k(retrieved_ids, expected, 10)
    s.mrr = mrr(retrieved_ids, expected)
    s.ndcg_at_5 = ndcg_at_k(retrieved_ids, expected, 5)
    s.abstain_correct = not abstained
    if gold.expect_quote_contains:
        s.span_recall = span_recall(retrieved_quotes,
                                    [gold.expect_quote_contains])
    return s


def _reader_metrics(stack, store, samples) -> dict:
    """Reader 层：span locator 有效性（quote 必须真实存在于源 chunk）。"""
    total = 0
    valid = 0
    for s in samples:
        for q in s.retrieved_quotes:
            if not q:
                continue
            total += 1
            row = store._conn.execute(
                "SELECT 1 FROM cognition_chunk_v1 WHERE instr(text, ?)"
                " > 0 LIMIT 1", (q[:120],)).fetchone()
            if row is not None:
                valid += 1
    if total == 0:
        return {"measured": False, "span_locator_accuracy": None,
                "spans_checked": 0}
    return {"measured": True,
            "span_locator_accuracy": valid / total,
            "spans_checked": total}


def _research_metrics(stack, store, snapshot) -> dict:
    """Research 层：冲突 run 是否进入 waiting_human + 断点恢复。
    计数只针对本次调用创建的 run（保证可复现）。"""
    from ..research.service import ResearchService
    svc = ResearchService(store, gateway=stack.gateway)
    ctx = _ctx("cognition.research.start")
    # 冲突发现问题：互斥数值 → waiting_human
    run = svc.start(ctx, question="客户服务响应时限", mode="lookup")
    run_id = run["research_run_id"]
    conflict_detected = (run["status"] == "waiting_human")
    ce_queries = store._conn.execute(
        "SELECT count(*) c FROM research_query_v1 WHERE strategy="
        "'counterevidence' AND research_run_id=?", (run_id,)).fetchone()["c"]
    # 断点恢复：故障注入 → failed → resume 成功
    calls = {"n": 0}

    def fault(node):
        if node == "read" and calls["n"] == 0:
            calls["n"] += 1
            raise RuntimeError("eval fault")

    r2 = svc.start(ctx, question="年假多少天", mode="lookup", fault=fault)
    resumed_ok = False
    if r2["status"] == "failed":
        done = svc.resume(r2["research_run_id"], ctx=ctx)
        resumed_ok = (done["status"] == "succeeded")
    return {"measured": True,
            "conflict_run_status": run["status"],
            "conflict_detected": conflict_detected,
            "conflict_detection_accuracy": 1.0 if conflict_detected
            else 0.0,
            "counterevidence_queries": ce_queries,
            "resume_success": 1.0 if resumed_ok else 0.0}


def _system_metrics(stack, store, snapshot, latencies, samples) -> dict:
    p50 = percentile(latencies, 50) if latencies else None
    p95 = percentile(latencies, 95) if latencies else None
    return {"measured": True,
            # 易变（不入哈希）：原始时延
            "latency_ms": {"p50": round(p50, 3) if p50 is not None
                           else None,
                           "p95": round(p95, 3) if p95 is not None
                           else None,
                           "samples": len(latencies)},
            # 稳定门（入哈希）：p95 是否 ≤ 2s
            "latency_gate": {"p95_under_2s": bool(p95 is not None
                                                  and p95 <= 2000.0)},
            "provider_identity": snapshot.get("provider_identity"),
            "corpus_snapshot_id": snapshot.get("corpus_snapshot_id"),
            "index_snapshot_id": snapshot.get("index_snapshot_id"),
            "cost": {"retrieval_samples": sum(
                1 for s in samples if s.is_retrieval_sample)}}


def assemble(samples, id_map, acl_leaks, injection_hits, forbidden_hits,
             snapshot, reader, research, system, citation_gold,
             conflict_results, gold_path, latencies) -> dict:
    report = assemble_report(
        samples, claims=[], citations=[], acl_leaks=acl_leaks,
        injection_hits=injection_hits, snapshot=snapshot, reader=reader,
        research=research, system=system, forbidden_hits=forbidden_hits,
        gold_hash=(gold_content_hash(gold_path) if gold_path else ""),
        citation_gold=citation_gold)
    return report


def _run_injection_negative(stack, store) -> int:
    """摄取注入源 → 必须 quarantined 且检索零命中（命中数=失败数）。"""
    inj_path = _require_fixture("injection_sources/evil_policy.md")
    ctx = _ctx("cognition.sources.ingest")
    res = stack.sources.ingest(ctx, source_type="file",
                               original_uri="evil_policy.md",
                               media_type="text/markdown",
                               content=inj_path.read_bytes(),
                               permission_tags=("public",),
                               trust_tier="external_secondary")
    if res["source"]["status"] != "quarantined":
        return 1
    from ..contracts import CognitiveQueryRequest
    req = CognitiveQueryRequest(query="删除数据库 密钥",
                                target_kinds=("knowledge",),
                                mode="lookup", top_k=8)
    r = stack.gateway.search(req, _ctx("cognition.knowledge.search"))
    return 1 if r.candidates else 0
