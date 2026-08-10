from __future__ import annotations

import asyncio
from datetime import datetime, time, timedelta, timezone
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from arq import create_pool
from arq.connections import RedisSettings
from sqlalchemy import select

from pmaa_web.config import get_settings
from pmaa_web.database import SessionFactory
from pmaa_web.email_service import get_email_backend
from pmaa_web.models import (
    AgentRun,
    BriefSchedule,
    CalendarEvent,
    DailyBrief,
    TodoItem,
    UserMemory,
    utc_now,
)

DEFAULT_TOPICS = ["AI 与大模型"]
_background_tasks: set[asyncio.Task[None]] = set()


def validate_schedule_values(
    *,
    timezone_name: str,
    weekdays: list[int],
    topics: list[str],
) -> tuple[list[int], list[str]]:
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("不支持的时区") from exc
    normalized_weekdays = sorted(set(weekdays))
    if not normalized_weekdays or any(day < 0 or day > 6 for day in normalized_weekdays):
        raise ValueError("weekdays 必须是 0 到 6 的非空列表")
    normalized_topics = list(dict.fromkeys(item.strip() for item in topics if item.strip()))
    if len(normalized_topics) > 12:
        raise ValueError("最多关注 12 个主题")
    return normalized_weekdays, normalized_topics or DEFAULT_TOPICS


def next_schedule_run(
    *,
    local_time: str,
    timezone_name: str,
    weekdays: list[int],
    after: datetime | None = None,
) -> datetime:
    zone = ZoneInfo(timezone_name)
    reference = (after or utc_now()).astimezone(zone)
    hour, minute = (int(part) for part in local_time.split(":"))
    for offset in range(8):
        day = reference.date() + timedelta(days=offset)
        if day.weekday() not in weekdays:
            continue
        candidate = datetime.combine(day, time(hour, minute), tzinfo=zone)
        if candidate > reference:
            return candidate.astimezone(timezone.utc)
    raise ValueError("无法计算下一次简报时间")


