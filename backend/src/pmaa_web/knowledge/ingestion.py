from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from arq import create_pool
from arq.connections import RedisSettings
from sqlalchemy import delete

from pmaa_web.config import get_settings
from pmaa_web.database import SessionFactory
from pmaa_web.knowledge.chunking import split_sections
from pmaa_web.knowledge.parsing import parse_document
from pmaa_web.knowledge.storage import download_object
from pmaa_web.knowledge.vector_store import index_chunks
from pmaa_web.models import DocumentChunk, KnowledgeDocument

_ingestion_tasks: set[asyncio.Task[None]] = set()


async def ingest_document(document_id: UUID) -> None:
    async with SessionFactory() as session:
        document = await session.get(KnowledgeDocument, document_id)
        if document is None:
            return
        document.status = "processing"
        document.error = ""
        await session.commit()

        try:
            raw_data = await download_object(document.storage_key)
            settings = get_settings()
            sections = parse_document(document.filename, raw_data)
            chunks = split_sections(
                sections,
                chunk_size=settings.chunk_size,
                overlap=settings.chunk_overlap,
            )
            if not chunks:
                raise ValueError("Document did not produce any chunks")

            await session.execute(
                delete(DocumentChunk).where(DocumentChunk.document_id == document.id)
            )
            vector_payloads: list[dict[str, Any]] = []
            for chunk in chunks:
                chunk_id = uuid4()
                session.add(
                    DocumentChunk(
                        id=chunk_id,
                        document_id=document.id,
                        chunk_index=chunk.index,
                        content=chunk.content,
                        character_count=len(chunk.content),
                        page_number=chunk.page_number,
                        chunk_metadata={},
                    )
                )
                vector_payloads.append(
                    {
                        "id": str(chunk_id),
                        "chunk_id": str(chunk_id),
                        "document_id": str(document.id),
                        "user_id": str(document.user_id),
                        "filename": document.filename,
                        "chunk_index": chunk.index,
                        "page_number": chunk.page_number,
                        "content": chunk.content,
                    }
                )
            document.chunk_count = len(chunks)
            await session.commit()

            warning = ""
            try:
                vector_indexed = await index_chunks(vector_payloads)
            except Exception as exc:
                vector_indexed = False
                warning = f"Vector indexing unavailable; lexical retrieval remains active: {exc}"

            document = await session.get(KnowledgeDocument, document_id)
            if document is None:
                return
            document.status = "indexed"
            document.indexed_at = datetime.now(timezone.utc)
            document.document_metadata = {
                "indexing_mode": "hybrid" if vector_indexed else "lexical",
                "vector_indexed": vector_indexed,
                "warning": warning,
            }
            await session.commit()
        except Exception as exc:
            await session.rollback()
            document = await session.get(KnowledgeDocument, document_id)
            if document is None:
                return
            document.status = "failed"
            document.error = str(exc)
            await session.commit()


async def dispatch_document_ingestion(document_id: UUID) -> None:
    settings = get_settings()
    if settings.task_execution_mode == "arq":
        pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        try:
            await pool.enqueue_job(
                "ingest_document_job",
                str(document_id),
                _job_id=f"document:{document_id}",
            )
        finally:
            await pool.aclose()
        return
    task = asyncio.create_task(ingest_document(document_id))
    _ingestion_tasks.add(task)
    task.add_done_callback(_ingestion_tasks.discard)
