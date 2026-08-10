from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pmaa_web.auth_context import current_user_id
from pmaa_web.database import get_session
from pmaa_web.memory_service import memory_key
from pmaa_web.models import UserMemory, utc_now
from pmaa_web.schemas import MemoryCreate, MemoryRead, MemoryStatsRead, MemoryUpdate

router = APIRouter(prefix="/memories", tags=["memories"])


async def _owned_memory(session: AsyncSession, memory_id: UUID) -> UserMemory:
    memory = await session.get(UserMemory, memory_id)
    if memory is None or memory.user_id != current_user_id():
        raise HTTPException(status_code=404, detail="Memory not found")
    return memory


@router.get("", response_model=list[MemoryRead])
async def list_memories(
    memory_type: str | None = None,
    enabled: bool | None = None,
    query: str = "",
    limit: int = Query(default=100, ge=1, le=300),
    session: AsyncSession = Depends(get_session),
) -> list[UserMemory]:
    statement = select(UserMemory).where(UserMemory.user_id == current_user_id())
    if memory_type:
        statement = statement.where(UserMemory.memory_type == memory_type)
    if enabled is not None:
        statement = statement.where(UserMemory.enabled.is_(enabled))
    if query.strip():
        statement = statement.where(UserMemory.content.ilike(f"%{query.strip()}%"))
    result = await session.scalars(statement.order_by(UserMemory.updated_at.desc()).limit(limit))
    return list(result)


@router.get("/stats", response_model=MemoryStatsRead)
async def memory_stats(session: AsyncSession = Depends(get_session)) -> MemoryStatsRead:
    rows = (
        await session.execute(
            select(UserMemory.memory_type, UserMemory.enabled, func.count(UserMemory.id))
            .where(UserMemory.user_id == current_user_id())
            .group_by(UserMemory.memory_type, UserMemory.enabled)
        )
    ).all()
    by_type: dict[str, int] = {}
    enabled_count = 0
    total = 0
    for memory_type, enabled, count in rows:
        by_type[memory_type] = by_type.get(memory_type, 0) + count
        total += count
        if enabled:
            enabled_count += count
    return MemoryStatsRead(
        total=total,
        enabled=enabled_count,
        disabled=total - enabled_count,
        by_type=by_type,
    )


@router.post("", response_model=MemoryRead, status_code=status.HTTP_201_CREATED)
async def create_memory(
    payload: MemoryCreate,
    session: AsyncSession = Depends(get_session),
) -> UserMemory:
    memory = UserMemory(
        user_id=current_user_id(),
        memory_type=payload.memory_type,
        content=payload.content.strip(),
        memory_key=memory_key(payload.content),
        source="manual",
        confidence=payload.confidence,
        validation_reason="user_confirmed",
    )
    session.add(memory)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="相同记忆已经存在") from exc
    await session.refresh(memory)
    return memory


@router.patch("/{memory_id}", response_model=MemoryRead)
async def update_memory(
    memory_id: UUID,
    payload: MemoryUpdate,
    session: AsyncSession = Depends(get_session),
) -> UserMemory:
    memory = await _owned_memory(session, memory_id)
    if payload.memory_type is not None:
        memory.memory_type = payload.memory_type
    if payload.content is not None:
        memory.content = payload.content.strip()
        memory.memory_key = memory_key(memory.content)
    if payload.confidence is not None:
        memory.confidence = payload.confidence
    if payload.enabled is not None:
        memory.enabled = payload.enabled
    memory.updated_at = utc_now()
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="修改后与已有记忆重复") from exc
    await session.refresh(memory)
    return memory


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    memory_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> None:
    memory = await _owned_memory(session, memory_id)
    await session.delete(memory)
    await session.commit()
