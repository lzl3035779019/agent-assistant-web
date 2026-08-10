from __future__ import annotations

import asyncio
from collections.abc import Iterable
from time import perf_counter
from uuid import UUID

from pmaa_web.agents.base import AgentExecutionContext
from pmaa_web.agents.protocol import (
    AgentMessage,
    AgentResult,
    AgentTask,
    MessageType,
    ResultStatus,
)
from pmaa_web.agents.registry import AgentRegistry


class AgentRuntime:
    def __init__(self, registry: AgentRegistry, *, max_concurrency: int = 4) -> None:
        self.registry = registry
        self.max_concurrency = max(1, max_concurrency)

    async def execute(
        self,
        tasks: Iterable[AgentTask],
        context: AgentExecutionContext,
    ) -> list[AgentResult]:
        pending = {task.task_id: task for task in tasks}
        self._validate_dependencies(pending)
        results: dict[UUID, AgentResult] = {}
        semaphore = asyncio.Semaphore(self.max_concurrency)

        for task in pending.values():
            await context.blackboard.add_task(task)

        while pending:
            failed_ids = {
                task_id
                for task_id, result in results.items()
                if result.status in {ResultStatus.FAILED, ResultStatus.BLOCKED}
            }
            blocked = [
                task
                for task in pending.values()
                if any(dependency in failed_ids for dependency in task.dependencies)
            ]
            for task in blocked:
                result = AgentResult(
                    task_id=task.task_id,
                    agent_id=task.assigned_agent,
                    status=ResultStatus.BLOCKED,
                    error="A dependency failed or was blocked",
                )
                await context.blackboard.add_result(result)
                results[task.task_id] = result
                pending.pop(task.task_id)

            ready = [
                task
                for task in pending.values()
                if all(dependency in results for dependency in task.dependencies)
            ]
            if not ready:
                if pending:
                    raise RuntimeError("Task graph contains a dependency cycle")
                break

            async def run_ready(task: AgentTask) -> AgentResult:
                async with semaphore:
                    return await self._execute_task(task, context)

            batch_results = await asyncio.gather(*(run_ready(task) for task in ready))
            for result in batch_results:
                results[result.task_id] = result
                pending.pop(result.task_id)

        return [results[task_id] for task_id in results]

    async def _execute_task(
        self,
        task: AgentTask,
        context: AgentExecutionContext,
    ) -> AgentResult:
        agent = self.registry.get(task.assigned_agent)
        dependency_outputs = await context.blackboard.dependency_outputs(task)
        effective_task = task.model_copy(
            update={
                "context": {
                    **task.context,
                    "dependency_results": dependency_outputs,
                }
            },
            deep=True,
        )
        dispatch_message = AgentMessage(
            trace_id=task.trace_id,
            task_id=task.task_id,
            sender="supervisor",
            receiver=agent.agent_id,
            message_type=MessageType.TASK_DELEGATED,
            payload={"objective": task.objective, "attempt": task.attempt},
        )
        await context.blackboard.post_message(dispatch_message)
        await context.emit(
            "agent_message",
            "supervisor",
            {
                "message_type": dispatch_message.message_type.value,
                "sender": dispatch_message.sender,
                "receiver": dispatch_message.receiver,
                "task_id": str(task.task_id),
                "title": f"Supervisor 委派 {agent.agent_id}",
                "summary": task.objective[:240],
            },
        )

        started_at = perf_counter()
        last_error = ""
        result: AgentResult | None = None
        for attempt in range(task.max_attempts):
            effective_task = effective_task.model_copy(update={"attempt": attempt})
            try:
                async with asyncio.timeout(task.timeout_seconds):
                    result = await agent.execute(effective_task, context)
                if result.status != ResultStatus.FAILED:
                    break
                last_error = result.error
            except Exception as exc:
                last_error = str(exc)
            if attempt + 1 < task.max_attempts:
                await context.emit(
                    "agent_retry",
                    agent.agent_id,
                    {
                        "task_id": str(task.task_id),
                        "attempt": attempt + 1,
                        "error": last_error,
                        "title": f"{agent.agent_id} 准备重试",
                        "summary": "子任务执行失败，Runtime 将按任务策略重新执行",
                    },
                )

        if result is None or result.status == ResultStatus.FAILED:
            result = AgentResult(
                task_id=task.task_id,
                agent_id=agent.agent_id,
                status=ResultStatus.FAILED,
                error=last_error or (result.error if result else "Agent execution failed"),
            )
        result.metrics = {
            **result.metrics,
            "runtime_duration_ms": round((perf_counter() - started_at) * 1000),
            "attempts": effective_task.attempt + 1,
        }
        await context.blackboard.add_result(result)
        result_message = AgentMessage(
            trace_id=task.trace_id,
            task_id=task.task_id,
            sender=agent.agent_id,
            receiver="supervisor",
            message_type=MessageType.TASK_RESULT,
            payload={
                "status": result.status.value,
                "confidence": result.confidence,
                "error": result.error,
            },
        )
        await context.blackboard.post_message(result_message)
        await context.emit(
            "agent_message",
            agent.agent_id,
            {
                "message_type": result_message.message_type.value,
                "sender": result_message.sender,
                "receiver": result_message.receiver,
                "task_id": str(task.task_id),
                "status": result.status.value,
                "title": f"{agent.agent_id} 返回结果",
                "summary": "Supervisor 已接收结构化子任务结果",
                "metrics": result.metrics,
            },
        )
        return result

    @staticmethod
    def _validate_dependencies(tasks: dict[UUID, AgentTask]) -> None:
        for task in tasks.values():
            unknown = [item for item in task.dependencies if item not in tasks]
            if unknown:
                raise ValueError(
                    f"Task {task.task_id} has unknown dependencies: {unknown}"
                )
