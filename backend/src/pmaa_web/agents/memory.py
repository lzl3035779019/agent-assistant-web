from __future__ import annotations

from time import perf_counter
from typing import Any, TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph

from pmaa_web.agents.base import AgentExecutionContext, BaseAgent
from pmaa_web.agents.protocol import AgentResult, AgentTask, ResultStatus
from pmaa_web.memory_service import (
    MemoryCandidate,
    extract_candidates,
    persist_memory_candidates,
    retrieve_memories,
    validate_candidate,
)


class MemoryState(TypedDict, total=False):
    operation: str
    query: str
    user_input: str
    candidates: list[dict[str, Any]]
    validations: list[dict[str, Any]]
    accepted: list[dict[str, Any]]
    memories: list[dict[str, Any]]
    saved_count: int
    saved_ids: list[str]


class MemoryAgent(BaseAgent):
    agent_id = "memory"
    description = "检索、提取、验证并维护用户长期记忆；敏感信息由确定性规则拦截。"
    capabilities = frozenset(
        {"memory_retrieval", "memory_extraction", "memory_validation", "memory_update"}
    )
    allowed_tools = frozenset({"memory_store"})

    async def execute(
        self,
        task: AgentTask,
        context: AgentExecutionContext,
    ) -> AgentResult:
        operation = str(task.context.get("operation", "retrieve"))
        if operation not in {"retrieve", "maintain"}:
            return AgentResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                status=ResultStatus.FAILED,
                error=f"Unsupported memory operation: {operation}",
            )

        started_at = perf_counter()
        workflow = ["retrieve"] if operation == "retrieve" else ["extract", "validate", "update"]
        await context.emit(
            "agent_started",
            self.agent_id,
            {
                "task_id": str(task.task_id),
                "operation": operation,
                "workflow": workflow,
                "title": (
                    "Memory Agent 开始检索长期记忆"
                    if operation == "retrieve"
                    else "Memory Agent 开始维护长期记忆"
                ),
                "summary": (
                    "从用户记忆库中筛选与当前请求相关的稳定信息"
                    if operation == "retrieve"
                    else "从本轮用户表达中提取候选，并执行安全校验和去重更新"
                ),
            },
        )
        graph = self._build_graph(task, context)
        final_state: dict[str, Any] = {}
        async for update in graph.astream(
            {
                "operation": operation,
                "query": task.objective,
                "user_input": task.objective,
                "candidates": [],
                "validations": [],
                "accepted": [],
                "memories": [],
                "saved_count": 0,
                "saved_ids": [],
            },
            stream_mode="updates",
        ):
            for node_update in update.values():
                final_state.update(node_update)

        if operation == "retrieve":
            memories = final_state.get("memories", [])
            output = {"operation": operation, "memories": memories}
            confidence = 0.9 if memories else 0.7
            summary = f"检索到 {len(memories)} 条相关长期记忆"
            metrics = {"memory_count": len(memories)}
        else:
            output = {
                "operation": operation,
                "candidate_count": len(final_state.get("candidates", [])),
                "saved_count": int(final_state.get("saved_count", 0)),
                "validations": final_state.get("validations", []),
                "saved_ids": final_state.get("saved_ids", []),
            }
            confidence = 0.95
            summary = (
                f"识别 {output['candidate_count']} 条候选，"
                f"通过校验并保存 {output['saved_count']} 条"
            )
            metrics = {
                "candidate_count": output["candidate_count"],
                "saved_count": output["saved_count"],
            }

        await context.emit(
            "agent_completed",
            self.agent_id,
            {
                "task_id": str(task.task_id),
                "operation": operation,
                "status": "completed",
                "duration_ms": round((perf_counter() - started_at) * 1000),
                "title": "Memory Agent 执行完成",
                "summary": summary,
                "metrics": metrics,
            },
        )
        return AgentResult(
            task_id=task.task_id,
            agent_id=self.agent_id,
            status=ResultStatus.COMPLETED,
            output=output,
            confidence=confidence,
            metrics={"operation": operation, **metrics},
        )

    def _build_graph(self, task: AgentTask, context: AgentExecutionContext):
        stage_started_at = perf_counter()

        async def emit_progress(
            node: str,
            title: str,
            summary: str,
            metrics: dict[str, Any],
        ) -> None:
            nonlocal stage_started_at
            now = perf_counter()
            await context.emit(
                "agent_progress",
                self.agent_id,
                {
                    "task_id": str(task.task_id),
                    "node": node,
                    "title": title,
                    "summary": summary,
                    "duration_ms": round((now - stage_started_at) * 1000),
                    "metrics": metrics,
                },
            )
            stage_started_at = now

        async def retrieve(state: MemoryState) -> dict[str, Any]:
            records = await retrieve_memories(
                context.session,
                user_id=context.run.user_id,
                query=state["query"],
            )
            memories = [
                {
                    "id": str(item.id),
                    "type": item.memory_type,
                    "content": item.content,
                    "confidence": item.confidence,
                }
                for item in records
            ]
            await emit_progress(
                "memory_retrieve",
                "检索长期记忆",
                "按当前请求与记忆内容的相关性筛选已启用记忆",
                {
                    "memory_count": len(memories),
                    "memory_types": len({item["type"] for item in memories}),
                },
            )
            return {"memories": memories}

        async def extract(state: MemoryState) -> dict[str, Any]:
            candidates = extract_candidates(state["user_input"])
            serialized = [
                {
                    "memory_type": item.memory_type,
                    "content": item.content,
                    "confidence": item.confidence,
                }
                for item in candidates
            ]
            await emit_progress(
                "memory_extract",
                "提取候选记忆",
                "在本地识别用户画像、稳定偏好、项目事实和长期指令",
                {"candidate_count": len(serialized)},
            )
            return {"candidates": serialized}

        async def validate(state: MemoryState) -> dict[str, Any]:
            validations: list[dict[str, Any]] = []
            accepted: list[dict[str, Any]] = []
            for item in state.get("candidates", []):
                candidate = MemoryCandidate(**item)
                should_save, reason = validate_candidate(candidate)
                validations.append(
                    {**item, "should_save": should_save, "reason": reason}
                )
                if should_save:
                    accepted.append(item)
            await emit_progress(
                "memory_validate",
                "验证候选记忆",
                "过滤敏感信息、短期事实、任务请求和低置信度内容",
                {
                    "candidate_count": len(validations),
                    "accepted_count": len(accepted),
                    "rejected_count": len(validations) - len(accepted),
                },
            )
            return {"validations": validations, "accepted": accepted}

        async def update(state: MemoryState) -> dict[str, Any]:
            accepted = [MemoryCandidate(**item) for item in state.get("accepted", [])]
            result = await persist_memory_candidates(
                context.session,
                user_id=context.run.user_id,
                candidates=accepted,
                source_conversation_id=self._uuid_or_none(
                    task.context.get("source_conversation_id")
                ),
                source_message_id=self._uuid_or_none(
                    task.context.get("source_message_id")
                ),
            )
            await emit_progress(
                "memory_update",
                "更新长期记忆",
                "按内容指纹去重，并新增或更新通过校验的记忆",
                {"saved_count": result["saved_count"]},
            )
            return {
                "saved_count": result["saved_count"],
                "saved_ids": result["saved_ids"],
            }

        def route(state: MemoryState) -> str:
            return "retrieve" if state["operation"] == "retrieve" else "extract"

        builder = StateGraph(MemoryState)
        builder.add_node("retrieve", retrieve)
        builder.add_node("extract", extract)
        builder.add_node("validate", validate)
        builder.add_node("update", update)
        builder.add_conditional_edges(
            START,
            route,
            {"retrieve": "retrieve", "extract": "extract"},
        )
        builder.add_edge("retrieve", END)
        builder.add_edge("extract", "validate")
        builder.add_edge("validate", "update")
        builder.add_edge("update", END)
        return builder.compile()

    @staticmethod
    def _uuid_or_none(value: Any) -> UUID | None:
        if value in {None, ""}:
            return None
        return UUID(str(value))
