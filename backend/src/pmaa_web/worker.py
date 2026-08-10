from __future__ import annotations

from datetime import timedelta

from arq import Retry, cron
from arq.connections import RedisSettings

from pmaa_web.config import get_settings
from pmaa_web.daily_brief_service import (
    run_brief_safely,
    run_due_brief_schedules,
)
from pmaa_web.database import SessionFactory
from pmaa_web.knowledge.ingestion import ingest_document
from pmaa_web.models import AgentRun, utc_now
from pmaa_web.monitor_service import run_due_monitor_rules
from pmaa_web.run_service import append_event, execute_run


async def run_agent_job(ctx, run_id: str) -> None:
    from uuid import UUID

    parsed_run_id = UUID(run_id)
    await execute_run(parsed_run_id)
    async with SessionFactory() as session:
        run = await session.get(AgentRun, parsed_run_id)
        if run is None or run.status != "failed":
            return
        if run.attempt_count >= run.max_attempts:
            return
        delay_seconds = min(120, 5 * (2 ** max(0, run.attempt_count - 1)))
        run.status = "queued"
        run.next_retry_at = utc_now() + timedelta(seconds=delay_seconds)
        await append_event(
            session,
            run,
            "agent_retry",
            payload={
                "title": "任务将在退避后重试",
                "summary": f"第 {run.attempt_count} 次执行失败，{delay_seconds} 秒后重试",
                "attempt": run.attempt_count,
                "max_attempts": run.max_attempts,
                "delay_seconds": delay_seconds,
            },
        )
    raise Retry(defer=delay_seconds)


async def ingest_document_job(ctx, document_id: str) -> None:
    from uuid import UUID

    await ingest_document(UUID(document_id))


async def generate_daily_brief_job(ctx, brief_id: str) -> None:
    from uuid import UUID

    await run_brief_safely(UUID(brief_id))


class WorkerSettings:
    functions = [run_agent_job, ingest_document_job, generate_daily_brief_job]
    cron_jobs = [
        cron(run_due_brief_schedules, second={0}),
        cron(run_due_monitor_rules, second={15}),
    ]
    max_jobs = 8
    job_timeout = 900
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
