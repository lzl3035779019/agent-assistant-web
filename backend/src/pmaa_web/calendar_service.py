from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pmaa_web.models import CalendarAction, CalendarEvent, TodoItem, utc_now

EVENT_ACTIONS = {"event.create", "event.update", "event.cancel"}
TODO_ACTIONS = {"todo.create", "todo.update", "todo.cancel"}
TODO_STATUSES = {"todo", "in_progress", "completed", "cancelled"}


def parse_datetime(value: Any, *, field: str) -> datetime:
    if isinstance(value, datetime):
        # Some database drivers return naive UTC datetimes even for timezone columns.
        parsed = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"{field} 必须是 ISO-8601 时间") from exc
    else:
        raise HTTPException(status_code=422, detail=f"{field} 不能为空")
    if parsed.tzinfo is None:
        raise HTTPException(status_code=422, detail=f"{field} 必须包含时区")
    return parsed


def normalize_action_payload(action: str, payload: dict[str, Any], target_id: UUID | None) -> dict:
    normalized = dict(payload)
    if action in {"event.update", "event.cancel", "todo.update", "todo.cancel"} and not target_id:
        raise HTTPException(status_code=422, detail="修改或取消操作必须指定 target_id")

    if action in {"event.create", "event.update"}:
        if action == "event.create" and not str(payload.get("title", "")).strip():
            raise HTTPException(status_code=422, detail="日程标题不能为空")
        if "title" in payload:
            normalized["title"] = str(payload["title"]).strip()
            if not normalized["title"]:
                raise HTTPException(status_code=422, detail="日程标题不能为空")
        for field in ("description", "location"):
            if field in payload:
                normalized[field] = str(payload[field]).strip()
        if action == "event.create" or "start_at" in payload or "end_at" in payload:
            start_at = parse_datetime(payload.get("start_at"), field="start_at")
            end_at = parse_datetime(payload.get("end_at"), field="end_at")
            if end_at <= start_at:
                raise HTTPException(status_code=422, detail="日程结束时间必须晚于开始时间")
            normalized["start_at"] = start_at.isoformat()
            normalized["end_at"] = end_at.isoformat()
    elif action in {"todo.create", "todo.update"}:
        if action == "todo.create" and not str(payload.get("title", "")).strip():
            raise HTTPException(status_code=422, detail="待办标题不能为空")
        if "title" in payload:
            normalized["title"] = str(payload["title"]).strip()
            if not normalized["title"]:
                raise HTTPException(status_code=422, detail="待办标题不能为空")
        if "description" in payload:
            normalized["description"] = str(payload["description"]).strip()
        if payload.get("due_at") not in {None, ""}:
            normalized["due_at"] = parse_datetime(payload["due_at"], field="due_at").isoformat()
        elif "due_at" in payload:
            normalized["due_at"] = None
        if "priority" in payload:
            priority = int(payload["priority"])
            if not 0 <= priority <= 10:
                raise HTTPException(status_code=422, detail="priority 必须在 0 到 10 之间")
            normalized["priority"] = priority
        if "status" in payload:
            todo_status = str(payload["status"])
            if todo_status not in TODO_STATUSES:
                raise HTTPException(status_code=422, detail="待办状态无效")
            normalized["status"] = todo_status
    return normalized


async def list_conflicts(
    session: AsyncSession,
    *,
    user_id: UUID,
    start_at: datetime,
    end_at: datetime,
    exclude_event_id: UUID | None = None,
) -> list[CalendarEvent]:
    statement = select(CalendarEvent).where(
        CalendarEvent.user_id == user_id,
        CalendarEvent.status == "active",
        CalendarEvent.start_at < end_at,
        CalendarEvent.end_at > start_at,
    )
    if exclude_event_id:
        statement = statement.where(CalendarEvent.id != exclude_event_id)
    records = await session.scalars(statement.order_by(CalendarEvent.start_at))
    return list(records)


async def validate_target(
    session: AsyncSession,
    *,
    user_id: UUID,
    action: str,
    target_id: UUID | None,
) -> None:
    if target_id is None:
        return
    model = CalendarEvent if action in EVENT_ACTIONS else TodoItem
    target = await session.scalar(
        select(model).where(model.id == target_id, model.user_id == user_id)
    )
    if target is None:
        label = "日程" if model is CalendarEvent else "待办"
        raise HTTPException(status_code=404, detail=f"{label}不存在")


