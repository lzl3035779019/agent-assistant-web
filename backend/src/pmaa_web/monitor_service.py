from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select

from pmaa_web.config import get_settings
from pmaa_web.database import SessionFactory
from pmaa_web.models import AgentRun, MonitorRule, utc_now
from pmaa_web.run_service import dispatch_run


def next_monitor_run(interval_minutes: int):
    return utc_now() + timedelta(minutes=interval_minutes)


async def create_monitor_run(rule_id: UUID) -> AgentRun:
    async with SessionFactory() as session:
        rule = await session.get(MonitorRule, rule_id)
        if rule is None:
            raise LookupError("监控规则不存在")
        run = AgentRun(
            user_id=rule.user_id,
            objective=f"检查信息监控规则：{rule.name}",
            run_type="monitor",
            input_payload={"monitor_rule_id": str(rule.id)},
        )
        session.add(run)
        rule.last_run_status = "queued"
        rule.last_run_id = run.id
        await session.commit()
    await dispatch_run(run.id)
    return run


async def run_due_monitor_rules(ctx: dict[str, Any]) -> None:
    if not get_settings().automation_scheduler_enabled:
        return
    now = utc_now()
    run_ids: list[UUID] = []
    async with SessionFactory() as session:
        rules = list(
            await session.scalars(
                select(MonitorRule)
                .where(
                    MonitorRule.enabled.is_(True),
                    MonitorRule.next_run_at.is_not(None),
                    MonitorRule.next_run_at <= now,
                    MonitorRule.last_run_status.not_in(["queued", "running"]),
                )
                .with_for_update(skip_locked=True)
            )
        )
        for rule in rules:
            run = AgentRun(
                user_id=rule.user_id,
                objective=f"检查信息监控规则：{rule.name}",
                run_type="monitor",
                input_payload={"monitor_rule_id": str(rule.id)},
            )
            session.add(run)
            await session.flush()
            run_ids.append(run.id)
            rule.last_run_status = "queued"
            rule.last_run_id = run.id
            rule.next_run_at = now + timedelta(minutes=rule.interval_minutes)
        await session.commit()

    redis = ctx.get("redis")
    for run_id in run_ids:
        if redis is not None:
            await redis.enqueue_job("run_agent_job", str(run_id), _job_id=str(run_id))
        else:
            await dispatch_run(run_id)
