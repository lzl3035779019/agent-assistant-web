from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

from pmaa_web.agents.protocol import AgentMessage, AgentResult, AgentTask


class Blackboard:
    """Run-scoped shared state with Supervisor-mediated communication."""

    def __init__(self, trace_id: UUID) -> None:
        self.trace_id = trace_id
        self._tasks: dict[UUID, AgentTask] = {}
        self._messages: list[AgentMessage] = []
        self._results: dict[UUID, AgentResult] = {}
        self._scratchpad: dict[str, Any] = {}
        self._lock = asyncio.Lock()

    async def add_task(self, task: AgentTask) -> None:
        if task.trace_id != self.trace_id:
            raise ValueError("Task trace_id does not belong to this blackboard")
        async with self._lock:
            self._tasks[task.task_id] = task.model_copy(deep=True)

    async def post_message(self, message: AgentMessage) -> None:
        if message.trace_id != self.trace_id:
            raise ValueError("Message trace_id does not belong to this blackboard")
        if message.sender != "supervisor" and message.receiver != "supervisor":
            raise ValueError("Child agents may communicate only through Supervisor")
        async with self._lock:
            self._messages.append(message.model_copy(deep=True))

    async def add_result(self, result: AgentResult) -> None:
        async with self._lock:
            if result.task_id not in self._tasks:
                raise KeyError(f"Unknown task: {result.task_id}")
            self._results[result.task_id] = result.model_copy(deep=True)

    async def get_result(self, task_id: UUID) -> AgentResult | None:
        async with self._lock:
            result = self._results.get(task_id)
            return result.model_copy(deep=True) if result else None

    async def dependency_outputs(self, task: AgentTask) -> dict[str, Any]:
        async with self._lock:
            return {
                str(dependency_id): {
                    "agent_id": self._results[dependency_id].agent_id,
                    "status": self._results[dependency_id].status.value,
                    "output": self._results[dependency_id].output,
                    "evidence": self._results[dependency_id].evidence,
                    "confidence": self._results[dependency_id].confidence,
                }
                for dependency_id in task.dependencies
                if dependency_id in self._results
            }

    async def put(self, key: str, value: Any) -> None:
        async with self._lock:
            self._scratchpad[key] = value

    async def get(self, key: str, default: Any = None) -> Any:
        async with self._lock:
            return self._scratchpad.get(key, default)

    async def snapshot(self) -> dict[str, Any]:
        async with self._lock:
            return {
                "trace_id": str(self.trace_id),
                "task_count": len(self._tasks),
                "message_count": len(self._messages),
                "result_count": len(self._results),
                "tasks": [task.model_dump(mode="json") for task in self._tasks.values()],
                "messages": [
                    message.model_dump(mode="json") for message in self._messages
                ],
                "results": [
                    result.model_dump(mode="json") for result in self._results.values()
                ],
            }