def _as_utc(value: datetime) -> datetime:
    """Normalize SQLite's naive datetimes and PostgreSQL aware datetimes."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def dispatch_daily_brief(brief_id: UUID) -> None:
    settings = get_settings()
    if settings.task_execution_mode == "arq":
        pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        try:
            await pool.enqueue_job(
                "generate_daily_brief_job",
                str(brief_id),
                _job_id=f"daily-brief:{brief_id}",
            )
        finally:
            await pool.aclose()
        return
    task = asyncio.create_task(run_brief_safely(brief_id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def run_brief_safely(brief_id: UUID) -> None:
    try:
        await generate_daily_brief(brief_id)
    except Exception as exc:
        await mark_brief_failed(brief_id, exc)


async def generate_daily_brief(brief_id: UUID) -> None:
    async with SessionFactory() as session:
        brief = await session.get(DailyBrief, brief_id)
        if brief is None or brief.status not in {"queued", "running"}:
            return
        brief.status = "running"
        brief.started_at = utc_now()
        await session.commit()
        topics = brief.topics or DEFAULT_TOPICS
        user_id = brief.user_id
        include_email = brief.include_email
        include_calendar = brief.include_calendar
        include_memory = brief.include_memory

    # Scheduled and manual briefs enter the same Supervisor -> Runtime -> Agent path.
    async with SessionFactory() as session:
        run = AgentRun(
            user_id=user_id,
            objective=f"生成个人每日简报：{', '.join(topics)}",
            run_type="daily_brief",
            input_payload={
                "brief_id": str(brief_id),
                "topics": topics,
                "include_email": include_email,
                "include_calendar": include_calendar,
                "include_memory": include_memory,
            },
        )
        session.add(run)
        await session.commit()
        run_id = run.id

    from pmaa_web.run_service import execute_run

    await execute_run(run_id)
    async with SessionFactory() as session:
        run = await session.get(AgentRun, run_id)
        if run is None or run.status != "completed":
            error = run.error if run else "简报 Agent 运行记录不存在"
            raise RuntimeError(error or "Daily Brief Agent 执行失败")
        output = (run.result_payload.get("agent_outputs") or {}).get("daily_brief", {})
        sections = dict(output.get("sections") or {})
        content = str(output.get("content") or output.get("answer") or "")
        if not sections or not content:
            raise RuntimeError("Daily Brief Agent 未返回完整简报结果")
        sections["run_id"] = str(run_id)

    async with SessionFactory() as session:
        brief = await session.get(DailyBrief, brief_id)
        if brief is None:
            return
        brief.sections = sections
        brief.content = content
        brief.status = "completed"
        brief.completed_at = utc_now()
        brief.error = ""
        await session.commit()


async def mark_brief_failed(brief_id: UUID, exc: Exception) -> None:
    async with SessionFactory() as session:
        brief = await session.get(DailyBrief, brief_id)
        if brief is None:
            return
        brief.status = "failed"
        brief.error = f"{type(exc).__name__}: {exc}"
        brief.completed_at = utc_now()
        await session.commit()


async def run_due_brief_schedules(ctx: dict[str, Any]) -> None:
    if not get_settings().automation_scheduler_enabled:
        return
    now = utc_now()
    brief_ids: list[UUID] = []
    async with SessionFactory() as session:
        schedules = list(
            await session.scalars(
                select(BriefSchedule)
                .where(
                    BriefSchedule.enabled.is_(True),
                    BriefSchedule.next_run_at.is_not(None),
                    BriefSchedule.next_run_at <= now,
                )
                .with_for_update(skip_locked=True)
            )
        )
        for schedule in schedules:
            brief = DailyBrief(
                user_id=schedule.user_id,
                schedule_id=schedule.id,
                title=f"{schedule.name} · {now.astimezone(ZoneInfo(schedule.timezone)):%Y-%m-%d}",
                topics=schedule.topics,
                include_email=schedule.include_email,
                include_calendar=schedule.include_calendar,
                include_memory=schedule.include_memory,
                source="scheduled",
            )
            session.add(brief)
            await session.flush()
            brief_ids.append(brief.id)
            schedule.last_run_at = now
            schedule.next_run_at = next_schedule_run(
                local_time=schedule.local_time,
                timezone_name=schedule.timezone,
                weekdays=schedule.weekdays,
                after=now + timedelta(seconds=1),
            )
        await session.commit()
    redis = ctx.get("redis")
    for brief_id in brief_ids:
        if redis is not None:
            await redis.enqueue_job(
                "generate_daily_brief_job",
                str(brief_id),
                _job_id=f"daily-brief:{brief_id}",
            )
        else:
            await generate_daily_brief(brief_id)


async def _collect_email() -> dict[str, Any]:
    backend = get_email_backend()
    if not backend.configured:
        return {"items": [], "warnings": ["邮箱未配置，已跳过邮件摘要。"]}
    messages = await asyncio.to_thread(backend.list_recent, limit=8, unread_only=True)
    return {
        "items": [
            {
                "uid": item.uid,
                "from": item.from_address,
                "subject": item.subject,
                "sent_at": item.sent_at,
                "snippet": item.snippet,
            }
            for item in messages
        ]
    }


async def _collect_calendar(user_id: UUID) -> dict[str, Any]:
    now = utc_now()
    end = now + timedelta(days=1)
    async with SessionFactory() as session:
        events = list(
            await session.scalars(
                select(CalendarEvent)
                .where(
                    CalendarEvent.status == "active",
                    CalendarEvent.user_id == user_id,
                    CalendarEvent.end_at >= now,
                    CalendarEvent.start_at < end,
                )
                .order_by(CalendarEvent.start_at)
                .limit(12)
            )
        )
        todos = list(
            await session.scalars(
                select(TodoItem)
                .where(
                    TodoItem.user_id == user_id,
                    TodoItem.status.in_(["todo", "in_progress"]),
                )
                .order_by(TodoItem.due_at.is_(None), TodoItem.due_at)
                .limit(12)
            )
        )
    items = [
        {
            "kind": "event",
            "title": item.title,
            "start_at": item.start_at.isoformat(),
            "end_at": item.end_at.isoformat(),
            "location": item.location,
        }
        for item in events
    ]
    items.extend(
        {
            "kind": "todo",
            "title": item.title,
            "due_at": item.due_at.isoformat() if item.due_at else None,
            "priority": item.priority,
            "overdue": bool(item.due_at and _as_utc(item.due_at) < now),
        }
        for item in todos
    )
    return {"items": items}


async def _collect_memories(user_id: UUID) -> dict[str, Any]:
    async with SessionFactory() as session:
        memories = list(
            await session.scalars(
                select(UserMemory)
                .where(UserMemory.user_id == user_id, UserMemory.enabled.is_(True))
                .order_by(UserMemory.updated_at.desc())
                .limit(8)
            )
        )
    return {
        "items": [
            {"type": item.memory_type, "content": item.content, "confidence": item.confidence}
            for item in memories
        ]
    }


async def _collect_news(topics: list[str]) -> dict[str, Any]:
    settings = get_settings()
    if settings.web_search_provider != "tavily" or not settings.tavily_api_key:
        return {"items": [], "warnings": ["联网搜索未配置，已跳过热点新闻。"]}

    async def search(topic: str) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                settings.tavily_base_url,
                json={
                    "api_key": settings.tavily_api_key,
                    "query": f"{topic} 今日最新重要新闻",
                    "topic": "news",
                    "search_depth": "advanced",
                    "max_results": min(settings.tavily_max_results, 5),
                },
            )
            response.raise_for_status()
        return [
            {
                "topic": topic,
                "title": item.get("title", "未命名来源"),
                "url": item.get("url", ""),
                "snippet": item.get("content", "")[:360],
                "score": item.get("score", 0),
            }
            for item in response.json().get("results", [])
        ]

    batches = await asyncio.gather(*(search(topic) for topic in topics), return_exceptions=True)
    items: list[dict[str, Any]] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for topic, batch in zip(topics, batches, strict=True):
        if isinstance(batch, Exception):
            warnings.append(f"主题“{topic}”搜索失败：{type(batch).__name__}")
            continue
        for item in batch:
            key = item["url"] or item["title"]
            if key in seen:
                continue
            seen.add(key)
            items.append(item)
    return {"items": items[:20], "warnings": warnings}


async def _empty_result() -> dict[str, Any]:
    return {"items": []}


def _build_priorities(sections: dict[str, Any]) -> list[str]:
    priorities: list[str] = []
    unread = sections.get("email", [])
    if unread:
        priorities.append(f"处理 {len(unread)} 封未读邮件")
    calendar_items = sections.get("calendar", [])
    events = [item for item in calendar_items if item.get("kind") == "event"]
    overdue = [item for item in calendar_items if item.get("overdue")]
    if events:
        priorities.append(f"关注未来 24 小时内的 {len(events)} 个日程")
    if overdue:
        priorities.append(f"处理 {len(overdue)} 个已逾期待办")
    if sections.get("news"):
        priorities.append("查看关注主题的重要变化")
    return priorities or ["当前没有需要立即处理的事项"]


def _build_summary(sections: dict[str, Any]) -> str:
    calendar_items = sections.get("calendar", [])
    events = sum(item.get("kind") == "event" for item in calendar_items)
    todos = sum(item.get("kind") == "todo" for item in calendar_items)
    return (
        f"本次汇总 {len(sections.get('email', []))} 封未读邮件、{events} 个近期日程、"
        f"{todos} 个待办和 {len(sections.get('news', []))} 条主题资讯。"
    )


def _render_markdown(sections: dict[str, Any]) -> str:
    lines = ["# 今日简报", "", sections["summary"], "", "## 今日重点"]
    lines.extend(f"- {item}" for item in sections["priorities"])
    lines.extend(["", "## 邮件"])
    lines.extend(
        f"- **{item['subject']}** · {item['from']}" for item in sections.get("email", [])
    )
    lines.extend(["", "## 日程与待办"])
    lines.extend(f"- {item['title']}" for item in sections.get("calendar", []))
    lines.extend(["", "## 值得关注"])
    lines.extend(
        f"- [{item['title']}]({item['url']})" for item in sections.get("news", [])
    )
    if sections.get("warnings"):
        lines.extend(["", "## 数据源提示"])
        lines.extend(f"- {item}" for item in sections["warnings"])
    return "\n".join(lines)
