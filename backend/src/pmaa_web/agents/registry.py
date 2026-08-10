from __future__ import annotations

from pmaa_web.agents.base import BaseAgent


class AgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, BaseAgent] = {}

    def register(self, agent: BaseAgent) -> None:
        if agent.agent_id in self._agents:
            raise ValueError(f"Agent already registered: {agent.agent_id}")
        self._agents[agent.agent_id] = agent

    def get(self, agent_id: str) -> BaseAgent:
        try:
            return self._agents[agent_id]
        except KeyError as exc:
            raise LookupError(f"Agent is not registered: {agent_id}") from exc

    def has(self, agent_id: str) -> bool:
        return agent_id in self._agents

    def catalog(self) -> list[dict[str, object]]:
        return [
            {
                "agent_id": agent.agent_id,
                "description": agent.description,
                "capabilities": sorted(agent.capabilities),
                "allowed_tools": sorted(agent.allowed_tools),
            }
            for agent in self._agents.values()
        ]

    def find_by_capability(self, capability: str) -> list[BaseAgent]:
        return [agent for agent in self._agents.values() if capability in agent.capabilities]
