from __future__ import annotations

from datetime import datetime, timedelta, timezone
from time import perf_counter
from typing import Any, TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from sqlalchemy import select

from pmaa_web.agents.base import AgentExecutionContext, BaseAgent
from pmaa_web.agents.protocol import AgentResult, AgentTask, ResultStatus
from pmaa_web.calendar_service import prepare_calendar_action_record
from pmaa_web.models import CalendarEvent, TodoItem


class CalendarState(TypedDict, total=False):
    objective: str
    operation: str
    request_payload: dict[str, Any]
    events: list[dict[str, Any]]
    todos: list[dict[str, Any]]
    pending_action: dict[str, Any]
    answer: str


class CalendarAgent(BaseAgent):
    agent_id = "calendar"
    description = "查询日程与待办、检查冲突并生成需要用户确认的日历动作。"
    capabilities = frozenset(
        {"calendar_query", "todo_query", "schedule_conflict", "calendar_action_plan"}
    )
    allowed_tools = frozenset(
        {"calendar_read", "todo_read", "conflict_check", "calendar_action_prepare"}
    )

    async def execute(
        self,
        task: AgentTask,
        context: AgentExecutionContext,
    ) -> AgentResult:
        started_at = perf_counter()
        await context.emit(
            "agent_started",
            self.agent_id,
            {
                "task_id": str(task.task_id),
                "workflow": ["analyze", "retrieve", "plan", "summarize"],
                "title": "Calendar / Task Agent 开始执行",
                "summary": "读取日程与待办，检查计划可行性；任何写操作仅生成待确认动作",
            },
        )
        try:
            graph = self._build_graph(task, context)
            final_state: dict[str, Any] = {}
            async for update in graph.astream(
                {
                    "objective": task.objective,
                    "operation": "overview",
                    "request_payload": dict(task.context.get("request_payload") or {}),
                    "events": [],
                    "todos": [],
                    "pending_action": {},
                    "answer": "",
                },
                stream_mode="updates",
            ):
                for node_update in update.values():
                    final_state.update(node_update)
        except Exception as exc:
            await context.emit(
                "agent_completed",
                self.agent_id,
                {
                    "task_id": str(task.task_id),
                    "status": "failed",
                    "title": "Calendar / Task Agent 执行失败",
                    "summary": str(exc),
                },
            )
            return AgentResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                status=ResultStatus.FAILED,
                error=str(exc),
            )

        events = final_state.get("events", [])
        todos = final_state.get("todos", [])
        pending_action = final_state.get("pending_action", {})
        operation = str(final_state.get("operation", "overview"))
        await context.emit(
            "agent_completed",
            self.agent_id,
            {
                "task_id": str(task.task_id),
                "status": "completed",
                "operation": operation,
                "duration_ms": round((perf_counter() - started_at) * 1000),
                "title": "Calendar / Task Agent 执行完成",
                "summary": (
                    "已生成待确认动作，尚未修改真实日程"
                    if pending_action
                    else "已完成日程与待办查询"
                ),
                "metrics": {
                    "calendar_event_count": len(events),
                    "todo_count": len(todos),
                    "pending_action_count": 1 if pending_action else 0,
                },
            },
        )
        return AgentResult(
            task_id=task.task_id,
            agent_id=self.agent_id,
            status=ResultStatus.COMPLETED,
            output={
                "answer": str(final_state.get("answer", "")),
                "operation": operation,
                "events": events,
                "todos": todos,
                "pending_action": pending_action,
                "requires_confirmation": bool(pending_action),
            },
            confidence=0.92,
            metrics={
                "operation": operation,
                "calendar_event_count": len(events),
                "todo_count": len(todos),
                "pending_action_count": 1 if pending_action else 0,
            },
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

        async def analyze(state: CalendarState) -> dict[str, Any]:
            payload = state.get("request_payload", {})
            operation = str(payload.get("calendar_operation", "")).strip()
            if not operation:
                has_action = payload.get("calendar_action") and payload.get("action_payload")
                operation = "prepare_action" if has_action else "overview"
            if operation not in {"overview", "prepare_action"}:
                operation = "overview"
            await emit_progress(
                "calendar_analyze",
                "分析日历任务",
                "判断本轮是查询日程待办，还是生成待用户确认的变更计划",
                {"calendar_operation": operation},
            )
            return {"operation": operation}

        async def retrieve(state: CalendarState) -> dict[str, Any]:
            payload = state.get("request_payload", {})
            now = datetime.now(timezone.utc)
            start_at = self._datetime_or_default(payload.get("start_at"), now - timedelta(days=1))
            end_at = self._datetime_or_default(payload.get("end_at"), now + timedelta(days=30))
            event_records = await context.session.scalars(
                select(CalendarEvent)
                .where(
                    CalendarEvent.user_id == context.run.user_id,
                    CalendarEvent.status == "active",
                    CalendarEvent.start_at < end_at,
                    CalendarEvent.end_at > start_at,
                )
                .order_by(CalendarEvent.start_at)
            )
            todo_records = await context.session.scalars(
                select(TodoItem)
                .where(
                    TodoItem.user_id == context.run.user_id,
                    TodoItem.status.in_(["todo", "in_progress"]),
                )
                .order_by(TodoItem.due_at.is_(None), TodoItem.due_at)
                .limit(100)
            )
            events = [self._event_dict(item) for item in event_records]
            todos = [self._todo_dict(item) for item in todo_records]
            await emit_progress(
                "calendar_retrieve",
                "读取日程与待办",
                "从业务数据库读取查询窗口内的活动日程和未完成待办",
                {"calendar_event_count": len(events), "todo_count": len(todos)},
            )
            return {"events": events, "todos": todos}

        async def plan(state: CalendarState) -> dict[str, Any]:
            if state["operation"] != "prepare_action":
                await emit_progress(
                    "calendar_plan",
                    "检查是否需要变更",
                    "当前任务为只读查询，不生成写操作",
                    {"pending_action_count": 0},
                )
                return {"pending_action": {}}
            payload = state.get("request_payload", {})
            action = str(payload.get("calendar_action", ""))
            action_payload = payload.get("action_payload")
            if not action or not isinstance(action_payload, dict):
                raise ValueError("生成日历动作需要 calendar_action 和 action_payload")
            target_id = self._uuid_or_none(payload.get("target_id"))
            record = await prepare_calendar_action_record(
                context.session,
                user_id=context.run.user_id,
                action=action,
                target_id=target_id,
                payload=action_payload,
            )
            pending = {
                "id": str(record.id),
                "action": record.action,
                "target_id": str(record.target_id) if record.target_id else None,
                "payload": record.payload,
                "status": record.status,
                "has_conflict": bool(record.result_payload.get("has_conflict")),
                "conflicts": record.result_payload.get("conflicts", []),
            }
            await emit_progress(
                "calendar_plan",
                "生成待确认动作",
                "完成参数校验和时间冲突检查，仅写入 pending 动作",
                {
                    "pending_action_count": 1,
                    "conflict_count": len(pending["conflicts"]),
                },
            )
            return {"pending_action": pending}

        async def summarize(state: CalendarState) -> dict[str, Any]:
            pending = state.get("pending_action", {})
            if pending:
                conflict_copy = (
                    f"检测到 {len(pending.get('conflicts', []))} 项时间冲突。"
                    if pending.get("has_conflict")
                    else "未检测到时间冲突。"
                )
                answer = (
                    f"已生成 `{pending['action']}` 待确认动作，{conflict_copy}"
                    "当前尚未修改日程或待办，请在日历页面核对后确认执行。"
                )
            else:
                answer = (
                    f"未来查询窗口内有 {len(state.get('events', []))} 项日程，"
                    f"当前有 {len(state.get('todos', []))} 项未完成待办。"
                )
            await emit_progress(
                "calendar_summarize",
                "形成日历结果",
                "汇总日程、待办和待确认动作状态",
                {"answer_length": len(answer)},
            )
            return {"answer": answer}

        builder = StateGraph(CalendarState)
        builder.add_node("analyze", analyze)
        builder.add_node("retrieve", retrieve)
        builder.add_node("plan", plan)
        builder.add_node("summarize", summarize)
        builder.add_edge(START, "analyze")
        builder.add_edge("analyze", "retrieve")
        builder.add_edge("retrieve", "plan")
        builder.add_edge("plan", "summarize")
        builder.add_edge("summarize", END)
        return builder.compile()

    @staticmethod
    def _datetime_or_default(value: Any, default: datetime) -> datetime:
        if not value:
            return default
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("日历查询时间必须包含时区")
        return parsed

    @staticmethod
    def _uuid_or_none(value: Any) -> UUID | None:
        return UUID(str(value)) if value else None

    @staticmethod
    def _event_dict(item: CalendarEvent) -> dict[str, Any]:
        return {
            "id": str(item.id),
            "title": item.title,
            "description": item.description,
            "location": item.location,
            "start_at": item.start_at.isoformat(),
            "end_at": item.end_at.isoformat(),
            "provider": item.provider,
        }

    @staticmethod
    def _todo_dict(item: TodoItem) -> dict[str, Any]:
        return {
            "id": str(item.id),
            "title": item.title,
            "description": item.description,
            "status": item.status,
            "due_at": item.due_at.isoformat() if item.due_at else None,
            "priority": item.priority,
        }
