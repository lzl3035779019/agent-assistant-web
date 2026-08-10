from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pmaa_web.models import UserMemory, utc_now

MEMORY_TYPES = {"profile", "preference", "project", "instruction"}


@dataclass(slots=True)
class MemoryCandidate:
    memory_type: str
    content: str
    confidence: float


def normalize_memory(content: str) -> str:
    return re.sub(r"[\W_]+", "", content, flags=re.UNICODE).lower()


def memory_key(content: str) -> str:
    return hashlib.sha256(normalize_memory(content).encode("utf-8")).hexdigest()


def validate_candidate(candidate: MemoryCandidate) -> tuple[bool, str]:
    content = candidate.content.strip()
    lowered = content.lower()
    if candidate.memory_type not in MEMORY_TYPES:
        return False, "unsupported_type"
    if candidate.confidence < 0.65:
        return False, "low_confidence"
    if len(content) < 4:
        return False, "too_short"
    sensitive = (
        "api key",
        "apikey",
        "secret",
        "token",
        "password",
        "密码",
        "授权码",
        "身份证",
        "银行卡",
        "私钥",
        "sk-",
        "github_pat_",
    )
    if any(item in lowered for item in sensitive):
        return False, "sensitive_content"
    if any(item in content for item in ("今天的天气", "当前股价", "实时新闻", "本次搜索")):
        return False, "transient_information"
    if candidate.memory_type != "preference" and any(
        item in content for item in ("帮我", "请问", "查询", "搜索一下", "？", "?")
    ):
        return False, "task_request"
    return True, "stable_user_memory"


def extract_candidates(user_input: str) -> list[MemoryCandidate]:
    """Extract explicit stable facts locally; no conversation is sent to a third party."""
    text = user_input.strip()
    candidates: list[MemoryCandidate] = []
    name = re.search(r"(?:我叫|我的名字是)\s*([\u4e00-\u9fffA-Za-z0-9_-]{2,24})", text)
    if name:
        candidates.append(MemoryCandidate("profile", f"用户的名字是{name.group(1)}。", 0.92))

    preference = re.search(r"((?:我)?(?:喜欢|偏好|关注|不喜欢)[^。！？?]{1,160})", text)
    if preference:
        value = re.split(r"(?:，|,)?(?:请|帮我|你可以|给我)", preference.group(1))[0].strip("，,。 ")
        if value:
            candidates.append(MemoryCandidate("preference", f"用户{value.lstrip('我')}。", 0.84))

    explicit_instruction = any(
        marker in text for marker in ("以后回答", "以后都", "不要再", "必须")
    )
    standalone_reminder = text.startswith("记住") and not candidates
    if explicit_instruction or standalone_reminder:
        instruction = re.split(r"[。！？?]", text, maxsplit=1)[0].strip()
        candidates.append(MemoryCandidate("instruction", f"用户长期指令：{instruction}", 0.8))

    if any(marker in text.lower() for marker in ("我的项目", "项目使用", "项目基于", "pmaa")):
        fact = re.split(r"[。！？?]", text, maxsplit=1)[0].strip()
        candidates.append(MemoryCandidate("project", f"用户项目事实：{fact}", 0.74))
    return candidates


async def consolidate_memories(
    session: AsyncSession,
    *,
    user_id: UUID,
    user_input: str,
    source_conversation_id: UUID | None,
    source_message_id: UUID | None,
) -> dict[str, Any]:
    candidates = extract_candidates(user_input)
    return await persist_memory_candidates(
        session,
        user_id=user_id,
        candidates=candidates,
        source_conversation_id=source_conversation_id,
        source_message_id=source_message_id,
    )


async def persist_memory_candidates(
    session: AsyncSession,
    *,
    user_id: UUID,
    candidates: list[MemoryCandidate],
    source_conversation_id: UUID | None,
    source_message_id: UUID | None,
) -> dict[str, Any]:
    """Validate again at the persistence boundary and upsert accepted memories."""
    validations: list[dict[str, Any]] = []
    saved: list[UserMemory] = []
    for candidate in candidates:
        should_save, reason = validate_candidate(candidate)
        validations.append(
            {
                "type": candidate.memory_type,
                "content": candidate.content,
                "confidence": candidate.confidence,
                "should_save": should_save,
                "reason": reason,
            }
        )
        if not should_save:
            continue
        key = memory_key(candidate.content)
        existing = await session.scalar(
            select(UserMemory).where(
                UserMemory.user_id == user_id,
                UserMemory.memory_type == candidate.memory_type,
                UserMemory.memory_key == key,
            )
        )
        if existing:
            existing.confidence = max(existing.confidence, candidate.confidence)
            existing.enabled = True
            existing.validation_reason = reason
            existing.source_conversation_id = source_conversation_id
            existing.source_message_id = source_message_id
            existing.updated_at = utc_now()
            saved.append(existing)
            continue
        record = UserMemory(
            user_id=user_id,
            memory_type=candidate.memory_type,
            content=candidate.content,
            memory_key=key,
            source_conversation_id=source_conversation_id,
            source_message_id=source_message_id,
            source="user",
            confidence=candidate.confidence,
            validation_reason=reason,
        )
        session.add(record)
        saved.append(record)
    await session.commit()
    return {
        "candidate_count": len(candidates),
        "saved_count": len(saved),
        "validations": validations,
        "saved_ids": [str(item.id) for item in saved],
    }


async def retrieve_memories(
    session: AsyncSession,
    *,
    user_id: UUID,
    query: str,
    limit: int = 5,
) -> list[UserMemory]:
    records = list(
        await session.scalars(
            select(UserMemory)
            .where(UserMemory.user_id == user_id, UserMemory.enabled.is_(True))
            .order_by(UserMemory.updated_at.desc())
            .limit(200)
        )
    )
    query_terms = _terms(query)
    scored: list[tuple[float, UserMemory]] = []
    for record in records:
        overlap = len(query_terms & _terms(record.content)) / max(len(query_terms), 1)
        baseline = 0.18 if record.memory_type in {"profile", "preference", "instruction"} else 0.0
        score = overlap + baseline + record.confidence * 0.05
        if score > 0:
            scored.append((score, record))
    selected = [item for _, item in sorted(scored, key=lambda row: row[0], reverse=True)[:limit]]
    if selected:
        now = utc_now()
        for record in selected:
            record.usage_count += 1
            record.last_used_at = now
        await session.commit()
    return selected


def _terms(text: str) -> set[str]:
    compact = normalize_memory(text)
    terms = set(re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", compact))
    chinese = "".join(re.findall(r"[\u4e00-\u9fff]", compact))
    terms.update(chinese[index : index + 2] for index in range(max(0, len(chinese) - 1)))
    return {item for item in terms if item}
