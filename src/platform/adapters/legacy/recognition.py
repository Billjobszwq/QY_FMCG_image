"""legacy.recognition.v2 adapter：转发识别请求到 8091 /v2/recognize。

失败分类（adapter 必须报告失败类型，手册 §6）：
- bad_request        上游 400
- overloaded         上游 429（可重试）
- model_unavailable  上游 503
- unreachable        连接失败
- timeout            超时
- bad_response       其他/非 JSON
"""

from __future__ import annotations

import base64

import httpx

CAPABILITY_ID = "legacy.recognition.v2"


class RecognitionAdapterError(Exception):
    def __init__(self, kind: str, detail: str = "", upstream_status: int | None = None):
        super().__init__(f"{kind}: {detail}")
        self.kind = kind
        self.detail = detail
        self.upstream_status = upstream_status


class RecognitionV2Adapter:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8091",
        timeout: float = 60.0,
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

    def recognize(self, image_bytes: bytes, conf: float = 0.25) -> dict:
        payload = {"image_base64": base64.b64encode(image_bytes).decode(), "conf": conf}
        try:
            resp = self._get_client().post(
                self.base_url + "/v2/recognize", json=payload, timeout=self.timeout
            )
        except httpx.TimeoutException as e:
            raise RecognitionAdapterError("timeout", str(e)) from e
        except httpx.HTTPError as e:
            raise RecognitionAdapterError("unreachable", str(e)) from e

        if resp.status_code == 200:
            try:
                return resp.json()
            except Exception as e:
                raise RecognitionAdapterError("bad_response", "invalid JSON", resp.status_code) from e

        detail = resp.text[:300]
        if resp.status_code == 400:
            kind = "bad_request"
        elif resp.status_code == 429:
            kind = "overloaded"
        elif resp.status_code == 503:
            kind = "model_unavailable"
        else:
            kind = "bad_response"
        raise RecognitionAdapterError(kind, detail, resp.status_code)

    def close(self) -> None:
        if self._owns_client and self._client is not None:
            self._client.close()
            self._client = None
