from __future__ import annotations

import asyncio
from typing import Any, cast
from uuid import uuid4

import pytest
from pmaa_web.agents import (
    AgentExecutionContext,
    AgentMessage,
    AgentResult,
    AgentRuntime,
    AgentTask,
    Blackboard,
    CalendarAgent,
    EmailAgent,
    FunctionAgent,
    MemoryAgent,
    MessageType,
    MonitorAgent,
    ResultStatus,
)
from pmaa_web.agents.registry import AgentRegistry
from pmaa_web.agents.supervisor import Supervisor
from pmaa_web.agents.web_research import WebResearchAgent
from pmaa_web.database import SessionFactory
from pmaa_web.email_service import MailMessage
from pmaa_web.models import (
    AgentRun,
    CalendarAction,
    CalendarEvent,
    MonitorNotification,
    MonitorResult,
    MonitorRule,
    UserMemory,
)
from sqlalchemy import select


@pytest.mark.asyncio
async def test_blackboard_rejects_direct_child_agent_messages() -> None:
    trace_id = uuid4()
    blackboard = Blackboard(trace_id)
    with pytest.raises(ValueError, match="only through Supervisor"):
        await blackboard.post_message(
            AgentMessage(
                trace_id=trace_id,
                sender="knowledge",
                receiver="web_research",
                message_type=MessageType.STATUS_UPDATE,
            )
        )


@pytest.mark.asyncio
async def test_runtime_runs_independent_tasks_concurrently_and_resolves_dependencies() -> None:
    trace_id = uuid4()
    run_id = uuid4()
    active = 0
    peak_active = 0
    lock = asyncio.Lock()

    async def handler(task, context):
        nonlocal active, peak_active
        async with lock:
            active += 1
            peak_active = max(peak_active, active)
        await asyncio.sleep(0.03)
        async with lock:
            active -= 1
        return AgentResult(
            task_id=task.task_id,
            agent_id=task.assigned_agent,
            status=ResultStatus.COMPLETED,
            output={"objective": task.objective, "dependencies": task.context["dependency_results"]},
            confidence=0.9,
        )

    registry = AgentRegistry()
    for agent_id in ("alpha", "beta"):
        registry.register(
            FunctionAgent(
                agent_id=agent_id,
                description=agent_id,
                capabilities={agent_id},
                allowed_tools=set(),
                handler=handler,
            )
        )
    first = AgentTask(
        run_id=run_id,
        trace_id=trace_id,
        assigned_agent="alpha",
        objective="first",
    )
    second = AgentTask(
        run_id=run_id,
        trace_id=trace_id,
        assigned_agent="beta",
        objective="second",
    )
    dependent = AgentTask(
        run_id=run_id,
        trace_id=trace_id,
        assigned_agent="alpha",
        objective="dependent",
        dependencies=[first.task_id, second.task_id],
    )
    events: list[tuple[str, str, dict[str, Any]]] = []

    async def emit(event_type: str, agent_id: str, payload: dict[str, Any]) -> None:
        events.append((event_type, agent_id, payload))

    context = AgentExecutionContext(
        session=cast(Any, None),
        run=cast(Any, None),
        blackboard=Blackboard(trace_id),
        emit=emit,
    )
    results = await AgentRuntime(registry, max_concurrency=2).execute(
        [first, second, dependent],
        context,
    )

    assert peak_active == 2
    assert all(result.status == ResultStatus.COMPLETED for result in results)
    dependent_result = next(result for result in results if result.task_id == dependent.task_id)
    assert set(dependent_result.output["dependencies"]) == {
        str(first.task_id),
        str(second.task_id),
    }
    snapshot = await context.blackboard.snapshot()
    assert snapshot["task_count"] == 3
    assert snapshot["message_count"] == 6
    assert [event[0] for event in events].count("agent_message") == 6


