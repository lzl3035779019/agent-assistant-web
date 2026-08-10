from __future__ import annotations

import imaplib
import re
import smtplib
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from email import policy
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import formatdate, make_msgid, parseaddr
from html import unescape
from typing import Any

from pmaa_web.config import get_settings


class EmailConfigurationError(RuntimeError):
    pass


class EmailConnectionError(RuntimeError):
    pass


@dataclass(slots=True)
class MailMessage:
    uid: str
    from_address: str
    subject: str
    sent_at: str
    snippet: str
    unread: bool
    body: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class QQEmailBackend:
    def __init__(self) -> None:
        settings = get_settings()
        self.enabled = settings.email_enabled
        self.address = settings.qq_email_address
        self.auth_code = settings.qq_email_auth_code
        self.imap_host = settings.qq_imap_host
        self.imap_port = settings.qq_imap_port
        self.smtp_host = settings.qq_smtp_host
        self.smtp_port = settings.qq_smtp_port

    @property
    def configured(self) -> bool:
        return bool(self.enabled and self.address and self.auth_code)

    def list_recent(
        self,
        *,
        limit: int = 10,
        unread_only: bool = False,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[MailMessage]:
        self._ensure_configured()
        try:
            with self._imap(readonly=True) as client:
                criteria: list[str] = []
                if unread_only:
                    criteria.append("UNSEEN")
                if start_date:
                    criteria.extend(["SINCE", _imap_date(start_date)])
                if end_date:
                    criteria.extend(["BEFORE", _imap_date(end_date + timedelta(days=1))])
                status, data = client.uid("search", None, *(criteria or ["ALL"]))
                if status != "OK" or not data or not data[0]:
                    return []
                uids = data[0].split()[-limit:]
                messages = [self._fetch(client, uid.decode("ascii")) for uid in reversed(uids)]
                return [message for message in messages if message is not None]
        except EmailConfigurationError:
            raise
        except Exception as exc:
            raise EmailConnectionError(f"QQ 邮箱读取失败：{type(exc).__name__}") from exc

    def count_unread(self, *, today_only: bool = True) -> int:
        self._ensure_configured()
        try:
            with self._imap(readonly=True) as client:
                criteria = ["UNSEEN"]
                if today_only:
                    criteria.extend(["SINCE", _imap_date(datetime.now().astimezone())])
                status, data = client.uid("search", None, *criteria)
                if status != "OK" or not data or not data[0]:
                    return 0
                return len(data[0].split())
        except EmailConfigurationError:
            raise
        except Exception as exc:
            raise EmailConnectionError(f"QQ 邮箱未读统计失败：{type(exc).__name__}") from exc

    def get_message(self, uid: str, *, mark_read: bool = False) -> MailMessage | None:
        self._ensure_configured()
        if not uid.isdigit():
            raise ValueError("邮件 UID 无效")
        try:
            with self._imap(readonly=not mark_read) as client:
                message = self._fetch(client, uid, include_body=True)
                if message and mark_read and message.unread:
                    status, _ = client.uid("store", uid, "+FLAGS.SILENT", "(\\Seen)")
                    if status == "OK":
                        message.unread = False
                return message
        except (EmailConfigurationError, ValueError):
            raise
        except Exception as exc:
            raise EmailConnectionError(f"QQ 邮件全文读取失败：{type(exc).__name__}") from exc

    def send(self, *, recipient: str, subject: str, body: str) -> str:
        self._ensure_configured()
        parsed_recipient = parseaddr(recipient)[1]
        if not valid_email(parsed_recipient):
            raise ValueError("收件人邮箱地址无效")
        if not body.strip():
            raise ValueError("邮件正文不能为空")

        message = EmailMessage()
        message["From"] = self.address
        message["To"] = parsed_recipient
        message["Subject"] = subject.strip() or "无主题"
        message["Date"] = formatdate(localtime=True)
        message["Message-ID"] = make_msgid()
        message.set_content(body.strip())
        try:
            with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=20) as client:
                client.login(self.address, self.auth_code)
                client.send_message(message)
        except Exception as exc:
            raise EmailConnectionError(f"QQ 邮件发送失败：{type(exc).__name__}") from exc
        return str(message["Message-ID"])

    def _ensure_configured(self) -> None:
        if not self.enabled:
            raise EmailConfigurationError("邮件模块尚未启用")
        if not self.address or not self.auth_code:
            raise EmailConfigurationError("QQ_EMAIL_ADDRESS 或 QQ_EMAIL_AUTH_CODE 未配置")

    def _imap(self, *, readonly: bool) -> _SelectedMailbox:
        return _SelectedMailbox(self, readonly=readonly)

    @staticmethod
    def _fetch(
        client: imaplib.IMAP4_SSL,
        uid: str,
        *,
        include_body: bool = False,
    ) -> MailMessage | None:
        status, fetch_data = client.uid("fetch", uid, "(BODY.PEEK[] FLAGS)")
        if status != "OK" or not fetch_data:
            return None
        raw = _first_bytes_payload(fetch_data)
        if raw is None:
            return None
        flags = _flags_text(fetch_data)
        parsed = BytesParser(policy=policy.default).parsebytes(raw)
        body = _message_text(parsed).strip()
        compact = " ".join(body.split())
        return MailMessage(
            uid=uid,
            from_address=str(parsed.get("From", "")),
            subject=_decode_header_value(str(parsed.get("Subject", ""))) or "无主题",
            sent_at=str(parsed.get("Date", "")),
            snippet=compact[:280],
            unread="\\Seen" not in flags,
            body=body if include_body else "",
        )


