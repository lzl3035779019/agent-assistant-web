from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta
from time import perf_counter
from typing import Any, TypedDict
from uuid import UUID

import httpx
from langgraph.graph import END, START, StateGraph

from pmaa_web.agents.base import AgentExecutionContext, BaseAgent
from pmaa_web.agents.protocol import AgentResult, AgentTask, ResultStatus
from pmaa_web.config import get_settings
from pmaa_web.models import MonitorNotification, MonitorResult, MonitorRule, utc_now

MonitorCollector = Callable[[MonitorRule], Awaitable[list[dict[str, Any]]]]


class MonitorState(TypedDict, total=False):
    rule_id: str
    rule: MonitorRule
    items: list[dict[str, Any]]
    new_items: list[dict[str, Any]]
    baseline_created: bool
    answer: str


class MonitorAgent(BaseAgent):
    agent_id = "information_monitor"
    description = "持续跟踪公司、新闻、GitHub 项目和技术博客，建立基线并只报告新增变化。"
    capabilities = frozenset(
        {"information_monitor", "change_detection", "github_monitor", "news_monitor"}
    )
    allowed_tools = frozenset({"web_search", "github_search", "notification_write"})

    def __init__(self, collector: MonitorCollector | None = None) -> None:
        self._collector = collector or self._collect

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
                "workflow": ["analyze", "collect", "compare", "notify"],
                "title": "Monitor Agent 开始执行",
                "summary": "读取监控规则并检查相对上次基线出现的重要变化",
            },
        )
        try:
            rule_id = str(
                (task.context.get("request_payload") or {}).get("monitor_rule_id", "")
            )
            if not rule_id:
                raise ValueError("Monitor Agent 需要 monitor_rule_id")
            graph = self._build_graph(task, context)
            final_state: dict[str, Any] = {}
            async for update in graph.astream(
                {"rule_id": rule_id, "items": [], "new_items": [], "answer": ""},
                stream_mode="updates",
            ):
                for node_update in update.values():
                    final_state.update(node_update)
        except Exception as exc:
            try:
                rule_id = str(
                    (task.context.get("request_payload") or {}).get("monitor_rule_id", "")
                )
                if rule_id:
                    rule = await context.session.get(MonitorRule, UUID(rule_id))
                    if rule is not None:
                        rule.last_run_status = "failed"
                        rule.last_error = str(exc)
                        rule.last_run_at = utc_now()
                        rule.next_run_at = utc_now() + timedelta(
                            minutes=rule.interval_minutes
                        )
                        await context.session.commit()
            except Exception:
                await context.session.rollback()
            await context.emit(
                "agent_completed",
                self.agent_id,
                {
                    "task_id": str(task.task_id),
                    "status": "failed",
                    "title": "Monitor Agent 执行失败",
                    "summary": str(exc),
                },
            )
            return AgentResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                status=ResultStatus.FAILED,
                error=str(exc),
            )

        items = final_state.get("items", [])
        new_items = final_state.get("new_items", [])
        baseline_created = bool(final_state.get("baseline_created"))
        await context.emit(
            "agent_completed",
            self.agent_id,
            {
                "task_id": str(task.task_id),
                "status": "completed",
                "duration_ms": round((perf_counter() - started_at) * 1000),
                "title": "Monitor Agent 执行完成",
                "summary": "首次基线已建立" if baseline_created else "监控变化检查已完成",
                "metrics": {
                    "monitor_item_count": len(items),
                    "change_count": len(new_items),
                    "notification_count": 1 if new_items else 0,
                },
            },
        )
        return AgentResult(
            task_id=task.task_id,
            agent_id=self.agent_id,
            status=ResultStatus.COMPLETED,
            output={
                "answer": final_state.get("answer", ""),
                "items": items,
                "new_items": new_items,
                "baseline_created": baseline_created,
                "rule_id": rule_id,
            },
            confidence=0.9,
            metrics={
                "monitor_item_count": len(items),
                "change_count": len(new_items),
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

        async def analyze(state: MonitorState) -> dict[str, Any]:
            rule = await context.session.get(MonitorRule, UUID(state["rule_id"]))
            if rule is None or rule.user_id != context.run.user_id:
                raise LookupError("监控规则不存在")
            rule.last_run_status = "running"
            rule.last_run_id = context.run.id
            rule.last_error = ""
            await context.session.commit()
            await emit_progress(
                "monitor_analyze",
                "分析监控规则",
                "确定监控对象、数据源和已有基线",
                {
                    "monitor_type": rule.target_type,
                    "baseline_count": len(rule.baseline_keys),
                },
            )
            return {"rule": rule}

        async def collect(state: MonitorState) -> dict[str, Any]:
            items = await self._collector(state["rule"])
            normalized = [self._normalize(item) for item in items if item.get("url")]
            await emit_progress(
                "monitor_collect",
                "获取监控数据",
                "根据规则选择 GitHub API 或联网搜索收集当前快照",
                {"monitor_item_count": len(normalized)},
            )
            return {"items": normalized}

        async def compare(state: MonitorState) -> dict[str, Any]:
            rule = state["rule"]
            previous = set(rule.baseline_keys)
            baseline_created = not previous
            new_items = [] if baseline_created else [
                item for item in state["items"] if self._key(item) not in previous
            ]
            await emit_progress(
                "monitor_compare",
                "比较历史基线",
                "通过稳定资源标识过滤已见结果，仅保留新增变化",
                {
                    "baseline_count": len(previous),
                    "change_count": len(new_items),
                },
            )
            return {"new_items": new_items, "baseline_created": baseline_created}

        async def notify(state: MonitorState) -> dict[str, Any]:
            rule = state["rule"]
            keys = list(dict.fromkeys(self._key(item) for item in state["items"]))[:500]
            rule.baseline_keys = keys
            rule.last_result = state["items"][:50]
            rule.last_run_status = "completed"
            rule.last_run_at = utc_now()
            rule.next_run_at = utc_now() + timedelta(minutes=rule.interval_minutes)
            if state["baseline_created"]:
                answer = f"已为“{rule.name}”建立 {len(state['items'])} 项初始基线，后续仅提醒新增变化。"
            elif state["new_items"]:
                answer = f"“{rule.name}”发现 {len(state['new_items'])} 项新增变化，已写入通知中心。"
            else:
                answer = f"“{rule.name}”本轮未发现相对基线的新变化。"
            context.session.add(
                MonitorResult(
                    user_id=rule.user_id,
                    rule_id=rule.id,
                    run_id=context.run.id,
                    rule_name=rule.name,
                    target_type=rule.target_type,
                    summary=answer,
                    item_count=len(state["items"]),
                    change_count=len(state["new_items"]),
                    baseline_created=state["baseline_created"],
                    payload={
                        "items": state["items"][:50],
                        "new_items": state["new_items"][:20],
                    },
                )
            )
            if state["new_items"]:
                context.session.add(
                    MonitorNotification(
                        user_id=rule.user_id,
                        rule_id=rule.id,
                        title=f"{rule.name} 发现 {len(state['new_items'])} 项变化",
                        summary="；".join(
                            item.get("title", "未命名变化") for item in state["new_items"][:3]
                        ),
                        payload={"items": state["new_items"][:20], "run_id": str(context.run.id)},
                    )
                )
            await context.session.commit()
            await emit_progress(
                "monitor_notify",
                "更新基线与通知",
                "保存本轮快照，并在发现新增变化时创建未读通知",
                {"notification_count": 1 if state["new_items"] else 0},
            )
            return {"answer": answer}

        builder = StateGraph(MonitorState)
        builder.add_node("analyze", analyze)
        builder.add_node("collect", collect)
        builder.add_node("compare", compare)
        builder.add_node("notify", notify)
        builder.add_edge(START, "analyze")
        builder.add_edge("analyze", "collect")
        builder.add_edge("collect", "compare")
        builder.add_edge("compare", "notify")
        builder.add_edge("notify", END)
        return builder.compile()

    async def _collect(self, rule: MonitorRule) -> list[dict[str, Any]]:
        if rule.target_type == "github":
            return await self._collect_github(rule.query)
        return await self._collect_web(rule.query, rule.target_type)

    @staticmethod
    async def _collect_github(query: str) -> list[dict[str, Any]]:
        settings = get_settings()
        headers = {"Accept": "application/vnd.github+json"}
        if settings.github_token:
            headers["Authorization"] = f"Bearer {settings.github_token}"
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{settings.github_api_base_url.rstrip('/')}/search/repositories",
                params={"q": query, "sort": "updated", "order": "desc", "per_page": 20},
                headers=headers,
            )
            response.raise_for_status()
        return [
            {
                "title": item["full_name"],
                "url": item["html_url"],
                "summary": item.get("description") or "",
                "published_at": item.get("pushed_at") or item.get("updated_at"),
                "score": item.get("stargazers_count", 0),
                "source": "github",
            }
            for item in response.json().get("items", [])
        ]

    @staticmethod
    async def _collect_web(query: str, target_type: str) -> list[dict[str, Any]]:
        settings = get_settings()
        if settings.web_search_provider != "tavily" or not settings.tavily_api_key:
            raise RuntimeError("信息监控需要配置 Tavily 联网搜索")
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                settings.tavily_base_url,
                json={
                    "api_key": settings.tavily_api_key,
                    "query": query,
                    "topic": "news" if target_type in {"news", "company"} else "general",
                    "search_depth": "advanced",
                    "max_results": min(settings.tavily_max_results, 20),
                },
            )
            response.raise_for_status()
        return [
            {
                "title": item.get("title") or "未命名结果",
                "url": item.get("url") or "",
                "summary": (item.get("content") or "")[:500],
                "published_at": item.get("published_date"),
                "score": item.get("score", 0),
                "source": "web",
            }
            for item in response.json().get("results", [])
        ]

    @staticmethod
    def _normalize(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "title": str(item.get("title") or "未命名结果")[:512],
            "url": str(item.get("url") or "")[:2000],
            "summary": str(item.get("summary") or "")[:1000],
            "published_at": item.get("published_at"),
            "score": item.get("score", 0),
            "source": str(item.get("source") or "web"),
        }

    @staticmethod
    def _key(item: dict[str, Any]) -> str:
        return str(item.get("url") or item.get("title", "")).strip().lower()
