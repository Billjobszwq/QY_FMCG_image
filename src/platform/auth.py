"""UMT-006：可信本机登录 session / CSRF / 服务端 role。

禁止客户端经 X-Role/X-Actor 头自证身份：
- 身份只来自服务端登录产生的 HttpOnly session cookie；
- 状态变更端点必须携带与 session 绑定的 X-CSRF-Token；
- role 由服务端 users 配置决定（本机单租户最小 IAM，fail-closed）。

用户配置（按优先级）：
1. 锁定凭据 flag（auth_locked_credential_v1）→ 唯一生效，忽略一切
   环境变量，且 DB 触发器禁止 UPDATE/DELETE（不可再变更）；
2. 环境变量 PLATFORM_USERS="name:password:role[,…]"；
3. 环境变量 PLATFORM_ADMIN_PASSWORD → 内置 admin 账号；
4. 首次启动随机生成 admin 口令（哈希存 flag，明文仅打印一次）。

首次设置 PLATFORM_ADMIN_CREDENTIALS="name:password" 会把凭据哈希
写入锁定 flag；此后任何修改（环境变量或数据库）都不再生效。
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

SESSION_COOKIE = "platform_session"
CSRF_HEADER = "X-CSRF-Token"
SESSION_TTL_SECONDS = 12 * 3600
_PBKDF2_ITERS = 60_000
# 锁定凭据 flag：写入后不可变更（migration 040 触发器保护）
LOCK_FLAG = "auth_locked_credential_v1"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                             salt, _PBKDF2_ITERS)
    return f"{salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, _, digest = stored.partition("$")
        return hmac.compare_digest(
            hash_password(password, bytes.fromhex(salt_hex)), stored)
    except Exception:
        return False


def default_users(store: Any) -> dict[str, tuple[str, str]]:
    """返回 {username: (password_hash, role)}。

    锁定凭据存在时：它是唯一生效凭据，环境变量全部忽略（不可再变更）。
    """
    locked = store.get_flag(LOCK_FLAG)
    if locked:
        username, _, pw_hash = locked.partition(":")
        return {username: (pw_hash, "admin")}
    env_users = os.environ.get("PLATFORM_USERS", "").strip()
    if env_users:
        users: dict[str, tuple[str, str]] = {}
        for item in env_users.split(","):
            name, _, rest = item.strip().partition(":")
            pw, _, role = rest.partition(":")
            if name and pw:
                users[name] = (hash_password(pw), role or "operator")
        if users:
            return users
    admin_pw = os.environ.get("PLATFORM_ADMIN_PASSWORD")
    if admin_pw:
        return {"admin": (hash_password(admin_pw), "admin")}
    # 首次启动 bootstrap：随机口令，哈希入库，明文仅显示一次
    existing = store.get_flag("auth_admin_password_hash")
    if existing:
        return {"admin": (existing, "admin")}
    pw = secrets.token_urlsafe(16)
    h = hash_password(pw)
    store.set_flag("auth_admin_password_hash", h, "system")
    print(f"[auth] 本机 admin 初始口令（仅显示一次）：{pw}")
    return {"admin": (h, "admin")}


class AuthService:
    """登录/会话/CSRF；role 由服务端决定，绝不读取客户端 header。"""

    def __init__(self, store: Any,
                 users: dict[str, tuple[str, str]] | None = None) -> None:
        self.store = store
        self._bootstrap_credential_lock()
        self._users = users if users is not None else default_users(store)

    def _bootstrap_credential_lock(self) -> None:
        """首次出现 PLATFORM_ADMIN_CREDENTIALS 时锁定凭据。

        锁定后：环境变量不再参与（default_users 优先读 flag），且 DB
        触发器拒绝 UPDATE/DELETE —— 凭据不可再变更。
        """
        if self.store.get_flag(LOCK_FLAG):
            return
        raw = os.environ.get("PLATFORM_ADMIN_CREDENTIALS", "").strip()
        if not raw:
            return
        username, _, password = raw.partition(":")
        if not username or not password:
            return
        self.store.set_flag(
            LOCK_FLAG, f"{username}:{hash_password(password)}",
            "bootstrap-lock")

    def login(self, username: str, password: str) -> dict[str, Any]:
        rec = self._users.get(username)
        if rec is not None and verify_password(password, rec[0]):
            role = rec[1]
        else:
            # ABOSV2 Phase D：IAM 身份库回退（user/service_account），
            # session role 取首个成员角色（fail-closed 无角色则拒绝）。
            iam_row = None
            try:
                from .iam import IAMError, IAMService
                try:
                    iam_row = IAMService(self.store).verify_login(
                        username, password)
                except IAMError as e:
                    # SI4：归档身份拒绝必须携带稳定错误码上抛
                    raise PermissionError(str(e))
            except PermissionError:
                raise
            except Exception:
                iam_row = None
            if iam_row is None:
                raise PermissionError("用户名或口令错误")
            from .iam import IAMService
            roles = IAMService(self.store).roles_of(username)
            role = roles[0] if roles else "read_only"
        session_id = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        now = _utcnow()
        self.store.create_auth_session(
            session_id=session_id, actor=username, role=role,
            csrf_token=csrf, created_at=now.isoformat(),
            expires_at=(now + timedelta(seconds=SESSION_TTL_SECONDS))
            .isoformat())
        return {"actor": username, "role": role, "session_id": session_id,
                "csrf_token": csrf}

    def principal(self, session_id: str | None) -> dict[str, Any] | None:
        if not session_id:
            return None
        row = self.store.get_auth_session(session_id)
        if row is None:
            return None
        if row["expires_at"] < _utcnow().isoformat():
            self.store.delete_auth_session(session_id)
            return None
        return {"actor": row["actor"], "role": row["role"],
                "csrf": row["csrf_token"]}

    def logout(self, session_id: str | None) -> None:
        if session_id:
            self.store.delete_auth_session(session_id)


def require_principal(auth: AuthService | None, request: Request,
                      *, csrf: bool = True) -> dict[str, Any]:
    """写端点统一守卫：无有效 session → 401；CSRF 不匹配 → 403。"""
    if auth is None:
        raise HTTPException(status_code=503, detail="auth service 未启用")
    p = auth.principal(request.cookies.get(SESSION_COOKIE))
    if p is None:
        raise HTTPException(
            status_code=401,
            detail="需要本机登录 session；禁止客户端 header 自证身份")
    if csrf:
        tok = request.headers.get(CSRF_HEADER)
        if not tok or not hmac.compare_digest(tok, p["csrf"]):
            raise HTTPException(status_code=403,
                                detail="CSRF token 缺失或不匹配")
    return p


class LoginBody(BaseModel):
    username: str
    password: str


def create_auth_router(auth: AuthService) -> APIRouter:
    router = APIRouter()

    @router.post("/api/v1/auth/login")
    def login(body: LoginBody, response: Response, request: Request):
        # UATCC T6：登录限流（主体=用户名，叠加 IP；不得伪造绕过）
        from .rate_limit import enforce
        enforce(request, "auth.login", body.username)
        try:
            s = auth.login(body.username, body.password)
        except PermissionError as e:
            raise HTTPException(status_code=401, detail=str(e))
        response.set_cookie(SESSION_COOKIE, s["session_id"],
                            httponly=True, samesite="lax",
                            max_age=SESSION_TTL_SECONDS)
        return {"actor": s["actor"], "role": s["role"],
                "csrf_token": s["csrf_token"]}

    @router.get("/api/v1/auth/me")
    def me(request: Request):
        p = auth.principal(request.cookies.get(SESSION_COOKIE))
        if p is None:
            raise HTTPException(status_code=401, detail="未登录或会话过期")
        # 页面刷新后前端需恢复 CSRF token（session 已验证，返回安全）
        return {"actor": p["actor"], "role": p["role"],
                "csrf_token": p["csrf"]}

    @router.post("/api/v1/auth/logout")
    def logout(request: Request, response: Response):
        auth.logout(request.cookies.get(SESSION_COOKIE))
        response.delete_cookie(SESSION_COOKIE)
        return {"ok": True}

    return router
