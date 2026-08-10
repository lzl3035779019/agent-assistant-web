from __future__ import annotations

import json
import re
from typing import Any

import httpx

from pmaa_web.config import get_settings


def llm_available() -> bool:
    settings = get_settings()
    return bool((settings.llm_api_key or settings.deepseek_api_key) and settings.llm_model)


async def chat_completion(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.2,
    json_mode: bool = False,
) -> str:
    settings = get_settings()
    api_key = settings.llm_api_key or settings.deepseek_api_key
    if not api_key:
        raise RuntimeError("LLM API key is not configured")
    payload: dict[str, Any] = {
        "model": settings.llm_model,
        "temperature": temperature,
        "messages": messages,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            f"{settings.llm_base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
        )
        response.raise_for_status()
    return str(response.json()["choices"][0]["message"]["content"]).strip()


def parse_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, re.DOTALL)
        if not match:
            raise ValueError("LLM response does not contain a JSON object")
        value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("LLM response must be a JSON object")
    return value


async def generate_direct_answer(
    objective: str,
) -> str:
    if get_settings().app_env == "test":
        return "任务已由 Supervisor 直接处理。"
    if not llm_available():
        return "当前未配置可用的 LLM，无法生成自然语言回答。请先检查 LLM_API_KEY。"
    return await chat_completion(
        [
            {
                "role": "system",
                "content": (
                    "你是 PMAA 个人智能助手。直接回答不需要外部工具的请求。"
                    "不要声称调用了未调用的工具，也不要编造外部事实。"
                ),
            },
            {"role": "user", "content": objective},
        ]
    )


async def generate_research_answer(
    objective: str,
    evidence: list[dict[str, Any]],
) -> str:
    if not evidence:
        return "未检索到可用的联网证据，无法形成可靠结论。"
    if not llm_available():
        lines = ["未配置可用 LLM，以下为联网检索到的证据摘要："]
        for item in evidence[:8]:
            lines.append(
                f"- {item.get('title', '未命名来源')}：{item.get('content', '')} "
                f"[{item.get('citation_id', 'S?')}]"
            )
        return "\n\n".join(lines)
    context = "\n\n".join(
        f"[{item['citation_id']}] {item.get('title', '')}\n"
        f"URL: {item.get('url', '')}\n{item.get('content', '')}"
        for item in evidence
    )
    return await chat_completion(
        [
            {
                "role": "system",
                "content": (
                    "你是 Web Research Agent。只依据联网证据形成研究结论，区分事实与推断。"
                    "关键事实必须使用 [S1] 形式引用；来源冲突或时效不明时明确提示。"
                    "结尾给出简洁的资料来源列表，不得编造 URL。"
                ),
            },
            {"role": "user", "content": f"研究目标：{objective}\n\n证据：\n{context}"},
        ]
    )