@pytest.mark.asyncio
async def test_supervisor_explicit_routes_are_deterministic() -> None:
    registry = AgentRegistry()
    for agent_id in (
        "knowledge",
        "web_research",
        "email",
        "calendar",
        "daily_brief",
        "information_monitor",
    ):
        registry.register(
            FunctionAgent(
                agent_id=agent_id,
                description=agent_id,
                capabilities={agent_id},
                allowed_tools=set(),
                handler=cast(Any, None),
            )
        )
    supervisor = Supervisor(registry)
    research = AgentRun(
        id=uuid4(),
        user_id=uuid4(),
        objective="today's AI news",
        run_type="research",
    )
    knowledge = AgentRun(
        id=uuid4(),
        user_id=uuid4(),
        objective="answer from my document",
        run_type="agentic_rag",
    )
    email = AgentRun(
        id=uuid4(),
        user_id=uuid4(),
        objective="list my unread emails",
        run_type="email",
    )
    calendar = AgentRun(
        id=uuid4(),
        user_id=uuid4(),
        objective="show my calendar",
        run_type="calendar",
    )
    daily_brief = AgentRun(
        id=uuid4(),
        user_id=uuid4(),
        objective="生成今天的个人简报",
        run_type="daily_brief",
    )
    monitor = AgentRun(
        id=uuid4(),
        user_id=uuid4(),
        objective="检查关注项目是否有重要更新",
        run_type="monitor",
    )

    assert (await supervisor.decide(research)).assigned_agents == ["web_research"]
    assert (await supervisor.decide(knowledge)).assigned_agents == ["knowledge"]
    assert (await supervisor.decide(email)).assigned_agents == ["email"]
    assert (await supervisor.decide(calendar)).assigned_agents == ["calendar"]
    assert (await supervisor.decide(daily_brief)).assigned_agents == ["daily_brief"]
    assert (await supervisor.decide(monitor)).assigned_agents == [
        "information_monitor"
    ]


@pytest.mark.asyncio
async def test_web_research_agent_runs_its_own_evidence_workflow() -> None:
    async def fake_search(query: str, max_results: int | None):
        index = abs(hash(query)) % 10000
        return [
            {
                "title": f"Source {index}",
                "url": f"https://source-{index}.example.com/report",
                "content": f"Evidence for {query}",
                "score": 0.92,
                "query": query,
                "source_type": "web",
            },
            {
                "title": f"Official {index}",
                "url": f"https://official-{index}.example.org/news",
                "content": f"Official evidence for {query}",
                "score": 0.86,
                "query": query,
                "source_type": "web",
            },
        ]

    async def fake_answer(objective: str, evidence: list[dict[str, Any]]) -> str:
        return f"{objective}: verified [{evidence[0]['citation_id']}]"

    trace_id = uuid4()
    task = AgentTask(
        run_id=trace_id,
        trace_id=trace_id,
        assigned_agent="web_research",
        objective="AI agent market update",
    )
    events: list[dict[str, Any]] = []

    async def emit(event_type: str, agent_id: str, payload: dict[str, Any]) -> None:
        events.append({"event_type": event_type, "agent_id": agent_id, **payload})

    context = AgentExecutionContext(
        session=cast(Any, None),
        run=cast(Any, None),
        blackboard=Blackboard(trace_id),
        emit=emit,
    )
    result = await WebResearchAgent(
        searcher=fake_search,
        answer_generator=fake_answer,
    ).execute(task, context)

    assert result.status == ResultStatus.COMPLETED
    assert len(result.evidence) >= 4
    assert result.output["answer"].endswith("[S1]")
    nodes = [event.get("node") for event in events if event["event_type"] == "agent_progress"]
    assert nodes == [
        "research_analyze",
        "research_search",
        "research_evaluate",
        "research_synthesize",
    ]


@pytest.mark.asyncio
async def test_memory_agent_runs_retrieve_extract_validate_update_workflows() -> None:
    trace_id = uuid4()
    user_id = uuid4()
    events: list[dict[str, Any]] = []

    async def emit(event_type: str, agent_id: str, payload: dict[str, Any]) -> None:
        events.append({"event_type": event_type, "agent_id": agent_id, **payload})

    async with SessionFactory() as session:
        run = AgentRun(
            id=trace_id,
            user_id=user_id,
            objective="我叫小林，我喜欢跑步和旅行，请记住",
            run_type="assistant",
        )
        session.add(run)
        await session.commit()
        context = AgentExecutionContext(
            session=session,
            run=run,
            blackboard=Blackboard(trace_id),
            emit=emit,
        )
        agent = MemoryAgent()
        maintain_task = AgentTask(
            run_id=trace_id,
            trace_id=trace_id,
            assigned_agent="memory",
            objective=run.objective,
            context={"operation": "maintain"},
        )
        maintained = await agent.execute(maintain_task, context)

        assert maintained.status == ResultStatus.COMPLETED
        assert maintained.output["candidate_count"] == 2
        assert maintained.output["saved_count"] == 2
        assert len(list(await session.scalars(select(UserMemory)))) == 2

        retrieve_task = AgentTask(
            run_id=trace_id,
            trace_id=trace_id,
            assigned_agent="memory",
            objective="根据我的偏好推荐运动旅行计划",
            context={"operation": "retrieve"},
        )
        retrieved = await agent.execute(retrieve_task, context)

    assert retrieved.status == ResultStatus.COMPLETED
    assert len(retrieved.output["memories"]) == 2
    nodes = [event.get("node") for event in events if event["event_type"] == "agent_progress"]
    assert nodes == [
        "memory_extract",
        "memory_validate",
        "memory_update",
        "memory_retrieve",
    ]