async def action_conflicts(
    session: AsyncSession,
    *,
    user_id: UUID,
    action: str,
    target_id: UUID | None,
    payload: dict,
) -> list[CalendarEvent]:
    if action not in {"event.create", "event.update"}:
        return []
    if action == "event.create":
        start_at = parse_datetime(payload["start_at"], field="start_at")
        end_at = parse_datetime(payload["end_at"], field="end_at")
    else:
        event = await session.scalar(
            select(CalendarEvent).where(
                CalendarEvent.id == target_id,
                CalendarEvent.user_id == user_id,
            )
        )
        if event is None:
            raise HTTPException(status_code=404, detail="日程不存在")
        start_at = parse_datetime(payload.get("start_at", event.start_at), field="start_at")
        end_at = parse_datetime(payload.get("end_at", event.end_at), field="end_at")
    return await list_conflicts(
        session,
        user_id=user_id,
        start_at=start_at,
        end_at=end_at,
        exclude_event_id=target_id,
    )


async def prepare_calendar_action_record(
    session: AsyncSession,
    *,
    user_id: UUID,
    action: str,
    target_id: UUID | None,
    payload: dict[str, Any],
) -> CalendarAction:
    normalized = normalize_action_payload(action, payload, target_id)
    await validate_target(
        session,
        user_id=user_id,
        action=action,
        target_id=target_id,
    )
    conflicts = await action_conflicts(
        session,
        user_id=user_id,
        action=action,
        target_id=target_id,
        payload=normalized,
    )
    record = CalendarAction(
        user_id=user_id,
        action=action,
        target_id=target_id,
        payload=normalized,
        status="pending",
        result_payload={
            "has_conflict": bool(conflicts),
            "conflicts": [
                {
                    "id": str(item.id),
                    "title": item.title,
                    "start_at": item.start_at.isoformat(),
                    "end_at": item.end_at.isoformat(),
                }
                for item in conflicts
            ],
        },
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record


async def execute_calendar_action(
    session: AsyncSession,
    *,
    action_record: CalendarAction,
) -> dict[str, Any]:
    action = action_record.action
    payload = action_record.payload
    user_id = action_record.user_id

    if action == "event.create":
        event = CalendarEvent(
            user_id=user_id,
            title=payload["title"],
            description=payload.get("description", ""),
            location=payload.get("location", ""),
            start_at=parse_datetime(payload["start_at"], field="start_at"),
            end_at=parse_datetime(payload["end_at"], field="end_at"),
            source="manual",
        )
        session.add(event)
        await session.flush()
        return {"target_type": "event", "target_id": str(event.id)}

    if action in {"event.update", "event.cancel"}:
        event = await _locked_target(session, CalendarEvent, action_record.target_id, user_id)
        if action == "event.cancel":
            event.status = "cancelled"
        else:
            for field in ("title", "description", "location"):
                if field in payload:
                    setattr(event, field, payload[field])
            if "start_at" in payload:
                event.start_at = parse_datetime(payload["start_at"], field="start_at")
            if "end_at" in payload:
                event.end_at = parse_datetime(payload["end_at"], field="end_at")
            if event.end_at <= event.start_at:
                raise HTTPException(status_code=422, detail="日程结束时间必须晚于开始时间")
        event.updated_at = utc_now()
        return {"target_type": "event", "target_id": str(event.id)}

    if action == "todo.create":
        todo = TodoItem(
            user_id=user_id,
            title=payload["title"],
            description=payload.get("description", ""),
            due_at=(
                parse_datetime(payload["due_at"], field="due_at")
                if payload.get("due_at")
                else None
            ),
            priority=payload.get("priority", 5),
            source="manual",
        )
        session.add(todo)
        await session.flush()
        return {"target_type": "todo", "target_id": str(todo.id)}

    todo = await _locked_target(session, TodoItem, action_record.target_id, user_id)
    if action == "todo.cancel":
        todo.status = "cancelled"
    elif action == "todo.update":
        for field in ("title", "description", "status", "priority"):
            if field in payload:
                setattr(todo, field, payload[field])
        if "due_at" in payload:
            todo.due_at = (
                parse_datetime(payload["due_at"], field="due_at")
                if payload["due_at"]
                else None
            )
    else:
        raise HTTPException(status_code=422, detail="不支持的日历操作")
    todo.updated_at = utc_now()
    return {"target_type": "todo", "target_id": str(todo.id)}


async def _locked_target(
    session: AsyncSession,
    model: type[CalendarEvent] | type[TodoItem],
    target_id: UUID | None,
    user_id: UUID,
) -> CalendarEvent | TodoItem:
    target = await session.scalar(
        select(model)
        .where(model.id == target_id, model.user_id == user_id)
        .with_for_update()
    )
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="操作目标不存在")
    return target
