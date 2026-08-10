from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

RunStatus = Literal["queued", "running", "completed", "failed", "cancelled"]
MemoryType = Literal["profile", "preference", "project", "instruction"]
CalendarActionType = Literal[
    "event.create",
    "event.update",
    "event.cancel",
    "todo.create",
    "todo.update",
    "todo.cancel",
]


class RunCreate(BaseModel):
    objective: str = Field(min_length=1, max_length=8000)
    run_type: Literal[
        "assistant", "agentic_rag", "research", "email", "calendar", "daily_brief", "monitor"
    ] = "assistant"
    conversation_id: UUID | None = None
    input_payload: dict[str, Any] = Field(default_factory=dict)


class RunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    conversation_id: UUID | None
    objective: str
    run_type: str
    status: RunStatus
    idempotency_key: str
    retry_of_run_id: UUID | None
    cancel_requested_at: datetime | None
    attempt_count: int
    max_attempts: int
    next_retry_at: datetime | None
    result_payload: dict[str, Any]
    error: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class RunPage(BaseModel):
    items: list[RunRead]
    total: int
    limit: int
    offset: int


class ConversationCreate(BaseModel):
    title: str = Field(default="新对话", min_length=1, max_length=512)


class ConversationUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=512)


class ConversationMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    conversation_id: UUID
    run_id: UUID | None
    sequence: int
    role: str
    content: str
    message_metadata: dict[str, Any]
    created_at: datetime


class ConversationSummaryRead(BaseModel):
    id: UUID
    title: str
    message_count: int
    last_message: str
    latest_run_id: UUID | None
    created_at: datetime
    updated_at: datetime


class ConversationRead(ConversationSummaryRead):
    messages: list[ConversationMessageRead]


class MemoryCreate(BaseModel):
    memory_type: MemoryType
    content: str = Field(min_length=2, max_length=2000)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class MemoryUpdate(BaseModel):
    memory_type: MemoryType | None = None
    content: str | None = Field(default=None, min_length=2, max_length=2000)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    enabled: bool | None = None


class MemoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    memory_type: str
    content: str
    source_conversation_id: UUID | None
    source_message_id: UUID | None
    source: str
    confidence: float
    validation_reason: str
    enabled: bool
    usage_count: int
    last_used_at: datetime | None
    created_at: datetime
    updated_at: datetime


class MemoryStatsRead(BaseModel):
    total: int
    enabled: int
    disabled: int
    by_type: dict[str, int]


class EmailStatusRead(BaseModel):
    enabled: bool
    configured: bool
    address: str
    provider: str


class EmailMessageRead(BaseModel):
    uid: str
    from_address: str
    subject: str
    sent_at: str
    snippet: str
    unread: bool
    body: str = ""


class EmailUnreadCountRead(BaseModel):
    count: int
    scope: Literal["today", "all"]


class EmailReplyDraftCreate(BaseModel):
    message_uid: str = Field(min_length=1, max_length=128)


class EmailDraftRead(BaseModel):
    to: str
    subject: str
    body: str
    source_message_uid: str


class EmailSendActionCreate(BaseModel):
    to: str = Field(min_length=3, max_length=512)
    subject: str = Field(default="无主题", max_length=998)
    body: str = Field(min_length=1, max_length=100_000)
    source_message_uid: str = Field(default="", max_length=128)


class EmailSendActionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    recipient: str
    subject: str
    body: str
    source_message_uid: str
    status: str
    provider_message_id: str
    error: str
    created_at: datetime
    confirmed_at: datetime | None
    sent_at: datetime | None


class CalendarEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    description: str
    location: str
    start_at: datetime
    end_at: datetime
    status: str
    provider: str
    provider_event_id: str
    source: str
    created_at: datetime
    updated_at: datetime


class TodoItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    description: str
    status: str
    due_at: datetime | None
    priority: int
    source: str
    created_at: datetime
    updated_at: datetime


class CalendarActionCreate(BaseModel):
    action: CalendarActionType
    target_id: UUID | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class CalendarActionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    action: str
    target_id: UUID | None
    payload: dict[str, Any]
    status: str
    result_payload: dict[str, Any]
    error: str
    created_at: datetime
    confirmed_at: datetime | None
    executed_at: datetime | None


