from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from pmaa_web.models import Conversation, ConversationMessage, utc_now


def title_from_message(content: str, *, limit: int = 48) -> str:
    title = re.sub(r"\s+", " ", content).strip()
    if not title:
        return "新对话"
    return title if len(title) <= limit else f"{title[:limit]}…"


async def append_conversation_message(
    session: AsyncSession,
    conversation: Conversation,
    *,
    role: str,
    content: str,
    run_id: UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> ConversationMessage:
    next_sequence = await session.scalar(
        update(Conversation)
        .where(Conversation.id == conversation.id)
        .values(
            next_message_sequence=Conversation.next_message_sequence + 1,
            updated_at=utc_now(),
        )
        .returning(Conversation.next_message_sequence)
        .execution_options(synchronize_session=False)
    )
    if next_sequence is None:
        raise LookupError(f"Conversation {conversation.id} not found")
    set_committed_value(conversation, "next_message_sequence", next_sequence)
    message = ConversationMessage(
        conversation_id=conversation.id,
        run_id=run_id,
        sequence=next_sequence - 1,
        role=role,
        content=content,
        message_metadata=metadata or {},
    )
    session.add(message)
    await session.commit()
    await session.refresh(message)
    return message
