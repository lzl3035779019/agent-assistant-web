from __future__ import annotations

from uuid import UUID

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from pmaa_web.auth_context import (
    DEVELOPMENT_USER_ID,
    reset_current_user_id,
    set_current_user_id,
)
from pmaa_web.auth_service import AuthError, decode_token
from pmaa_web.config import get_settings
from pmaa_web.database import SessionFactory
from pmaa_web.models import User

PUBLIC_PATHS = {
    "/api/v1/health",
    "/api/v1/auth/status",
    "/api/v1/auth/register",
    "/api/v1/auth/login",
    "/api/v1/auth/refresh",
    "/docs",
    "/openapi.json",
}


class AuthenticationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        settings = get_settings()
        if not settings.auth_enabled:
            context_token = set_current_user_id(DEVELOPMENT_USER_ID)
            try:
                return await call_next(request)
            finally:
                reset_current_user_id(context_token)

        if request.url.path in PUBLIC_PATHS or request.method == "OPTIONS":
            return await call_next(request)

        raw_token = None
        if request.method == "GET" and request.url.path.endswith("/events"):
            raw_token = request.query_params.get("access_token")
        authorization = request.headers.get("authorization", "")
        if authorization.lower().startswith("bearer "):
            raw_token = authorization[7:].strip()
        if not raw_token:
            return JSONResponse(status_code=401, content={"detail": "请先登录"})

        try:
            payload = decode_token(raw_token, expected_type="access")
            user_id = UUID(str(payload["sub"]))
            async with SessionFactory() as session:
                user = await session.scalar(
                    select(User).where(User.id == user_id, User.active.is_(True))
                )
            if user is None:
                raise AuthError("用户不存在或已停用")
        except AuthError as exc:
            return JSONResponse(status_code=401, content={"detail": str(exc)})

        context_token = set_current_user_id(user_id)
        try:
            request.state.user_id = user_id
            return await call_next(request)
        finally:
            reset_current_user_id(context_token)