class CalendarStatsRead(BaseModel):
    today_events: int
    upcoming_events: int
    open_todos: int
    overdue_todos: int


class CalendarConflictRead(BaseModel):
    has_conflict: bool
    conflicts: list[CalendarEventRead]


class BriefScheduleCreate(BaseModel):
    name: str = Field(default="每日简报", min_length=1, max_length=255)
    local_time: str = Field(default="08:00", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    timezone: str = Field(default="Asia/Shanghai", max_length=64)
    weekdays: list[int] = Field(default_factory=lambda: list(range(7)), min_length=1)
    topics: list[str] = Field(default_factory=lambda: ["AI 与大模型"])
    include_email: bool = True
    include_calendar: bool = True
    include_memory: bool = True
    enabled: bool = True


class BriefScheduleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    local_time: str | None = Field(
        default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$"
    )
    timezone: str | None = Field(default=None, max_length=64)
    weekdays: list[int] | None = Field(default=None, min_length=1)
    topics: list[str] | None = None
    include_email: bool | None = None
    include_calendar: bool | None = None
    include_memory: bool | None = None
    enabled: bool | None = None


class BriefScheduleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    local_time: str
    timezone: str
    weekdays: list[int]
    topics: list[str]
    include_email: bool
    include_calendar: bool
    include_memory: bool
    enabled: bool
    next_run_at: datetime | None
    last_run_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DailyBriefGenerate(BaseModel):
    schedule_id: UUID | None = None
    topics: list[str] = Field(default_factory=list)
    include_email: bool = True
    include_calendar: bool = True
    include_memory: bool = True


class DailyBriefRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    schedule_id: UUID | None
    title: str
    status: str
    topics: list[str]
    include_email: bool
    include_calendar: bool
    include_memory: bool
    sections: dict[str, Any]
    content: str
    error: str
    unread: bool
    source: str
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    read_at: datetime | None


class DailyBriefStatsRead(BaseModel):
    unread_count: int
    total_count: int
    active_schedule_count: int
    generating_count: int


MonitorTargetType = Literal["news", "github", "company", "blog"]


class MonitorRuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    target_type: MonitorTargetType = "news"
    query: str = Field(min_length=2, max_length=1000)
    interval_minutes: int = Field(default=360, ge=15, le=43_200)
    enabled: bool = True


class MonitorRuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    target_type: MonitorTargetType | None = None
    query: str | None = Field(default=None, min_length=2, max_length=1000)
    interval_minutes: int | None = Field(default=None, ge=15, le=43_200)
    enabled: bool | None = None


class MonitorRuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    target_type: str
    query: str
    interval_minutes: int
    enabled: bool
    last_result: list[dict[str, Any]]
    last_run_status: str
    last_error: str
    last_run_id: UUID | None
    next_run_at: datetime | None
    last_run_at: datetime | None
    created_at: datetime
    updated_at: datetime


class MonitorNotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    rule_id: UUID
    title: str
    summary: str
    payload: dict[str, Any]
    unread: bool
    created_at: datetime
    read_at: datetime | None


class MonitorResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    rule_id: UUID
    run_id: UUID | None
    rule_name: str
    target_type: str
    summary: str
    item_count: int
    change_count: int
    baseline_created: bool
    payload: dict[str, Any]
    created_at: datetime


class MonitorResultPageRead(BaseModel):
    items: list[MonitorResultRead]
    total: int
    limit: int
    offset: int


class MonitorStatsRead(BaseModel):
    rule_count: int
    enabled_count: int
    unread_count: int
    running_count: int


class RunEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    run_id: UUID
    sequence: int
    event_type: str
    agent_id: str
    payload: dict[str, Any]
    created_at: datetime


class KnowledgeDocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    filename: str
    content_type: str
    size_bytes: int
    status: str
    error: str
    chunk_count: int
    document_metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    indexed_at: datetime | None


class KnowledgeStatsRead(BaseModel):
    document_count: int
    indexed_count: int
    processing_count: int
    failed_count: int
    chunk_count: int
