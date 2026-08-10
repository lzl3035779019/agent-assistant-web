from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pmaa_web.auth_context import current_user_id
from pmaa_web.database import get_session
from pmaa_web.models import AgentRun, MonitorNotification, MonitorResult, MonitorRule, utc_now
from pmaa_web.monitor_service import create_monitor_run, next_monitor_run
from pmaa_web.schemas import (
    MonitorNotificationRead,
    MonitorResultPageRead,
    MonitorRuleCreate,
    MonitorRuleRead,
    MonitorRuleUpdate,
    MonitorStatsRead,
    RunRead,
)

router = APIRouter(prefix="/monitors", tags=["monitors"])


async def _owned_rule(session: AsyncSession, rule_id: UUID) -> MonitorRule:
    rule = await session.scalar(
        select(MonitorRule).where(
            MonitorRule.id == rule_id,
            MonitorRule.user_id == current_user_id(),
        )
    )
    if rule is None:
        raise HTTPException(status_code=404, detail="监控规则不存在")
    return rule


@router.get("/stats", response_model=MonitorStatsRead)
async def monitor_stats(session: AsyncSession = Depends(get_session)) -> MonitorStatsRead:
    rule_count = await session.scalar(
        select(func.count()).select_from(MonitorRule).where(
            MonitorRule.user_id == current_user_id()
        )
    )
    enabled_count = await session.scalar(
        select(func.count()).select_from(MonitorRule).where(
            MonitorRule.user_id == current_user_id(),
            MonitorRule.enabled.is_(True),
        )
    )
    unread_count = await session.scalar(
        select(func.count()).select_from(MonitorNotification).where(
            MonitorNotification.user_id == current_user_id(),
            MonitorNotification.unread.is_(True),
        )
    )
    running_count = await session.scalar(
        select(func.count()).select_from(MonitorRule).where(
            MonitorRule.user_id == current_user_id(),
            MonitorRule.last_run_status.in_(["queued", "running"]),
        )
    )
    return MonitorStatsRead(
        rule_count=rule_count or 0,
        enabled_count=enabled_count or 0,
        unread_count=unread_count or 0,
        running_count=running_count or 0,
    )


@router.get("/rules", response_model=list[MonitorRuleRead])
async def list_rules(session: AsyncSession = Depends(get_session)) -> list[MonitorRule]:
    return list(
        await session.scalars(
            select(MonitorRule)
            .where(MonitorRule.user_id == current_user_id())
            .order_by(MonitorRule.created_at.desc())
        )
    )


@router.post(
    "/rules",
    response_model=MonitorRuleRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_rule(
    payload: MonitorRuleCreate,
    session: AsyncSession = Depends(get_session),
) -> MonitorRule:
    rule = MonitorRule(
        user_id=current_user_id(),
        **payload.model_dump(),
        next_run_at=next_monitor_run(payload.interval_minutes) if payload.enabled else None,
    )
    session.add(rule)
    await session.commit()
    await session.refresh(rule)
    return rule


@router.patch("/rules/{rule_id}", response_model=MonitorRuleRead)
async def update_rule(
    rule_id: UUID,
    payload: MonitorRuleUpdate,
    session: AsyncSession = Depends(get_session),
) -> MonitorRule:
    rule = await _owned_rule(session, rule_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(rule, field, value)
    rule.updated_at = utc_now()
    rule.next_run_at = (
        next_monitor_run(rule.interval_minutes) if rule.enabled else None
    )
    await session.commit()
    await session.refresh(rule)
    return rule


@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    rule_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> None:
    rule = await _owned_rule(session, rule_id)
    await session.delete(rule)
    await session.commit()


@router.post("/rules/{rule_id}/run", response_model=RunRead, status_code=202)
async def run_rule(
    rule_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> AgentRun:
    rule = await _owned_rule(session, rule_id)
    if rule.last_run_status in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="该规则正在运行")
    return await create_monitor_run(rule.id)


@router.get("/results", response_model=MonitorResultPageRead)
async def list_results(
    rule_id: UUID | None = None,
    limit: int = Query(default=9, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> MonitorResultPageRead:
    statement = select(MonitorResult).where(
        MonitorResult.user_id == current_user_id()
    )
    count_statement = select(func.count()).select_from(MonitorResult).where(
        MonitorResult.user_id == current_user_id()
    )
    if rule_id is not None:
        statement = statement.where(MonitorResult.rule_id == rule_id)
        count_statement = count_statement.where(MonitorResult.rule_id == rule_id)
    total = await session.scalar(count_statement) or 0
    items = list(
        await session.scalars(
            statement.order_by(MonitorResult.created_at.desc()).offset(offset).limit(limit)
        )
    )
    return MonitorResultPageRead(items=items, total=total, limit=limit, offset=offset)


@router.delete("/results/{result_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_result(
    result_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> None:
    result = await session.scalar(
        select(MonitorResult).where(
            MonitorResult.id == result_id,
            MonitorResult.user_id == current_user_id(),
        )
    )
    if result is None:
        raise HTTPException(status_code=404, detail="监控结果不存在")
    await session.delete(result)
    await session.commit()


@router.delete("/results", status_code=status.HTTP_204_NO_CONTENT)
async def clear_results(
    rule_id: UUID | None = None,
    session: AsyncSession = Depends(get_session),
) -> None:
    statement = delete(MonitorResult).where(
        MonitorResult.user_id == current_user_id()
    )
    if rule_id is not None:
        statement = statement.where(MonitorResult.rule_id == rule_id)
    await session.execute(statement)
    await session.commit()


@router.get("/notifications", response_model=list[MonitorNotificationRead])
async def list_notifications(
    unread_only: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> list[MonitorNotification]:
    statement = select(MonitorNotification).where(
        MonitorNotification.user_id == current_user_id()
    )
    if unread_only:
        statement = statement.where(MonitorNotification.unread.is_(True))
    return list(
        await session.scalars(
            statement.order_by(MonitorNotification.created_at.desc()).limit(limit)
        )
    )


@router.post("/notifications/{notification_id}/read", response_model=MonitorNotificationRead)
async def mark_notification_read(
    notification_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> MonitorNotification:
    notification = await session.scalar(
        select(MonitorNotification).where(
            MonitorNotification.id == notification_id,
            MonitorNotification.user_id == current_user_id(),
        )
    )
    if notification is None:
        raise HTTPException(status_code=404, detail="监控通知不存在")
    notification.unread = False
    notification.read_at = utc_now()
    await session.commit()
    await session.refresh(notification)
    return notification


@router.post("/notifications/read-all", status_code=204)
async def mark_all_notifications_read(
    session: AsyncSession = Depends(get_session),
) -> None:
    notifications = list(
        await session.scalars(
            select(MonitorNotification).where(
                MonitorNotification.user_id == current_user_id(),
                MonitorNotification.unread.is_(True),
            )
        )
    )
    now = utc_now()
    for notification in notifications:
        notification.unread = False
        notification.read_at = now
    await session.commit()
