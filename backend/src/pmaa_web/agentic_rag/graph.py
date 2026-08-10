from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

Retriever = Callable[[str], Awaitable[list[dict[str, Any]]]]
AnswerGenerator = Callable[[str, list[dict[str, Any]]], Awaitable[str]]


class AgenticRAGState(TypedDict, total=False):
    query: str
    rewritten_query: str
    evidence: list[dict[str, Any]]
    confidence: float
    attempt: int
    max_attempts: int
    answer: str


def build_agentic_rag_graph(
    retriever: Retriever,
    answer_generator: AnswerGenerator,
):
    async def analyze_query(state: AgenticRAGState) -> dict[str, Any]:
        return {
            "rewritten_query": state["query"].strip(),
            "attempt": state.get("attempt", 0),
        }

    async def retrieve(state: AgenticRAGState) -> dict[str, Any]:
        return {"evidence": await retriever(state["rewritten_query"])}

    async def grade_evidence(state: AgenticRAGState) -> dict[str, Any]:
        evidence = state.get("evidence", [])
        if not evidence:
            return {"confidence": 0.0}
        scores = [float(item.get("score", 0.0)) for item in evidence[:5]]
        coverage = min(len(evidence) / 3, 1.0)
        relevance = sum(scores) / max(len(scores), 1)
        return {"confidence": round(min(0.95, coverage * 0.45 + relevance * 0.55), 4)}

    def route_after_grade(state: AgenticRAGState) -> str:
        if state.get("confidence", 0) >= 0.52:
            return "synthesize"
        if state.get("attempt", 0) + 1 < state.get("max_attempts", 2):
            return "retry"
        return "synthesize"

    async def expand_query(state: AgenticRAGState) -> dict[str, Any]:
        return {
            "attempt": state.get("attempt", 0) + 1,
            "rewritten_query": f"{state['query']} 核心概念 原理 实践",
        }

    async def synthesize(state: AgenticRAGState) -> dict[str, Any]:
        return {"answer": await answer_generator(state["query"], state.get("evidence", []))}

    builder = StateGraph(AgenticRAGState)
    builder.add_node("analyze", analyze_query)
    builder.add_node("retrieve", retrieve)
    builder.add_node("grade", grade_evidence)
    builder.add_node("expand", expand_query)
    builder.add_node("synthesize", synthesize)
    builder.add_edge(START, "analyze")
    builder.add_edge("analyze", "retrieve")
    builder.add_edge("retrieve", "grade")
    builder.add_conditional_edges(
        "grade",
        route_after_grade,
        {"retry": "expand", "synthesize": "synthesize"},
    )
    builder.add_edge("expand", "retrieve")
    builder.add_edge("synthesize", END)
    return builder.compile()