@pytest.mark.asyncio
async def test_email_agent_triages_messages_and_never_sends() -> None:
    class FakeBackend:
        configured = True

        def __init__(self) -> None:
            self.send_calls = 0

        def list_recent(self, *, limit: int, unread_only: bool):
            del limit, unread_only
            return [
                MailMessage(
                    uid="1",
                    from_address="hr@example.com",
                    subject="面试时间确认",
                    sent_at="",
                    snippet="请尽快确认明天下午三点",
                    unread=True,
                ),
                MailMessage(
                    uid="2",
                    from_address="news@example.com",
                    subject="每周资讯",
                    sent_at="",
                    snippet="本周摘要",
                    unread=False,
                ),
            ]

        def get_message(self, uid: str, *, mark_read: bool = False):
            del uid, mark_read
            return None

        def send(self, **kwargs):
            del kwargs
            self.send_calls += 1

    backend = FakeBackend()
    trace_id = uuid4()
    events: list[dict[str, Any]] = []

    async def emit(event_type: str, agent_id: str, payload: dict[str, Any]) -> None:
        events.append({"event_type": event_type, "agent_id": agent_id, **payload})

    task = AgentTask(
        run_id=trace_id,
        trace_id=trace_id,
        assigned_agent="email",
        objective="查看最近邮件并告诉我哪些重要",
        context={"request_payload": {"email_operation": "list_recent"}},
    )
    context = AgentExecutionContext(
        session=cast(Any, None),
        run=cast(Any, None),
        blackboard=Blackboard(trace_id),
        emit=emit,
    )
    result = await EmailAgent(backend_factory=lambda: cast(Any, backend)).execute(
        task,
        context,
    )

    assert result.status == ResultStatus.COMPLETED
    assert result.output["messages"][0]["uid"] == "1"
    assert result.output["messages"][0]["priority"] >= 0.7
    assert result.output["requires_confirmation"] is False
    assert backend.send_calls == 0
    assert [
        event.get("node") for event in events if event["event_type"] == "agent_progress"
    ] == ["email_analyze", "email_fetch", "email_triage", "email_compose"]


@pytest.mark.asyncio
async def test_calendar_agent_prepares_action_without_executing_it() -> None:
    trace_id = uuid4()
    user_id = uuid4()
    events: list[dict[str, Any]] = []

    async def emit(event_type: str, agent_id: str, payload: dict[str, Any]) -> None:
        events.append({"event_type": event_type, "agent_id": agent_id, **payload})

    async with SessionFactory() as session:
        run = AgentRun(
            id=trace_id,
            user_id=user_id,
            objective="安排项目评审",
            run_type="calendar",
        )
        session.add(run)
        await session.commit()
        task = AgentTask(
            run_id=trace_id,
            trace_id=trace_id,
            assigned_agent="calendar",
            objective=run.objective,
            context={
                "request_payload": {
                    "calendar_operation": "prepare_action",
                    "calendar_action": "event.create",
                    "action_payload": {
                        "title": "项目评审",
                        "start_at": "2027-08-08T14:00:00+08:00",
                        "end_at": "2027-08-08T15:00:00+08:00",
                    },
                }
            },
        )
        context = AgentExecutionContext(
            session=session,
            run=run,
            blackboard=Blackboard(trace_id),
            emit=emit,
        )
        result = await CalendarAgent().execute(task, context)
        pending = list(await session.scalars(select(CalendarAction)))
        actual_events = list(await session.scalars(select(CalendarEvent)))

    assert result.status == ResultStatus.COMPLETED
    assert result.output["requires_confirmation"] is True
    assert result.output["pending_action"]["status"] == "pending"
    assert len(pending) == 1
    assert actual_events == []
    assert [
        event.get("node") for event in events if event["event_type"] == "agent_progress"
    ] == [
        "calendar_analyze",
        "calendar_retrieve",
        "calendar_plan",
        "calendar_summarize",
    ]


