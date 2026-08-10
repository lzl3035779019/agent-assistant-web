from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pmaa_web.auth_context import current_user_id
from pmaa_web.calendar_service import (
    execute_calendar_action,
    list_conflicts,
    prepare_calendar_action_record,
)
from pmaa_web.config import get_settings
from pmaa_web.database import get_session
from pmaa_web.models import CalendarAction, CalendarEvent, TodoItem, utc_now
from pmaa_web.schemas import (
    CalendarActionCreate,
    CalendarActionRead,
    CalendarConflictRead,
    CalendarEventRead,
    CalendarStatsRead,
    TodoItemRead,
)

router = APIRouter(prefix="/calendar", tags=["calendar"])
SHANGHAI = ZoneInfo("Asia/Shanghai")


def _day_window(value: datetime | None = None) -> tuple[datetime, datetime]:
    local = (value or datetime.now(timezone.utc)).astimezone(SHANGHAI)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc)


@router.get("/status")
async def calendar_status() -> dict:
    settings = get_settings()
    return {
        "provider": "local",
        "ready": True,
        "feishu_enabled": settings.feishu_calendar_enabled,
        "feishu_configured": bool(
            settings.feishu_calendar_enabled
            and settings.feishu_app_id
            and settings.feishu_app_secret
        ),
        "write_confirmation_required": True,
    }


@router.get("/stats", response_model=CalendarStatsRead)
async def calendar_stats(
    session: AsyncSession = Depends(get_session),
) -> CalendarStatsRead:
    now = datetime.now(timezone.utc)
    day_start, day_end = _day_window(now)
    today_events = await session.scalar(
        select(func.count()).select_from(CalendarEvent).where(
            CalendarEvent.user_id == current_user_id(),
            CalendarEvent.status == "active",
            CalendarEvent.start_at < day_end,
            CalendarEvent.end_at > day_start,
        )
    )
    upcoming_events = await session.scalar(
        select(func.count()).select_from(CalendarEvent).where(
            CalendarEvent.user_id == current_user_id(),
            CalendarEvent.status == "active",
            CalendarEvent.end_at >= now,
        )
    )
    open_todos = await session.scalar(
        select(func.count()).select_from(TodoItem).where(
            TodoItem.user_id == current_user_id(),
            TodoItem.status.in_(["todo", "in_progress"]),
        )
    )
    overdue_todos = await session.scalar(
        select(func.count()).select_from(TodoItem).where(
            TodoItem.user_id == current_user_id(),
            TodoItem.status.in_(["todo", "in_progress"]),
            TodoItem.due_at.is_not(None),
            TodoItem.due_at < now,
        )
    )
    return CalendarStatsRead(
        today_events=today_events or 0,
        upcoming_events=upcoming_events or 0,
        open_todos=open_todos or 0,
        overdue_todos=overdue_todos or 0,
    )


@router.get("/events", response_model=list[CalendarEventRead])
async def list_events(
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    include_cancelled: bool = False,
    session: AsyncSession = Depends(get_session),
) -> list[CalendarEvent]:
    now = datetime.now(timezone.utc)
    start = start_at or now - timedelta(days=1)
    end = end_at or now + timedelta(days=30)
    if end <= start:
        raise HTTPException(status_code=422, detail="end_at 必须晚于 start_at")
    if end - start > timedelta(days=366):
        raise HTTPException(status_code=422, detail="单次最多查询 366 天日程")
    statement = select(CalendarEvent).where(
        CalendarEvent.user_id == current_user_id(),
        CalendarEvent.start_at < end,
        CalendarEvent.end_at > start,
    )
    if not include_cancelled:
        statement = statement.where(CalendarEvent.status == "active")
    records = await session.scalars(statement.order_by(CalendarEvent.start_at))
    return list(records)


@router.get("/todos", response_model=list[TodoItemRead])
async def list_todos(
    include_completed: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> list[TodoItem]:
    statement = select(TodoItem).where(TodoItem.user_id == current_user_id())
    if not include_completed:
        statement = statement.where(TodoItem.status.in_(["todo", "in_progress"]))
    statement = statement.order_by(TodoItem.due_at.is_(None), TodoItem.due_at, TodoItem.created_at.desc())
    records = await session.scalars(statement.limit(limit))
    return list(records)


@router.get("/conflicts", response_model=CalendarConflictRead)
async def check_conflicts(
    start_at: datetime,
    end_at: datetime,
    exclude_event_id: UUID | None = None,
    session: AsyncSession = Depends(get_session),
) -> CalendarConflictRead:
    if end_at <= start_at:
        raise HTTPException(status_code=422, detail="结束时间必须晚于开始时间")
    conflicts = await list_conflicts(
        session,
        user_id=current_user_id(),
        start_at=start_at,
        end_at=end_at,
        exclude_event_id=exclude_event_id,
    )
    return CalendarConflictRead(
        has_conflict=bool(conflicts),
        conflicts=[CalendarEventRead.model_validate(item) for item in conflicts],
    )


@router.get("/actions", response_model=list[CalendarActionRead])
async def list_actions(
    limit: int = Query(default=30, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> list[CalendarAction]:
    records = await session.scalars(
        select(CalendarAction)
        .where(CalendarAction.user_id == current_user_id())
        .order_by(CalendarAction.created_at.desc())
        .limit(limit)
    )
    return list(records)


@router.post(
    "/actions",
    response_model=CalendarActionRead,
    status_code=status.HTTP_201_CREATED,
)
async def prepare_action(
    request: CalendarActionCreate,
    session: AsyncSession = Depends(get_session),
) -> CalendarAction:
    return await prepare_calendar_action_record(
        session,
        user_id=current_user_id(),
        action=request.action,
        target_id=request.target_id,
        payload=request.payload,
    )


async def _owned_action(
    session: AsyncSession,
    action_id: UUID,
) -> CalendarAction:
    record = await session.scalar(
        select(CalendarAction)
        .where(
            CalendarAction.id == action_id,
            CalendarAction.user_id == current_user_id(),
        )
        .with_for_update()
    )
    if record is None:
        raise HTTPException(status_code=404, detail="日历操作不存在")
    return record


@router.post("/actions/{action_id}/confirm", response_model=CalendarActionRead)
async def confirm_action(
    action_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> CalendarAction:
    record = await _owned_action(session, action_id)
    if record.status != "pending":
        raise HTTPException(status_code=409, detail=f"当前操作状态为 {record.status}，不能重复执行")
    record.status = "executing"
    record.confirmed_at = utc_now()
    try:
        result = await execute_calendar_action(session, action_record=record)
    except HTTPException as exc:
        record.status = "failed"
        record.error = str(exc.detail)
        await session.commit()
        raise
    record.status = "executed"
    record.result_payload = {**record.result_payload, **result}
    record.executed_at = utc_now()
    record.error = ""
    await session.commit()
    await session.refresh(record)
    return record


@router.post("/actions/{action_id}/cancel", response_model=CalendarActionRead)
async def cancel_action(
    action_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> CalendarAction:
    record = await _owned_action(session, action_id)
    if record.status != "pending":
        raise HTTPException(status_code=409, detail=f"当前操作状态为 {record.status}，不能取消")
    record.status = "cancelled"
    await session.commit()
    await session.refresh(record)
    return record
