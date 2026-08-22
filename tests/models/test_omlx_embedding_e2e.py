"""M7（G6）：统一模型管理 → 认知索引桥接 + 本地 OMLX e2e。

hermetic 单元（fake adapter）验证桥接合同；真实 e2e 只在
127.0.0.1:8455 可达且受控凭据可用时执行，否则如实 skip
（BLOCKED_BY_PROVIDER_AUTH），绝不用 fake 顶替真实语义证据。
凭据来源：进程环境 TAAS_OMLX_API_KEY 或用户本机 OMLX 配置；
测试不打印、不写入任何凭据值。
"""
from __future__ import annotations

import json
import math
import os
import socket
import urllib.request
from pathlib import Path

import pytest

from src.platform.data.store import PlatformStore
from src.platform.models.bootstrap import bootstrap_local_omlx
from src.platform.models.integrations import (
    ManagedVectorProvider,
    resolve_embedding_provider,
)
from src.platform.models.providers.base import (
    EmbedResult,
    ProbeResult,
    ProviderModel,
    Usage,
)
from src.platform.models.secrets import EncryptedSQLiteSecretStore
from src.platform.models.service import ModelManagementServices

KEK = bytes(range(32))
FAKE_DIM = 8


class FakeOmlxAdapter:
    kind = "openai_compatible"

    def list_models(self):
        return [ProviderModel(model_id="Qwen3-Embedding-0.6B-8bit")]

    def probe(self, model_id, capability):
        return ProbeResult(ok=True, capability=capability,
                           model_id=model_id,
                           dimension=FAKE_DIM if capability == "embedding"
                           else None)

    def embed(self, request):
        vecs = tuple(
            tuple(1.0 / math.sqrt(FAKE_DIM) for _ in range(FAKE_DIM))
            for _ in request.inputs)
        return EmbedResult(model_id=request.model_id, vectors=vecs,
                           dimension=FAKE_DIM, usage=Usage(),
                           usage_complete=False, provider_request_id="",
                           latency_ms=1.0)

    def chat(self, request):
        raise AssertionError("M7 桥接测试不调用 chat")


@pytest.fixture()
def services(tmp_path: Path):
    store = PlatformStore(tmp_path / "p.sqlite")
    svc = ModelManagementServices(
        store,
        secret_store=EncryptedSQLiteSecretStore(store, kek=KEK),
        adapter_factory=lambda row, get_secret: FakeOmlxAdapter())
    yield svc
    store.close()


class TestManagedBridge:
    def test_bootstrap_and_resolve_managed_provider(self, services):
        out = bootstrap_local_omlx(services, get_key=lambda: b"fake-key")
        assert out["ok"] is True and out["stage"] == "complete"
        assert out["embedding_dimension"] == FAKE_DIM
        assert "fake-key" not in json.dumps(out, ensure_ascii=False)

        provider = resolve_embedding_provider(
            services, principal_id="svc-eval")
        assert provider is not None
        assert provider.model_name == "Qwen3-Embedding-0.6B-8bit"
        assert provider.dimension == FAKE_DIM
        assert provider.provider_id == "managed:local-omlx@v1"
        vecs = provider.encode_documents(["a", "b"])
        assert len(vecs) == 2 and len(vecs[0]) == FAKE_DIM

    def test_no_binding_returns_none_legacy_fallback(self, services):
        assert resolve_embedding_provider(
            services, principal_id="svc-eval") is None

    def test_disabled_connection_blocks_resolve(self, services):
        bootstrap_local_omlx(services, get_key=lambda: b"fake-key")
        services.disable_connection(tenant_id="local",
                                    connection_id="local-omlx",
                                    version=1, actor="admin")
        assert resolve_embedding_provider(
            services, principal_id="svc-eval") is None

    def test_dimension_mismatch_fails_closed(self):
        class BadDim(FakeOmlxAdapter):
            def embed(self, request):
                r = super().embed(request)
                return EmbedResult(model_id=r.model_id, vectors=r.vectors,
                                   dimension=4, usage=r.usage,
                                   usage_complete=False,
                                   provider_request_id="", latency_ms=1.0)

        adapter = BadDim()
        provider = ManagedVectorProvider(
            adapter, connection_id="c", connection_version=1,
            model_id="m", model_revision="", dimension=FAKE_DIM,
            normalization_version="l2-normalized@v1")
        with pytest.raises(RuntimeError):
            provider.encode_documents(["x"])


