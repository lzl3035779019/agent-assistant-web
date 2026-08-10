from __future__ import annotations

from typing import Any

import httpx

from pmaa_web.config import get_settings


async def search_web(query: str, max_results: int | None = None) -> list[dict[str, Any]]:
    settings = get_settings()
    if settings.web_search_provider != "tavily":
        raise RuntimeError("WEB_SEARCH_PROVIDER must be tavily for Web Research Agent")
    if not settings.tavily_api_key:
        raise RuntimeError("TAVILY_API_KEY is not configured")
    limit = max_results or settings.tavily_max_results
    async with httpx.AsyncClient(timeout=45) as client:
        response = await client.post(
            settings.tavily_base_url,
            json={
                "api_key": settings.tavily_api_key,
                "query": query,
                "search_depth": "advanced",
                "topic": "general",
                "max_results": limit,
                "include_answer": False,
                "include_raw_content": False,
            },
        )
        response.raise_for_status()
    payload = response.json()
    return [
        {
            "title": str(item.get("title", "未命名来源")),
            "url": str(item.get("url", "")),
            "content": str(item.get("content", "")),
            "score": float(item.get("score", 0.0) or 0.0),
            "query": query,
            "source_type": "web",
        }
        for item in payload.get("results", [])
        if item.get("url")
    ]
