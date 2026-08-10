from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from time import perf_counter
from typing import Any
from uuid import UUID

from arq import create_pool
from arq.connections import RedisSettings
from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from pmaa_web.agentic_rag.graph import build_agentic_rag_graph
from pmaa_web.agents import (
    AgentExecutionContext,
    AgentRegistry,
    AgentResult,
    AgentRuntime,
    AgentTask,
    Blackboard,
    CalendarAgent,
    DailyBriefAgent,
    EmailAgent,
    FunctionAgent,
    MemoryAgent,
    MonitorAgent,
    ResultStatus,
    SynthesisAgent,
)
from pmaa_web.agents.llm import generate_direct_answer
from pmaa_web.agents.supervisor import Supervisor
from pmaa_web.agents.web_research import WebResearchAgent
from pmaa_web.config import get_settings
from pmaa_web.conversation_service import append_conversation_message
from pmaa_web.event_bus import RedisEventBus
from pmaa_web.knowledge.providers import generate_grounded_answer
from pmaa_web.knowledge.retrieval import retrieve_evidence
from pmaa_web.models import AgentRun, Conversation, ConversationMessage, RunEvent

_background_tasks: set[asyncio.Task[None]] = set()


class RunCancelled(RuntimeError):
    pass

_STAGE_COPY: dict[str, tuple[str, str]] = {
    "analyze": ("理解问题", "规范化用户问题并确定知识检索目标"),
    "retrieve": ("检索知识库", "执行 BM25 与向量混合检索并合并候选证据"),
    "grade": ("评估证据", "检查证据数量、相关度与回答覆盖度"),
    "expand": ("补充检索", "扩展查询词后再次检索不足的证据"),
    "synthesize": ("生成回答", "基于通过校验的证据生成带引用回答"),
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def ensure_run_active(session: AsyncSession, run: AgentRun) -> None:
    await session.refresh(run, attribute_names=["status", "cancel_requested_at"])
    if run.status == "cancelled" or run.cancel_requested_at is not None:
        raise RunCancelled("任务已由用户取消")


async def append_event(
    session: AsyncSession,
    run: AgentRun,
    event_type: str,
    *,
    agent_id: str = "system",
    payload: dict[str, Any] | None = None,
) -> RunEvent:
    next_sequence = await session.scalar(
        update(AgentRun)
        .where(AgentRun.id == run.id)
        .values(next_event_sequence=AgentRun.next_event_sequence + 1)
        .returning(AgentRun.next_event_sequence)
        .execution_options(synchronize_session=False)
    )
    if next_sequence is None:
        raise LookupError(f"Run {run.id} not found")

    # The Core update bypasses ORM synchronization; keep the local model current.
    set_committed_value(run, "next_event_sequence", next_sequence)
    event = RunEvent(
        run_id=run.id,
        sequence=next_sequence - 1,
        event_type=event_type,
        agent_id=agent_id,
        payload=payload or {},
    )
    session.add(event)
    await session.commit()

    settings = get_settings()
    if settings.app_env == "test":
        return event
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        async with asyncio.timeout(settings.redis_publish_timeout_seconds):
            await RedisEventBus(redis).publish(
                run.id,
                sequence=event.sequence,
                event_type=event.event_type,
                agent_id=event.agent_id,
                payload=event.payload,
            )
    except Exception:
        # PostgreSQL remains the replayable source of truth.
        pass
    finally:
        await redis.aclose()
    return event


async def _execute_agentic_rag(
    session: AsyncSession,
    run: AgentRun,
) -> dict[str, Any]:
    async def retriever(query: str) -> list[dict[str, Any]]:
        return await retrieve_evidence(session, query, user_id=run.user_id)

    graph = build_agentic_rag_graph(retriever, generate_grounded_answer)
    workflow_started_at = perf_counter()
    await append_event(
        session,
        run,
        "agent_started",
        agent_id="knowledge",
        payload={
            "objective": run.objective[:240],
            "workflow": "agentic_rag",
            "title": "Knowledge Agent 开始执行",
            "summary": "目标：检索本地知识库、评估证据并生成可追溯回答",
        },
    )

    final_state: dict[str, Any] = {}
    stage_started_at = perf_counter()
    async for update_payload in graph.astream(
        {"query": run.objective, "attempt": 0, "max_attempts": 2},
        stream_mode="updates",
    ):
        for node_name, node_update in update_payload.items():
            final_state.update(node_update)
            now = perf_counter()
            title, summary = _STAGE_COPY.get(
                node_name,
                ("执行工作流节点", "Knowledge Agent 正在推进当前任务"),
            )
            metrics: dict[str, Any] = {}
            event_payload: dict[str, Any] = {
                "node": node_name,
                "title": title,
                "summary": summary,
                "duration_ms": round((now - stage_started_at) * 1000),
            }
            stage_started_at = now
            if node_name == "analyze":
                metrics["query"] = str(node_update.get("rewritten_query", ""))[:160]
            if node_name == "retrieve":
                evidence = node_update.get("evidence", [])
                metrics["evidence_count"] = len(evidence)
                metrics["document_count"] = len(
                    {item.get("document_id") for item in evidence if item.get("document_id")}
                )
                metrics["top_score"] = round(
                    max((float(item.get("score", 0)) for item in evidence), default=0),
                    4,
                )
            elif node_name == "grade":
                confidence = float(node_update.get("confidence", 0))
                metrics["confidence"] = round(confidence, 4)
                metrics["decision"] = "证据充分，进入回答生成" if confidence >= 0.52 else "证据不足，准备补充检索"
            elif node_name == "expand":
                metrics["attempt"] = node_update.get("attempt", 0)
                metrics["query"] = str(node_update.get("rewritten_query", ""))[:160]
            elif node_name == "synthesize":
                answer = str(node_update.get("answer", ""))
                metrics["answer_length"] = len(answer)
                metrics["citation_count"] = answer.count("[S")
            event_payload["metrics"] = metrics
            await append_event(
                session,
                run,
                "agent_progress",
                agent_id="knowledge",
                payload=event_payload,
            )

    evidence = final_state.get("evidence", [])
    result = {
        "answer": final_state.get("answer", ""),
        "evidence": evidence,
        "confidence": final_state.get("confidence", 0),
    }
    await append_event(
        session,
        run,
        "agent_completed",
        agent_id="knowledge",
        payload={
            "status": "completed",
            "evidence_count": len(evidence),
            "confidence": result["confidence"],
            "answer_length": len(str(result["answer"])),
            "duration_ms": round((perf_counter() - workflow_started_at) * 1000),
            "title": "Knowledge Agent 执行完成",
            "summary": "知识检索、证据校验和回答生成已完成",
        },
    )
    return result


def _build_agent_registry() -> AgentRegistry:
    registry = AgentRegistry()

    async def execute_knowledge(task, context: AgentExecutionContext) -> AgentResult:
        payload = await _execute_agentic_rag(context.session, context.run)
        return AgentResult(
            task_id=task.task_id,
            agent_id="knowledge",
            status=ResultStatus.COMPLETED,
            output={"answer": payload.get("answer", "")},
            evidence=payload.get("evidence", []),
            confidence=float(payload.get("confidence", 0)),
            metrics={"workflow": "agentic_rag"},
        )

    registry.register(
        FunctionAgent(
            agent_id="knowledge",
            description="检索用户本地知识库，评估证据并生成可追溯回答。",
            capabilities={"local_knowledge_query", "agentic_rag", "citation_grounding"},
            allowed_tools={"hybrid_retrieval", "vector_search", "bm25"},
            handler=execute_knowledge,
        )
    )
    registry.register(WebResearchAgent())
    registry.register(MemoryAgent())
    registry.register(SynthesisAgent())
    registry.register(EmailAgent())
    registry.register(CalendarAgent())
    registry.register(DailyBriefAgent())
    registry.register(MonitorAgent())
    return registry


async def _execute_supervised(
    session: AsyncSession,
    run: AgentRun,
    registry: AgentRegistry,
    blackboard: Blackboard,
) -> dict[str, Any]:
    supervisor = Supervisor(registry)
    decision = await supervisor.decide(run)
    await append_event(
        session,
        run,
        "supervisor_decision",
        agent_id="supervisor",
        payload={
            "intent": decision.intent,
            "mode": decision.mode,
            "assigned_agents": decision.assigned_agents,
            "confidence": decision.confidence,
            "reason": decision.reason,
            "title": "Supervisor 完成路由决策",
            "summary": decision.reason,
            "available_agents": [item["agent_id"] for item in registry.catalog()],
        },
    )

    if decision.mode == "direct_answer":
        answer = await generate_direct_answer(run.objective)
        return {
            "answer": answer,
            "evidence": [],
            "confidence": decision.confidence,
            "orchestration": {
                "mode": decision.mode,
                "intent": decision.intent,
                "assigned_agents": [],
            },
        }

    async def emit(event_type: str, agent_id: str, payload: dict[str, Any]) -> None:
        await append_event(
            session,
            run,
            event_type,
            agent_id=agent_id,
            payload=payload,
        )

    context = AgentExecutionContext(
        session=session,
        run=run,
        blackboard=blackboard,
        emit=emit,
    )
    tasks = supervisor.build_tasks(run, decision)
    runtime = AgentRuntime(
        registry,
        max_concurrency=get_settings().agent_runtime_max_concurrency,
    )
    results = await runtime.execute(tasks, context)
    successful = [
        result
        for result in results
        if result.status in {ResultStatus.COMPLETED, ResultStatus.PARTIAL}
    ]
    if not successful:
        errors = "; ".join(result.error for result in results if result.error)
        raise RuntimeError(errors or "All delegated agents failed")

    synthesis_result = next(
        (result for result in successful if result.agent_id == "synthesis"),
        None,
    )
    answer = "\n\n".join(
        str(result.output.get("answer", ""))
        for result in ([synthesis_result] if synthesis_result else successful)
        if result is not None
        if result.output.get("answer")
    )
    evidence: list[dict[str, Any]] = []
    for result in ([synthesis_result] if synthesis_result else successful):
        if result is None:
            continue
        evidence.extend(result.evidence)
    agent_outputs = {result.agent_id: result.output for result in successful}
    snapshot = await blackboard.snapshot()
    return {
        "answer": answer,
        "evidence": evidence,
        "confidence": round(
            sum(result.confidence for result in successful) / len(successful),
            4,
        ),
        "agent_outputs": agent_outputs,
        "orchestration": {
            "mode": decision.mode,
            "intent": decision.intent,
            "assigned_agents": decision.assigned_agents,
            "task_count": snapshot["task_count"],
            "message_count": snapshot["message_count"],
            "result_count": snapshot["result_count"],
        },
    }


async def _execute_memory_operation(
    session: AsyncSession,
    run: AgentRun,
    registry: AgentRegistry,
    blackboard: Blackboard,
    *,
    operation: str,
    source_message_id: UUID | None = None,
) -> AgentResult:
    async def emit(event_type: str, agent_id: str, payload: dict[str, Any]) -> None:
        await append_event(
            session,
            run,
            event_type,
            agent_id=agent_id,
            payload=payload,
        )

    task = AgentTask(
        run_id=run.id,
        trace_id=run.id,
        assigned_agent="memory",
        objective=run.objective,
        context={
            "operation": operation,
            "source_conversation_id": (
                str(run.conversation_id) if run.conversation_id else None
            ),
            "source_message_id": str(source_message_id) if source_message_id else None,
        },
        max_attempts=1,
        timeout_seconds=60,
    )
    context = AgentExecutionContext(
        session=session,
        run=run,
        blackboard=blackboard,
        emit=emit,
    )
    runtime = AgentRuntime(registry, max_concurrency=1)
    return (await runtime.execute([task], context))[0]


async def execute_run(run_id: UUID) -> None:
    from pmaa_web.database import SessionFactory

    async with SessionFactory() as session:
        run = await session.get(AgentRun, run_id)
        if run is None or run.status not in {"queued", "running"}:
            return

        run.status = "running"
        run.attempt_count += 1
        run.next_retry_at = None
        run.started_at = utc_now()
        await append_event(
            session,
            run,
            "run_started",
            payload={"objective": run.objective, "run_type": run.run_type},
        )

        try:
            registry = _build_agent_registry()
            blackboard = Blackboard(trace_id=run.id)
            memory_result = await _execute_memory_operation(
                session,
                run,
                registry,
                blackboard,
                operation="retrieve",
            )
            await ensure_run_active(session, run)
            memories = list(memory_result.output.get("memories", []))
            run.input_payload = {
                **(run.input_payload or {}),
                "retrieved_memories": memories,
            }
            result = await _execute_supervised(
                session,
                run,
                registry,
                blackboard,
            )
            await ensure_run_active(session, run)

            if run.conversation_id:
                conversation = await session.get(Conversation, run.conversation_id)
                if conversation:
                    await append_conversation_message(
                        session,
                        conversation,
                        role="assistant",
                        content=str(result.get("answer", "任务已完成。")),
                        run_id=run.id,
                        metadata={
                            "status": "completed",
                            "confidence": result.get("confidence", 0),
                            "evidence_count": len(result.get("evidence", [])),
                        },
                    )
            await _maintain_run_memory(
                session,
                run,
                registry,
                blackboard,
            )
            await ensure_run_active(session, run)
            run.status = "completed"
            run.result_payload = result
            run.finished_at = utc_now()
            await append_event(
                session,
                run,
                "run_completed",
                payload={
                    "status": "completed",
                    "evidence_count": len(result.get("evidence", [])),
                    "confidence": result.get("confidence", 0),
                    "answer_length": len(str(result.get("answer", ""))),
                    "title": "任务完成",
                    "summary": "Supervisor 已收到子 Agent 结果并完成聚合",
                },
            )
        except RunCancelled:
            await session.rollback()
            run = await session.get(AgentRun, run_id)
            if run is None:
                return
            if run.status != "cancelled":
                run.status = "cancelled"
                run.cancel_requested_at = run.cancel_requested_at or utc_now()
                run.finished_at = utc_now()
                await append_event(
                    session,
                    run,
                    "run_cancelled",
                    payload={"title": "任务已取消", "summary": "执行链已停止"},
                )
        except Exception as exc:
            await session.rollback()
            run = await session.get(AgentRun, run_id)
            if run is None:
                return
            run.status = "failed"
            run.error = str(exc)
            run.finished_at = utc_now()
            await append_event(
                session,
                run,
                "run_failed",
                payload={"error": str(exc)},
            )
            if run.conversation_id:
                conversation = await session.get(Conversation, run.conversation_id)
                if conversation:
                    await append_conversation_message(
                        session,
                        conversation,
                        role="assistant",
                        content=f"任务执行失败：{exc}",
                        run_id=run.id,
                        metadata={"status": "failed"},
                    )


async def _maintain_run_memory(
    session: AsyncSession,
    run: AgentRun,
    registry: AgentRegistry,
    blackboard: Blackboard,
) -> None:
    if not run.conversation_id:
        return
    try:
        user_message = await session.scalar(
            select(ConversationMessage).where(
                ConversationMessage.run_id == run.id,
                ConversationMessage.role == "user",
            )
        )
        result = await _execute_memory_operation(
            session,
            run,
            registry,
            blackboard,
            operation="maintain",
            source_message_id=user_message.id if user_message else None,
        )
        if result.status == ResultStatus.FAILED:
            raise RuntimeError(result.error or "Memory maintenance failed")
    except Exception as exc:
        await session.rollback()
        await append_event(
            session,
            run,
            "agent_completed",
            agent_id="memory",
            payload={
                "title": "Memory Agent 跳过本轮写入",
                "summary": "记忆维护失败不会影响主任务回答",
                "saved_count": 0,
                "error": str(exc),
            },
        )


async def dispatch_run(run_id: UUID) -> None:
    settings = get_settings()
    if settings.task_execution_mode == "arq":
        pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        try:
            await pool.enqueue_job("run_agent_job", str(run_id), _job_id=str(run_id))
        finally:
            await pool.aclose()
        return
    task = asyncio.create_task(execute_run(run_id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
