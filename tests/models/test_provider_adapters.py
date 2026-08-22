"""M3（G2）：OpenAI-compatible 与 Anthropic Adapter 的 hermetic 合同测试。

Fake HTTP server（127.0.0.1 随机端口，stdlib http.server）覆盖：
认证、429 Retry-After、timeout、非 JSON、部分响应、usage 缺失、
向量数量/维度错误与 secret 净化。主测试不访问公网。
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

OPENAI_KEY = "sk-test-openai-compatible-key-777"
ANTHROPIC_KEY = "sk-ant-test-key-888"
DIM = 8


# ------------------------------------------------------------ fake provider


class _Handler(BaseHTTPRequestHandler):
    server_version = "FakeProvider/1.0"

    # ---- 测试可注入的行为（类级配置，按用例重置）
    mode = "normal"  # normal|no_usage|bad_count|bad_dim|non_json|partial|slow|echo_key

    def log_message(self, fmt, *args):  # 静默；失败输出不得包含 header
        pass

    def _auth_ok_openai(self):
        return self.headers.get("Authorization") == f"Bearer {OPENAI_KEY}"

    def _auth_ok_anthropic(self):
        return (self.headers.get("x-api-key") == ANTHROPIC_KEY
                and bool(self.headers.get("anthropic-version")))

    def _send(self, code: int, payload: dict | None, *,
              raw: bytes | None = None, headers: dict | None = None):
        body = raw if raw is not None else json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _record_headers(self):
        self.server.received_headers.append(  # type: ignore[attr-defined]
            {k: v for k, v in self.headers.items()})

    def do_GET(self):
        self._record_headers()
        if self.path == "/v1/models":
            if not self._auth_ok_openai():
                self._send(401, {"error": {"message": "bad key"}})
                return
            self._send(200, {"data": [{"id": "fake-embed"},
                                       {"id": "fake-chat"}]})
            return
        if self.path == "/anthropic/v1/models":
            if not self._auth_ok_anthropic():
                self._send(401, {"error": {"message": "bad key"}})
                return
            self._send(200, {"data": [{"id": "claude-fake-1"}],
                             "has_more": False})
            return
        self._send(404, {"error": "not found"})

    def do_POST(self):
        self._record_headers()
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b"{}"
        try:
            req = json.loads(body)
        except json.JSONDecodeError:
            req = {}

        if self.path == "/v1/embeddings":
            if not self._auth_ok_openai():
                self._send(401, {"error": {"message": "bad key"}})
                return
            if self.mode == "echo_key":
                # 模拟 Provider 在错误体里回显凭据（adapter 必须净化）
                self._send(500, {"error": {
                    "message": f"internal failure for {OPENAI_KEY}"}})
                return
            inputs = req.get("input") or []
            dim = 4 if self.mode == "bad_dim" else DIM
            n = len(inputs) - 1 if self.mode == "bad_count" else len(inputs)
            data = [{"object": "embedding", "index": i,
                     "embedding": [0.05 * (i + 1)] * dim} for i in range(n)]
            payload = {"object": "list", "data": data,
                       "model": req.get("model", "")}
            if self.mode != "no_usage":
                payload["usage"] = {"prompt_tokens": len(inputs) * 3,
                                    "total_tokens": len(inputs) * 3}
            self._send(200, payload)
            return

        if self.path == "/v1/chat/completions":
            if not self._auth_ok_openai():
                self._send(401, {"error": {"message": "bad key"}})
                return
            if self.mode == "rate_limited":
                self._send(429, {"error": {"message": "slow down"}},
                           headers={"Retry-After": "2"})
                return
            if self.mode == "non_json":
                self._send(200, None, raw=b"<html>not json</html>")
                return
            if self.mode == "partial":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"id": "req-1", "cho')
                self.wfile.flush()
                self.connection.close()
                return
            if self.mode == "slow":
                time.sleep(1.0)
            usage = {"prompt_tokens": 11, "completion_tokens": 7}
            if self.mode == "no_usage":
                usage = {}
            self._send(200, {
                "id": "req-1", "object": "chat.completion",
                "model": req.get("model", ""),
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant",
                                         "content": "hello back"}}],
                "usage": usage})
            return

        if self.path == "/anthropic/v1/messages":
            if not self._auth_ok_anthropic():
                self._send(401, {"error": {"message": "invalid x-api-key"}})
                return
            self._send(200, {
                "id": "msg-ant-1", "type": "message", "role": "assistant",
                "model": req.get("model", ""),
                "content": [{"type": "text", "text": "anthropic says hi"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 13, "output_tokens": 5,
                          "cache_read_input_tokens": 2}})
            return

        self._send(404, {"error": "not found"})


@pytest.fixture()
def fake_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.received_headers = []
    _Handler.mode = "normal"
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield server
    server.shutdown()
    server.server_close()


def _endpoint(server, path_prefix: str = "/v1"):
    from src.platform.models.endpoint_policy import Endpoint
    host, port = server.server_address[:2]
    return Endpoint(url=f"http://{host}:{port}{path_prefix}", scheme="http",
                    host=host, port=port, path=path_prefix, query="",
                    location="local", pinned_ips=(host,))


def _openai_adapter(server, *, timeout_ms=3000, max_retries=1,
                    expected_dimension=None):
    from src.platform.models.providers.openai_compatible import (
        OpenAICompatibleAdapter)
    return OpenAICompatibleAdapter(
        _endpoint(server), get_secret=lambda: OPENAI_KEY.encode(),
        timeout_ms=timeout_ms, max_retries=max_retries,
        expected_dimension=expected_dimension)


def _anthropic_adapter(server, *, timeout_ms=3000):
    from src.platform.models.providers.anthropic import AnthropicAdapter
    return AnthropicAdapter(
        _endpoint(server, path_prefix=""),
        get_secret=lambda: ANTHROPIC_KEY.encode(),
        timeout_ms=timeout_ms, max_retries=0,
        base_path="/anthropic")


# ------------------------------------------------------------------- tests


class TestOpenAICompatible:
    def test_chat_normalization(self, fake_server):
        adapter = _openai_adapter(fake_server)
        from src.platform.models.providers.base import ChatRequest, ChatMessage
        result = adapter.chat(ChatRequest(
            model_id="fake-chat",
            messages=(ChatMessage(role="user", content="hi"),)))
        assert result.model_id == "fake-chat"
        assert result.text == "hello back"
        assert result.usage.input_tokens == 11
        assert result.usage.output_tokens == 7
        assert result.provider_request_id == "req-1"
        assert result.latency_ms >= 0

    def test_embed_normalization(self, fake_server):
        adapter = _openai_adapter(fake_server, expected_dimension=DIM)
        from src.platform.models.providers.base import EmbedRequest
        result = adapter.embed(EmbedRequest(
            model_id="fake-embed", inputs=("a", "b")))
        assert len(result.vectors) == 2
        assert all(len(v) == DIM for v in result.vectors)
        assert result.usage.input_tokens == 6
        assert result.latency_ms >= 0

    def test_list_models(self, fake_server):
        adapter = _openai_adapter(fake_server)
        ids = [m.model_id for m in adapter.list_models()]
        assert ids == ["fake-embed", "fake-chat"]

    def test_auth_header_sent(self, fake_server):
        adapter = _openai_adapter(fake_server)
        adapter.list_models()
        auths = [h.get("Authorization")
                 for h in fake_server.received_headers]  # type: ignore
        assert f"Bearer {OPENAI_KEY}" in auths

    def test_auth_failed_maps_to_stable_code(self, fake_server):
        from src.platform.models.providers.base import (
            ProviderAuthFailed, EmbedRequest)
        from src.platform.models.providers.openai_compatible import (
            OpenAICompatibleAdapter)
        from src.platform.models.contracts import MODEL_AUTH_FAILED
        adapter = OpenAICompatibleAdapter(
            _endpoint(fake_server), get_secret=lambda: b"wrong-key",
            timeout_ms=3000, max_retries=0)
        with pytest.raises(ProviderAuthFailed) as ei:
            adapter.embed(EmbedRequest(model_id="fake-embed", inputs=("a",)))
        assert ei.value.code == MODEL_AUTH_FAILED

    def test_rate_limited_429_with_retry_after(self, fake_server):
        from src.platform.models.providers.base import (
            ChatRequest, ChatMessage, ProviderRateLimited)
        _Handler.mode = "rate_limited"
        adapter = _openai_adapter(fake_server, max_retries=0)
        with pytest.raises(ProviderRateLimited) as ei:
            adapter.chat(ChatRequest(
                model_id="fake-chat",
                messages=(ChatMessage(role="user", content="hi"),)))
        assert ei.value.retry_after == 2

    def test_timeout_maps_to_stable_code(self, fake_server):
        from src.platform.models.providers.base import (
            ChatRequest, ChatMessage, ProviderTimeout)
        _Handler.mode = "slow"
        adapter = _openai_adapter(fake_server, timeout_ms=150, max_retries=0)
        with pytest.raises(ProviderTimeout):
            adapter.chat(ChatRequest(
                model_id="fake-chat",
                messages=(ChatMessage(role="user", content="hi"),)))

    def test_non_json_response_fails_closed(self, fake_server):
        from src.platform.models.providers.base import (
            ChatRequest, ChatMessage, ProviderResponseInvalid)
        _Handler.mode = "non_json"
        adapter = _openai_adapter(fake_server, max_retries=0)
        with pytest.raises(ProviderResponseInvalid):
            adapter.chat(ChatRequest(
                model_id="fake-chat",
                messages=(ChatMessage(role="user", content="hi"),)))

    def test_partial_response_fails_closed(self, fake_server):
        from src.platform.models.providers.base import (
            ChatRequest, ChatMessage, ProviderError)
        _Handler.mode = "partial"
        adapter = _openai_adapter(fake_server, max_retries=0)
        with pytest.raises(ProviderError):
            adapter.chat(ChatRequest(
                model_id="fake-chat",
                messages=(ChatMessage(role="user", content="hi"),)))

    def test_missing_usage_marked_not_complete(self, fake_server):
        from src.platform.models.providers.base import ChatRequest, ChatMessage
        _Handler.mode = "no_usage"
        adapter = _openai_adapter(fake_server, max_retries=0)
        result = adapter.chat(ChatRequest(
            model_id="fake-chat",
            messages=(ChatMessage(role="user", content="hi"),)))
        assert result.usage.input_tokens is None
        assert result.usage.output_tokens is None
        assert result.usage_complete is False

    def test_vector_count_mismatch_fails_closed(self, fake_server):
        from src.platform.models.providers.base import (
            EmbedRequest, ProviderResponseInvalid)
        _Handler.mode = "bad_count"
        adapter = _openai_adapter(fake_server, max_retries=0)
        with pytest.raises(ProviderResponseInvalid):
            adapter.embed(EmbedRequest(model_id="fake-embed",
                                       inputs=("a", "b")))

    def test_dimension_mismatch_maps_to_stable_code(self, fake_server):
        from src.platform.models.providers.base import (
            EmbedRequest, ProviderDimensionMismatch)
        from src.platform.models.contracts import MODEL_DIMENSION_MISMATCH
        _Handler.mode = "bad_dim"
        adapter = _openai_adapter(fake_server, max_retries=0,
                                  expected_dimension=DIM)
        with pytest.raises(ProviderDimensionMismatch) as ei:
            adapter.embed(EmbedRequest(model_id="fake-embed", inputs=("a",)))
        assert ei.value.code == MODEL_DIMENSION_MISMATCH

    def test_secret_never_leaks_in_repr_errors_or_logs(
            self, fake_server, capsys):
        from src.platform.models.providers.base import (
            EmbedRequest, ProviderError)
        adapter = _openai_adapter(fake_server, max_retries=0)
        assert OPENAI_KEY not in repr(adapter)
        _Handler.mode = "echo_key"  # Provider 错误体故意回显 key
        with pytest.raises(ProviderError) as ei:
            adapter.embed(EmbedRequest(model_id="fake-embed", inputs=("a",)))
        assert OPENAI_KEY not in str(ei.value)
        assert OPENAI_KEY not in repr(ei.value)
        captured = capsys.readouterr()
        assert OPENAI_KEY not in captured.out + captured.err

    def test_probe_embedding_ok(self, fake_server):
        adapter = _openai_adapter(fake_server, expected_dimension=DIM)
        probe = adapter.probe("fake-embed", "embedding")
        assert probe.ok is True
        assert probe.capability == "embedding"
        assert probe.dimension == DIM


class TestAnthropic:
    def test_messages_native_parsing(self, fake_server):
        from src.platform.models.providers.base import ChatRequest, ChatMessage
        adapter = _anthropic_adapter(fake_server)
        result = adapter.chat(ChatRequest(
            model_id="claude-fake-1",
            messages=(ChatMessage(role="user", content="hi"),)))
        assert result.text == "anthropic says hi"
        assert result.usage.input_tokens == 13
        assert result.usage.output_tokens == 5
        assert result.usage.cached_input_tokens == 2
        assert result.provider_request_id == "msg-ant-1"

    def test_auth_headers_native(self, fake_server):
        from src.platform.models.providers.base import ChatRequest, ChatMessage
        adapter = _anthropic_adapter(fake_server)
        adapter.chat(ChatRequest(
            model_id="claude-fake-1",
            messages=(ChatMessage(role="user", content="hi"),)))
        hdrs = fake_server.received_headers[-1]  # type: ignore
        assert hdrs.get("x-api-key") == ANTHROPIC_KEY
        assert hdrs.get("anthropic-version")
        assert "Authorization" not in hdrs or not hdrs["Authorization"]

    def test_list_models(self, fake_server):
        adapter = _anthropic_adapter(fake_server)
        ids = [m.model_id for m in adapter.list_models()]
        assert ids == ["claude-fake-1"]

    def test_embed_not_faked(self, fake_server):
        from src.platform.models.providers.base import (
            EmbedRequest, ProviderCapabilityMismatch)
        adapter = _anthropic_adapter(fake_server)
        with pytest.raises(ProviderCapabilityMismatch):
            adapter.embed(EmbedRequest(model_id="claude-fake-1",
                                       inputs=("a",)))

    def test_auth_failed(self, fake_server):
        from src.platform.models.providers.anthropic import AnthropicAdapter
        from src.platform.models.providers.base import ProviderAuthFailed
        adapter = AnthropicAdapter(
            _endpoint(fake_server, path_prefix=""),
            get_secret=lambda: b"wrong",
            timeout_ms=3000, max_retries=0, base_path="/anthropic")
        with pytest.raises(ProviderAuthFailed):
            adapter.list_models()

    def test_secret_not_in_repr(self, fake_server):
        adapter = _anthropic_adapter(fake_server)
        assert ANTHROPIC_KEY not in repr(adapter)
