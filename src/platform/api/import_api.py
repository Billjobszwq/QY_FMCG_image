"""ABOSV3 T3：Import Center API（统一导入中心）。
OSV5（指令第六节）：全端点接入 IAMService 与结构化作用域。

- GET  /api/v1/import/templates：14 套模板清单；
- GET  /api/v1/import/templates/{tid}/download?fmt=csv|xlsx：模板下载；
- POST /api/v1/import/upload：上传（multipart；模板权限矩阵 +
  逐客户整批授权 fail-closed；可选 test_run_id 同事务写 fixture）；
- GET  /api/v1/import/batches：默认 effective operational ∩ 调用者
  客户作用域；view=mine|history|quarantine；include_fixture 需授权；
- GET  /batches/{id}：批次作用域授权 + 显式 DTO（无原始 payload）；
- GET  /batches/{id}/preview：原始行预览（创建者/data.import.audit，
  脱敏 + 行数上限）；
- POST /batches/{id}/dry-run、/commit：权限 + 作用域 + 归档守卫；
- GET  /batches/{id}/errors.csv：批次作用域授权。
"""
from __future__ import annotations

import csv
import io

from fastapi import (APIRouter, File, Form, HTTPException, Request,
                     UploadFile)
from fastapi.responses import Response

from ..auth import AuthService, require_principal
from ..import_center import (ImportAuthError, ImportCenter, ImportError_,
                             TEMPLATE_SCOPE)
from ..scope import ScopeViolation


def create_import_router(center: ImportCenter,
                         auth: AuthService | None) -> APIRouter:
    router = APIRouter(tags=["import-center"])

    def _principal(request: Request, *, csrf: bool) -> dict:
        p = require_principal(auth, request, csrf=csrf)
        return p

    @router.get("/api/v1/import/templates")
    def templates(request: Request) -> dict:
        require_principal(auth, request, csrf=False)
        rows = center.list_templates()
        return {"count": len(rows), "templates": rows}

    @router.get("/api/v1/import/templates/{template_id}/download")
    def download(template_id: str, request: Request,
                 fmt: str = "csv"):
        require_principal(auth, request, csrf=False)
        try:
            data, filename = center.render_template(template_id, fmt)
        except ImportError_ as e:
            raise HTTPException(404, str(e))
        media = ("application/vnd.openxmlformats-officedocument"
                 ".spreadsheetml.sheet" if fmt == "xlsx" else "text/csv")
        return Response(
            content=data, media_type=media,
            headers={"content-disposition":
                     f'attachment; filename="{filename}"'})

    @router.post("/api/v1/import/upload")
    async def upload(request: Request,
                     template_id: str = Form(...),
                     test_run_id: str = Form(""),
                     file: UploadFile = File(...)) -> dict:
        p = _principal(request, csrf=True)
        from ..rate_limit import enforce
        enforce(request, "import.upload", p["actor"])
        data = await file.read()
        if len(data) > 20 * 1024 * 1024:
            raise HTTPException(413, "上传文件超过 20MB 限制")
        try:
            return {"batch": center.upload(
                template_id=template_id, filename=file.filename or "",
                data=data, actor=p["actor"], session_role=p["role"],
                test_run_id=test_run_id)}
        except ImportAuthError as e:
            raise HTTPException(403, str(e))
        except ScopeViolation as e:
            # archived/不存在 test_run → fail-closed 409
            raise HTTPException(409, str(e))
        except ImportError_ as e:
            raise HTTPException(409, str(e))

    @router.get("/api/v1/import/batches")
    def batches(request: Request, view: str = "operational",
                include_fixture: str = "") -> dict:
        p = _principal(request, csrf=False)
        if view not in ("operational", "mine", "history", "quarantine"):
            raise HTTPException(422, f"非法 view: {view}")
        try:
            rows = center.list_batches(
                actor=p["actor"], session_role=p["role"], view=view,
                include_fixture=include_fixture in ("1", "true"))
        except ImportAuthError as e:
            raise HTTPException(403, str(e))
        return {"count": len(rows), "batches": rows, "view": view}

    @router.get("/api/v1/import/batches/{batch_id}")
    def batch(batch_id: str, request: Request) -> dict:
        p = _principal(request, csrf=False)
        try:
            b = center.get_batch(batch_id)
            center.authorize_batch(p["actor"], p["role"], b)
        except ImportAuthError as e:
            raise HTTPException(403, str(e))
        except ImportError_ as e:
            raise HTTPException(404, str(e))
        return {"batch": center.batch_dto(b)}

    @router.get("/api/v1/import/batches/{batch_id}/preview")
    def preview(batch_id: str, request: Request) -> dict:
        """原始行预览：仅创建者或 data.import.audit（脱敏+行数上限）。"""
        p = _principal(request, csrf=False)
        try:
            b = center.get_batch(batch_id)
        except ImportError_ as e:
            raise HTTPException(404, str(e))
        platform = center._platform_actor(p["actor"], p["role"])
        if p["actor"] != b.get("actor") and not platform and \
                not center.iam.authorize(p["actor"], "data.import.audit"):
            raise HTTPException(
                403, "IMPORT_PREVIEW_DENIED: 原始预览需创建者或"
                " data.import.audit")
        return center.preview_rows(batch_id)

    @router.post("/api/v1/import/batches/{batch_id}/dry-run")
    def dry_run(batch_id: str, request: Request) -> dict:
        p = _principal(request, csrf=True)
        try:
            return {"batch": center.dry_run(
                batch_id, actor=p["actor"], session_role=p["role"])}
        except ImportAuthError as e:
            raise HTTPException(403, str(e))
        except ImportError_ as e:
            raise HTTPException(409, str(e))

    @router.post("/api/v1/import/batches/{batch_id}/commit")
    def commit(batch_id: str, request: Request) -> dict:
        p = _principal(request, csrf=True)
        from ..rate_limit import enforce
        enforce(request, "import.commit", p["actor"])
        try:
            return {"batch": center.commit(
                batch_id, actor=p["actor"], session_role=p["role"])}
        except ImportAuthError as e:
            raise HTTPException(403, str(e))
        except ImportError_ as e:
            raise HTTPException(409, str(e))

    @router.get("/api/v1/import/batches/{batch_id}/errors.csv")
    def errors_csv(batch_id: str, request: Request):
        p = _principal(request, csrf=False)
        try:
            b = center.get_batch(batch_id)
            center.authorize_batch(p["actor"], p["role"], b)
        except ImportAuthError as e:
            raise HTTPException(403, str(e))
        except ImportError_ as e:
            raise HTTPException(404, str(e))
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["row", "error"])
        for e in b["errors"]:
            w.writerow([e.get("row"), e.get("error")])
        return Response(
            content=buf.getvalue().encode("utf-8-sig"),
            media_type="text/csv",
            headers={"content-disposition":
                     f'attachment; filename="{batch_id}_errors.csv"'})

    return router
