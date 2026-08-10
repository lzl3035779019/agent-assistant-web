from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pmaa_web.auth_context import current_user_id
from pmaa_web.conversation_service import append_conversation_message, title_from_message
from pmaa_web.database import SessionFactory, get_session
from pmaa_web.models import AgentRun, Conversation, ConversationMessage, RunEvent, utc_now
from pmaa_web.run_service import append_event, dispatch_run
from pmaa_web.schemas import RunCreate, RunEventRead, RunPage, RunRead, RunStatus

router = APIRouter(prefix="/runs", tags=["runs"])


@router.post("", response_model=RunRead, status_code=status.HTTP_202_ACCEPTED)
async def create_run(
    payload: RunCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_session),
) -> AgentRun:
    normalized_key = (idempotency_key or "").strip()[:128]
    if normalized_key:
        existing = await session.scalar(
            select(AgentRun).where(
                AgentRun.user_id == current_user_id(),
                AgentRun.idempotency_key == normalized_key,
            )
        )
        if existing:
            return existing
    conversation: Conversation | None = None
    if payload.conversation_id:
        conversation = await session.get(Conversation, payload.conversation_id)
        if conversation is None or conversation.user_id != current_user_id():
            raise HTTPException(status_code=404, detail="Conversation not found")
    else:
        conversation = Conversation(
            user_id=current_user_id(),
            title=title_from_message(payload.objective),
        )
        session.add(conversation)
        await session.flush()

    history = list(
        await session.scalars(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation.id)
            .order_by(ConversationMessage.sequence.desc())
            .limit(12)
        )
    )
    input_payload = dict(payload.input_payload)
    input_payload["conversation_history"] = [
        {"role": message.role, "content": message.content}
        for message in reversed(history)
    ]
    run = AgentRun(
        user_id=current_user_id(),
        conversation_id=conversation.id,
        objective=payload.objective,
        run_type=payload.run_type,
        input_payload=input_payload,
        idempotency_key=normalized_key,
    )
    session.add(run)
    await session.flush()
    await append_conversation_message(
        session,
        conversation,
        role="user",
        content=payload.objective,
        run_id=run.id,
        metadata={"run_type": payload.run_type},
    )
    await dispatch_run(run.id)
    return run


@router.get("", response_model=RunPage)
async def list_runs(
    run_status: RunStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> RunPage:
    filters = [AgentRun.user_id == current_user_id()]
    if run_status:
        filters.append(AgentRun.status == run_status)
    total = int(
        await session.scalar(select(func.count()).select_from(AgentRun).where(*filters)) or 0
    )
    records = list(
        await session.scalars(
            select(AgentRun)
            .where(*filters)
            .order_by(AgentRun.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    return RunPage(
        items=[RunRead.model_validate(item) for item in records],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/{run_id}/cancel", response_model=RunRead)
async def cancel_run(
    run_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> AgentRun:
    run = await session.get(AgentRun, run_id)
    if run is None or run.user_id != current_user_id():
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status not in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="只有排队中或运行中的任务可以取消")
    run.cancel_requested_at = utc_now()
    run.status = "cancelled"
    run.finished_at = utc_now()
    await append_event(
        session,
        run,
        "run_cancelled",
        payload={"title": "任务已取消", "summary": "用户请求停止后续执行"},
    )
    return run


@router.post("/{run_id}/retry", response_model=RunRead, status_code=status.HTTP_202_ACCEPTED)
async def retry_run(
    run_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> AgentRun:
    original = await session.get(AgentRun, run_id)
    if original is None or original.user_id != current_user_id():
        raise HTTPException(status_code=404, detail="Run not found")
    if original.status not in {"failed", "cancelled"}:
        raise HTTPException(status_code=409, detail="只有失败或已取消任务可以重试")
    retried = AgentRun(
        user_id=current_user_id(),
        conversation_id=original.conversation_id,
        objective=original.objective,
        run_type=original.run_type,
        input_payload=dict(original.input_payload or {}),
        retry_of_run_id=original.id,
        max_attempts=original.max_attempts,
    )
    session.add(retried)
    await session.flush()
    await session.commit()
    await dispatch_run(retried.id)
    return retried


@router.get("/{run_id}", response_model=RunRead)
async def get_run(
    run_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> AgentRun:
    run = await session.get(AgentRun, run_id)
    if run is None or run.user_id != current_user_id():
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get("/{run_id}/events/history", response_model=list[RunEventRead])
async def get_run_events(
    run_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> list[RunEvent]:
    run = await session.get(AgentRun, run_id)
    if run is None or run.user_id != current_user_id():
        raise HTTPException(status_code=404, detail="Run not found")
    result = await session.scalars(
        select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.sequence)
    )
    return list(result)


@router.get("/{run_id}/events")
async def stream_run_events(
    run_id: UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    run = await session.get(AgentRun, run_id)
    if run is None or run.user_id != current_user_id():
        raise HTTPException(status_code=404, detail="Run not found")

    raw_last_id = request.headers.get("last-event-id") or request.query_params.get("after", "0")
    try:
        last_sequence = int(raw_last_id)
    except ValueError:
        last_sequence = 0

    async def generate() -> AsyncIterator[str]:
        nonlocal last_sequence
        idle_cycles = 0
        while not await request.is_disconnected():
            async with SessionFactory() as polling_session:
                result = await polling_session.scalars(
                    select(RunEvent)
                    .where(
                        RunEvent.run_id == run_id,
                        RunEvent.sequence > last_sequence,
                    )
                    .order_by(RunEvent.sequence)
                )
                events = list(result)
                current_run = await polling_session.get(AgentRun, run_id)
            if events:
                idle_cycles = 0
                for event in events:
                    last_sequence = event.sequence
                    data = RunEventRead.model_validate(event).model_dump(mode="json")
                    yield (
                        f"id: {event.sequence}\n"
                        f"event: {event.event_type}\n"
                        f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                    )
            else:
                idle_cycles += 1
                if idle_cycles % 15 == 0:
                    yield ": keep-alive\n\n"
            if current_run and current_run.status in {"completed", "failed", "cancelled"}:
                if not events:
                    break
            await asyncio.sleep(0.5)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
