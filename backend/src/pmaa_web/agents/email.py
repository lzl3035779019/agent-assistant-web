from __future__ import annotations

import asyncio
from collections.abc import Callable
from time import perf_counter
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from pmaa_web.agents.base import AgentExecutionContext, BaseAgent
from pmaa_web.agents.protocol import AgentResult, AgentTask, ResultStatus
from pmaa_web.email_service import (
    QQEmailBackend,
    create_reply_draft,
    get_email_backend,
)

EmailBackendFactory = Callable[[], QQEmailBackend]


class EmailState(TypedDict, total=False):
    objective: str
    operation: str
    request_payload: dict[str, Any]
    messages: list[dict[str, Any]]
    selected_message: dict[str, Any]
    draft: dict[str, str]
    answer: str


class EmailAgent(BaseAgent):
    agent_id = "email"
    description = "读取与筛选邮件、判断优先级并生成回复草稿；不直接执行发送。"
    capabilities = frozenset(
        {"email_read", "email_triage", "email_summary", "email_reply_draft"}
    )
    allowed_tools = frozenset({"imap_read", "email_draft"})

    def __init__(self, backend_factory: EmailBackendFactory = get_email_backend) -> None:
        self._backend_factory = backend_factory

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
                "workflow": ["analyze", "fetch", "triage", "compose"],
                "title": "Email Agent 开始执行",
                "summary": "分析邮件处理目标，并在只读工具边界内读取、筛选或起草回复",
            },
        )
        try:
            backend = self._backend_factory()
            if not backend.configured:
                raise RuntimeError("邮件模块尚未配置或启用")
            graph = self._build_graph(task, context, backend)
            final_state: dict[str, Any] = {}
            async for update in graph.astream(
                {
                    "objective": task.objective,
                    "operation": "list_recent",
                    "request_payload": dict(task.context.get("request_payload") or {}),
                    "messages": [],
                    "selected_message": {},
                    "draft": {},
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
                    "title": "Email Agent 执行失败",
                    "summary": str(exc),
                },
            )
            return AgentResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                status=ResultStatus.FAILED,
                error=str(exc),
            )

        messages = final_state.get("messages", [])
        draft = final_state.get("draft", {})
        answer = str(final_state.get("answer", ""))
        operation = str(final_state.get("operation", "list_recent"))
        await context.emit(
            "agent_completed",
            self.agent_id,
            {
                "task_id": str(task.task_id),
                "status": "completed",
                "operation": operation,
                "duration_ms": round((perf_counter() - started_at) * 1000),
                "title": "Email Agent 执行完成",
                "summary": "邮件读取与分析已完成；如需发送，仍须创建动作并由用户确认",
                "metrics": {
                    "email_count": len(messages),
                    "draft_count": 1 if draft else 0,
                },
            },
        )
        return AgentResult(
            task_id=task.task_id,
            agent_id=self.agent_id,
            status=ResultStatus.COMPLETED,
            output={
                "answer": answer,
                "operation": operation,
                "messages": messages,
                "draft": draft,
                "requires_confirmation": bool(draft),
            },
            confidence=0.9,
            metrics={
                "operation": operation,
                "email_count": len(messages),
                "draft_count": 1 if draft else 0,
            },
        )

    def _build_graph(
        self,
        task: AgentTask,
        context: AgentExecutionContext,
        backend: QQEmailBackend,
    ):
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

        async def analyze(state: EmailState) -> dict[str, Any]:
            payload = state.get("request_payload", {})
            operation = str(payload.get("email_operation", "")).strip()
            if not operation:
                objective = state["objective"].lower()
                operation = (
                    "draft_reply"
                    if any(marker in objective for marker in ("回复", "回信", "草稿"))
                    else "list_recent"
                )
            if operation not in {"list_recent", "draft_reply"}:
                operation = "list_recent"
            await emit_progress(
                "email_analyze",
                "分析邮件目标",
                "确定本轮执行邮件读取筛选还是回复草稿生成",
                {"email_operation": operation},
            )
            return {"operation": operation}

        async def fetch(state: EmailState) -> dict[str, Any]:
            payload = state.get("request_payload", {})
            if state["operation"] == "draft_reply":
                uid = str(payload.get("message_uid", "")).strip()
                if not uid:
                    raise ValueError("生成回复草稿需要 message_uid")
                message = await asyncio.to_thread(backend.get_message, uid, mark_read=False)
                if message is None:
                    raise ValueError("指定邮件不存在")
                serialized = message.to_dict()
                await emit_progress(
                    "email_fetch",
                    "读取邮件线程",
                    "按 UID 读取选中邮件全文，发送状态保持不变",
                    {"email_count": 1},
                )
                return {"selected_message": serialized, "messages": [serialized]}

            limit = max(1, min(50, int(payload.get("limit", 10))))
            unread_only = bool(payload.get("unread_only", False))
            records = await asyncio.to_thread(
                backend.list_recent,
                limit=limit,
                unread_only=unread_only,
            )
            messages = [record.to_dict() for record in records]
            await emit_progress(
                "email_fetch",
                "读取收件箱",
                "通过 IMAP 只读连接获取最近邮件",
                {"email_count": len(messages), "unread_count": sum(item["unread"] for item in messages)},
            )
            return {"messages": messages}

        async def triage(state: EmailState) -> dict[str, Any]:
            ranked = sorted(
                (
                    {**message, "priority": self._priority(message)}
                    for message in state.get("messages", [])
                ),
                key=lambda item: (item["priority"], bool(item.get("unread"))),
                reverse=True,
            )
            await emit_progress(
                "email_triage",
                "筛选邮件优先级",
                "根据未读状态、主题和行动时效识别需要优先处理的邮件",
                {
                    "email_count": len(ranked),
                    "important_count": sum(item["priority"] >= 0.7 for item in ranked),
                },
            )
            return {"messages": ranked}

        async def compose(state: EmailState) -> dict[str, Any]:
            if state["operation"] == "draft_reply":
                selected = state.get("selected_message", {})
                from pmaa_web.email_service import MailMessage

                draft = create_reply_draft(MailMessage(**selected))
                answer = (
                    f"已为《{selected.get('subject', '无主题')}》生成回复草稿。"
                    "草稿尚未发送；请在邮件页面检查收件人、主题和正文后创建发送动作并确认。"
                )
                await emit_progress(
                    "email_compose",
                    "生成回复草稿",
                    "基于选中邮件生成可编辑草稿，不调用 SMTP",
                    {"draft_count": 1},
                )
                return {"draft": draft, "answer": answer}

            messages = state.get("messages", [])
            lines = [f"已读取最近 {len(messages)} 封邮件，并按处理优先级排序："]
            for index, message in enumerate(messages[:10], start=1):
                priority = "高" if message["priority"] >= 0.7 else "普通"
                unread = "未读" if message.get("unread") else "已读"
                lines.append(
                    f"{index}. [{priority}/{unread}] {message.get('subject', '无主题')}"
                    f" - {message.get('from_address', '未知发件人')}"
                )
            await emit_progress(
                "email_compose",
                "形成邮件摘要",
                "输出邮件优先级、未读状态和发件人摘要",
                {"answer_length": len("\n".join(lines))},
            )
            return {"answer": "\n".join(lines)}

        builder = StateGraph(EmailState)
        builder.add_node("analyze", analyze)
        builder.add_node("fetch", fetch)
        builder.add_node("triage", triage)
        builder.add_node("compose", compose)
        builder.add_edge(START, "analyze")
        builder.add_edge("analyze", "fetch")
        builder.add_edge("fetch", "triage")
        builder.add_edge("triage", "compose")
        builder.add_edge("compose", END)
        return builder.compile()

    @staticmethod
    def _priority(message: dict[str, Any]) -> float:
        text = f"{message.get('subject', '')} {message.get('snippet', '')}".lower()
        urgent = ("紧急", "尽快", "截止", "面试", "确认", "安全", "urgent", "action required")
        score = 0.35 + (0.2 if message.get("unread") else 0.0)
        score += 0.35 if any(marker in text for marker in urgent) else 0.0
        return round(min(score, 1.0), 2)
