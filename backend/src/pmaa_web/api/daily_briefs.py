from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pmaa_web.auth_context import current_user_id
from pmaa_web.daily_brief_service import (
    DEFAULT_TOPICS,
    dispatch_daily_brief,
    next_schedule_run,
    validate_schedule_values,
)
from pmaa_web.database import get_session
from pmaa_web.models import BriefSchedule, DailyBrief, utc_now
from pmaa_web.schemas import (
    BriefScheduleCreate,
    BriefScheduleRead,
    BriefScheduleUpdate,
    DailyBriefGenerate,
    DailyBriefRead,
    DailyBriefStatsRead,
)

router = APIRouter(prefix="/daily-briefs", tags=["daily-briefs"])


def _validation_error(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=422, detail=str(exc))


async def _owned_schedule(session: AsyncSession, schedule_id: UUID) -> BriefSchedule:
    schedule = await session.scalar(
        select(BriefSchedule).where(
            BriefSchedule.id == schedule_id,
            BriefSchedule.user_id == current_user_id(),
        )
    )
    if schedule is None:
        raise HTTPException(status_code=404, detail="简报计划不存在")
    return schedule


async def _owned_brief(session: AsyncSession, brief_id: UUID) -> DailyBrief:
    brief = await session.scalar(
        select(DailyBrief).where(
            DailyBrief.id == brief_id,
            DailyBrief.user_id == current_user_id(),
        )
    )
    if brief is None:
        raise HTTPException(status_code=404, detail="简报不存在")
    return brief


@router.get("/stats", response_model=DailyBriefStatsRead)
async def brief_stats(
    session: AsyncSession = Depends(get_session),
) -> DailyBriefStatsRead:
    unread = await session.scalar(
        select(func.count()).select_from(DailyBrief).where(
            DailyBrief.user_id == current_user_id(),
            DailyBrief.unread.is_(True),
            DailyBrief.status == "completed",
        )
    )
    total = await session.scalar(
        select(func.count()).select_from(DailyBrief).where(
            DailyBrief.user_id == current_user_id()
        )
    )
    active = await session.scalar(
        select(func.count()).select_from(BriefSchedule).where(
            BriefSchedule.user_id == current_user_id(),
            BriefSchedule.enabled.is_(True),
        )
    )
    generating = await session.scalar(
        select(func.count()).select_from(DailyBrief).where(
            DailyBrief.user_id == current_user_id(),
            DailyBrief.status.in_(["queued", "running"]),
        )
    )
    return DailyBriefStatsRead(
        unread_count=unread or 0,
        total_count=total or 0,
        active_schedule_count=active or 0,
        generating_count=generating or 0,
    )


@router.get("/schedules", response_model=list[BriefScheduleRead])
async def list_schedules(
    session: AsyncSession = Depends(get_session),
) -> list[BriefSchedule]:
    records = await session.scalars(
        select(BriefSchedule)
        .where(BriefSchedule.user_id == current_user_id())
        .order_by(BriefSchedule.created_at)
    )
    return list(records)


@router.post(
    "/schedules",
    response_model=BriefScheduleRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_schedule(
    payload: BriefScheduleCreate,
    session: AsyncSession = Depends(get_session),
) -> BriefSchedule:
    try:
        weekdays, topics = validate_schedule_values(
            timezone_name=payload.timezone,
            weekdays=payload.weekdays,
            topics=payload.topics,
        )
        next_run_at = next_schedule_run(
            local_time=payload.local_time,
            timezone_name=payload.timezone,
            weekdays=weekdays,
        ) if payload.enabled else None
    except ValueError as exc:
        raise _validation_error(exc) from exc
    record = BriefSchedule(
        user_id=current_user_id(),
        **payload.model_dump(exclude={"weekdays", "topics"}),
        weekdays=weekdays,
        topics=topics,
        next_run_at=next_run_at,
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record


@router.patch("/schedules/{schedule_id}", response_model=BriefScheduleRead)
async def update_schedule(
    schedule_id: UUID,
    payload: BriefScheduleUpdate,
    session: AsyncSession = Depends(get_session),
) -> BriefSchedule:
    record = await _owned_schedule(session, schedule_id)
    changes = payload.model_dump(exclude_unset=True)
    timezone_name = changes.get("timezone", record.timezone)
    weekdays_value = changes.get("weekdays", record.weekdays)
    topics_value = changes.get("topics", record.topics)
    try:
        weekdays, topics = validate_schedule_values(
            timezone_name=timezone_name,
            weekdays=weekdays_value,
            topics=topics_value,
        )
    except ValueError as exc:
        raise _validation_error(exc) from exc
    for field, value in changes.items():
        if field not in {"weekdays", "topics"}:
            setattr(record, field, value)
    record.weekdays = weekdays
    record.topics = topics
    record.updated_at = utc_now()
    record.next_run_at = (
        next_schedule_run(
            local_time=record.local_time,
            timezone_name=record.timezone,
            weekdays=record.weekdays,
        )
        if record.enabled
        else None
    )
    await session.commit()
    await session.refresh(record)
    return record


@router.delete("/schedules/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schedule(
    schedule_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> None:
    record = await _owned_schedule(session, schedule_id)
    await session.delete(record)
    await session.commit()


@router.post("/generate", response_model=DailyBriefRead, status_code=status.HTTP_202_ACCEPTED)
async def generate_brief(
    payload: DailyBriefGenerate,
    session: AsyncSession = Depends(get_session),
) -> DailyBrief:
    schedule = await _owned_schedule(session, payload.schedule_id) if payload.schedule_id else None
    topics = payload.topics or (schedule.topics if schedule else DEFAULT_TOPICS)
    brief = DailyBrief(
        user_id=current_user_id(),
        schedule_id=schedule.id if schedule else None,
        title=f"{schedule.name if schedule else '今日简报'} · {datetime.now().astimezone():%Y-%m-%d}",
        topics=topics,
        include_email=schedule.include_email if schedule else payload.include_email,
        include_calendar=schedule.include_calendar if schedule else payload.include_calendar,
        include_memory=schedule.include_memory if schedule else payload.include_memory,
        source="manual",
    )
    session.add(brief)
    if schedule:
        schedule.last_run_at = utc_now()
    await session.commit()
    await session.refresh(brief)
    await dispatch_daily_brief(brief.id)
    return brief


@router.get("", response_model=list[DailyBriefRead])
async def list_briefs(
    unread_only: bool = False,
    limit: int = Query(default=30, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> list[DailyBrief]:
    statement = select(DailyBrief).where(DailyBrief.user_id == current_user_id())
    if unread_only:
        statement = statement.where(DailyBrief.unread.is_(True))
    records = await session.scalars(statement.order_by(DailyBrief.created_at.desc()).limit(limit))
    return list(records)


@router.get("/{brief_id}", response_model=DailyBriefRead)
async def get_brief(
    brief_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> DailyBrief:
    return await _owned_brief(session, brief_id)


@router.post("/{brief_id}/read", response_model=DailyBriefRead)
async def mark_brief_read(
    brief_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> DailyBrief:
    brief = await _owned_brief(session, brief_id)
    brief.unread = False
    brief.read_at = utc_now()
    await session.commit()
    await session.refresh(brief)
    return brief


@router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT)
async def mark_all_read(session: AsyncSession = Depends(get_session)) -> None:
    records = list(
        await session.scalars(
            select(DailyBrief).where(
                DailyBrief.user_id == current_user_id(),
                DailyBrief.unread.is_(True),
            )
        )
    )
    now = utc_now()
    for brief in records:
        brief.unread = False
        brief.read_at = now
    await session.commit()
