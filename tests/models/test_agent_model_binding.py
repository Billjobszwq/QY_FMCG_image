"""M8（G7）：Agent Definition 模型绑定与消费者迁移合同。

合同（DEC-M004/M010、01 §6）：
- Agent 模型变更只创建 Definition 新 draft；Soul/Prompt/Tools/Budget/
  Memory ACL 原样保留（字节等价）；
- checker 批准后发布并重建 Manifest 投影；旧版本可回滚；
- Resolver 的 Agent 事实源钩子返回 source=agent_definition；
- 统一调用端口：受管路径落账本；旧环境变量回退显式标注
  source=legacy_env 并可观测；
- 未通过 probe / 无 chat 能力的模型不得绑定。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.platform.agents.runtime import AgentRuntime
from src.platform.data.store import PlatformStore
from src.platform.models.contracts import StateMachineError
from src.platform.models.integrations import (
    agent_definition_lookup_factory,
)
from src.platform.models.invocation import ModelInvocationService
from src.platform.models.providers.base import (
    ChatResult,
    EmbedResult,
    ProbeResult,
    ProviderModel,
    Usage,
)
from src.platform.models.resolver import ModelResolver
from src.platform.models.secrets import EncryptedSQLiteSecretStore
from src.platform.models.service import ModelManagementServices

KEK = bytes(range(32))
API_KEY = b"sk-m8-test-key"


class FakeChatAdapter:
    kind = "openai_compatible"

    def list_models(self):
        return [ProviderModel(model_id="fake-chat"),
                ProviderModel(model_id="fake-embed")]

    def probe(self, model_id, capability):
        return ProbeResult(ok=True, capability=capability,
                           model_id=model_id)

    def embed(self, request):
        return EmbedResult(model_id=request.model_id,
                           vectors=((0.1, 0.2),) * len(request.inputs),
                           dimension=2, usage=Usage(),
                           usage_complete=False, provider_request_id="",
                           latency_ms=1.0)

    def chat(self, request):
        return ChatResult(model_id=request.model_id, text="composed-answer",
                          finish_reason="stop",
                          usage=Usage(input_tokens=11, output_tokens=7),
                          usage_complete=True, provider_request_id="req-m8",
                          latency_ms=3.0)


@pytest.fixture()
def env(tmp_path: Path):
    store = PlatformStore(tmp_path / "p.sqlite")
    runtime = AgentRuntime(store)
    svc = ModelManagementServices(
        store,
        secret_store=EncryptedSQLiteSecretStore(store, kek=KEK),
        iam=None,
        adapter_factory=lambda row, get_secret: FakeChatAdapter())
    from src.platform.iam import IAMService
    svc.iam = IAMService(store)
    return store, runtime, svc


def _active_chat_connection(svc, model_id="fake-chat",
                            capabilities=("chat",)) -> None:
    from src.platform.models.contracts import (
        CatalogManualEntry, ConnectionDraft)
    draft = ConnectionDraft.model_validate({
        "name": "llm-gw", "location": "api",
        "adapter_kind": "openai_compatible",
        "base_url": "https://93.184.216.34/v1",
        "timeout_ms": 30000, "max_retries": 1})
    conn = svc.create_connection_draft(tenant_id="local", draft=draft,
                                       actor="maker", connection_id="llm-gw")
    svc.set_secret(tenant_id="local", connection_id="llm-gw",
                   version=conn.version, value=API_KEY, actor="maker")
    test = svc.test_connection(tenant_id="local", connection_id="llm-gw",
                               version=conn.version, actor="maker")
    assert test["ok"]
    sub = svc.submit_connection(tenant_id="local", connection_id="llm-gw",
                                version=conn.version, actor="maker")
    svc.policy.decide_approval(sub["approval_id"], actor="checker",
                               decision="approved")
    svc.approve_connection(tenant_id="local", connection_id="llm-gw",
                           version=conn.version, approver="checker",
                           approval_id=sub["approval_id"])
    entry = CatalogManualEntry.model_validate({
        "model_id": model_id, "capabilities": list(capabilities)})
    cat = svc.register_manual(tenant_id="local", connection_id="llm-gw",
                              version=conn.version, entry=entry,
                              actor="maker")
    probe = svc.probe_model(tenant_id="local", catalog_id=cat.catalog_id,
                            actor="maker")
    assert probe["probe_status"] == "ready"


class TestAgentDefinitionBinding:
    def test_draft_replaces_only_provider_and_model(self, env):
        store, runtime, svc = env
        _active_chat_connection(svc)
        before = runtime.get_published_definition("supervisor")
        out = svc.propose_agent_model_change(
            agent_runtime=runtime, agent_id="supervisor",
            connection_id="llm-gw", connection_version=1,
            model_id="fake-chat", actor="maker")
        draft = runtime.get_definition("supervisor", out["version"])
        assert draft["status"] == "draft"
        assert draft["provider"] == "connection:llm-gw@v1"
        assert draft["model"] == "fake-chat"
        # 其余字段原样保留（字节等价）
        assert json.dumps(draft["soul"], sort_keys=True,
                          ensure_ascii=False) == json.dumps(
                              before["soul"], sort_keys=True,
                              ensure_ascii=False)
        assert draft["system_prompt"] == before["system_prompt"]
        assert draft["tool_allowlist"] == before["tool_allowlist"]
        assert draft["budget"] == before["budget"]

    def test_unprobed_or_non_chat_model_rejected(self, env):
        store, runtime, svc = env
        _active_chat_connection(svc, model_id="fake-embed",
                                capabilities=("embedding",))
        with pytest.raises(StateMachineError):
            svc.propose_agent_model_change(
                agent_runtime=runtime, agent_id="supervisor",
                connection_id="llm-gw", connection_version=1,
                model_id="fake-embed", actor="maker")
        with pytest.raises(StateMachineError):
            svc.propose_agent_model_change(
                agent_runtime=runtime, agent_id="supervisor",
                connection_id="llm-gw", connection_version=1,
                model_id="never-registered", actor="maker")

    def test_publish_requires_checker_and_rebuilds_manifest(self, env):
        store, runtime, svc = env
        _active_chat_connection(svc)
        svc.propose_agent_model_change(
            agent_runtime=runtime, agent_id="supervisor",
            connection_id="llm-gw", connection_version=1,
            model_id="fake-chat", actor="maker")
        draft = runtime.get_definition("supervisor")
        sub = svc.submit_agent_model_change(
            agent_id="supervisor", version=draft["version"], actor="maker")
        # maker 自批拒绝（decide 层即拦截；verify 层为第二道防御）
        from src.platform.governance.policy_service import GovernanceError
        with pytest.raises(GovernanceError):
            svc.policy.decide_approval(sub["approval_id"], actor="maker",
                                       decision="approved")
        with pytest.raises(GovernanceError):
            svc.approve_agent_model_change(
                agent_runtime=runtime, agent_id="supervisor",
                version=draft["version"], approver="maker",
                approval_id=sub["approval_id"])
        # checker 批准 → 发布 + Manifest 投影一致
        svc.policy.decide_approval(sub["approval_id"], actor="checker",
                                   decision="approved")
        out = svc.approve_agent_model_change(
            agent_runtime=runtime, agent_id="supervisor",
            version=draft["version"], approver="checker",
            approval_id=sub["approval_id"])
        assert out["status"] == "published"
        pub = runtime.get_published_definition("supervisor")
        assert pub["provider"] == "connection:llm-gw@v1"
        assert pub["version"] == draft["version"]
        from src.platform.agents.manifest_projection import (
            consistency_report)
        assert consistency_report(store)["ok"] is True

    def test_rollback_restores_previous_provider(self, env):
        store, runtime, svc = env
        _active_chat_connection(svc)
        before = runtime.get_published_definition("supervisor")
        svc.propose_agent_model_change(
            agent_runtime=runtime, agent_id="supervisor",
            connection_id="llm-gw", connection_version=1,
            model_id="fake-chat", actor="maker")
        draft = runtime.get_definition("supervisor")
        sub = svc.submit_agent_model_change(
            agent_id="supervisor", version=draft["version"], actor="maker")
        svc.policy.decide_approval(sub["approval_id"], actor="checker",
                                   decision="approved")
        svc.approve_agent_model_change(
            agent_runtime=runtime, agent_id="supervisor",
            version=draft["version"], approver="checker",
            approval_id=sub["approval_id"])
        svc.rollback_agent_model(agent_runtime=runtime,
                                 agent_id="supervisor", actor="checker")
        pub = runtime.get_published_definition("supervisor")
        assert pub["provider"] == before["provider"]
        assert pub["model"] == before["model"]


class TestResolverAgentHook:
    def test_lookup_returns_agent_definition_source(self, env):
        store, runtime, svc = env
        _active_chat_connection(svc)
        svc.propose_agent_model_change(
            agent_runtime=runtime, agent_id="survey_agent",
            connection_id="llm-gw", connection_version=1,
            model_id="fake-chat", actor="maker")
        draft = runtime.get_definition("survey_agent")
        sub = svc.submit_agent_model_change(
            agent_id="survey_agent", version=draft["version"],
            actor="maker")
        svc.policy.decide_approval(sub["approval_id"], actor="checker",
                                   decision="approved")
        svc.approve_agent_model_change(
            agent_runtime=runtime, agent_id="survey_agent",
            version=draft["version"], approver="checker",
            approval_id=sub["approval_id"])
        resolver = ModelResolver(
            svc.repo,
            agent_definition_lookup=agent_definition_lookup_factory(
                runtime, svc.repo))
        from src.platform.models.contracts import ResolveRequest
        req = ResolveRequest.model_validate({
            "principal_id": "svc", "tenant_id": "local",
            "subject_kind": "module", "subject_id": "agent:survey_agent",
            "capability": "chat", "as_of": "2027-01-01T00:00:00+00:00"})
        resolved = resolver.resolve(req)
        assert resolved is not None
        assert resolved.source == "agent_definition"
        assert resolved.model_id == "fake-chat"
        assert resolved.connection_id == "llm-gw"


class TestInvocationService:
    def test_managed_chat_records_usage_with_agent_attribution(self, env):
        store, runtime, svc = env
        _active_chat_connection(svc)
        svc.propose_agent_model_change(
            agent_runtime=runtime, agent_id="analytics_agent",
            connection_id="llm-gw", connection_version=1,
            model_id="fake-chat", actor="maker")
        draft = runtime.get_definition("analytics_agent")
        sub = svc.submit_agent_model_change(
            agent_id="analytics_agent", version=draft["version"],
            actor="maker")
        svc.policy.decide_approval(sub["approval_id"], actor="checker",
                                   decision="approved")
        svc.approve_agent_model_change(
            agent_runtime=runtime, agent_id="analytics_agent",
            version=draft["version"], approver="checker",
            approval_id=sub["approval_id"])
        inv = ModelInvocationService(svc)
        pub = runtime.get_published_definition("analytics_agent")
        out = inv.chat_for_agent(
            "analytics_agent", published_definition=pub,
            messages=[{"role": "user", "content": "hi"}],
            principal_id="alice")
        assert out["source"] == "managed"
        assert out["text"] == "composed-answer"
        rows = [r for r in store.list_usage_events_v2()
                if r.get("model_call_id")]
        assert rows
        for r in rows:
            assert r["principal_id"] == "alice"
            assert r["connection_id"] == "llm-gw"
            assert r["model"] == "fake-chat"
        ledger = store._conn.execute(
            "SELECT * FROM model_call_ledger_v1").fetchall()
        assert any(l["agent_id"] == "analytics_agent" for l in ledger)

    def test_legacy_env_fallback_marked_and_audited(self, env, monkeypatch):
        store, runtime, svc = env
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        inv = ModelInvocationService(svc)
        from src.platform.models.providers.base import ProviderError
        # 未配置受管连接且无环境变量 → 诚实拒绝（不静默）
        with pytest.raises(ProviderError):
            inv.chat_for_agent(
                "supervisor",
                published_definition={"provider": "rules_tool_loop",
                                      "model": ""},
                messages=[{"role": "user", "content": "hi"}],
                principal_id="alice")
        audits = [e for e in svc.iam.list_audit(limit=50)
                  if e["action"] == "model.legacy_env_fallback"]
        assert audits, "legacy 回退必须可观测（审计）"

    def test_runtime_compose_without_port_keeps_honest_none(self, env,
                                                            monkeypatch):
        store, runtime, svc = env
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        defn = runtime.get_published_definition("supervisor")
        assert runtime._llm_compose(defn, "你好", "工具事实") is None