# ---------------------------------------------------------------- real e2e


def _omlx_reachable() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 8455), timeout=3):
            return True
    except OSError:
        return False


def _omlx_key() -> bytes | None:
    env = os.environ.get("TAAS_OMLX_API_KEY", "").strip()
    if env:
        return env.encode("utf-8")
    settings = Path.home() / ".omlx" / "settings.json"
    try:
        cfg = json.loads(settings.read_text())
        key = (cfg.get("auth") or {}).get("api_key") or ""
        return key.encode("utf-8") if key else None
    except (OSError, json.JSONDecodeError):
        return None


_SKIP_REASON = ("BLOCKED_BY_PROVIDER_AUTH/BLOCKED_BY_LOCAL_EMBEDDING："
                "本机 OMLX 不可达或无受控凭据；不得用 fake 顶替真实证据")


@pytest.mark.skipif(not (_omlx_reachable() and _omlx_key()),
                    reason=_SKIP_REASON)
class TestRealOmlxEmbedding:
    def test_real_bootstrap_probe_and_semantic_sanity(self, tmp_path):
        key = _omlx_key()
        assert key
        store = PlatformStore(tmp_path / "omlx.sqlite")
        svc = ModelManagementServices(
            store, secret_store=EncryptedSQLiteSecretStore(store, kek=KEK))
        out = bootstrap_local_omlx(svc, get_key=lambda: key)
        assert out["ok"] is True, out
        assert out["model_id"] == "Qwen3-Embedding-0.6B-8bit"
        assert out["embedding_dimension"] > 0
        assert out["normalization_version"]

        provider = resolve_embedding_provider(svc, principal_id="svc-e2e")
        assert provider is not None
        vecs = provider.encode_queries([
            "员工入职满一年可以享受五天年假",
            "工作满一年的职员享有 5 天带薪假期",
            "货架陈列检查每天早晨进行",
        ])
        assert len(vecs) == 3
        dim = len(vecs[0])
        assert dim == out["embedding_dimension"]

        def cos(a, b):
            num = sum(x * y for x, y in zip(a, b))
            da = math.sqrt(sum(x * x for x in a))
            db = math.sqrt(sum(x * x for x in b))
            return num / (da * db) if da and db else 0.0

        paraphrase = cos(vecs[0], vecs[1])
        unrelated = cos(vecs[0], vecs[2])
        assert paraphrase > unrelated, (
            f"真实语义相似性必须可分：{paraphrase} <= {unrelated}")
        assert paraphrase > 0.5, "同语义改写应显著相似"
        # Usage 归属：真实调用必须落模型账本（诚实单位，不伪造）
        usage_rows = [r for r in store.list_usage_events_v2()
                      if r.get("model_call_id")]
        assert usage_rows, "真实调用必须产生账号级 Usage"
        for r in usage_rows:
            assert r["principal_id"] == "svc-e2e"
            assert r["connection_id"] == "local-omlx"
            assert r["binding_id"] == "cognition-embedding-default"
            assert r["model"] == "Qwen3-Embedding-0.6B-8bit"
            assert r["meter_source"] in ("provider_reported",
                                         "platform_observed")
        units = {r["unit"] for r in usage_rows}
        assert "model_request" in units and "embedding_input" in units
        # 凭据卫生：全程产物不得含密钥
        assert key.decode("utf-8") not in json.dumps(
            out, ensure_ascii=False)
        store.close()
