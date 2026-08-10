from __future__ import annotations

import asyncio
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pmaa_web.auth_context import current_user_id
from pmaa_web.database import get_session
from pmaa_web.email_service import (
    EmailConfigurationError,
    EmailConnectionError,
    QQEmailBackend,
    create_reply_draft,
    get_email_backend,
    valid_email,
)
from pmaa_web.models import EmailSendAction, utc_now
from pmaa_web.schemas import (
    EmailDraftRead,
    EmailMessageRead,
    EmailReplyDraftCreate,
    EmailSendActionCreate,
    EmailSendActionRead,
    EmailStatusRead,
    EmailUnreadCountRead,
)

router = APIRouter(prefix="/email", tags=["email"])


def _email_error(exc: Exception) -> HTTPException:
    code = status.HTTP_503_SERVICE_UNAVAILABLE
    if isinstance(exc, ValueError):
        code = status.HTTP_422_UNPROCESSABLE_ENTITY
    return HTTPException(status_code=code, detail=str(exc))


@router.get("/status", response_model=EmailStatusRead)
async def email_status(
    backend: QQEmailBackend = Depends(get_email_backend),
) -> EmailStatusRead:
    return EmailStatusRead(
        enabled=backend.enabled,
        configured=backend.configured,
        address=backend.address if backend.configured else "",
        provider="qq",
    )


@router.get("/unread-count", response_model=EmailUnreadCountRead)
async def unread_count(
    today_only: bool = True,
    backend: QQEmailBackend = Depends(get_email_backend),
) -> EmailUnreadCountRead:
    if not backend.configured:
        return EmailUnreadCountRead(count=0, scope="today" if today_only else "all")
    try:
        count = await asyncio.to_thread(backend.count_unread, today_only=today_only)
    except (EmailConfigurationError, EmailConnectionError) as exc:
        raise _email_error(exc) from exc
    return EmailUnreadCountRead(count=count, scope="today" if today_only else "all")


@router.get("/messages", response_model=list[EmailMessageRead])
async def list_messages(
    limit: int = Query(default=10, ge=1, le=100),
    unread_only: bool = False,
    start_date: date | None = None,
    end_date: date | None = None,
    backend: QQEmailBackend = Depends(get_email_backend),
) -> list[dict]:
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=422, detail="开始日期不能晚于结束日期")
    filters = {"limit": limit, "unread_only": unread_only}
    if start_date:
        filters["start_date"] = start_date
    if end_date:
        filters["end_date"] = end_date
    try:
        messages = await asyncio.to_thread(
            backend.list_recent,
            **filters,
        )
    except (EmailConfigurationError, EmailConnectionError) as exc:
        raise _email_error(exc) from exc
    return [message.to_dict() for message in messages]


@router.get("/messages/{message_uid}", response_model=EmailMessageRead)
async def get_message(
    message_uid: str,
    backend: QQEmailBackend = Depends(get_email_backend),
) -> dict:
    try:
        message = await asyncio.to_thread(backend.get_message, message_uid, mark_read=False)
    except (EmailConfigurationError, EmailConnectionError, ValueError) as exc:
        raise _email_error(exc) from exc
    if message is None:
        raise HTTPException(status_code=404, detail="邮件不存在，请刷新收件箱")
    return message.to_dict()


@router.post("/messages/{message_uid}/read", response_model=EmailMessageRead)
async def mark_message_read(
    message_uid: str,
    backend: QQEmailBackend = Depends(get_email_backend),
) -> dict:
    try:
        message = await asyncio.to_thread(backend.get_message, message_uid, mark_read=True)
    except (EmailConfigurationError, EmailConnectionError, ValueError) as exc:
        raise _email_error(exc) from exc
    if message is None:
        raise HTTPException(status_code=404, detail="邮件不存在，请刷新收件箱")
    return message.to_dict()


@router.post("/drafts/reply", response_model=EmailDraftRead)
async def draft_reply(
    payload: EmailReplyDraftCreate,
    backend: QQEmailBackend = Depends(get_email_backend),
) -> EmailDraftRead:
    try:
        message = await asyncio.to_thread(
            backend.get_message,
            payload.message_uid,
            mark_read=False,
        )
    except (EmailConfigurationError, EmailConnectionError, ValueError) as exc:
        raise _email_error(exc) from exc
    if message is None:
        raise HTTPException(status_code=404, detail="邮件不存在，请刷新收件箱")
    return EmailDraftRead(**create_reply_draft(message))


@router.get("/send-actions", response_model=list[EmailSendActionRead])
async def list_send_actions(
    limit: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> list[EmailSendAction]:
    records = await session.scalars(
        select(EmailSendAction)
        .where(EmailSendAction.user_id == current_user_id())
        .order_by(EmailSendAction.created_at.desc())
        .limit(limit)
    )
    return list(records)


@router.post(
    "/send-actions",
    response_model=EmailSendActionRead,
    status_code=status.HTTP_201_CREATED,
)
async def prepare_send_action(
    payload: EmailSendActionCreate,
    session: AsyncSession = Depends(get_session),
) -> EmailSendAction:
    recipient = payload.to.strip()
    body = payload.body.strip()
    if not valid_email(recipient):
        raise HTTPException(status_code=422, detail="收件人邮箱地址无效")
    if not body:
        raise HTTPException(status_code=422, detail="邮件正文不能为空")
    action = EmailSendAction(
        user_id=current_user_id(),
        recipient=recipient,
        subject=payload.subject.strip() or "无主题",
        body=body,
        source_message_uid=payload.source_message_uid.strip(),
        status="pending",
    )
    session.add(action)
    await session.commit()
    await session.refresh(action)
    return action


async def _owned_action(
    session: AsyncSession,
    action_id: UUID,
    *,
    lock: bool = False,
) -> EmailSendAction:
    statement = select(EmailSendAction).where(
        EmailSendAction.id == action_id,
        EmailSendAction.user_id == current_user_id(),
    )
    if lock:
        statement = statement.with_for_update()
    action = await session.scalar(statement)
    if action is None:
        raise HTTPException(status_code=404, detail="邮件发送动作不存在")
    return action


@router.post("/send-actions/{action_id}/confirm", response_model=EmailSendActionRead)
async def confirm_send_action(
    action_id: UUID,
    session: AsyncSession = Depends(get_session),
    backend: QQEmailBackend = Depends(get_email_backend),
) -> EmailSendAction:
    action = await _owned_action(session, action_id, lock=True)
    if action.status != "pending":
        raise HTTPException(status_code=409, detail=f"当前动作状态为 {action.status}，不能重复发送")
    action.status = "sending"
    action.confirmed_at = utc_now()
    await session.commit()

    try:
        message_id = await asyncio.to_thread(
            backend.send,
            recipient=action.recipient,
            subject=action.subject,
            body=action.body,
        )
    except (EmailConfigurationError, EmailConnectionError, ValueError) as exc:
        action.status = "failed"
        action.error = str(exc)
        await session.commit()
        raise _email_error(exc) from exc

    action.status = "sent"
    action.provider_message_id = message_id
    action.sent_at = utc_now()
    action.error = ""
    await session.commit()
    await session.refresh(action)
    return action


@router.post("/send-actions/{action_id}/cancel", response_model=EmailSendActionRead)
async def cancel_send_action(
    action_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> EmailSendAction:
    action = await _owned_action(session, action_id, lock=True)
    if action.status != "pending":
        raise HTTPException(status_code=409, detail=f"当前动作状态为 {action.status}，不能取消")
    action.status = "cancelled"
    await session.commit()
    await session.refresh(action)
    return action
