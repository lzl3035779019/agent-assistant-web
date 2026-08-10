from __future__ import annotations

import json
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from pmaa_web.agents.base import AgentExecutionContext, BaseAgent
from pmaa_web.agents.llm import chat_completion, llm_available
from pmaa_web.agents.protocol import AgentResult, AgentTask, ResultStatus


class SynthesisState(TypedDict, total=False):
    objective: str
    dependency_results: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    conflicts: list[str]
    answer: str
    confidence: float


class SynthesisAgent(BaseAgent):
    agent_id = "synthesis"
    description = "合并多个专业 Agent 的结构化结果，处理冲突并形成统一回答"
    capabilities = frozenset({"result_aggregation", "conflict_resolution", "evidence_merge"})
    allowed_tools = frozenset()

    async def execute(
        self,
        task: AgentTask,
        context: AgentExecutionContext,
    ) -> AgentResult:
        graph = self._build_graph()
        raw_dependencies = task.context.get("dependency_results", {})
        dependencies = [
            item for item in raw_dependencies.values() if isinstance(item, dict)
        ]
        await context.emit(
            "agent_started",
            self.agent_id,
            {
                "title": "Synthesis Agent 开始综合结果",
                "summary": f"正在合并 {len(dependencies)} 个专业 Agent 的结构化输出",
            },
        )
        state = await graph.ainvoke(
            {"objective": task.objective, "dependency_results": dependencies}
        )
        await context.emit(
            "agent_completed",
            self.agent_id,
            {
                "title": "Synthesis Agent 完成结果综合",
                "summary": "已完成证据去重、冲突检查和统一回答",
                "source_agent_count": len(dependencies),
                "evidence_count": len(state.get("evidence", [])),
                "conflict_count": len(state.get("conflicts", [])),
            },
        )
        return AgentResult(
            task_id=task.task_id,
            agent_id=self.agent_id,
            status=ResultStatus.COMPLETED,
            output={
                "answer": state.get("answer", "任务已完成。"),
                "conflicts": state.get("conflicts", []),
                "source_agents": [item.get("agent_id", "unknown") for item in dependencies],
            },
            evidence=state.get("evidence", []),
            confidence=state.get("confidence", 0.0),
        )

    def _build_graph(self):
        async def assess(state: SynthesisState) -> dict[str, Any]:
            evidence: list[dict[str, Any]] = []
            seen: set[str] = set()
            confidences: list[float] = []
            for result in state.get("dependency_results", []):
                confidences.append(float(result.get("confidence", 0.0)))
                for item in result.get("evidence", []):
                    if not isinstance(item, dict):
                        continue
                    key = str(
                        item.get("url")
                        or item.get("citation_id")
                        or item.get("content")
                        or json.dumps(item, sort_keys=True, ensure_ascii=False)
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                    evidence.append(item)
            confidence = sum(confidences) / len(confidences) if confidences else 0.0
            return {"evidence": evidence, "confidence": round(confidence, 4)}

        async def resolve(state: SynthesisState) -> dict[str, Any]:
            answers = [
                str(item.get("output", {}).get("answer", "")).strip()
                for item in state.get("dependency_results", [])
                if isinstance(item.get("output"), dict)
            ]
            conflicts: list[str] = []
            if len({answer for answer in answers if answer}) > 1:
                conflicts.append("多个 Agent 返回了互补结论，已按证据来源统一组织。")
            return {"conflicts": conflicts}

        async def compose(state: SynthesisState) -> dict[str, Any]:
            dependencies = state.get("dependency_results", [])
            if llm_available():
                material = json.dumps(
                    [
                        {
                            "agent_id": item.get("agent_id"),
                            "answer": item.get("output", {}).get("answer", ""),
                            "confidence": item.get("confidence", 0),
                        }
                        for item in dependencies
                    ],
                    ensure_ascii=False,
                )
                answer = await chat_completion(
                    [
                        {
                            "role": "system",
                            "content": (
                                "你是多 Agent 系统的结果综合 Agent。只能使用给定子 Agent 结果，"
                                "消除重复、明确冲突和不确定性，保留已有引用标记，不得编造新事实。"
                            ),
                        },
                        {
                            "role": "user",
                            "content": f"用户目标：{state['objective']}\n子 Agent 结果：{material}",
                        },
                    ],
                    temperature=0.1,
                )
                return {"answer": answer.strip()}
            sections = []
            for item in dependencies:
                answer = str(item.get("output", {}).get("answer", "")).strip()
                if answer:
                    sections.append(f"### {item.get('agent_id', 'Agent')}\n\n{answer}")
            return {"answer": "\n\n".join(sections) or "专业 Agent 未返回可综合的内容。"}

        builder = StateGraph(SynthesisState)
        builder.add_node("assess", assess)
        builder.add_node("resolve", resolve)
        builder.add_node("compose", compose)
        builder.add_edge(START, "assess")
        builder.add_edge("assess", "resolve")
        builder.add_edge("resolve", "compose")
        builder.add_edge("compose", END)
        return builder.compile()
