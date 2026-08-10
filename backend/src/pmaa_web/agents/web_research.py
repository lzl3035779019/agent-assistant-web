from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from time import perf_counter
from typing import Any, TypedDict
from urllib.parse import urlparse

from langgraph.graph import END, START, StateGraph

from pmaa_web.agents.base import AgentExecutionContext, BaseAgent
from pmaa_web.agents.llm import (
    chat_completion,
    generate_research_answer,
    llm_available,
    parse_json_object,
)
from pmaa_web.agents.protocol import AgentResult, AgentTask, ResultStatus
from pmaa_web.config import get_settings
from pmaa_web.tools.web_search import search_web

SearchTool = Callable[[str, int | None], Awaitable[list[dict[str, Any]]]]
AnswerGenerator = Callable[[str, list[dict[str, Any]]], Awaitable[str]]


class WebResearchState(TypedDict, total=False):
    objective: str
    queries: list[str]
    searched_queries: list[str]
    evidence: list[dict[str, Any]]
    confidence: float
    gaps: list[str]
    round: int
    max_rounds: int
    answer: str


class WebResearchAgent(BaseAgent):
    agent_id = "web_research"
    description = "从互联网获取实时、可信、可引用的信息，并在证据不足时自主补充检索。"
    capabilities = frozenset({"web_research", "realtime_information", "source_verification"})
    allowed_tools = frozenset({"web_search"})

    def __init__(
        self,
        *,
        searcher: SearchTool = search_web,
        answer_generator: AnswerGenerator = generate_research_answer,
    ) -> None:
        self._searcher = searcher
        self._answer_generator = answer_generator

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
                "objective": task.objective[:240],
                "workflow": "web_research",
                "title": "Web Research Agent 开始执行",
                "summary": "分析目标、规划查询并收集可引用的实时网络证据",
            },
        )
        graph = self._build_graph(context)
        final_state: dict[str, Any] = {}
        async for update in graph.astream(
            {
                "objective": task.objective,
                "searched_queries": [],
                "evidence": [],
                "round": 0,
                "max_rounds": get_settings().web_research_max_rounds,
            },
            stream_mode="updates",
        ):
            for node_update in update.values():
                final_state.update(node_update)

        evidence = final_state.get("evidence", [])
        answer = str(final_state.get("answer", ""))
        confidence = float(final_state.get("confidence", 0.0))
        status = ResultStatus.COMPLETED if evidence else ResultStatus.FAILED
        error = "" if evidence else "Web search returned no usable evidence"
        await context.emit(
            "agent_completed",
            self.agent_id,
            {
                "task_id": str(task.task_id),
                "status": status.value,
                "evidence_count": len(evidence),
                "confidence": confidence,
                "answer_length": len(answer),
                "duration_ms": round((perf_counter() - started_at) * 1000),
                "title": "Web Research Agent 执行完成",
                "summary": "已完成网络检索、证据评估与研究结果生成",
            },
        )
        return AgentResult(
            task_id=task.task_id,
            agent_id=self.agent_id,
            status=status,
            output={"answer": answer},
            evidence=evidence,
            confidence=confidence,
            error=error,
            metrics={
                "query_count": len(final_state.get("searched_queries", [])),
                "research_rounds": int(final_state.get("round", 0)) + 1,
            },
        )

    def _build_graph(self, context: AgentExecutionContext):
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
                    "node": node,
                    "title": title,
                    "summary": summary,
                    "duration_ms": round((now - stage_started_at) * 1000),
                    "metrics": metrics,
                },
            )
            stage_started_at = now

        async def analyze(state: WebResearchState) -> dict[str, Any]:
            queries = await self._plan_queries(state["objective"])
            await emit_progress(
                "research_analyze",
                "分析研究目标",
                "将用户目标拆解为多个互补的网络检索方向",
                {"query_count": len(queries), "query": " | ".join(queries)[:260]},
            )
            return {"queries": queries}

        async def search(state: WebResearchState) -> dict[str, Any]:
            queries = state.get("queries", [])
            batches = await asyncio.gather(
                *(self._searcher(query, get_settings().tavily_max_results) for query in queries)
            )
            merged = self._deduplicate([*state.get("evidence", []), *sum(batches, [])])
            searched = [*state.get("searched_queries", []), *queries]
            await emit_progress(
                "research_search",
                "并行检索网络资料",
                "对多个研究方向并行搜索，并按 URL 合并重复来源",
                {
                    "query_count": len(queries),
                    "evidence_count": len(merged),
                    "source_count": len({item.get("url") for item in merged}),
                },
            )
            return {"evidence": merged, "searched_queries": searched}

        async def evaluate(state: WebResearchState) -> dict[str, Any]:
            confidence, gaps = self._evaluate_evidence(state.get("evidence", []))
            await emit_progress(
                "research_evaluate",
                "评估证据质量",
                "检查来源数量、站点多样性、相关度和内容完整性",
                {
                    "confidence": confidence,
                    "evidence_count": len(state.get("evidence", [])),
                    "gap_count": len(gaps),
                    "decision": "证据充分" if confidence >= 0.58 else "证据不足，需要补搜",
                },
            )
            return {"confidence": confidence, "gaps": gaps}

        def route_after_evaluate(state: WebResearchState) -> str:
            if state.get("confidence", 0) >= 0.58:
                return "synthesize"
            if state.get("round", 0) + 1 < state.get("max_rounds", 2):
                return "supplement"
            return "synthesize"

        async def supplement(state: WebResearchState) -> dict[str, Any]:
            next_round = state.get("round", 0) + 1
            gaps = state.get("gaps", [])
            suffix = " ".join(gaps) if gaps else "官方来源 最新进展 交叉验证"
            query = f"{state['objective']} {suffix}".strip()
            await emit_progress(
                "research_supplement",
                "规划补充检索",
                "针对证据缺口生成新的检索查询",
                {"attempt": next_round, "query": query[:260]},
            )
            return {"queries": [query], "round": next_round}

        async def synthesize(state: WebResearchState) -> dict[str, Any]:
            evidence = self._assign_citations(state.get("evidence", []))
            answer = await self._answer_generator(state["objective"], evidence)
            await emit_progress(
                "research_synthesize",
                "形成研究结论",
                "基于通过评估的网络证据生成带引用结论",
                {
                    "answer_length": len(answer),
                    "citation_count": answer.count("[S"),
                    "evidence_count": len(evidence),
                },
            )
            return {"answer": answer, "evidence": evidence}

        builder = StateGraph(WebResearchState)
        builder.add_node("analyze", analyze)
        builder.add_node("search", search)
        builder.add_node("evaluate", evaluate)
        builder.add_node("supplement", supplement)
        builder.add_node("synthesize", synthesize)
        builder.add_edge(START, "analyze")
        builder.add_edge("analyze", "search")
        builder.add_edge("search", "evaluate")
        builder.add_conditional_edges(
            "evaluate",
            route_after_evaluate,
            {"supplement": "supplement", "synthesize": "synthesize"},
        )
        builder.add_edge("supplement", "search")
        builder.add_edge("synthesize", END)
        return builder.compile()

    async def _plan_queries(self, objective: str) -> list[str]:
        limit = get_settings().web_research_max_queries
        if llm_available() and get_settings().app_env != "test":
            try:
                response = await chat_completion(
                    [
                        {
                            "role": "system",
                            "content": (
                                "你是 Web Research Agent 的查询规划器。根据目标生成互补查询，"
                                "覆盖核心事实、最新进展和权威来源。输出 JSON："
                                '{"queries":["..."]}。不要回答问题。'
                            ),
                        },
                        {"role": "user", "content": objective},
                    ],
                    temperature=0.1,
                    json_mode=True,
                )
                queries = parse_json_object(response).get("queries", [])
                cleaned = [str(item).strip() for item in queries if str(item).strip()]
                if cleaned:
                    return cleaned[:limit]
            except Exception:
                pass
        candidates = [
            objective.strip(),
            f"{objective.strip()} 最新进展",
            f"{objective.strip()} 官方 权威来源",
        ]
        return list(dict.fromkeys(candidates))[:limit]

    @staticmethod
    def _deduplicate(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_url: dict[str, dict[str, Any]] = {}
        for item in evidence:
            url = str(item.get("url", "")).strip()
            if not url:
                continue
            current = by_url.get(url)
            if current is None or float(item.get("score", 0)) > float(current.get("score", 0)):
                by_url[url] = item
        return sorted(by_url.values(), key=lambda item: float(item.get("score", 0)), reverse=True)

    @staticmethod
    def _evaluate_evidence(evidence: list[dict[str, Any]]) -> tuple[float, list[str]]:
        if not evidence:
            return 0.0, ["补充公开网络来源", "核对检索关键词"]
        domains = {
            urlparse(str(item.get("url", ""))).netloc.lower()
            for item in evidence
            if item.get("url")
        }
        scores = [float(item.get("score", 0.0)) for item in evidence[:8]]
        average_score = sum(scores) / max(len(scores), 1)
        count_score = min(len(evidence) / 5, 1.0)
        diversity_score = min(len(domains) / 3, 1.0)
        confidence = round(min(0.95, count_score * 0.35 + diversity_score * 0.25 + average_score * 0.4), 4)
        gaps: list[str] = []
        if len(evidence) < 4:
            gaps.append("更多独立来源")
        if len(domains) < 2:
            gaps.append("交叉验证来源")
        if average_score < 0.45:
            gaps.append("更精确的关键词")
        return confidence, gaps

    @staticmethod
    def _assign_citations(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {**item, "citation_id": f"S{index}"}
            for index, item in enumerate(evidence[:12], start=1)
        ]
