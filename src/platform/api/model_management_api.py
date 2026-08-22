"""统一模型管理 API：/api/v1/models/*（M4/G3，02 §1/§2）。

安全合同：
- 全部端点 session 鉴权；写端点额外 CSRF；资源读取与变更按 IAM scope
  授权（models.*），跨主体统一 404 零泄漏。
- 错误码稳定（02 §2）：401/403/404/409/422/429/503。
- GET 返回配置/状态/凭据元数据（secret_configured/secret_version/
  last_rotated_at），永不返回 API Key、密文、认证 header 或可逆掩码。
- 普通员工无 models.* 权限：后端独立强制，不依赖前端隐藏。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from ..api.cognition_auth import is_platform_principal
from ..auth import AuthService, require_principal
from ..governance.policy_service import GovernanceError
from ..iam import IAMService
from ..models.contracts import (
    BindingDraft,
    CatalogManualEntry,
    ConnectionDraft,
    ModelManagementError,
    SecretSubmit,
)
from ..models.service import ModelManagementServices

# 权限集（02 §7；M5 注册进 IAM SCOPES 与角色矩阵）
P_USE = "models.use"
P_CONFIG_READ = "models.config.read"
P_CONN_MANAGE = "models.connection.manage"
P_SECRET_ROTATE = "models.secret.rotate"
P_BINDING_MANAGE = "models.binding.manage"
P_RELEASE_APPROVE = "models.release.approve"
P_USAGE_READ = "models.usage.read"
P_AUDIT_READ = "models.audit.read"

_TENANT = "local"  # V1 单租户部署；多租户由 IAM membership 派生（后续）


def _error_response(e: ModelManagementError) -> JSONResponse:
    return JSONResponse(status_code=e.http_status,
                        content=e.safe_payload())


def _governance_error(e: GovernanceError) -> JSONResponse:
    """审批账本拒绝（maker=checker、未批准、不匹配等）→ 409。"""
    return JSONResponse(status_code=409, content={
        "error_code": "MODEL_APPROVAL_INVALID",
        "message": str(e)})


def _state_error(message: str) -> ModelManagementError:
    from ..models.contracts import StateMachineError
    return StateMachineError(message)


def create_model_management_router(services: ModelManagementServices, *,
                                   auth: AuthService,
                                   iam: IAMService) -> APIRouter:
    router = APIRouter()

    # ------------------------------------------------------------ helpers

    def _principal(request: Request, *, csrf: bool):
        return require_principal(auth, request, csrf=csrf)

    def _authorize(principal: dict, scope: str, *,
                   customer_id: str = "", project_id: str = "") -> None:
        if is_platform_principal(iam, principal):
            return
        if not iam.authorize(principal["actor"], scope,
                             customer_id=customer_id,
                             project_id=project_id):
            raise HTTPException(
                status_code=403,
                detail="无模型管理权限（后端强制，与前端投影无关）")

    # -------------------------------------------------------- connections

    @router.get("/api/v1/models/connections")
    def list_connections(request: Request):
        p = _principal(request, csrf=False)
        _authorize(p, P_CONFIG_READ)
        rows = services.repo.list_connections(tenant_id=_TENANT)
        latest: dict[str, dict] = {}
        for row in rows:
            view = services.public_connection_view(row)
            cur = latest.get(row.connection_id)
            if cur is None or view["version"] > cur["version"]:
                latest[row.connection_id] = view
        active = {r.connection_id: r.version for r in rows
                  if r.status == "active"}
        out = []
        for cid, view in sorted(latest.items()):
            view["active_version"] = active.get(cid)
            out.append(view)
        return {"count": len(out), "connections": out}

    @router.get("/api/v1/models/connections/{connection_id}")
    def get_connection(request: Request, connection_id: str,
                       version: int | None = None):
        p = _principal(request, csrf=False)
        _authorize(p, P_CONFIG_READ)
        row = None
        if version is None:
            latest = services.repo.latest_connection_version(
                tenant_id=_TENANT, connection_id=connection_id)
            if latest > 0:
                row = services.repo.get_connection(
                    tenant_id=_TENANT, connection_id=connection_id,
                    version=latest)
        else:
            row = services.repo.get_connection(
                tenant_id=_TENANT, connection_id=connection_id,
                version=version)
        if row is None:
            return JSONResponse(status_code=404, content={
                "error_code": "MODEL_NOT_FOUND",
                "message": "资源不存在或不可见"})
        return services.public_connection_view(row)

    @router.post("/api/v1/models/connections/drafts")
    async def create_draft(request: Request):
        p = _principal(request, csrf=True)
        _authorize(p, P_CONN_MANAGE)
        body = await request.json()
        # connection_id 是信封字段，不属于合同本体
        payload = {k: v for k, v in body.items() if k != "connection_id"}
        try:
            draft = ConnectionDraft.model_validate(payload)
        except ValidationError as e:
            return JSONResponse(status_code=422, content={
                "error_code": "MODEL_CONTRACT_INVALID",
                "message": "输入合同不合法",
                "fields": [list(err["loc"]) + [err["msg"]]
                           for err in e.errors()]})
        try:
            row = services.create_connection_draft(
                tenant_id=_TENANT, draft=draft, actor=p["actor"],
                connection_id=body.get("connection_id"))
            return {"connection_id": row.connection_id,
                    "version": row.version, "status": row.status,
                    "etag": row.etag}
        except ModelManagementError as e:
            return _error_response(e)

    @router.post("/api/v1/models/connections/{connection_id}"
                 "/versions/{version}/secret")
    async def submit_secret(request: Request, connection_id: str,
                            version: int):
        p = _principal(request, csrf=True)
        _authorize(p, P_SECRET_ROTATE)
        body = await request.json()
        try:
            sub = SecretSubmit.model_validate(body)
        except ValidationError:
            return JSONResponse(status_code=422, content={
                "error_code": "MODEL_CONTRACT_INVALID",
                "message": "secret 输入不合法"})
        try:
            result = services.set_secret(
                tenant_id=_TENANT, connection_id=connection_id,
                version=version,
                value=sub.secret_value.get_secret_value().encode("utf-8"),
                actor=p["actor"])
        except ModelManagementError as e:
            return _error_response(e)
        # write-only：不回显任何凭据内容
        return result

    @router.post("/api/v1/models/connections/{connection_id}"
                 "/versions/{version}/test")
    async def test_connection(request: Request, connection_id: str,
                              version: int):
        p = _principal(request, csrf=True)
        _authorize(p, P_CONN_MANAGE)
        try:
            return services.test_connection(
                tenant_id=_TENANT, connection_id=connection_id,
                version=version, actor=p["actor"])
        except ModelManagementError as e:
            return _error_response(e)

    @router.post("/api/v1/models/connections/{connection_id}"
                 "/versions/{version}/submit")
    async def submit_connection(request: Request, connection_id: str,
                                version: int):
        p = _principal(request, csrf=True)
        _authorize(p, P_CONN_MANAGE)
        body = await request.json() if await request.body() else {}
        try:
            return services.submit_connection(
                tenant_id=_TENANT, connection_id=connection_id,
                version=version, actor=p["actor"],
                expected_etag=body.get("expected_etag"))
        except ModelManagementError as e:
            return _error_response(e)

    @router.post("/api/v1/models/connections/{connection_id}"
                 "/versions/{version}/approve")
    async def approve_connection(request: Request, connection_id: str,
                                 version: int):
        p = _principal(request, csrf=True)
        _authorize(p, P_RELEASE_APPROVE)
        body = await request.json()
        approval_id = body.get("approval_id", "")
        try:
            return services.approve_connection(
                tenant_id=_TENANT, connection_id=connection_id,
                version=version, approver=p["actor"],
                approval_id=approval_id)
        except ModelManagementError as e:
            return _error_response(e)
        except GovernanceError as e:
            return _governance_error(e)

    @router.post("/api/v1/models/connections/{connection_id}"
                 "/versions/{version}/disable")
    async def disable_connection(request: Request, connection_id: str,
                                 version: int):
        p = _principal(request, csrf=True)
        _authorize(p, P_RELEASE_APPROVE)
        body = await request.json() if await request.body() else {}
        try:
            return services.disable_connection(
                tenant_id=_TENANT, connection_id=connection_id,
                version=version, actor=p["actor"],
                expected_etag=body.get("expected_etag"))
        except ModelManagementError as e:
            return _error_response(e)

    # ------------------------------------------------------------- catalog

    @router.get("/api/v1/models/catalog")
    def list_catalog(request: Request, connection_id: str | None = None):
        p = _principal(request, csrf=False)
        _authorize(p, P_CONFIG_READ)
        rows = services.repo.list_catalog(
            tenant_id=_TENANT, connection_id=connection_id)
        return {"count": len(rows), "entries": [_catalog_view(r)
                                                 for r in rows]}

    @router.post("/api/v1/models/connections/{connection_id}"
                 "/versions/{version}/discover")
    async def discover_models(request: Request, connection_id: str,
                              version: int):
        p = _principal(request, csrf=True)
        _authorize(p, P_CONN_MANAGE)
        try:
            found = services.discover_models(
                tenant_id=_TENANT, connection_id=connection_id,
                version=version, actor=p["actor"])
            return {"count": len(found), "models": found}
        except ModelManagementError as e:
            return _error_response(e)

    @router.post("/api/v1/models/catalog/manual")
    async def register_manual(request: Request):
        p = _principal(request, csrf=True)
        _authorize(p, P_CONN_MANAGE)
        body = await request.json()
        # connection_id/connection_version 是信封字段，不属于目录合同
        payload = {k: v for k, v in body.items()
                   if k not in ("connection_id", "connection_version")}
        try:
            entry = CatalogManualEntry.model_validate(payload)
        except ValidationError:
            return JSONResponse(status_code=422, content={
                "error_code": "MODEL_CONTRACT_INVALID",
                "message": "目录输入不合法"})
        try:
            row = services.register_manual(
                tenant_id=_TENANT,
                connection_id=body.get("connection_id", ""),
                version=int(body.get("connection_version", 0) or 0),
                entry=entry, actor=p["actor"])
            return _catalog_view(row)
        except (ModelManagementError, ValueError, TypeError) as e:
            if isinstance(e, (ValueError, TypeError)):
                return JSONResponse(status_code=422, content={
                    "error_code": "MODEL_CONTRACT_INVALID",
                    "message": "connection 标识不合法"})
            return _error_response(e)

    @router.post("/api/v1/models/catalog/{catalog_id}/probe")
    async def probe_model(request: Request, catalog_id: str):
        p = _principal(request, csrf=True)
        _authorize(p, P_CONN_MANAGE)
        try:
            return services.probe_model(tenant_id=_TENANT,
                                        catalog_id=catalog_id,
                                        actor=p["actor"])
        except ModelManagementError as e:
            return _error_response(e)

    # ------------------------------------------------------------ bindings

    @router.get("/api/v1/models/bindings")
    def list_bindings(request: Request, subject_kind: str | None = None,
                      capability: str | None = None,
                      status: str | None = None):
        p = _principal(request, csrf=False)
        _authorize(p, P_CONFIG_READ)
        rows = services.repo.list_bindings(
            tenant_id=_TENANT, subject_kind=subject_kind,
            capability=capability, status=status)
        return {"count": len(rows), "bindings": [_binding_view(r)
                                                  for r in rows]}

    @router.post("/api/v1/models/bindings/drafts")
    async def create_binding_draft(request: Request):
        p = _principal(request, csrf=True)
        _authorize(p, P_BINDING_MANAGE)
        body = await request.json()
        payload = {k: v for k, v in body.items() if k != "binding_id"}
        try:
            draft = BindingDraft.model_validate(payload)
        except ValidationError:
            return JSONResponse(status_code=422, content={
                "error_code": "MODEL_CONTRACT_INVALID",
                "message": "binding 输入不合法"})
        try:
            row = services.create_binding_draft(
                tenant_id=_TENANT, draft=draft, actor=p["actor"],
                binding_id=body.get("binding_id"))
            return {"binding_id": row.binding_id, "version": row.version,
                    "status": row.status, "etag": row.etag}
        except ModelManagementError as e:
            return _error_response(e)

    @router.post("/api/v1/models/bindings/{binding_id}"
                 "/versions/{version}/validate")
    async def validate_binding(request: Request, binding_id: str,
                               version: int):
        p = _principal(request, csrf=True)
        _authorize(p, P_BINDING_MANAGE)
        body = await request.json() if await request.body() else {}
        try:
            return services.validate_binding(
                tenant_id=_TENANT, binding_id=binding_id, version=version,
                actor=p["actor"], expected_etag=body.get("expected_etag"))
        except ModelManagementError as e:
            return _error_response(e)

    @router.post("/api/v1/models/bindings/{binding_id}"
                 "/versions/{version}/submit")
    async def submit_binding(request: Request, binding_id: str,
                             version: int):
        p = _principal(request, csrf=True)
        _authorize(p, P_BINDING_MANAGE)
        body = await request.json() if await request.body() else {}
        try:
            return services.submit_binding(
                tenant_id=_TENANT, binding_id=binding_id, version=version,
                actor=p["actor"], expected_etag=body.get("expected_etag"))
        except ModelManagementError as e:
            return _error_response(e)

    @router.post("/api/v1/models/bindings/{binding_id}"
                 "/versions/{version}/approve")
    async def approve_binding(request: Request, binding_id: str,
                              version: int):
        """checker 批准：核验审批账本（maker≠checker）并在行上记录
        approval。状态保持 pending_approval，直到 canary/active CAS。"""
        p = _principal(request, csrf=True)
        _authorize(p, P_RELEASE_APPROVE)
        body = await request.json()
        approval_id = body.get("approval_id", "")
        try:
            row = services._get_binding(_TENANT, binding_id, version)
            if row.status != "pending_approval":
                return _error_response(_state_error(
                    "只有 pending_approval 可批准"))
            services._verify_binding_approval(
                row, approval_id=approval_id, approver=p["actor"])
            etag = services.repo.set_binding_approval(
                tenant_id=_TENANT, binding_id=binding_id, version=version,
                approval_id=approval_id, expected_etag=row.etag)
            return {"approved": True, "status": "pending_approval",
                    "etag": etag}
        except ModelManagementError as e:
            return _error_response(e)
        except GovernanceError as e:
            return _governance_error(e)

    @router.post("/api/v1/models/bindings/{binding_id}"
                 "/versions/{version}/activate-canary")
    async def activate_canary(request: Request, binding_id: str,
                              version: int):
        p = _principal(request, csrf=True)
        _authorize(p, P_RELEASE_APPROVE)
        body = await request.json()
        try:
            return services.activate_canary(
                tenant_id=_TENANT, binding_id=binding_id, version=version,
                approver=p["actor"], approval_id=body.get("approval_id", ""),
                expected_etag=body.get("expected_etag"))
        except ModelManagementError as e:
            return _error_response(e)
        except GovernanceError as e:
            return _governance_error(e)

    @router.post("/api/v1/models/bindings/{binding_id}"
                 "/versions/{version}/activate")
    async def activate_binding(request: Request, binding_id: str,
                               version: int):
        p = _principal(request, csrf=True)
        _authorize(p, P_RELEASE_APPROVE)
        body = await request.json()
        try:
            return services.activate_binding(
                tenant_id=_TENANT, binding_id=binding_id, version=version,
                approver=p["actor"], approval_id=body.get("approval_id", ""),
                expected_etag=body.get("expected_etag"))
        except ModelManagementError as e:
            return _error_response(e)

    @router.post("/api/v1/models/bindings/{binding_id}/rollback")
    async def rollback_binding(request: Request, binding_id: str):
        p = _principal(request, csrf=True)
        _authorize(p, P_RELEASE_APPROVE)
        body = await request.json()
        try:
            return services.rollback_binding(
                tenant_id=_TENANT, binding_id=binding_id,
                to_version=int(body.get("to_version", 0) or 0),
                approver=p["actor"],
                approval_id=body.get("approval_id", ""),
                index_snapshot_id=body.get("index_snapshot_id"))
        except ModelManagementError as e:
            return _error_response(e)
        except GovernanceError as e:
            return _governance_error(e)

    # ------------------------------------------------ usage / governance

    @router.get("/api/v1/models/usage/summary")
    def usage_summary(request: Request, since_hours: float = 24,
                      principal_id: str = "", customer_id: str = "",
                      project_id: str = ""):
        p = _principal(request, csrf=False)
        _authorize(p, P_USAGE_READ, customer_id=customer_id,
                   project_id=project_id)
        return services.metering.summary(
            tenant_id=_TENANT, since_hours=since_hours,
            principal_id=principal_id, customer_id=customer_id,
            project_id=project_id)

    @router.get("/api/v1/models/usage/timeseries")
    def usage_timeseries(request: Request, since_hours: float = 24,
                         bucket_minutes: int = 60):
        p = _principal(request, csrf=False)
        _authorize(p, P_USAGE_READ)
        return {"buckets": services.metering.timeseries(
            tenant_id=_TENANT, since_hours=since_hours,
            bucket_minutes=max(1, int(bucket_minutes)))}

    @router.get("/api/v1/models/usage/rows")
    def usage_rows(request: Request, principal_id: str = "",
                   customer_id: str = "", project_id: str = "",
                   connection_id: str = "", model_id: str = "",
                   limit: int = 200):
        p = _principal(request, csrf=False)
        _authorize(p, P_USAGE_READ, customer_id=customer_id,
                   project_id=project_id)
        rows = services.metering.usage_rows(
            tenant_id=_TENANT, principal_id=principal_id,
            customer_id=customer_id, project_id=project_id,
            connection_id=connection_id, model_id=model_id, limit=limit)
        return {"count": len(rows), "rows": rows}

    @router.get("/api/v1/models/health")
    def models_health(request: Request):
        p = _principal(request, csrf=False)
        _authorize(p, P_CONFIG_READ)
        rows = services.repo.list_connections(tenant_id=_TENANT)
        by_id: dict[str, dict] = {}
        for row in rows:
            slot = by_id.setdefault(row.connection_id, {
                "connection_id": row.connection_id,
                "location": row.location, "status": row.status,
                "active_version": None})
            if row.status == "active":
                slot["status"] = "active"
                slot["active_version"] = row.version
        return {"count": len(by_id),
                "connections": sorted(by_id.values(),
                                      key=lambda c: c["connection_id"])}

    @router.get("/api/v1/models/alerts")
    def models_alerts(request: Request):
        p = _principal(request, csrf=False)
        _authorize(p, P_USAGE_READ)
        alerts = [a for a in services.alerts.list_alerts()
                  if str(a.get("rule_id", "")).startswith("budget_")
                  or "模型" in str(a.get("content", ""))]
        return {"count": len(alerts), "alerts": alerts}

    @router.get("/api/v1/models/audit")
    def models_audit(request: Request, limit: int = 200):
        p = _principal(request, csrf=False)
        _authorize(p, P_AUDIT_READ)
        if services.iam is None:
            return {"count": 0, "events": []}
        events = [e for e in services.iam.list_audit(limit=limit)
                  if str(e.get("action", "")).startswith("model.")]
        return {"count": len(events), "events": events}

    return router


def _catalog_view(row) -> dict:
    import json as _json
    try:
        caps = _json.loads(row.capabilities_json)
    except _json.JSONDecodeError:
        caps = []
    return {
        "catalog_id": row.catalog_id,
        "connection_id": row.connection_id,
        "connection_version": row.connection_version,
        "model_id": row.model_id,
        "model_revision": row.model_revision,
        "capabilities": caps,
        "embedding_dimension": row.embedding_dimension,
        "normalization_version": row.normalization_version,
        "source": row.source,
        "probe_status": row.probe_status,
        "last_verified_at": row.last_verified_at,
    }


def _binding_view(row) -> dict:
    return {
        "binding_id": row.binding_id,
        "version": row.version,
        "customer_id": row.customer_id,
        "project_id": row.project_id,
        "subject_kind": row.subject_kind,
        "subject_id": row.subject_id,
        "capability": row.capability,
        "connection_id": row.connection_id,
        "connection_version": row.connection_version,
        "model_id": row.model_id,
        "status": row.status,
        "etag": row.etag,
        "created_by": row.created_by,
        "created_at": row.created_at,
        "activated_at": row.activated_at,
    }
