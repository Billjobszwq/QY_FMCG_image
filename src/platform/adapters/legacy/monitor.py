"""legacy.training.monitor adapter：只读代理 8092 监控数据。"""

from __future__ import annotations

import httpx

CAPABILITY_ID = "legacy.training.monitor"


class MonitorAdapterError(Exception):
    def __init__(self, kind: str, detail: str = ""):
        super().__init__(f"{kind}: {detail}")
        self.kind = kind
        self.detail = detail


class MonitorAdapter:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8092",
        timeout: float = 5.0,
        client: httpx.Client | None = None,
    ):
        self.base_url = base_url
        self.timeout = timeout
        self._client = client
        self._owns_client = client is None

    @property
    def capability_id(self) -> str:
        return CAPABILITY_ID

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client()
        return self._client

    def _get(self, path: str) -> dict:
        try:
            resp = self._get_client().get(self.base_url + path, timeout=self.timeout)
        except httpx.TimeoutException as e:
            raise MonitorAdapterError("timeout", str(e)) from e
        except httpx.HTTPError as e:
            raise MonitorAdapterError("unreachable", str(e)) from e
        if resp.status_code >= 400:
            raise MonitorAdapterError("bad_response", f"HTTP {resp.status_code}")
        try:
            return resp.json()
        except Exception as e:
            raise MonitorAdapterError("bad_response", "invalid JSON") from e

    def live(self) -> dict:
        return self._get("/api/live")

    def overview(self) -> dict:
        return self._get("/api/overview")

    def close(self) -> None:
        if self._owns_client and self._client is not None:
            self._client.close()
            self._client = None
