from __future__ import annotations

from dataclasses import replace

from fastapi.testclient import TestClient
from pmaa_web.email_service import (
    MailMessage,
    create_reply_draft,
    get_email_backend,
    valid_email,
)
from pmaa_web.main import app


class FakeEmailBackend:
    enabled = True
    configured = True
    address = "owner@example.com"

    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []
        self.last_list_filters: dict = {}
        self.messages = {
            "101": MailMessage(
                uid="101",
                from_address="招聘负责人 <hr@example.com>",
                subject="面试时间确认",
                sent_at="Sat, 8 Aug 2026 09:30:00 +0800",
                snippet="请确认下周一下午的面试时间。",
                unread=True,
                body="小林你好，\n\n请确认下周一下午三点的面试时间。",
            )
        }

    def count_unread(self, *, today_only: bool = True) -> int:
        del today_only
        return sum(message.unread for message in self.messages.values())

    def list_recent(
        self,
        *,
        limit: int,
        unread_only: bool,
        start_date=None,
        end_date=None,
    ) -> list[MailMessage]:
        self.last_list_filters = {
            "limit": limit,
            "unread_only": unread_only,
            "start_date": start_date,
            "end_date": end_date,
        }
        messages = list(self.messages.values())
        if unread_only:
            messages = [message for message in messages if message.unread]
        return [replace(message, body="") for message in messages[:limit]]

    def get_message(self, uid: str, *, mark_read: bool = False) -> MailMessage | None:
        message = self.messages.get(uid)
        if message and mark_read:
            message.unread = False
        return message

    def send(self, *, recipient: str, subject: str, body: str) -> str:
        self.sent.append({"recipient": recipient, "subject": subject, "body": body})
        return "<fake-message-id@example.com>"


def test_email_helpers() -> None:
    assert valid_email("person@example.com") is True
    assert valid_email("not-an-address") is False
    message = MailMessage(
        uid="7",
        from_address="测试用户 <person@example.com>",
        subject="项目进度",
        sent_at="",
        snippet="",
        unread=True,
    )
    assert create_reply_draft(message) == {
        "to": "person@example.com",
        "subject": "Re: 项目进度",
        "body": "您好，\n\n我已收到您关于“项目进度”的邮件。相关内容我会进一步确认，并尽快回复您。\n\n谢谢。",
        "source_message_uid": "7",
    }


def test_email_read_draft_confirm_and_audit() -> None:
    backend = FakeEmailBackend()
    app.dependency_overrides[get_email_backend] = lambda: backend
    try:
        with TestClient(app) as client:
            status = client.get("/api/v1/email/status")
            assert status.status_code == 200
            assert status.json()["configured"] is True

            unread = client.get("/api/v1/email/unread-count")
            assert unread.status_code == 200
            assert unread.json() == {"count": 1, "scope": "today"}

            messages = client.get("/api/v1/email/messages?limit=10&unread_only=true")
            assert messages.status_code == 200
            assert messages.json()[0]["body"] == ""

            filtered = client.get(
                "/api/v1/email/messages?limit=25&start_date=2026-08-01&end_date=2026-08-10"
            )
            assert filtered.status_code == 200
            assert backend.last_list_filters["limit"] == 25
            assert str(backend.last_list_filters["start_date"]) == "2026-08-01"
            assert str(backend.last_list_filters["end_date"]) == "2026-08-10"

            invalid_range = client.get(
                "/api/v1/email/messages?start_date=2026-08-10&end_date=2026-08-01"
            )
            assert invalid_range.status_code == 422

            opened = client.post("/api/v1/email/messages/101/read")
            assert opened.status_code == 200
            assert opened.json()["unread"] is False
            assert "下午三点" in opened.json()["body"]

            draft = client.post(
                "/api/v1/email/drafts/reply",
                json={"message_uid": "101"},
            )
            assert draft.status_code == 200
            assert draft.json()["to"] == "hr@example.com"

            prepared = client.post(
                "/api/v1/email/send-actions",
                json={
                    "to": "hr@example.com",
                    "subject": "Re: 面试时间确认",
                    "body": "您好，我可以参加。",
                    "source_message_uid": "101",
                },
            )
            assert prepared.status_code == 201
            assert prepared.json()["status"] == "pending"
            action_id = prepared.json()["id"]
            assert backend.sent == []

            confirmed = client.post(f"/api/v1/email/send-actions/{action_id}/confirm")
            assert confirmed.status_code == 200
            assert confirmed.json()["status"] == "sent"
            assert backend.sent == [
                {
                    "recipient": "hr@example.com",
                    "subject": "Re: 面试时间确认",
                    "body": "您好，我可以参加。",
                }
            ]

            duplicate = client.post(f"/api/v1/email/send-actions/{action_id}/confirm")
            assert duplicate.status_code == 409

            audit = client.get("/api/v1/email/send-actions")
            assert audit.status_code == 200
            assert audit.json()[0]["status"] == "sent"
    finally:
        app.dependency_overrides.pop(get_email_backend, None)


def test_email_send_action_can_be_cancelled_before_send() -> None:
    backend = FakeEmailBackend()
    app.dependency_overrides[get_email_backend] = lambda: backend
    try:
        with TestClient(app) as client:
            prepared = client.post(
                "/api/v1/email/send-actions",
                json={"to": "person@example.com", "subject": "测试", "body": "正文"},
            )
            action_id = prepared.json()["id"]
            cancelled = client.post(f"/api/v1/email/send-actions/{action_id}/cancel")
            assert cancelled.status_code == 200
            assert cancelled.json()["status"] == "cancelled"
            assert backend.sent == []
    finally:
        app.dependency_overrides.pop(get_email_backend, None)