@pytest.mark.asyncio
async def test_monitor_agent_builds_baseline_then_notifies_only_new_items() -> None:
    trace_id = uuid4()
    user_id = uuid4()
    calls = 0
    events: list[dict[str, Any]] = []

    async def fake_collect(rule: MonitorRule) -> list[dict[str, Any]]:
        nonlocal calls
        calls += 1
        items = [
            {
                "title": f"{rule.name} 基线项目",
                "url": "https://example.com/baseline",
                "summary": "初始项目",
                "source": "web",
            }
        ]
        if calls > 1:
            items.append(
                {
                    "title": "新增重要更新",
                    "url": "https://example.com/new-release",
                    "summary": "第二轮出现的新内容",
                    "source": "web",
                }
            )
        return items

    async def emit(event_type: str, agent_id: str, payload: dict[str, Any]) -> None:
        events.append({"event_type": event_type, "agent_id": agent_id, **payload})

    async with SessionFactory() as session:
        rule = MonitorRule(
            user_id=user_id,
            name="AI 项目更新",
            target_type="news",
            query="AI agent release",
            interval_minutes=60,
        )
        first_run = AgentRun(
            id=trace_id,
            user_id=user_id,
            objective="建立监控基线",
            run_type="monitor",
        )
        session.add_all([rule, first_run])
        await session.commit()
        await session.refresh(rule)

        first_task = AgentTask(
            run_id=first_run.id,
            trace_id=first_run.id,
            assigned_agent="information_monitor",
            objective=first_run.objective,
            context={"request_payload": {"monitor_rule_id": str(rule.id)}},
        )
        first_context = AgentExecutionContext(
            session=session,
            run=first_run,
            blackboard=Blackboard(first_run.id),
            emit=emit,
        )
        agent = MonitorAgent(collector=fake_collect)
        first_result = await agent.execute(first_task, first_context)

        assert first_result.status == ResultStatus.COMPLETED
        assert first_result.output["baseline_created"] is True
        assert first_result.output["new_items"] == []
        assert list(await session.scalars(select(MonitorNotification))) == []

        second_run = AgentRun(
            user_id=user_id,
            objective="检查新增变化",
            run_type="monitor",
        )
        session.add(second_run)
        await session.commit()
        second_task = AgentTask(
            run_id=second_run.id,
            trace_id=second_run.id,
            assigned_agent="information_monitor",
            objective=second_run.objective,
            context={"request_payload": {"monitor_rule_id": str(rule.id)}},
        )
        second_context = AgentExecutionContext(
            session=session,
            run=second_run,
            blackboard=Blackboard(second_run.id),
            emit=emit,
        )
        second_result = await agent.execute(second_task, second_context)
        notifications = list(await session.scalars(select(MonitorNotification)))
        monitor_results = list(
            await session.scalars(
                select(MonitorResult).order_by(MonitorResult.created_at.asc())
            )
        )

    assert second_result.status == ResultStatus.COMPLETED
    assert second_result.output["baseline_created"] is False
    assert [item["title"] for item in second_result.output["new_items"]] == [
        "新增重要更新"
    ]
    assert len(notifications) == 1
    assert notifications[0].unread is True
    assert notifications[0].payload["items"][0]["url"].endswith("new-release")
    assert len(monitor_results) == 2
    assert monitor_results[0].baseline_created is True
    assert monitor_results[0].item_count == 1
    assert monitor_results[1].change_count == 1
    assert monitor_results[1].payload["new_items"][0]["url"].endswith("new-release")
    assert [
        event.get("node")
        for event in events
        if event["event_type"] == "agent_progress"
    ] == [
        "monitor_analyze",
        "monitor_collect",
        "monitor_compare",
        "monitor_notify",
        "monitor_analyze",
        "monitor_collect",
        "monitor_compare",
        "monitor_notify",
    ]