class _SelectedMailbox:
    def __init__(self, backend: QQEmailBackend, *, readonly: bool) -> None:
        self.backend = backend
        self.readonly = readonly
        self.client: imaplib.IMAP4_SSL | None = None

    def __enter__(self) -> imaplib.IMAP4_SSL:
        client = imaplib.IMAP4_SSL(
            self.backend.imap_host,
            self.backend.imap_port,
            timeout=20,
        )
        client.login(self.backend.address, self.backend.auth_code)
        status, _ = client.select("INBOX", readonly=self.readonly)
        if status != "OK":
            client.logout()
            raise EmailConnectionError("无法打开 QQ 邮箱收件箱")
        self.client = client
        return client

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self.client is None:
            return
        try:
            self.client.close()
        except Exception:
            pass
        try:
            self.client.logout()
        except Exception:
            pass


def get_email_backend() -> QQEmailBackend:
    return QQEmailBackend()


def create_reply_draft(message: MailMessage) -> dict[str, str]:
    recipient = parseaddr(message.from_address)[1] or message.from_address
    subject = message.subject if message.subject.lower().startswith("re:") else f"Re: {message.subject}"
    body = (
        "您好，\n\n"
        f"我已收到您关于“{message.subject}”的邮件。"
        "相关内容我会进一步确认，并尽快回复您。\n\n"
        "谢谢。"
    )
    return {
        "to": recipient,
        "subject": subject,
        "body": body,
        "source_message_uid": message.uid,
    }


def valid_email(value: str) -> bool:
    return bool(re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value))


def _imap_date(value: date | datetime) -> str:
    months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    return f"{value.day:02d}-{months[value.month - 1]}-{value.year:04d}"


def _decode_header_value(value: str) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _first_bytes_payload(fetch_data: list[Any]) -> bytes | None:
    for item in fetch_data:
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], bytes):
            return item[1]
    return None


def _flags_text(fetch_data: list[Any]) -> str:
    values: list[str] = []
    for item in fetch_data:
        if isinstance(item, tuple) and item and isinstance(item[0], bytes):
            values.append(item[0].decode("utf-8", errors="ignore"))
        elif isinstance(item, bytes):
            values.append(item.decode("utf-8", errors="ignore"))
    return " ".join(values)


def _message_text(message: EmailMessage) -> str:
    if message.is_multipart():
        html_body = ""
        for part in message.walk():
            disposition = str(part.get("Content-Disposition", "")).lower()
            if "attachment" in disposition:
                continue
            if part.get_content_type() == "text/plain":
                try:
                    return str(part.get_content())
                except Exception:
                    continue
            if part.get_content_type() == "text/html" and not html_body:
                try:
                    html_body = str(part.get_content())
                except Exception:
                    continue
        return _html_to_text(html_body) if html_body else ""
    try:
        content = str(message.get_content())
    except Exception:
        return ""
    return _html_to_text(content) if message.get_content_type() == "text/html" else content


def _html_to_text(html: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p\s*>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())
