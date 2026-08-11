"""ABOSV3 T3：Import Center API（统一导入中心）。

- GET  /api/v1/import/templates：14 套模板清单；
- GET  /api/v1/import/templates/{tid}/download?fmt=csv|xlsx：模板下载
  （下载后必须能被同一系统重新解析，round-trip 测试强制）；
- POST /api/v1/import/upload：上传（multipart，template_id 字段）；
- GET  /api/v1/import/batches / /batches/{id}：批次与逐行错误；
- POST /batches/{id}/dry-run：预检（新增/跳过/冲突/错误分类）；
- POST /batches/{id}/commit：提交（幂等、证据、审计）；
- GET  /batches/{id}/errors.csv：错误报告下载。
"""
from __future__ import annotations

import csv
import io
from typing import Any

from fastapi import (APIRouter, File, Form, HTTPException, Request,
                     UploadFile)
from fastapi.responses import Response

from ..auth import AuthService, require_principal
from ..import_center import ImportError_, ImportCenter


def create_import_router(center: ImportCenter,
                         auth: AuthService | None) -> APIRouter:
    router = APIRouter(tags=["import-center"])

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
                     file: UploadFile = File(...)) -> dict:
        p = require_principal(auth, request, csrf=True)
        data = await file.read()
        if len(data) > 20 * 1024 * 1024:
            raise HTTPException(413, "上传文件超过 20MB 限制")
        try:
            return {"batch": center.upload(
                template_id=template_id, filename=file.filename or "",
                data=data, actor=p["actor"])}
        except ImportError_ as e:
            raise HTTPException(409, str(e))

    @router.get("/api/v1/import/batches")
    def batches(request: Request) -> dict:
        require_principal(auth, request, csrf=False)
        rows = center.list_batches()
        # 列表只回摘要（不返回全部行/回执）
        slim = [{k: b[k] for k in
                 ("batch_id", "template_id", "filename", "file_format",
                  "status", "actor", "row_count", "created_at",
                  "updated_at")} | {"errors": len(b["errors"])}
                for b in rows]
        return {"count": len(slim), "batches": slim}

    @router.get("/api/v1/import/batches/{batch_id}")
    def batch(batch_id: str, request: Request) -> dict:
        require_principal(auth, request, csrf=False)
        try:
            b = center.get_batch(batch_id)
        except ImportError_ as e:
            raise HTTPException(404, str(e))
        b.pop("mapping", None)  # 行内容经 errors/dry_run 呈现
        return {"batch": b}

    @router.post("/api/v1/import/batches/{batch_id}/dry-run")
    def dry_run(batch_id: str, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        try:
            b = center.dry_run(batch_id)
        except ImportError_ as e:
            raise HTTPException(409, str(e))
        b.pop("mapping", None)
        return {"batch": b}

    @router.post("/api/v1/import/batches/{batch_id}/commit")
    def commit(batch_id: str, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        try:
            b = center.commit(batch_id, actor=p["actor"])
        except ImportError_ as e:
            raise HTTPException(409, str(e))
        b.pop("mapping", None)
        return {"batch": b}

    @router.get("/api/v1/import/batches/{batch_id}/errors.csv")
    def errors_csv(batch_id: str, request: Request):
        require_principal(auth, request, csrf=False)
        try:
            b = center.get_batch(batch_id)
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
