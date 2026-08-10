from __future__ import annotations

from typing import Any
from uuid import UUID

from qdrant_client import AsyncQdrantClient, models

from pmaa_web.config import get_settings
from pmaa_web.knowledge.providers import embed_texts, embedding_enabled


async def index_chunks(chunks: list[dict[str, Any]]) -> bool:
    if not chunks or not embedding_enabled():
        return False
    settings = get_settings()
    vectors = await embed_texts([item["content"] for item in chunks])
    client = AsyncQdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key or None)
    try:
        if not await client.collection_exists(settings.qdrant_collection):
            await client.create_collection(
                collection_name=settings.qdrant_collection,
                vectors_config=models.VectorParams(
                    size=settings.embedding_dimensions,
                    distance=models.Distance.COSINE,
                ),
            )
        await client.upsert(
            collection_name=settings.qdrant_collection,
            points=[
                models.PointStruct(id=item["id"], vector=vector, payload=item)
                for item, vector in zip(chunks, vectors, strict=True)
            ],
            wait=True,
        )
    finally:
        await client.close()
    return True


async def vector_search(query: str, *, user_id: UUID, limit: int = 20) -> list[dict[str, Any]]:
    if not embedding_enabled():
        return []
    settings = get_settings()
    vector = (await embed_texts([query]))[0]
    client = AsyncQdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key or None)
    try:
        if not await client.collection_exists(settings.qdrant_collection):
            return []
        response = await client.query_points(
            collection_name=settings.qdrant_collection,
            query=vector,
            query_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="user_id", match=models.MatchValue(value=str(user_id))
                    )
                ]
            ),
            limit=limit,
            with_payload=True,
        )
        return [
            {**(point.payload or {}), "vector_score": float(point.score)}
            for point in response.points
        ]
    finally:
        await client.close()


async def delete_document_vectors(document_id: UUID) -> None:
    if not embedding_enabled():
        return
    settings = get_settings()
    client = AsyncQdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key or None)
    try:
        if await client.collection_exists(settings.qdrant_collection):
            await client.delete(
                collection_name=settings.qdrant_collection,
                points_selector=models.FilterSelector(
                    filter=models.Filter(
                        must=[
                            models.FieldCondition(
                                key="document_id",
                                match=models.MatchValue(value=str(document_id)),
                            )
                        ]
                    )
                ),
                wait=True,
            )
    finally:
        await client.close()
