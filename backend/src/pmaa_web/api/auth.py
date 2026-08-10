from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pmaa_web.auth_context import current_user_id
from pmaa_web.auth_service import (
    AuthError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    token_digest,
    verify_password,
)
from pmaa_web.config import get_settings
from pmaa_web.database import get_session
from pmaa_web.models import RefreshToken, User, utc_now

router = APIRouter(prefix="/auth", tags=["auth"])


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=256)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
            raise ValueError("邮箱格式无效")
        return normalized


class RegisterRequest(Credentials):
    display_name: str = Field(default="", max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str


class AuthUser(BaseModel):
    id: UUID
    email: str
    display_name: str
    active: bool
    created_at: datetime


class AuthTokens(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: AuthUser


class AuthStatus(BaseModel):
    enabled: bool


def _user_payload(user: User) -> AuthUser:
    return AuthUser(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        active=user.active,
        created_at=user.created_at,
    )


async def _issue_tokens(session: AsyncSession, user: User) -> AuthTokens:
    refresh_token, expires_at = create_refresh_token(user.id)
    session.add(
        RefreshToken(
            user_id=user.id,
            token_hash=token_digest(refresh_token),
            expires_at=expires_at,
        )
    )
    await session.commit()
    return AuthTokens(
        access_token=create_access_token(user.id),
        refresh_token=refresh_token,
        expires_in=get_settings().access_token_expire_minutes * 60,
        user=_user_payload(user),
    )


@router.get("/status", response_model=AuthStatus)
async def auth_status() -> AuthStatus:
    return AuthStatus(enabled=get_settings().auth_enabled)


@router.post("/register", response_model=AuthTokens, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest,
    session: AsyncSession = Depends(get_session),
) -> AuthTokens:
    email = str(payload.email).strip().lower()
    if await session.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(status_code=409, detail="该邮箱已注册")
    try:
        encoded_password = hash_password(payload.password)
    except AuthError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    user = User(
        email=email,
        display_name=payload.display_name.strip() or email.split("@", 1)[0],
        password_hash=encoded_password,
    )
    session.add(user)
    await session.flush()
    return await _issue_tokens(session, user)


@router.post("/login", response_model=AuthTokens)
async def login(
    payload: Credentials,
    session: AsyncSession = Depends(get_session),
) -> AuthTokens:
    user = await session.scalar(
        select(User).where(User.email == str(payload.email).strip().lower())
    )
    if user is None or not user.active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="邮箱或密码错误")
    return await _issue_tokens(session, user)


@router.post("/refresh", response_model=AuthTokens)
async def refresh(
    payload: RefreshRequest,
    session: AsyncSession = Depends(get_session),
) -> AuthTokens:
    try:
        claims = decode_token(payload.refresh_token, expected_type="refresh")
        user_id = UUID(str(claims["sub"]))
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    record = await session.scalar(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_digest(payload.refresh_token),
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > datetime.now(timezone.utc),
        )
    )
    user = await session.get(User, user_id)
    if record is None or user is None or not user.active or record.user_id != user.id:
        raise HTTPException(status_code=401, detail="刷新令牌无效或已撤销")
    record.revoked_at = utc_now()
    await session.flush()
    return await _issue_tokens(session, user)


@router.get("/me", response_model=AuthUser)
async def me(session: AsyncSession = Depends(get_session)) -> AuthUser:
    user = await session.get(User, current_user_id())
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    return _user_payload(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    payload: RefreshRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> None:
    record = await session.scalar(
        select(RefreshToken).where(
            RefreshToken.user_id == current_user_id(),
            RefreshToken.token_hash == token_digest(payload.refresh_token),
            RefreshToken.revoked_at.is_(None),
        )
    )
    if record:
        record.revoked_at = utc_now()
        await session.commit()
