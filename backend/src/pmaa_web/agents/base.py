from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from pmaa_web.agents.blackboard import Blackboard
from pmaa_web.agents.protocol import AgentResult, AgentTask
from pmaa_web.models import AgentRun

EventEmitter = Callable[[str, str, dict[str, Any]], Awaitable[None]]
AgentHandler = Callable[[AgentTask, "AgentExecutionContext"], Awaitable[AgentResult]]


@dataclass(slots=True)
class AgentExecutionContext:
    session: AsyncSession
    run: AgentRun
    blackboard: Blackboard
    emit: EventEmitter


class BaseAgent(ABC):
    agent_id: str
    description: str
    capabilities: frozenset[str]
    allowed_tools: frozenset[str]

    @abstractmethod
    async def execute(
        self,
        task: AgentTask,
        context: AgentExecutionContext,
    ) -> AgentResult:
        raise NotImplementedError


class FunctionAgent(BaseAgent):
    def __init__(
        self,
        *,
        agent_id: str,
        description: str,
        capabilities: set[str],
        allowed_tools: set[str],
        handler: AgentHandler,
    ) -> None:
        self.agent_id = agent_id
        self.description = description
        self.capabilities = frozenset(capabilities)
        self.allowed_tools = frozenset(allowed_tools)
        self._handler = handler

    async def execute(
        self,
        task: AgentTask,
        context: AgentExecutionContext,
    ) -> AgentResult:
        return await self._handler(task, context)
