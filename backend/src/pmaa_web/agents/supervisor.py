from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field

from pmaa_web.agents.llm import chat_completion, llm_available, parse_json_object
from pmaa_web.agents.protocol import AgentTask
from pmaa_web.agents.registry import AgentRegistry
from pmaa_web.config import get_settings
from pmaa_web.models import AgentRun


class SupervisorDecision(BaseModel):
    intent: str
    mode: Literal["direct_answer", "delegate"]
    assigned_agents: list[str] = Field(default_factory=list)
    dependency_map: dict[str, list[str]] = Field(default_factory=dict)
    reason: str
    confidence: float = Field(ge=0.0, le=1.0)


class Supervisor:
    def __init__(self, registry: AgentRegistry) -> None:
        self.registry = registry

    async def decide(self, run: AgentRun) -> SupervisorDecision:
        explicit = self._explicit_route(run.run_type)
        if explicit:
            return explicit

        settings = get_settings()
        if settings.app_env != "test" and llm_available():
            try:
                decision = await self._llm_route(run)
                return self._validate(decision, run)
            except Exception:
                pass
        return self._validate(self._fallback_route(run), run)

    def build_tasks(self, run: AgentRun, decision: SupervisorDecision) -> list[AgentTask]:
        if decision.mode != "delegate":
            return []
        task_ids = {agent_id: AgentTask(
            run_id=run.id,
            trace_id=run.id,
            assigned_agent=agent_id,
            objective=run.objective,
        ).task_id for agent_id in decision.assigned_agents}
        tasks = [
            AgentTask(
                task_id=task_ids[agent_id],
                run_id=run.id,
                trace_id=run.id,
                assigned_agent=agent_id,
                objective=run.objective,
                context={
                    "conversation_id": str(run.conversation_id) if run.conversation_id else None,
                    "request_payload": dict(run.input_payload or {}),
                    "memory_count": len(
                        (run.input_payload or {}).get("retrieved_memories", [])
                    ),
                },
                dependencies=[
                    task_ids[dependency]
                    for dependency in decision.dependency_map.get(agent_id, [])
                    if dependency in task_ids
                ],
                max_attempts=2,
                timeout_seconds=240,
            )
            for agent_id in decision.assigned_agents
        ]
        if len(tasks) > 1:
            tasks.append(
                AgentTask(
                    run_id=run.id,
                    trace_id=run.id,
                    assigned_agent="synthesis",
                    objective=run.objective,
                    context={"source_agents": decision.assigned_agents},
                    dependencies=[task.task_id for task in tasks],
                    max_attempts=2,
                    timeout_seconds=180,
                )
            )
        return tasks

    def _explicit_route(self, run_type: str) -> SupervisorDecision | None:
        if run_type == "agentic_rag":
            return SupervisorDecision(
                intent="local_knowledge_query",
                mode="delegate",
                assigned_agents=["knowledge"],
                reason="调用方明确指定 Agentic RAG，本任务交给 Knowledge Agent。",
                confidence=1.0,
            )
        if run_type == "research":
            return SupervisorDecision(
                intent="web_research",
                mode="delegate",
                assigned_agents=["web_research"],
                reason="调用方明确指定联网研究，本任务交给 Web Research Agent。",
                confidence=1.0,
            )
        if run_type == "email":
            return SupervisorDecision(
                intent="email_assistance",
                mode="delegate",
                assigned_agents=["email"],
                reason="调用方明确指定邮件任务，本任务交给 Email Agent。",
                confidence=1.0,
            )
        if run_type == "calendar":
            return SupervisorDecision(
                intent="calendar_assistance",
                mode="delegate",
                assigned_agents=["calendar"],
                reason="调用方明确指定日历与待办任务，本任务交给 Calendar / Task Agent。",
                confidence=1.0,
            )
        if run_type == "daily_brief":
            return SupervisorDecision(
                intent="daily_brief_generation",
                mode="delegate",
                assigned_agents=["daily_brief"],
                reason="调用方明确指定个人简报生成，本任务交给 Daily Brief Agent。",
                confidence=1.0,
            )
        if run_type == "monitor":
            return SupervisorDecision(
                intent="information_monitoring",
                mode="delegate",
                assigned_agents=["information_monitor"],
                reason="调用方明确指定信息监控检查，本任务交给 Monitor Agent。",
                confidence=1.0,
            )
        return None

    async def _llm_route(self, run: AgentRun) -> SupervisorDecision:
        catalog = json.dumps(self.registry.catalog(), ensure_ascii=False)
        content = await chat_completion(
            [
                {
                    "role": "system",
                    "content": (
                        "你是多 Agent 系统的 Supervisor，只负责路由，不回答用户。"
                        "判断是否需要委派。实时新闻、天气、最新状态和公开网络资料必须委派 "
                        "web_research；基于用户已上传资料的问题委派 knowledge；"
                        "读取、筛选或回复邮件委派 email；"
                        "查询日程、待办、时间冲突或规划日历变更委派 calendar；"
                        "汇总邮件、日程、偏好和关注主题生成个人简报委派 daily_brief；"
                        "持续跟踪公司、GitHub 项目、新闻或技术博客的变化委派 information_monitor；"
                        "闲聊、改写和无需外部事实的常识问答 direct_answer。"
                        "memory 是由系统生命周期自动调度的 Agent，synthesis 是内部聚合 Agent，"
                        "两者都不得作为用户请求的业务路由目标。"
                        "只能选择目录中存在的 Agent。输出 JSON："
                        '{"intent":"...","mode":"direct_answer|delegate",'
                        '"assigned_agents":["..."],'
                        '"dependency_map":{"下游Agent":["上游Agent"]},'
                        '"reason":"...","confidence":0.0}。'
                    ),
                },
                {
                    "role": "user",
                    "content": f"Agent 目录：{catalog}\n当前请求：{run.objective}",
                },
            ],
            temperature=0.0,
            json_mode=True,
        )
        return SupervisorDecision.model_validate(parse_json_object(content))

    def _fallback_route(self, run: AgentRun) -> SupervisorDecision:
        objective = run.objective.lower()
        local_markers = ("知识库", "上传的文档", "我的文档", "本地资料", "根据资料")
        email_markers = ("邮件", "邮箱", "收件箱", "回信")
        calendar_markers = ("日历", "日程", "待办", "会议安排", "时间冲突")
        brief_markers = ("每日简报", "今日简报", "生成简报", "个人简报")
        monitor_markers = ("持续监控", "信息监控", "跟踪更新", "监控项目", "监控公司")
        realtime_markers = (
            "最新",
            "今天",
            "实时",
            "新闻",
            "搜索",
            "查一下",
            "天气",
            "股价",
            "现在",
        )
        has_local = any(marker in objective for marker in local_markers)
        has_realtime = any(marker in objective for marker in realtime_markers)
        has_email = any(marker in objective for marker in email_markers)
        has_calendar = any(marker in objective for marker in calendar_markers)
        if any(marker in objective for marker in brief_markers):
            return SupervisorDecision(
                intent="daily_brief_generation",
                mode="delegate",
                assigned_agents=["daily_brief"],
                reason="LLM 路由不可用，确定性降级规则识别为个人简报生成任务。",
                confidence=0.84,
            )
        if any(marker in objective for marker in monitor_markers):
            return SupervisorDecision(
                intent="information_monitoring",
                mode="delegate",
                assigned_agents=["information_monitor"],
                reason="LLM 路由不可用，确定性降级规则识别为持续信息监控任务。",
                confidence=0.84,
            )
        if has_email and has_calendar:
            return SupervisorDecision(
                intent="email_to_calendar",
                mode="delegate",
                assigned_agents=["email", "calendar"],
                dependency_map={"calendar": ["email"]},
                reason="任务需要先理解邮件，再生成日历处理建议。",
                confidence=0.88,
            )
        if has_local and has_realtime:
            return SupervisorDecision(
                intent="hybrid_research",
                mode="delegate",
                assigned_agents=["knowledge", "web_research"],
                reason="任务同时需要本地知识和实时网络证据，两个研究 Agent 可并行执行。",
                confidence=0.88,
            )
        if any(marker in objective for marker in email_markers):
            return SupervisorDecision(
                intent="email_assistance",
                mode="delegate",
                assigned_agents=["email"],
                reason="LLM 路由不可用，确定性降级规则识别为邮件处理任务。",
                confidence=0.82,
            )
        if any(marker in objective for marker in calendar_markers):
            return SupervisorDecision(
                intent="calendar_assistance",
                mode="delegate",
                assigned_agents=["calendar"],
                reason="LLM 路由不可用，确定性降级规则识别为日历与待办任务。",
                confidence=0.82,
            )
        if any(marker in objective for marker in local_markers):
            return SupervisorDecision(
                intent="local_knowledge_query",
                mode="delegate",
                assigned_agents=["knowledge"],
                reason="LLM 路由不可用，确定性降级规则识别为本地知识查询。",
                confidence=0.76,
            )
        if any(marker in objective for marker in realtime_markers):
            return SupervisorDecision(
                intent="web_research",
                mode="delegate",
                assigned_agents=["web_research"],
                reason="LLM 路由不可用，确定性降级规则识别为实时联网查询。",
                confidence=0.74,
            )
        return SupervisorDecision(
            intent="direct_answer",
            mode="direct_answer",
            assigned_agents=[],
            reason="请求不依赖外部信息或专业工具，由 Supervisor 直接回答。",
            confidence=0.72,
        )

    def _validate(
        self,
        decision: SupervisorDecision,
        run: AgentRun,
    ) -> SupervisorDecision:
        explicit = self._explicit_route(run.run_type)
        if explicit:
            return explicit
        valid_agents = [
            agent_id
            for agent_id in decision.assigned_agents
            if agent_id not in {"memory", "synthesis"} and self.registry.has(agent_id)
        ]
        if decision.mode == "delegate" and not valid_agents:
            return self._fallback_route(run)
        if decision.mode == "direct_answer":
            valid_agents = []
        dependency_map = {
            agent_id: [
                dependency
                for dependency in dependencies
                if dependency in valid_agents and dependency != agent_id
            ]
            for agent_id, dependencies in decision.dependency_map.items()
            if agent_id in valid_agents
        }
        return decision.model_copy(
            update={"assigned_agents": valid_agents, "dependency_map": dependency_map}
        )
