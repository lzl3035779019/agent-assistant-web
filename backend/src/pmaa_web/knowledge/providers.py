from __future__ import annotations

import asyncio
from functools import lru_cache
from typing import Any

import httpx

from pmaa_web.config import get_settings


def embedding_enabled() -> bool:
    settings = get_settings()
    if settings.embedding_provider == "fastembed":
        return bool(settings.embedding_model)
    if settings.embedding_provider == "openai_compatible":
        return bool(settings.embedding_base_url and settings.embedding_model)
    return False


async def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    settings = get_settings()
    if not embedding_enabled():
        raise RuntimeError("Embedding provider is not configured")
    if settings.embedding_provider == "fastembed":
        return await asyncio.to_thread(
            _embed_with_fastembed,
            texts,
            settings.embedding_model,
            settings.embedding_dimensions,
            settings.embedding_batch_size,
            settings.fastembed_cache_dir,
            settings.fastembed_threads,
        )

    headers = {}
    if settings.embedding_api_key:
        headers["Authorization"] = f"Bearer {settings.embedding_api_key}"
    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.post(
            f"{settings.embedding_base_url.rstrip('/')}/embeddings",
            headers=headers,
            json={"model": settings.embedding_model, "input": texts},
        )
        response.raise_for_status()
        data: list[dict[str, Any]] = response.json()["data"]
    vectors = [item["embedding"] for item in sorted(data, key=lambda item: item["index"])]
    if vectors and len(vectors[0]) != settings.embedding_dimensions:
        raise ValueError(
            "Embedding dimension mismatch: "
            f"expected {settings.embedding_dimensions}, got {len(vectors[0])}"
        )
    return vectors


@lru_cache(maxsize=4)
def _load_fastembed_model(model_name: str, cache_dir: str, threads: int | None) -> Any:
    from fastembed import TextEmbedding

    return TextEmbedding(model_name=model_name, cache_dir=cache_dir, threads=threads)


def _embed_with_fastembed(
    texts: list[str],
    model_name: str,
    expected_dimensions: int,
    batch_size: int,
    cache_dir: str,
    threads: int | None,
) -> list[list[float]]:
    model = _load_fastembed_model(model_name, cache_dir, threads)
    vectors = [vector.tolist() for vector in model.embed(texts, batch_size=batch_size)]
    actual_dimensions = len(vectors[0]) if vectors else 0
    if actual_dimensions != expected_dimensions:
        raise ValueError(
            "Embedding dimension mismatch: "
            f"expected {expected_dimensions}, got {actual_dimensions}"
        )
    return vectors


async def generate_grounded_answer(
    query: str,
    evidence: list[dict[str, Any]],
) -> str:
    settings = get_settings()
    api_key = settings.llm_api_key or settings.deepseek_api_key
    if not api_key:
        return _extractive_fallback(evidence)

    context = "\n\n".join(_format_evidence(item) for item in evidence)
    payload = {
        "model": settings.llm_model,
        "temperature": 0.2,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是企业知识库助手。只能依据给定证据回答；证据不足时必须明确说明。"
                    "每个事实后使用 [S1] 形式引用，不得编造来源。"
                ),
            },
            {"role": "user", "content": f"问题：{query}\n\n证据：\n{context}"},
        ],
    }
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            f"{settings.llm_base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
        )
        response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"].strip()


def _extractive_fallback(evidence: list[dict[str, Any]]) -> str:
    if not evidence:
        return "知识库中没有检索到足够证据，暂时无法回答。"
    lines = ["当前未配置 LLM，以下是从知识库检索到的相关证据："]
    for item in evidence[:5]:
        excerpt = item["content"].replace("\n", " ").strip()
        if len(excerpt) > 320:
            excerpt = f"{excerpt[:320]}..."
        lines.append(f"- {excerpt} [{item['citation_id']}]")
    return "\n\n".join(lines)


def _format_evidence(item: dict[str, Any]) -> str:
    page = f"，第 {item['page_number']} 页" if item.get("page_number") else ""
    return f"[{item['citation_id']}] 文件：{item['filename']}{page}\n{item['content']}"
