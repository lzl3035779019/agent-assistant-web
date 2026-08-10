from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from redis.asyncio import Redis

from pmaa_web.config import get_settings


class RedisEventBus:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis
        self.settings = get_settings()

    @staticmethod
    def stream_name(run_id: UUID | str) -> str:
        return f"pmaa:run:{run_id}:events"

    async def publish(
        self,
        run_id: UUID | str,
        *,
        sequence: int,
        event_type: str,
        agent_id: str,
        payload: dict[str, Any],
    ) -> str:
        return await self.redis.xadd(
            self.stream_name(run_id),
            {
                "sequence": str(sequence),
                "event_type": event_type,
                "agent_id": agent_id,
                "payload": json.dumps(payload, ensure_ascii=False),
            },
            maxlen=self.settings.redis_event_stream_maxlen,
            approximate=True,
        )
