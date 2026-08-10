from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MessageType(str, Enum):
    TASK_DELEGATED = "task_delegated"
    TASK_RESULT = "task_result"
    STATUS_UPDATE = "status_update"
    CAPABILITY_REQUEST = "capability_request"
    CAPABILITY_RESPONSE = "capability_response"


class ResultStatus(str, Enum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    BLOCKED = "blocked"


class AgentTask(BaseModel):
    task_id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    trace_id: UUID
    parent_task_id: UUID | None = None
    assigned_agent: str
    objective: str = Field(min_length=1, max_length=8000)
    context: dict[str, Any] = Field(default_factory=dict)
    dependencies: list[UUID] = Field(default_factory=list)
    attempt: int = 0
    max_attempts: int = 2
    timeout_seconds: float = 180.0


class AgentMessage(BaseModel):
    message_id: UUID = Field(default_factory=uuid4)
    trace_id: UUID
    task_id: UUID | None = None
    sender: str
    receiver: str
    message_type: MessageType
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class AgentResult(BaseModel):
    task_id: UUID
    agent_id: str
    status: ResultStatus
    output: dict[str, Any] = Field(default_factory=dict)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    error: str = ""
    metrics: dict[str, Any] = Field(default_factory=dict)
    child_tasks: list[AgentTask] = Field(default_factory=list)
    completed_at: datetime = Field(default_factory=utc_now)
