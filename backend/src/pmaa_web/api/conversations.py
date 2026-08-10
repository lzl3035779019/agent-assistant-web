from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pmaa_web.auth_context import current_user_id
from pmaa_web.database import get_session
from pmaa_web.models import AgentRun, Conversation, ConversationMessage
from pmaa_web.schemas import (
    ConversationCreate,
    ConversationRead,
    ConversationSummaryRead,
    ConversationUpdate,
)

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.post("", response_model=ConversationRead, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    payload: ConversationCreate,
    session: AsyncSession = Depends(get_session),
) -> dict:
    conversation = Conversation(user_id=current_user_id(), title=payload.title.strip())
    session.add(conversation)
    await session.commit()
    await session.refresh(conversation)
    return _conversation_payload(conversation, [], 0, "", None)


@router.get("", response_model=list[ConversationSummaryRead])
async def list_conversations(
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    message_count = (
        select(func.count(ConversationMessage.id))
        .where(ConversationMessage.conversation_id == Conversation.id)
        .correlate(Conversation)
        .scalar_subquery()
    )
    last_message = (
        select(ConversationMessage.content)
        .where(ConversationMessage.conversation_id == Conversation.id)
        .order_by(ConversationMessage.sequence.desc())
        .limit(1)
        .correlate(Conversation)
        .scalar_subquery()
    )
    latest_run_id = (
        select(AgentRun.id)
        .where(AgentRun.conversation_id == Conversation.id)
        .order_by(AgentRun.created_at.desc())
        .limit(1)
        .correlate(Conversation)
        .scalar_subquery()
    )
    rows = (
        await session.execute(
            select(
                Conversation,
                message_count.label("message_count"),
                last_message.label("last_message"),
                latest_run_id.label("latest_run_id"),
            )
            .where(Conversation.user_id == current_user_id())
            .order_by(Conversation.updated_at.desc())
            .limit(limit)
        )
    ).all()
    return [
        _conversation_payload(
            conversation,
            None,
            int(count or 0),
            last or "",
            run_id,
        )
        for conversation, count, last, run_id in rows
    ]


@router.get("/{conversation_id}", response_model=ConversationRead)
async def get_conversation(
    conversation_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict:
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None or conversation.user_id != current_user_id():
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = list(
        await session.scalars(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation.id)
            .order_by(ConversationMessage.sequence)
        )
    )
    latest_run_id = await session.scalar(
        select(AgentRun.id)
        .where(AgentRun.conversation_id == conversation.id)
        .order_by(AgentRun.created_at.desc())
        .limit(1)
    )
    last_message = messages[-1].content if messages else ""
    return _conversation_payload(
        conversation,
        messages,
        len(messages),
        last_message,
        latest_run_id,
    )


@router.patch("/{conversation_id}", response_model=ConversationSummaryRead)
async def update_conversation(
    conversation_id: UUID,
    payload: ConversationUpdate,
    session: AsyncSession = Depends(get_session),
) -> dict:
    conversation = await _get_owned_conversation(session, conversation_id)
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Conversation title cannot be empty")
    conversation.title = title
    await session.commit()
    await session.refresh(conversation)
    return await _conversation_summary_payload(session, conversation)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> None:
    conversation = await _get_owned_conversation(session, conversation_id)
    await session.delete(conversation)
    await session.commit()


async def _get_owned_conversation(
    session: AsyncSession,
    conversation_id: UUID,
) -> Conversation:
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None or conversation.user_id != current_user_id():
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


async def _conversation_summary_payload(
    session: AsyncSession,
    conversation: Conversation,
) -> dict:
    message_count = await session.scalar(
        select(func.count(ConversationMessage.id)).where(
            ConversationMessage.conversation_id == conversation.id
        )
    )
    last_message = await session.scalar(
        select(ConversationMessage.content)
        .where(ConversationMessage.conversation_id == conversation.id)
        .order_by(ConversationMessage.sequence.desc())
        .limit(1)
    )
    latest_run_id = await session.scalar(
        select(AgentRun.id)
        .where(AgentRun.conversation_id == conversation.id)
        .order_by(AgentRun.created_at.desc())
        .limit(1)
    )
    return _conversation_payload(
        conversation,
        None,
        int(message_count or 0),
        last_message or "",
        latest_run_id,
    )


def _conversation_payload(
    conversation: Conversation,
    messages: list[ConversationMessage] | None,
    message_count: int,
    last_message: str,
    latest_run_id: UUID | None,
) -> dict:
    payload = {
        "id": conversation.id,
        "title": conversation.title,
        "message_count": message_count,
        "last_message": last_message[:240],
        "latest_run_id": latest_run_id,
        "created_at": conversation.created_at,
        "updated_at": conversation.updated_at,
    }
    if messages is not None:
        payload["messages"] = messages
    return payload
