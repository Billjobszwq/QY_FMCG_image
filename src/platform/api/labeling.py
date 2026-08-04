"""M4：Label Studio 闭环 API（批次/导入/对账/webhook 收件箱）。

平台只承载 HTTP 边界；标注业务逻辑在 src/modules/labeling（经组合根注入）。
"""

from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel

from ..adapters.legacy.label_studio import LabelStudioAdapterError

MAX_UPLOAD_BYTES = 15 * 1024 * 1024

# prediction_builder(photos) -> (按文件名 prediction dict, 失败数)；由组合根注入域逻辑
PredictionBuilder = Callable[[list[tuple[str, bytes]]], tuple[dict[str, list[dict]], int]]


class CreateBatchBody(BaseModel):
    name: str


def create_labeling_router(
    service: Any,
    *,
    label_config: str,
    prediction_builder: PredictionBuilder | None = None,
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/labeling/batches")
    def list_batches():
        batches = service.list_batches()
        return {"count": len(batches), "batches": batches}

    @router.post("/api/v1/labeling/batches")
    def create_batch(body: CreateBatchBody):
        if not body.name.strip():
            raise HTTPException(status_code=400, detail="name 不能为空")
        try:
            return service.create_batch(body.name.strip(), label_config)
        except LabelStudioAdapterError as e:
            raise HTTPException(status_code=502, detail=f"Label Studio 不可用: {e}")

    @router.get("/api/v1/labeling/batches/{batch_id}")
    def get_batch(batch_id: str):
        try:
            return service.get_batch(batch_id)
        except Exception as e:
            raise HTTPException(status_code=404, detail=str(e))

    @router.post("/api/v1/labeling/batches/{batch_id}/import")
    async def import_photos(
        batch_id: str,
        files: list[UploadFile] = File(...),
        assisted_from_recognition: bool = True,
    ):
        photos: list[tuple[str, bytes]] = []
        for f in files:
            data = await f.read()
            if len(data) > MAX_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail=f"{f.filename} too large")
            if not data:
                raise HTTPException(status_code=400, detail=f"{f.filename} 为空")
            photos.append((f.filename or f"upload_{len(photos)}.jpg", data))
        if not photos:
            raise HTTPException(status_code=400, detail="无文件")

        preds: dict[str, list[dict]] = {}
        pred_failures = 0
        if assisted_from_recognition and prediction_builder is not None:
            preds, pred_failures = prediction_builder(photos)
        try:
            report = service.import_photos(
                batch_id,
                photos,
                assisted_predictions=preds or None,
                model_version="legacy.recognition.v2@cascade_v3",
            )
        except LabelStudioAdapterError as e:
            raise HTTPException(status_code=502, detail=f"Label Studio 不可用: {e}")
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))
        report["prediction_failures"] = pred_failures
        return report

    @router.get("/api/v1/labeling/batches/{batch_id}/reconcile")
    def reconcile(batch_id: str):
        try:
            return service.reconcile(batch_id)
        except Exception as e:
            raise HTTPException(status_code=404, detail=str(e))

    @router.post("/api/v1/webhooks/label-studio")
    async def webhook_inbox(request: Request):
        try:
            payload = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="非 JSON payload")
        event_id = request.headers.get("X-Event-Id")
        result = service.ingest_webhook(payload, event_id=event_id)
        return result

    @router.get("/api/v1/labeling/inbox")
    def inbox(project_id: int | None = None):
        events = service.inbox(project_id=project_id)
        return {"count": len(events), "events": events}

    return router
