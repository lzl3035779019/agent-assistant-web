from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pmaa_web.config import get_settings
from pmaa_web.knowledge.vector_store import vector_search
from pmaa_web.models import DocumentChunk, KnowledgeDocument


async def retrieve_evidence(
    session: AsyncSession, query: str, *, user_id: UUID
) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(DocumentChunk, KnowledgeDocument.filename)
            .join(KnowledgeDocument, KnowledgeDocument.id == DocumentChunk.document_id)
            .where(
                KnowledgeDocument.user_id == user_id,
                KnowledgeDocument.status == "indexed",
            )
            .order_by(KnowledgeDocument.created_at.desc(), DocumentChunk.chunk_index)
            .limit(5000)
        )
    ).all()
    lexical_ranked = _bm25(query, rows)
    try:
        vector_ranked = await vector_search(query, user_id=user_id, limit=30)
    except Exception:
        vector_ranked = []

    details: dict[str, dict[str, Any]] = {}
    lexical_scores: dict[str, float] = {}
    for chunk, filename, score in lexical_ranked:
        chunk_id = str(chunk.id)
        lexical_scores[chunk_id] = score
        details[chunk_id] = {
            "chunk_id": chunk_id,
            "document_id": str(chunk.document_id),
            "filename": filename,
            "chunk_index": chunk.chunk_index,
            "page_number": chunk.page_number,
            "content": chunk.content,
        }
    for item in vector_ranked:
        details.setdefault(str(item["chunk_id"]), item)

    combined: Counter[str] = Counter()
    for rank, (chunk, _, score) in enumerate(lexical_ranked, start=1):
        if score > 0:
            combined[str(chunk.id)] += 1 / (60 + rank)
    for rank, item in enumerate(vector_ranked, start=1):
        combined[str(item["chunk_id"])] += 1 / (60 + rank)

    max_lexical = max(lexical_scores.values(), default=0.0)
    vector_scores = {
        str(item["chunk_id"]): float(item.get("vector_score", 0)) for item in vector_ranked
    }
    evidence: list[dict[str, Any]] = []
    top_k = get_settings().retrieval_top_k
    for index, (chunk_id, rrf_score) in enumerate(combined.most_common(top_k), start=1):
        item = details[chunk_id]
        lexical_relevance = lexical_scores.get(chunk_id, 0) / max_lexical if max_lexical else 0
        relevance = max(vector_scores.get(chunk_id, 0), lexical_relevance * 0.8)
        evidence.append(
            {
                **item,
                "citation_id": f"S{index}",
                "score": round(relevance, 4),
                "rrf_score": round(rrf_score, 6),
            }
        )
    return evidence


def _bm25(query: str, rows: list[Any]) -> list[tuple[DocumentChunk, str, float]]:
    query_terms = _tokenize(query)
    if not query_terms or not rows:
        return []
    documents = [_tokenize(chunk.content) for chunk, _ in rows]
    average_length = max(sum(map(len, documents)) / max(len(documents), 1), 1.0)
    document_frequency: Counter[str] = Counter()
    for tokens in documents:
        document_frequency.update(set(tokens))

    ranked: list[tuple[DocumentChunk, str, float]] = []
    total = len(documents)
    for (chunk, filename), tokens in zip(rows, documents, strict=True):
        frequencies = Counter(tokens)
        score = 0.0
        for term in query_terms:
            frequency = frequencies.get(term, 0)
            if not frequency:
                continue
            idf = math.log(
                1 + (total - document_frequency[term] + 0.5) / (document_frequency[term] + 0.5)
            )
            denominator = frequency + 1.2 * (1 - 0.75 + 0.75 * len(tokens) / average_length)
            score += idf * frequency * 2.2 / denominator
        if score > 0:
            ranked.append((chunk, filename, score))
    return sorted(ranked, key=lambda item: item[2], reverse=True)[:30]


def _tokenize(text: str) -> list[str]:
    normalized = text.lower()
    ascii_terms = re.findall(r"[a-z0-9][a-z0-9_+.-]{1,}", normalized)
    chinese = "".join(re.findall(r"[\u4e00-\u9fff]", normalized))
    chinese_terms = list(chinese)
    chinese_terms.extend(chinese[index : index + 2] for index in range(len(chinese) - 1))
    return ascii_terms + chinese_terms
