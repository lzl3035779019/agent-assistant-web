from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import UUID, uuid4

from pmaa_web.config import get_settings


class AuthError(ValueError):
    pass


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str) -> str:
    if len(password) < 8:
        raise AuthError("密码至少需要 8 个字符")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=2**14,
        r=8,
        p=1,
        dklen=32,
    )
    return f"scrypt$16384$8$1${_b64encode(salt)}${_b64encode(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, raw_n, raw_r, raw_p, raw_salt, raw_digest = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=_b64decode(raw_salt),
            n=int(raw_n),
            r=int(raw_r),
            p=int(raw_p),
            dklen=32,
        )
        return hmac.compare_digest(digest, _b64decode(raw_digest))
    except (ValueError, TypeError):
        return False


def create_access_token(user_id: UUID) -> str:
    settings = get_settings()
    return _encode_token(
        user_id,
        "access",
        timedelta(minutes=settings.access_token_expire_minutes),
    )


def create_refresh_token(user_id: UUID) -> tuple[str, datetime]:
    settings = get_settings()
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
    token = _encode_token(
        user_id,
        "refresh",
        timedelta(days=settings.refresh_token_expire_days),
    )
    return token, expires_at


def _encode_token(user_id: UUID, token_type: Literal["access", "refresh"], ttl: timedelta) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": str(user_id),
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
        "jti": str(uuid4()),
    }
    signing_input = ".".join(
        _b64encode(json.dumps(part, separators=(",", ":")).encode("utf-8"))
        for part in (header, payload)
    )
    signature = hmac.new(
        settings.jwt_secret_key.encode("utf-8"),
        signing_input.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{signing_input}.{_b64encode(signature)}"


def decode_token(token: str, *, expected_type: Literal["access", "refresh"]) -> dict[str, Any]:
    settings = get_settings()
    try:
        encoded_header, encoded_payload, encoded_signature = token.split(".", 2)
        signing_input = f"{encoded_header}.{encoded_payload}"
        expected = hmac.new(
            settings.jwt_secret_key.encode("utf-8"),
            signing_input.encode("ascii"),
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(expected, _b64decode(encoded_signature)):
            raise AuthError("令牌签名无效")
        payload = json.loads(_b64decode(encoded_payload))
        if payload.get("type") != expected_type:
            raise AuthError("令牌类型无效")
        if int(payload.get("exp", 0)) <= int(datetime.now(timezone.utc).timestamp()):
            raise AuthError("登录状态已过期")
        UUID(str(payload["sub"]))
        return payload
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        if isinstance(exc, AuthError):
            raise
        raise AuthError("令牌格式无效") from exc


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
