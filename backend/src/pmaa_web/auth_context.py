from __future__ import annotations

from contextvars import ContextVar, Token
from uuid import UUID

DEVELOPMENT_USER_ID = UUID("00000000-0000-0000-0000-000000000001")
_current_user_id: ContextVar[UUID] = ContextVar(
    "pmaa_current_user_id",
    default=DEVELOPMENT_USER_ID,
)


def set_current_user_id(user_id: UUID) -> Token[UUID]:
    return _current_user_id.set(user_id)


def reset_current_user_id(token: Token[UUID]) -> None:
    _current_user_id.reset(token)


def current_user_id() -> UUID:
    return _current_user_id.get()
