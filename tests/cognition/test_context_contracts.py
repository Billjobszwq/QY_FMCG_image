"""Task 2（G1）红测试：CognitiveContext 与公共 typed contracts。

契约来源：02-DATA-CONTRACTS-AND-SECURITY.md §1/§2/§6/§7。
fail-closed 要求：
- 缺 principal/tenant/action 必须拒绝；
- test scope 不得降级为 operational；
- LLM/外部输入不能覆盖服务端 context；
- JSON round-trip、hash 稳定、未知字段拒绝。
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.platform.cognition.context import (
    CognitiveContext,
    context_from_scope,
)
from src.platform.cognition.contracts import (
    ArtifactRef,
    Claim,
    CognitiveQueryRequest,
    EvidenceSpan,
    IndexSnapshot,
    SearchResult,
)
from src.platform.cognition.errors import (
    CognitionPolicyError,
    CognitionValidationError,
)
from src.platform.scope import ExecutionContext

AS_OF = datetime(2026, 8, 20, 12, 0, 0, tzinfo=timezone.utc)


def _scope(**kw) -> ExecutionContext:
    base = dict(tenant_id="local", customer_id="cust-a",
                project_id="prj-1", data_scope="operational",
                test_run_id="", correlation_id="corr-1")
    base.update(kw)
    return ExecutionContext(**base)


def _ctx(**kw) -> CognitiveContext:
    base = dict(principal_id="alice", tenant_id="local",
                customer_id="cust-a", project_id="prj-1",
                test_run_id="", data_scope="operational",
                action="cognition.knowledge.search",
                permission_tags=("public",), purpose="lookup",
                correlation_id="corr-1", parent_run_id=None, as_of=AS_OF)
    base.update(kw)
    return CognitiveContext(**base)


class TestContextFailClosed:
    def test_missing_principal_rejected(self):
        with pytest.raises(CognitionValidationError):
            _ctx(principal_id="")

    def test_missing_tenant_rejected(self):
        with pytest.raises(CognitionValidationError):
            _ctx(tenant_id="")

    def test_missing_action_rejected(self):
        with pytest.raises(CognitionValidationError):
            _ctx(action="")

    def test_missing_as_of_rejected(self):
        with pytest.raises(CognitionValidationError):
            _ctx(as_of=None)

    def test_unknown_data_scope_rejected(self):
        with pytest.raises(CognitionValidationError):
            _ctx(data_scope="everything")

    def test_fixture_scope_requires_test_run(self):
        with pytest.raises(CognitionValidationError):
            _ctx(data_scope="uat_fixture", test_run_id="")

    def test_context_is_immutable(self):
        ctx = _ctx()
        with pytest.raises(Exception):
            ctx.principal_id = "mallory"  # frozen


class TestScopeAdapter:
    def test_adapter_builds_context_from_scope(self):
        ctx = context_from_scope(_scope(), principal_id="alice",
                                 action="cognition.knowledge.search",
                                 as_of=AS_OF)
        assert ctx.customer_id == "cust-a"
        assert ctx.data_scope == "operational"
        assert ctx.tenant_id == "local"

    def test_adapter_requires_principal_and_action(self):
        with pytest.raises(CognitionValidationError):
            context_from_scope(_scope(), principal_id="",
                               action="x", as_of=AS_OF)
        with pytest.raises(CognitionValidationError):
            context_from_scope(_scope(), principal_id="alice",
                               action="", as_of=AS_OF)

    def test_fixture_scope_never_downgraded_to_operational(self):
        """test/UAT scope 不得被任何入参洗成 operational。"""
        fx = _scope(data_scope="uat_fixture", test_run_id="tr-1")
        ctx = context_from_scope(fx, principal_id="alice",
                                 action="cognition.memory.search",
                                 as_of=AS_OF)
        assert ctx.data_scope == "uat_fixture"
        assert ctx.test_run_id == "tr-1"
        with pytest.raises(CognitionPolicyError):
            context_from_scope(fx, principal_id="alice",
                               action="cognition.memory.search",
                               as_of=AS_OF, force_data_scope="operational")

    def test_operational_requires_no_test_run(self):
        with pytest.raises(CognitionValidationError):
            context_from_scope(_scope(test_run_id="tr-9"),
                               principal_id="alice",
                               action="cognition.knowledge.search",
                               as_of=AS_OF)


class TestUntrustedInputCannotOverride:
    def test_untrusted_payload_rejected_for_security_fields(self):
        """LLM/检索/文档输入不得覆盖服务端 context（02 §1）。"""
        evil = {"principal_id": "mallory", "tenant_id": "other",
                "data_scope": "operational", "test_run_id": "",
                "action": "cognition.publish"}
        with pytest.raises(CognitionPolicyError):
            context_from_scope(_scope(), principal_id="alice",
                               action="cognition.knowledge.search",
                               as_of=AS_OF, untrusted_overrides=evil)

    def test_untrusted_payload_rejected_even_if_harmless_looking(self):
        with pytest.raises(CognitionPolicyError):
            context_from_scope(_scope(), principal_id="alice",
                               action="cognition.knowledge.search",
                               as_of=AS_OF,
                               untrusted_overrides={"purpose": "hi"})

    def test_empty_untrusted_payload_allowed(self):
        ctx = context_from_scope(_scope(), principal_id="alice",
                                 action="cognition.knowledge.search",
                                 as_of=AS_OF, untrusted_overrides={})
        assert ctx.principal_id == "alice"


class TestContractRoundTrip:
    def test_query_request_round_trip_and_unknown_field(self):
        req = CognitiveQueryRequest(
            query="报销限额是多少", target_kinds=("knowledge",),
            mode="lookup", top_k=8, filters={"type": "finance"},
            include_history=False, require_citations=True)
        d = req.to_dict()
        assert CognitiveQueryRequest.from_dict(d) == req
        with pytest.raises(CognitionValidationError):
            CognitiveQueryRequest.from_dict({**d, "evil": 1})
        with pytest.raises(CognitionValidationError):
            CognitiveQueryRequest(target_kinds=("knowledge",), query="",
                                  mode="lookup")

    def test_artifact_ref_round_trip_and_hash(self):
        a = ArtifactRef(artifact_ref="cas:abc", sha256="f" * 64,
                        size_bytes=12, media_type="text/markdown",
                        producer_run="run-1", retention="project_lifetime")
        assert ArtifactRef.from_dict(a.to_dict()) == a
        assert a.content_hash() == ArtifactRef.from_dict(
            a.to_dict()).content_hash()

    def test_artifact_ref_negative_cases_split(self):
        """每个非法字段独立拒绝（02 §8.3：producer/retention 必填）。"""
        base = dict(artifact_ref="x", sha256="f" * 64, size_bytes=1,
                    media_type="t", producer_run="run-1",
                    retention="project_lifetime")
        for bad in ({"sha256": "nothex"}, {"producer_run": ""},
                    {"retention": ""}, {"size_bytes": True},
                    {"size_bytes": -1}, {"artifact_ref": ""}):
            with pytest.raises(CognitionValidationError):
                ArtifactRef(**{**base, **bad})

    def test_evidence_span_round_trip(self):
        s = EvidenceSpan(span_id="sp-1", chunk_id="ch-1", quote_start=0,
                         quote_end=10, quote_hash="a" * 64,
                         normalized_quote="规则 A",
                         locator={"page": 1, "section": "2.1"})
        assert EvidenceSpan.from_dict(s.to_dict()) == s
        with pytest.raises(CognitionValidationError):
            EvidenceSpan.from_dict({**s.to_dict(), "extra": True})
        with pytest.raises(CognitionValidationError):
            EvidenceSpan(span_id="s", chunk_id="c", quote_start=True,
                         quote_end=2, quote_hash="a" * 64,
                         normalized_quote="x")

    def test_claim_round_trip_and_types(self):
        c = Claim(claim_id="cl-1", research_run_id="rr-1",
                  text="报销限额 500 元",
                  claim_type="fact", importance="high",
                  support_status="supported", confidence=0.9)
        assert Claim.from_dict(c.to_dict()) == c
        with pytest.raises(CognitionValidationError):
            Claim(claim_id="cl-1", research_run_id="rr-1", text="x",
                  claim_type="guess",
                  importance="high", support_status="supported",
                  confidence=0.9)
        with pytest.raises(CognitionValidationError):
            Claim(claim_id="cl-1", research_run_id="rr-1", text="x",
                  claim_type="fact",
                  importance="high", support_status="supported",
                  confidence=1.7)
        # research_run_id 必填（Claim 必须回链研究运行，02 §6）
        with pytest.raises(CognitionValidationError):
            Claim(claim_id="cl-1", research_run_id="", text="x",
                  claim_type="fact", importance="high",
                  support_status="supported", confidence=0.5)
        # 数字字符串不得被当作 confidence（类型混淆）
        with pytest.raises(CognitionValidationError):
            Claim(claim_id="cl-1", research_run_id="rr-1", text="x",
                  claim_type="fact", importance="high",
                  support_status="supported", confidence="0.9")
        # 缺失字段走稳定错误码，不允许裸 TypeError
        with pytest.raises(CognitionValidationError):
            Claim.from_dict({"claim_id": "cl-1"})

    def test_index_snapshot_round_trip(self):
        snap = IndexSnapshot(index_snapshot_id="idx-1",
                             target_kind="knowledge",
                             corpus_snapshot_id="corpus-1",
                             backend="sqlite_lexical",
                             embedding_model=None, reranker_model=None,
                             analyzer_version="lex@1",
                             chunk_policy_version="chunk@1",
                             parameters={"k": 40}, item_count=10,
                             source_manifest_hash="b" * 64,
                             build_status="ready",
                             quality_report_ref="cas:q")
        assert IndexSnapshot.from_dict(snap.to_dict()) == snap
        with pytest.raises(CognitionValidationError):
            IndexSnapshot.from_dict({**snap.to_dict(),
                                     "build_status": "vibes"})

    def test_search_result_round_trip(self):
        r = SearchResult(query="q", candidates=[], degraded=False,
                         index_snapshot_ids=("idx-1",),
                         policy_decision={"allowed": True},
                         retrieval_trace={"rewrite": []})
        assert SearchResult.from_dict(r.to_dict()) == r


class TestHashStability:
    def test_context_hash_stable_across_field_order(self):
        c1 = _ctx()
        d = c1.to_dict()
        reordered = {k: d[k] for k in reversed(list(d))}
        assert CognitiveContext.hash_of(reordered) == c1.content_hash()

    def test_context_hash_changes_with_security_field(self):
        c1 = _ctx()
        c2 = _ctx(customer_id="cust-b")
        assert c1.content_hash() != c2.content_hash()

    def test_query_request_hash_stable(self):
        req = CognitiveQueryRequest(query="q", target_kinds=("knowledge",),
                                    mode="lookup", top_k=5, filters={},
                                    include_history=False,
                                    require_citations=True)
        d = req.to_dict()
        reordered = {k: d[k] for k in reversed(list(d))}
        assert CognitiveQueryRequest.hash_of(reordered) == \
            req.content_hash()


class TestContextSerialization:
    def test_context_round_trip(self):
        ctx = _ctx()
        assert CognitiveContext.from_dict(ctx.to_dict()) == ctx

    def test_context_unknown_field_rejected(self):
        with pytest.raises(CognitionValidationError):
            CognitiveContext.from_dict({**_ctx().to_dict(), "evil": 1})

    def test_context_missing_field_stable_code(self):
        d = _ctx().to_dict()
        d.pop("tenant_id")
        with pytest.raises(CognitionValidationError):
            CognitiveContext.from_dict(d)

    def test_as_of_z_suffix_normalized_to_utc_hash_stable(self):
        d = _ctx().to_dict()
        d["as_of"] = "2026-08-20T12:00:00Z"
        got = CognitiveContext.from_dict(d)
        assert got == _ctx()
        assert got.content_hash() == _ctx().content_hash()

    def test_as_of_invalid_string_stable_code(self):
        d = _ctx().to_dict()
        d["as_of"] = "not-a-date"
        with pytest.raises(CognitionValidationError):
            CognitiveContext.from_dict(d)

    def test_permission_tags_string_rejected(self):
        with pytest.raises(CognitionValidationError):
            _ctx(permission_tags="hr-confidential")
        with pytest.raises(CognitionValidationError):
            CognitiveContext.from_dict(
                {**_ctx().to_dict(), "permission_tags": "hr"})

    def test_permission_tags_order_insensitive(self):
        c1 = _ctx(permission_tags=("b-tag", "a-tag"))
        c2 = _ctx(permission_tags=("a-tag", "b-tag"))
        assert c1 == c2
        assert c1.content_hash() == c2.content_hash()


class TestScopeAdapterNegatives:
    def test_empty_tenant_rejected_not_whitewashed(self):
        with pytest.raises(CognitionValidationError):
            context_from_scope(_scope(tenant_id=""), principal_id="alice",
                               action="cognition.knowledge.search",
                               as_of=AS_OF)

    def test_falsy_mapping_subclass_still_rejected(self):
        class Sneaky(dict):
            def __bool__(self):
                return False
        with pytest.raises(CognitionPolicyError):
            context_from_scope(_scope(), principal_id="alice",
                               action="cognition.knowledge.search",
                               as_of=AS_OF,
                               untrusted_overrides=Sneaky(
                                   {"principal_id": "mallory"}))

    def test_empty_customer_requires_policy_declaration(self):
        # 未声明动作：空 customer/project fail-closed
        with pytest.raises(CognitionPolicyError):
            context_from_scope(_scope(customer_id="", project_id=""),
                               principal_id="alice",
                               action="cognition.totally.unknown.action",
                               as_of=AS_OF)
        # 已声明平台级动作：允许空（EMPTY_SCOPE_POLICY 显式例外）
        ctx = context_from_scope(_scope(customer_id="", project_id=""),
                                 principal_id="alice",
                                 action="cognition.knowledge.search",
                                 as_of=AS_OF)
        assert ctx.customer_id == "" and ctx.project_id == ""


class TestContractMissingFields:
    def test_query_request_missing_fields_stable_code(self):
        with pytest.raises(CognitionValidationError):
            CognitiveQueryRequest.from_dict({"query": "q"})

    def test_query_request_bool_top_k_rejected(self):
        with pytest.raises(CognitionValidationError):
            CognitiveQueryRequest(query="q",
                                  target_kinds=("knowledge",),
                                  mode="lookup", top_k=True)

    def test_index_snapshot_missing_fields_stable_code(self):
        with pytest.raises(CognitionValidationError):
            IndexSnapshot.from_dict({"index_snapshot_id": "idx-1"})
