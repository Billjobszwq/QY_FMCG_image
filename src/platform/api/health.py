"""W2 Health adapters：探测 legacy 服务并聚合平台健康状态。

健康语义（PV2-D-005）：
- healthy：全部服务正常
- degraded：非关键服务不可用或健康但异常（平台自身继续服务）
- unavailable：关键服务（如 8091 识别）不可用

探测绝不抛异常：超时/连接拒绝/非2xx 都归类为状态而非错误。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, asdict

import httpx

HEALTHY = "healthy"
DEGRADED = "degraded"
UNAVAILABLE = "unavailable"
DISABLED = "disabled"  # GLTC D1：legacy/disabled 服务不探测、不计 degraded


@dataclass(frozen=True)
class ServiceSpec:
    """一个被探测服务的声明式规格（无 FMCG 硬编码）。"""

    name: str
    base_url: str
    health_path: str
    critical: bool = False
    # require_ok_flag=True 时要求响应 JSON 的 ok 字段为 true（如 8091 /v2/health）
    require_ok_flag: bool = False
    description: str = ""
    # disabled=True：legacy 链路，不发起探测，不影响平台聚合状态
    disabled: bool = False


# 手册 §5 端口表 + services.json（ISSUE-018）
DEFAULT_SERVICES: tuple[ServiceSpec, ...] = (
    ServiceSpec(
        "recognize",
        "http://127.0.0.1:8091",
        "/v2/health",
        critical=True,
        require_ok_flag=True,
        description="级联识别服务（legacy.recognition.v2 适配对象）",
    ),
    ServiceSpec(
        "monitor",
        "http://127.0.0.1:8092",
        "/api/live",
        critical=False,
        description="训练/平台统一监控（legacy.training.monitor 适配对象）",
    ),
    ServiceSpec(
        "label_studio",
        "http://127.0.0.1:8300",
        "/health",
        critical=False,
        description="Label Studio 标注/审核平台",
    ),
    ServiceSpec(
        "ml_backend",
        "http://127.0.0.1:8301",
        "/health",
        critical=False,
        description="Label Studio 预标注 ML backend（legacy/disabled："
                    "proposal 正式写入口已收敛到平台识别能力，GLTC D1）",
        disabled=True,
    ),
    ServiceSpec(
        "omlx",
        "http://127.0.0.1:8455",
        "/health",
        critical=False,
        description="omlx 内部模型能力（模型接口需 API key，/health 无需）",
    ),
)


@dataclass(frozen=True)
class ServiceStatus:
    name: str
    status: str  # HEALTHY / DEGRADED / UNAVAILABLE
    latency_ms: float | None = None
    detail: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def probe_service(
    spec: ServiceSpec,
    timeout: float = 2.0,
    client: httpx.Client | None = None,
) -> ServiceStatus:
    """探测单个服务。任何异常都归类为 unavailable，绝不向调用方抛出。

    disabled 服务不发起探测（GLTC D1）：直接返回 disabled 状态。
    """
    if spec.disabled:
        return ServiceStatus(spec.name, DISABLED, None,
                             "legacy/disabled：不探测")

    def _probe(c: httpx.Client) -> ServiceStatus:
        try:
            t0 = time.monotonic()
            resp = c.get(spec.base_url + spec.health_path, timeout=timeout)
            latency = round((time.monotonic() - t0) * 1000, 2)
        except httpx.TimeoutException:
            return ServiceStatus(spec.name, UNAVAILABLE, None, "timeout")
        except httpx.HTTPError:
            return ServiceStatus(spec.name, UNAVAILABLE, None, "connection_error")

        if resp.status_code >= 400:
            return ServiceStatus(spec.name, UNAVAILABLE, latency, f"HTTP {resp.status_code}")

        if spec.require_ok_flag:
            try:
                payload = resp.json()
            except Exception:
                return ServiceStatus(spec.name, DEGRADED, latency, "invalid health JSON")
            if not payload.get("ok"):
                err = payload.get("error") or "ok != true"
                return ServiceStatus(spec.name, DEGRADED, latency, str(err))

        return ServiceStatus(spec.name, HEALTHY, latency, None)

    if client is not None:
        return _probe(client)
    with httpx.Client() as c:
        return _probe(c)


def aggregate_platform(pairs: list[tuple[ServiceSpec, ServiceStatus]]) -> str:
    """由 (spec, status) 列表计算平台整体状态。

    disabled 服务不参与聚合（GLTC D1）：legacy 链路下线不得把
    平台拖入 degraded。
    """

    for spec, st in pairs:
        if spec.disabled:
            continue
        if spec.critical and st.status == UNAVAILABLE:
            return UNAVAILABLE
    for spec, st in pairs:
        if spec.disabled:
            continue
        if st.status != HEALTHY:
            return DEGRADED
    return HEALTHY
