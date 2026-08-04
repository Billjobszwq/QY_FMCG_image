"""W2 Health adapters 契约测试（TDD，先于实现编写）。

覆盖：
- probe_service：200+ok / ok!=true / 非2xx / 超时 / 连接拒绝 → healthy/degraded/unavailable
- aggregate_platform：critical 与非 critical 故障的健康语义
- /api/v1/health 端点结构（fake probe，不打真实网络）
"""

import httpx
import pytest

from src.platform.api.health import (
    DEGRADED,
    HEALTHY,
    UNAVAILABLE,
    DEFAULT_SERVICES,
    ServiceSpec,
    ServiceStatus,
    aggregate_platform,
    probe_service,
)


def _spec(**kw):
    base = dict(
        name="svc",
        base_url="http://127.0.0.1:9",
        health_path="/health",
        critical=False,
        require_ok_flag=False,
    )
    base.update(kw)
    return ServiceSpec(**base)


def _mock_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


class TestProbeService:
    def test_200_ok_flag_true_is_healthy(self):
        spec = _spec(require_ok_flag=True)
        client = _mock_client(lambda req: httpx.Response(200, json={"ok": True}))
        st = probe_service(spec, client=client)
        assert st.status == HEALTHY
        assert st.latency_ms is not None and st.latency_ms >= 0

    def test_200_without_ok_flag_requirement_is_healthy(self):
        spec = _spec(require_ok_flag=False)
        client = _mock_client(lambda req: httpx.Response(200, json={"phase": "idle"}))
        assert probe_service(spec, client=client).status == HEALTHY

    def test_ok_flag_false_is_degraded(self):
        spec = _spec(require_ok_flag=True)
        client = _mock_client(lambda req: httpx.Response(200, json={"ok": False, "error": "boom"}))
        st = probe_service(spec, client=client)
        assert st.status == DEGRADED
        assert st.detail

    def test_ok_flag_invalid_json_is_degraded(self):
        spec = _spec(require_ok_flag=True)
        client = _mock_client(lambda req: httpx.Response(200, text="not-json"))
        assert probe_service(spec, client=client).status == DEGRADED

    def test_non_2xx_is_unavailable(self):
        client = _mock_client(lambda req: httpx.Response(404))
        st = probe_service(_spec(), client=client)
        assert st.status == UNAVAILABLE
        assert "404" in (st.detail or "")

    def test_timeout_is_unavailable_not_exception(self):
        def raise_timeout(req):
            raise httpx.ReadTimeout("slow")

        st = probe_service(_spec(), client=_mock_client(raise_timeout))
        assert st.status == UNAVAILABLE
        assert "timeout" in (st.detail or "").lower()

    def test_connection_refused_is_unavailable_not_exception(self):
        # 端口 1 在本机不会有服务；必须返回 unavailable 而不是抛异常
        st = probe_service(_spec(base_url="http://127.0.0.1:1"), timeout=2.0)
        assert st.status == UNAVAILABLE


class TestAggregatePlatform:
    def _pairs(self, statuses):
        specs = [_spec(name=f"s{i}", critical=(i == 0)) for i in range(len(statuses))]
        return [
            (spec, ServiceStatus(name=spec.name, status=s))
            for spec, s in zip(specs, statuses)
        ]

    def test_all_healthy(self):
        pairs = self._pairs([HEALTHY, HEALTHY])
        assert aggregate_platform(pairs) == HEALTHY

    def test_noncritical_unavailable_is_degraded(self):
        pairs = self._pairs([HEALTHY, UNAVAILABLE])
        assert aggregate_platform(pairs) == DEGRADED

    def test_noncritical_degraded_is_degraded(self):
        pairs = self._pairs([HEALTHY, DEGRADED])
        assert aggregate_platform(pairs) == DEGRADED

    def test_critical_unavailable_is_unavailable(self):
        pairs = self._pairs([UNAVAILABLE, HEALTHY])
        assert aggregate_platform(pairs) == UNAVAILABLE


class TestHealthEndpoint:
    def _client(self, fake_statuses):
        from fastapi.testclient import TestClient
        from src.platform.api.app import create_app

        def fake_probe(spec, timeout=2.0):
            return ServiceStatus(
                name=spec.name,
                status=fake_statuses.get(spec.name, UNAVAILABLE),
                latency_ms=1.0,
                detail=None,
            )

        app = create_app(probe=fake_probe)
        return TestClient(app)

    def test_health_lists_all_expected_services(self):
        client = self._client({"recognize": HEALTHY, "monitor": HEALTHY})
        r = client.get("/api/v1/health")
        assert r.status_code == 200
        body = r.json()
        names = {s["name"] for s in body["services"]}
        assert {"recognize", "monitor", "label_studio", "ml_backend", "omlx"} <= names
        assert body["status"] in (HEALTHY, DEGRADED, UNAVAILABLE)
        assert "generated_at" in body

    def test_health_degraded_when_label_studio_down(self):
        client = self._client(
            {"recognize": HEALTHY, "monitor": HEALTHY, "omlx": HEALTHY}
        )  # label_studio/ml_backend → unavailable
        r = client.get("/api/v1/health")
        assert r.json()["status"] == DEGRADED

    def test_health_unavailable_when_recognize_down(self):
        client = self._client({"monitor": HEALTHY})  # recognize → unavailable（critical）
        r = client.get("/api/v1/health")
        assert r.json()["status"] == UNAVAILABLE

    def test_default_services_cover_manual_required_ports(self):
        ports = {s.base_url.rsplit(":", 1)[1] for s in DEFAULT_SERVICES}
        assert {"8091", "8092", "8300", "8301", "8455"} <= ports
