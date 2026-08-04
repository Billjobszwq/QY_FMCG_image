"""W6/M2：RequestContext（request_id / idempotency_key / UTC 时间）+ 中间件。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware

REQUEST_ID_HEADER = "x-request-id"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class RequestContext:
    request_id: str
    created_at: str
    idempotency_key: str | None = None
    run_id: str | None = None


def new_request_context(
    idempotency_key: str | None = None,
    run_id: str | None = None,
    request_id: str | None = None,
) -> RequestContext:
    return RequestContext(
        request_id=request_id or uuid.uuid4().hex,
        created_at=_utcnow_iso(),
        idempotency_key=idempotency_key,
        run_id=run_id,
    )


class RequestContextMiddleware(BaseHTTPMiddleware):
    """为每个请求生成/沿用 X-Request-Id，并存入 request.state.context。"""

    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        request.state.context = new_request_context(
            request_id=rid,
            idempotency_key=request.headers.get("idempotency-key"),
        )
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = rid
        return response


def install_request_context_middleware(app: FastAPI) -> None:
    app.add_middleware(RequestContextMiddleware)
