from __future__ import annotations

import asyncio
from time import perf_counter
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from pmaa_web.agents.base import AgentExecutionContext, BaseAgent
from pmaa_web.agents.protocol import AgentResult, AgentTask, ResultStatus
from pmaa_web.daily_brief_service import (
    DEFAULT_TOPICS,
    _build_priorities,
    _build_summary,
    _collect_calendar,
    _collect_email,
    _collect_memories,
    _collect_news,
    _empty_result,
    _render_markdown,
)


class DailyBriefState(TypedDict, total=False):
    objective: str
    request_payload: dict[str, Any]
    topics: list[str]
    include_email: bool
    include_calendar: bool
    include_memory: bool
    sections: dict[str, Any]
    content: str


class DailyBriefAgent(BaseAgent):
    agent_id = "daily_brief"
    description = "并行汇总未读邮件、近期日程、长期偏好和关注主题新闻，生成个人每日简报。"
    capabilities = frozenset(
        {"daily_brief", "personal_digest", "parallel_collection", "priority_summary"}
    )
    allowed_tools = frozenset(
        {"imap_read", "calendar_read", "memory_read", "web_search"}
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
                "workflow": ["analyze", "collect", "prioritize", "compose"],
                "title": "Daily Brief Agent 开始执行",
                "summary": "分析简报配置，并行收集邮件、日历、记忆和关注主题新闻",
            },
        )
        try:
            graph = self._build_graph(task, context)
            final_state: dict[str, Any] = {}
            async for update in graph.astream(
                {
                    "objective": task.objective,
                    "request_payload": dict(task.context.get("request_payload") or {}),
                    "sections": {},
                    "content": "",
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
                    "title": "Daily Brief Agent 执行失败",
                    "summary": str(exc),
                },
            )
            return AgentResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                status=ResultStatus.FAILED,
                error=str(exc),
            )

        sections = final_state.get("sections", {})
        content = str(final_state.get("content", ""))
        await context.emit(
            "agent_completed",
            self.agent_id,
            {
                "task_id": str(task.task_id),
                "status": "completed",
                "duration_ms": round((perf_counter() - started_at) * 1000),
                "title": "Daily Brief Agent 执行完成",
                "summary": "多源数据已聚合为结构化个人简报",
                "metrics": self._section_metrics(sections),
            },
        )
        return AgentResult(
            task_id=task.task_id,
            agent_id=self.agent_id,
            status=ResultStatus.COMPLETED,
            output={
                "answer": content,
                "content": content,
                "sections": sections,
                "topics": final_state.get("topics", DEFAULT_TOPICS),
            },
            confidence=0.9 if not sections.get("warnings") else 0.76,
            metrics=self._section_metrics(sections),
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

        async def analyze(state: DailyBriefState) -> dict[str, Any]:
            payload = state.get("request_payload", {})
            topics = list(
                dict.fromkeys(
                    str(item).strip()
                    for item in payload.get("topics", DEFAULT_TOPICS)
                    if str(item).strip()
                )
            )[:12] or DEFAULT_TOPICS
            result = {
                "topics": topics,
                "include_email": bool(payload.get("include_email", True)),
                "include_calendar": bool(payload.get("include_calendar", True)),
                "include_memory": bool(payload.get("include_memory", True)),
            }
            await emit_progress(
                "brief_analyze",
                "分析简报配置",
                "确定关注主题和本轮需要聚合的数据源",
                {
                    "topic_count": len(topics),
                    "source_count": 1 + sum(
                        int(result[key])
                        for key in ("include_email", "include_calendar", "include_memory")
                    ),
                },
            )
            return result

        async def collect(state: DailyBriefState) -> dict[str, Any]:
            collectors = {
                "email": _collect_email() if state["include_email"] else _empty_result(),
                "calendar": (
                    _collect_calendar(context.run.user_id)
                    if state["include_calendar"]
                    else _empty_result()
                ),
                "memory": (
                    _collect_memories(context.run.user_id)
                    if state["include_memory"]
                    else _empty_result()
                ),
                "news": _collect_news(state["topics"]),
            }
            names = list(collectors)
            values = await asyncio.gather(
                *(collectors[name] for name in names),
                return_exceptions=True,
            )
            sections: dict[str, Any] = {"topics": state["topics"], "warnings": []}
            for name, value in zip(names, values, strict=True):
                if isinstance(value, Exception):
                    sections[name] = []
                    sections["warnings"].append(
                        f"{name} 数据获取失败：{type(value).__name__}"
                    )
                else:
                    sections[name] = value["items"]
                    sections["warnings"].extend(value.get("warnings", []))
            await emit_progress(
                "brief_collect",
                "并行收集简报数据",
                "邮件、日历、记忆和关注主题新闻已并行返回",
                self._section_metrics(sections),
            )
            return {"sections": sections}

        async def prioritize(state: DailyBriefState) -> dict[str, Any]:
            sections = dict(state["sections"])
            sections["priorities"] = _build_priorities(sections)
            sections["summary"] = _build_summary(sections)
            await emit_progress(
                "brief_prioritize",
                "评估今日优先级",
                "根据未读邮件、近期日程、逾期待办和主题变化提取今日重点",
                {"priority_count": len(sections["priorities"])},
            )
            return {"sections": sections}

        async def compose(state: DailyBriefState) -> dict[str, Any]:
            content = _render_markdown(state["sections"])
            await emit_progress(
                "brief_compose",
                "生成每日简报",
                "将多源结果整理为可阅读、可追溯的 Markdown 简报",
                {
                    "answer_length": len(content),
                    "warning_count": len(state["sections"].get("warnings", [])),
                },
            )
            return {"content": content}

        builder = StateGraph(DailyBriefState)
        builder.add_node("analyze", analyze)
        builder.add_node("collect", collect)
        builder.add_node("prioritize", prioritize)
        builder.add_node("compose", compose)
        builder.add_edge(START, "analyze")
        builder.add_edge("analyze", "collect")
        builder.add_edge("collect", "prioritize")
        builder.add_edge("prioritize", "compose")
        builder.add_edge("compose", END)
        return builder.compile()

    @staticmethod
    def _section_metrics(sections: dict[str, Any]) -> dict[str, int]:
        return {
            "email_count": len(sections.get("email", [])),
            "calendar_item_count": len(sections.get("calendar", [])),
            "memory_count": len(sections.get("memory", [])),
            "news_count": len(sections.get("news", [])),
            "warning_count": len(sections.get("warnings", [])),
        }
