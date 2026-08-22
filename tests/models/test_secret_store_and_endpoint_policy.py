"""M2（G1）：fail-closed 合同、AES-256-GCM SecretStore 与 EndpointPolicy。

红测试（实现前应按预期失败）：``src/platform/models`` 尚不存在。

覆盖合同 §四.8（secret write-only）、02 §5（SecretStore）、02 §6
（EndpointPolicy/SSRF）与 05 计划 M2 的全部负例。
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.platform.data.store import PlatformStore

KEK_A = bytes(range(32))
KEK_B = bytes(range(1, 33))
PLAINTEXT = b"sk-known-secret-value-0123456789"


@pytest.fixture(autouse=True)
def _isolate_provider_env(monkeypatch):
    from tests.models.helpers import PROVIDER_ENV_KEYS
    for key in PROVIDER_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture()
def store(tmp_path: Path):
    s = PlatformStore(tmp_path / "p.sqlite")
    yield s
    s.close()


@pytest.fixture()
def secret_store(store):
    from src.platform.models.secrets import EncryptedSQLiteSecretStore
    return EncryptedSQLiteSecretStore(store, kek=KEK_A)


def _scope(adapter_kind: str = "openai_compatible", tenant: str = "local"):
    from src.platform.models.secrets import SecretScope
    return SecretScope(tenant_id=tenant, secret_ref="model-secret/t1",
                       adapter_kind=adapter_kind)


# ---------------------------------------------------------------- contracts


class TestFailClosedContracts:
    def test_connection_draft_rejects_unknown_fields(self):
        from src.platform.models.contracts import ConnectionDraft
        with pytest.raises(ValidationError):
            ConnectionDraft.model_validate({
                "name": "x", "location": "api",
                "adapter_kind": "openai_compatible",
                "base_url": "https://example.com/v1",
                "timeout_ms": 30000, "max_retries": 2,
                "unexpected": "blocked",
            })

    def test_connection_draft_rejects_invalid_enums(self):
        from src.platform.models.contracts import ConnectionDraft
        base = {
            "name": "x", "adapter_kind": "openai_compatible",
            "base_url": "https://example.com/v1",
            "timeout_ms": 30000, "max_retries": 2,
        }
        with pytest.raises(ValidationError):
            ConnectionDraft.model_validate({**base, "location": "hybrid"})
        with pytest.raises(ValidationError):
            ConnectionDraft.model_validate(
                {**base, "location": "api", "adapter_kind": "azure_blob"})

    def test_connection_draft_rejects_negative_timeout_or_retries(self):
        from src.platform.models.contracts import ConnectionDraft
        base = {"name": "x", "location": "api",
                "adapter_kind": "openai_compatible",
                "base_url": "https://example.com/v1"}
        with pytest.raises(ValidationError):
            ConnectionDraft.model_validate(
                {**base, "timeout_ms": -1, "max_retries": 0})
        with pytest.raises(ValidationError):
            ConnectionDraft.model_validate(
                {**base, "timeout_ms": 0, "max_retries": 0})
        with pytest.raises(ValidationError):
            ConnectionDraft.model_validate(
                {**base, "timeout_ms": 1000, "max_retries": -2})

    def test_connection_draft_rejects_secret_material_in_config(self):
        from src.platform.models.contracts import ConnectionDraft
        base = {"name": "x", "location": "api",
                "adapter_kind": "openai_compatible",
                "base_url": "https://example.com/v1",
                "timeout_ms": 30000, "max_retries": 2}
        for forbidden in (
            {"api_key": "sk-abc"},
            {"authorization": "Bearer x"},
            {"headers": {"x-api-key": "k"}},
            {"password": "p"},
            {"secret": "s"},
        ):
            with pytest.raises(ValidationError):
                ConnectionDraft.model_validate({**base, "config": forbidden})
        # 未知 config 字段同样拒绝
        with pytest.raises(ValidationError):
            ConnectionDraft.model_validate(
                {**base, "config": {"anything": 1}})

    def test_connection_draft_rejects_non_http_scheme(self):
        from src.platform.models.contracts import ConnectionDraft
        base = {"name": "x", "location": "api",
                "adapter_kind": "openai_compatible",
                "timeout_ms": 30000, "max_retries": 2}
        for url in ("file:///etc/passwd", "ftp://host/v1", "gopher://h/"):
            with pytest.raises(ValidationError):
                ConnectionDraft.model_validate({**base, "base_url": url})

    def test_secret_submit_never_echoes_value(self):
        from src.platform.models.contracts import SecretSubmit
        sub = SecretSubmit.model_validate({"secret_value": PLAINTEXT.decode()})
        dumped = json.dumps(sub.model_dump(mode="json"))
        assert PLAINTEXT.decode() not in dumped
        assert PLAINTEXT.decode() not in repr(sub)
        assert PLAINTEXT.decode() not in sub.model_dump_json()

    def test_catalog_manual_rejects_unknown_capability(self):
        from src.platform.models.contracts import CatalogManualEntry
        with pytest.raises(ValidationError):
            CatalogManualEntry.model_validate({
                "model_id": "m", "capabilities": ["teleport"]})
        with pytest.raises(ValidationError):
            CatalogManualEntry.model_validate({
                "model_id": "m", "capabilities": ["embedding"],
                "embedding_dimension": -4})

    def test_binding_draft_rejects_unknown_fields(self):
        from src.platform.models.contracts import BindingDraft
        with pytest.raises(ValidationError):
            BindingDraft.model_validate({
                "subject_kind": "system_capability",
                "subject_id": "cognition.embedding",
                "capability": "embedding",
                "connection_id": "local-omlx",
                "connection_version": 1,
                "model_id": "Qwen3-Embedding-0.6B-8bit",
                "backdoor": True,
            })

    def test_resolve_request_requires_scope_and_capability(self):
        from src.platform.models.contracts import ResolveRequest
        with pytest.raises(ValidationError):
            ResolveRequest.model_validate({
                "tenant_id": "local", "capability": "embedding"})
        ok = ResolveRequest.model_validate({
            "principal_id": "svc", "tenant_id": "local",
            "subject_kind": "system_capability",
            "subject_id": "cognition.embedding",
            "capability": "embedding",
            "as_of": "2026-08-21T00:00:00+00:00"})
        assert ok.capability == "embedding"

    def test_error_codes_are_stable_constants(self):
        from src.platform.models import contracts
        for code in ("MODEL_AUTH_FAILED", "MODEL_ENDPOINT_BLOCKED",
                     "MODEL_DISCOVERY_UNSUPPORTED",
                     "MODEL_CAPABILITY_MISMATCH", "MODEL_DIMENSION_MISMATCH",
                     "MODEL_RATE_LIMITED", "MODEL_TIMEOUT",
                     "MODEL_METERING_INCOMPLETE", "MODEL_BUDGET_EXHAUSTED",
                     "MODEL_SECRET_UNAVAILABLE", "MODEL_PROVIDER_UNAVAILABLE",
                     "MODEL_IDENTITY_MISMATCH"):
            assert getattr(contracts, code) == code


# -------------------------------------------------------------- secret store


class TestSecretStore:
    def test_put_and_lease_roundtrip(self, secret_store):
        ref = secret_store.put(_scope(), PLAINTEXT, actor="maker")
        lease = secret_store.lease(ref.secret_ref, _scope())
        assert lease.value == PLAINTEXT

    def test_database_file_contains_no_plaintext(self, store, secret_store):
        secret_store.put(_scope(), PLAINTEXT, actor="maker")
        db_path = store._path
        blobs = db_path.read_bytes()
        wal = Path(str(db_path) + "-wal")
        if wal.exists():
            blobs += wal.read_bytes()
        assert PLAINTEXT not in blobs, "明文不得出现在数据库文件任何位置"

    def test_raw_envelope_row_is_encrypted(self, store, secret_store):
        secret_store.put(_scope(), PLAINTEXT, actor="maker")
        conn = sqlite3.connect(str(store._path))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM model_secret_envelope_v1").fetchone()
        conn.close()
        assert PLAINTEXT not in bytes(row["ciphertext"])
        assert PLAINTEXT not in bytes(row["wrapped_dek"])
        assert PLAINTEXT not in bytes(row["nonce"])
        assert row["algorithm"] == "AES-256-GCM"

    def test_repr_and_metadata_do_not_leak(self, secret_store):
        ref = secret_store.put(_scope(), PLAINTEXT, actor="maker")
        lease = secret_store.lease(ref.secret_ref, _scope())
        text = repr(ref) + repr(lease) + json.dumps(
            secret_store.metadata(ref.secret_ref), default=str)
        assert PLAINTEXT.decode() not in text
        assert PLAINTEXT not in text.encode()
        meta = secret_store.metadata(ref.secret_ref)
        for k in ("wrapped_dek", "nonce", "ciphertext", "secret_value"):
            assert k not in meta, "元数据不得包含密文字段"

    def test_wrong_kek_fails_closed(self, store, secret_store):
        from src.platform.models.secrets import (
            EncryptedSQLiteSecretStore, SecretStoreError)
        secret_store.put(_scope(), PLAINTEXT, actor="maker")
        evil = EncryptedSQLiteSecretStore(store, kek=KEK_B)
        with pytest.raises(SecretStoreError):
            evil.lease("model-secret/t1", _scope())

    def test_aad_scope_mismatch_fails_closed(self, secret_store):
        from src.platform.models.secrets import SecretStoreError
        secret_store.put(_scope(), PLAINTEXT, actor="maker")
        with pytest.raises(SecretStoreError):
            secret_store.lease("model-secret/t1", _scope(tenant="other"))
        with pytest.raises(SecretStoreError):
            secret_store.lease(
                "model-secret/t1", _scope(adapter_kind="anthropic"))

    def test_revoke_blocks_lease(self, secret_store):
        from src.platform.models.secrets import SecretNotFoundError
        meta = secret_store.put(_scope(), PLAINTEXT, actor="maker")
        secret_store.revoke(meta.secret_ref, actor="admin")
        with pytest.raises(SecretNotFoundError):
            secret_store.lease(meta.secret_ref, _scope())

    def test_rotate_supersedes_old_version_without_fallback(
            self, secret_store):
        from src.platform.models.secrets import SecretStoreError
        meta1 = secret_store.put(_scope(), PLAINTEXT, actor="maker")
        new_value = b"sk-rotated-value-9876543210"
        meta2 = secret_store.rotate(_scope(), new_value, actor="maker")
        assert meta2.version == meta1.version + 1
        lease = secret_store.lease(meta1.secret_ref, _scope())
        assert lease.value == new_value, "轮换后必须只返回新值"
        # 旧版本已 rotated：直接按旧版本 lease 拒绝（无自动回落）
        with pytest.raises(SecretStoreError):
            secret_store.lease_version(meta1.secret_ref, meta1.version,
                                       _scope())

    def test_put_twice_requires_rotate(self, secret_store):
        from src.platform.models.secrets import SecretStoreError
        secret_store.put(_scope(), PLAINTEXT, actor="maker")
        with pytest.raises(SecretStoreError):
            secret_store.put(_scope(), b"other", actor="maker")

    def test_missing_kek_is_unavailable_no_default_key(self, store):
        from src.platform.models.secrets import (
            EncryptedSQLiteSecretStore, SecretStoreUnavailable)
        unconfigured = EncryptedSQLiteSecretStore(store, kek=None)
        with pytest.raises(SecretStoreUnavailable):
            unconfigured.put(_scope(), PLAINTEXT, actor="maker")
        with pytest.raises(SecretStoreUnavailable):
            unconfigured.lease("model-secret/t1", _scope())

    def test_bad_kek_length_rejected(self, store):
        from src.platform.models.secrets import EncryptedSQLiteSecretStore
        with pytest.raises(ValueError):
            EncryptedSQLiteSecretStore(store, kek=b"short")

    def test_lease_is_short_lived(self, secret_store):
        from src.platform.models.secrets import SecretLeaseExpired
        meta = secret_store.put(_scope(), PLAINTEXT, actor="maker")
        short = secret_store.lease(meta.secret_ref, _scope(),
                                   ttl_seconds=0.01)
        assert short.expires_at > 0
        time.sleep(0.03)
        with pytest.raises(SecretLeaseExpired):
            secret_store.validate_lease(short)


# ------------------------------------------------------------ endpoint policy


class TestEndpointPolicy:
    def _policy(self, resolver=None):
        from src.platform.models.endpoint_policy import EndpointPolicy
        return EndpointPolicy(resolver=resolver)

    def test_rejects_non_http_schemes(self):
        from src.platform.models.endpoint_policy import EndpointPolicyError
        pol = self._policy()
        for url in ("file:///etc/passwd", "ftp://example.com/v1",
                    "javascript:alert(1)", "http+ssh://h/", "gopher://h/"):
            with pytest.raises(EndpointPolicyError):
                pol.validate(url, location="api")

    def test_rejects_userinfo_fragment_empty_host_and_oversize(self):
        from src.platform.models.endpoint_policy import EndpointPolicyError
        pol = self._policy()
        with pytest.raises(EndpointPolicyError):
            pol.validate("https://user:pass@example.com/v1", location="api")
        with pytest.raises(EndpointPolicyError):
            pol.validate("https://example.com/v1#frag", location="api")
        with pytest.raises(EndpointPolicyError):
            pol.validate("https:///v1", location="api")
        with pytest.raises(EndpointPolicyError):
            pol.validate("https://example.com/" + "a" * 4000, location="api")

    def test_api_requires_https(self):
        from src.platform.models.endpoint_policy import EndpointPolicyError
        pol = self._policy()
        with pytest.raises(EndpointPolicyError):
            pol.validate("http://api.example.com/v1", location="api")

    def test_api_rejects_private_loopback_linklocal_metadata(self):
        from src.platform.models.endpoint_policy import EndpointPolicyError
        pol = self._policy()
        for url in (
            "https://127.0.0.1/v1",
            "https://[::1]/v1",
            "https://10.0.0.5/v1",
            "https://192.168.1.10/v1",
            "https://172.16.4.4/v1",
            "https://169.254.169.254/latest/meta-data/",
            "https://169.254.1.1/v1",
            "https://[fe80::1]/v1",
            "https://[fc00::1]/v1",
            "https://0.0.0.0/v1",
            "https://224.0.0.1/v1",
        ):
            with pytest.raises(EndpointPolicyError):
                pol.validate(url, location="api")

    def test_local_allows_http_loopback_only(self):
        pol = self._policy()
        ep = pol.validate("http://127.0.0.1:8455/v1", location="local")
        assert ep.host == "127.0.0.1" and ep.port == 8455
        ep6 = pol.validate("http://[::1]:8455/v1", location="local")
        assert ep6.host == "::1"

    def test_local_rejects_public_and_private_non_loopback(self):
        from src.platform.models.endpoint_policy import EndpointPolicyError
        pol = self._policy()
        with pytest.raises(EndpointPolicyError):
            pol.validate("http://8.8.8.8:8455/v1", location="local")
        with pytest.raises(EndpointPolicyError):
            pol.validate("http://192.168.1.5:8455/v1", location="local")

    def test_api_allows_https_public_hostname(self):
        def resolver(host, port):
            assert host == "api.example.com"
            return ["93.184.216.34"]
        pol = self._policy(resolver=resolver)
        ep = pol.validate("https://api.example.com/v1", location="api")
        assert ep.pinned_ips == ("93.184.216.34",)

    def test_dns_rebinding_any_private_ip_fails_closed(self):
        from src.platform.models.endpoint_policy import EndpointPolicyError

        def resolver(host, port):
            return ["93.184.216.34", "169.254.169.254"]
        pol = self._policy(resolver=resolver)
        with pytest.raises(EndpointPolicyError):
            pol.validate("https://evil.example.com/v1", location="api")

    def test_unresolvable_host_fails_closed(self):
        from src.platform.models.endpoint_policy import EndpointPolicyError

        def resolver(host, port):
            raise OSError("no such host")
        pol = self._policy(resolver=resolver)
        with pytest.raises(EndpointPolicyError):
            pol.validate("https://no-such-host.example/v1", location="api")

    def test_redirect_target_revalidated(self):
        from src.platform.models.endpoint_policy import EndpointPolicyError
        pol = self._policy()
        with pytest.raises(EndpointPolicyError):
            pol.validate_redirect("http://127.0.0.1/v1", location="api")
        with pytest.raises(EndpointPolicyError):
            pol.validate_redirect("https://10.1.2.3/v1", location="api")
        # local 模式下回环重定向允许
        ep = pol.validate_redirect("http://127.0.0.1:8455/v1/models",
                                   location="local")
        assert ep.path == "/v1/models"

    def test_connection_targets_are_pinned_validated_ips(self):
        def resolver(host, port):
            return ["93.184.216.34"]
        pol = self._policy(resolver=resolver)
        ep = pol.validate("https://api.example.com/v1", location="api")
        targets = ep.connect_targets()
        assert targets, "必须提供 pinned 连接目标"
        for ip, port in targets:
            assert ip == "93.184.216.34"
            assert port == 443
