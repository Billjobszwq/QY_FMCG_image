"""W4 Recognition bridge / monitor proxy 契约测试（TDD）。

- legacy.recognition.v2 adapter：base64 转发、错误分类（400/429/503/超时/连接失败）
- legacy.training.monitor adapter：live/overview 代理
- /api/v1/recognition/recognize 与 /api/v1/monitor/* 端点
"""

import base64

import httpx

from src.platform.adapters.legacy.recognition import (
    RecognitionAdapterError,
    RecognitionV2Adapter,
)
from src.platform.adapters.legacy.monitor import MonitorAdapter, MonitorAdapterError

TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _mock_adapter(handler):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return RecognitionV2Adapter(base_url="http://legacy:8091", client=client)


class TestRecognitionAdapter:
    def test_recognize_forwards_base64_and_returns_products(self):
        seen = {}

        def handler(req):
            seen["url"] = str(req.url)
            seen["body"] = req.content
            return httpx.Response(
                200,
                json={"run_id": "r1", "products": [{"sku": "A"}], "count": 1, "elapsed_ms": 12},
            )

        ad = _mock_adapter(handler)
        result = ad.recognize(TINY_PNG, conf=0.25)
        assert seen["url"].endswith("/v2/recognize")
        assert result["run_id"] == "r1"
        assert result["count"] == 1
        import json

        assert json.loads(seen["body"])["image_base64"] == base64.b64encode(TINY_PNG).decode()

    def test_503_mapped_to_model_unavailable(self):
        ad = _mock_adapter(
            lambda req: httpx.Response(503, json={"error": "MODEL_UNAVAILABLE", "detail": "x"})
        )
        try:
            ad.recognize(TINY_PNG)
            raise AssertionError("expected error")
        except RecognitionAdapterError as e:
            assert e.kind == "model_unavailable"

    def test_429_mapped_to_overloaded_with_retry(self):
        ad = _mock_adapter(lambda req: httpx.Response(429, json={"error": "OVERLOADED"}))
        try:
            ad.recognize(TINY_PNG)
            raise AssertionError("expected error")
        except RecognitionAdapterError as e:
            assert e.kind == "overloaded"

    def test_400_mapped_to_bad_request(self):
        ad = _mock_adapter(lambda req: httpx.Response(400, json={"error": "bad base64"}))
        try:
            ad.recognize(TINY_PNG)
            raise AssertionError("expected error")
        except RecognitionAdapterError as e:
            assert e.kind == "bad_request"

    def test_connection_error_classified(self):
        def refuse(req):
            raise httpx.ConnectError("refused")

        ad = _mock_adapter(refuse)
        try:
            ad.recognize(TINY_PNG)
            raise AssertionError("expected error")
        except RecognitionAdapterError as e:
            assert e.kind == "unreachable"

    def test_timeout_classified(self):
        def slow(req):
            raise httpx.ReadTimeout("slow")

        ad = _mock_adapter(slow)
        try:
            ad.recognize(TINY_PNG)
            raise AssertionError("expected error")
        except RecognitionAdapterError as e:
            assert e.kind == "timeout"


class TestMonitorAdapter:
    def test_live_and_overview_return_json(self):
        def handler(req):
            if req.url.path == "/api/live":
                return httpx.Response(200, json={"phase": "idle"})
            return httpx.Response(200, json={"yolo_runs": []})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        ad = MonitorAdapter(base_url="http://legacy:8092", client=client)
        assert ad.live()["phase"] == "idle"
        assert ad.overview()["yolo_runs"] == []

    def test_down_raises_classified_error(self):
        def refuse(req):
            raise httpx.ConnectError("refused")

        ad = MonitorAdapter(base_url="http://legacy:8092", client=httpx.Client(transport=httpx.MockTransport(refuse)))
        try:
            ad.live()
            raise AssertionError("expected error")
        except MonitorAdapterError as e:
            assert e.kind == "unreachable"


class TestBridgeEndpoints:
    def _client(self, recognize_handler=None, monitor_handler=None):
        from fastapi.testclient import TestClient
        from src.platform.api.app import create_app
        from src.platform.adapters.legacy.recognition import RecognitionV2Adapter
        from src.platform.adapters.legacy.monitor import MonitorAdapter

        rec = None
        mon = None
        if recognize_handler is not None:
            rec = RecognitionV2Adapter(
                base_url="http://legacy:8091",
                client=httpx.Client(transport=httpx.MockTransport(recognize_handler)),
            )
        if monitor_handler is not None:
            mon = MonitorAdapter(
                base_url="http://legacy:8092",
                client=httpx.Client(transport=httpx.MockTransport(monitor_handler)),
            )
        app = create_app(recognition_adapter=rec, monitor_adapter=mon)
        return TestClient(app)

    def test_recognize_multipart_roundtrip(self):
        def handler(req):
            return httpx.Response(200, json={"run_id": "r9", "products": [], "count": 0, "elapsed_ms": 3})

        client = self._client(recognize_handler=handler)
        r = client.post(
            "/api/v1/recognition/recognize",
            files={"file": ("t.png", TINY_PNG, "image/png")},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["run_id"] == "r9"
        assert body["capability"] == "legacy.recognition.v2"

    def test_recognize_rejects_oversize(self):
        client = self._client(recognize_handler=lambda req: httpx.Response(200, json={}))
        big = b"\x00" * (11 * 1024 * 1024)
        r = client.post(
            "/api/v1/recognition/recognize",
            files={"file": ("big.png", big, "image/png")},
        )
        assert r.status_code == 413

    def test_recognize_upstream_unreachable_is_502(self):
        def refuse(req):
            raise httpx.ConnectError("refused")

        client = self._client(recognize_handler=refuse)
        r = client.post(
            "/api/v1/recognition/recognize",
            files={"file": ("t.png", TINY_PNG, "image/png")},
        )
        assert r.status_code == 502
        assert r.json()["error"] == "unreachable"

    def test_monitor_live_proxy(self):
        def handler(req):
            return httpx.Response(200, json={"phase": "idle"})

        client = self._client(monitor_handler=handler)
        assert client.get("/api/v1/monitor/live").json()["phase"] == "idle"

    def test_monitor_down_is_503_not_crash(self):
        def refuse(req):
            raise httpx.ConnectError("refused")

        client = self._client(monitor_handler=refuse)
        r = client.get("/api/v1/monitor/live")
        assert r.status_code == 503
