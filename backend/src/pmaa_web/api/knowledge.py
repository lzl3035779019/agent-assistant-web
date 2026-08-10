from __future__ import annotations

import re
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pmaa_web.auth_context import current_user_id
from pmaa_web.config import get_settings
from pmaa_web.database import get_session
from pmaa_web.knowledge.ingestion import dispatch_document_ingestion
from pmaa_web.knowledge.storage import delete_object, upload_object
from pmaa_web.knowledge.vector_store import delete_document_vectors
from pmaa_web.models import DocumentChunk, KnowledgeDocument
from pmaa_web.schemas import KnowledgeDocumentRead, KnowledgeStatsRead

router = APIRouter(prefix="/knowledge", tags=["knowledge"])
SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".md", ".markdown", ".txt"}


def _safe_filename(filename: str) -> str:
    base = Path(filename).name.strip()
    cleaned = re.sub(r"[^\w.\-\u4e00-\u9fff]", "_", base)
    return cleaned[:240] or "document.txt"


async def _owned_document(
    session: AsyncSession,
    document_id: UUID,
) -> KnowledgeDocument:
    document = await session.get(KnowledgeDocument, document_id)
    if document is None or document.user_id != current_user_id():
        raise HTTPException(status_code=404, detail="Document not found")
    return document


@router.post(
    "/documents",
    response_model=KnowledgeDocumentRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_document(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
) -> KnowledgeDocument:
    filename = _safe_filename(file.filename or "")
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail="Only PDF, DOCX, Markdown and TXT files are supported",
        )

    settings = get_settings()
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    data = await file.read(max_bytes + 1)
    if not data:
        raise HTTPException(status_code=400, detail="File is empty")
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds {settings.max_upload_size_mb} MB",
        )

    document_id = uuid4()
    storage_key = f"{current_user_id()}/{document_id}/{filename}"
    document = KnowledgeDocument(
        id=document_id,
        user_id=current_user_id(),
        filename=filename,
        storage_key=storage_key,
        content_type=file.content_type or "application/octet-stream",
        size_bytes=len(data),
        status="queued",
    )
    session.add(document)
    await session.commit()
    try:
        await upload_object(storage_key, data, document.content_type)
        await dispatch_document_ingestion(document.id)
    except Exception as exc:
        document.status = "failed"
        document.error = str(exc)
        await session.commit()
        raise HTTPException(status_code=502, detail=f"Upload failed: {exc}") from exc
    return document


@router.get("/documents", response_model=list[KnowledgeDocumentRead])
async def list_documents(
    session: AsyncSession = Depends(get_session),
) -> list[KnowledgeDocument]:
    result = await session.scalars(
        select(KnowledgeDocument)
        .where(KnowledgeDocument.user_id == current_user_id())
        .order_by(KnowledgeDocument.created_at.desc())
    )
    return list(result)


@router.get("/documents/{document_id}", response_model=KnowledgeDocumentRead)
async def get_document(
    document_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> KnowledgeDocument:
    return await _owned_document(session, document_id)


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_document(
    document_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> None:
    document = await _owned_document(session, document_id)
    try:
        await delete_document_vectors(document.id)
        await delete_object(document.storage_key)
    except Exception:
        # Database ownership is authoritative; stale external objects can be cleaned later.
        pass
    await session.delete(document)
    await session.commit()


@router.get("/stats", response_model=KnowledgeStatsRead)
async def knowledge_stats(
    session: AsyncSession = Depends(get_session),
) -> KnowledgeStatsRead:
    statuses = (
        await session.execute(
            select(KnowledgeDocument.status, func.count(KnowledgeDocument.id))
            .where(KnowledgeDocument.user_id == current_user_id())
            .group_by(KnowledgeDocument.status)
        )
    ).all()
    status_counts = {name: count for name, count in statuses}
    chunk_count = await session.scalar(
        select(func.count(DocumentChunk.id))
        .join(KnowledgeDocument)
        .where(KnowledgeDocument.user_id == current_user_id())
    )
    return KnowledgeStatsRead(
        document_count=sum(status_counts.values()),
        indexed_count=status_counts.get("indexed", 0),
        processing_count=status_counts.get("queued", 0) + status_counts.get("processing", 0),
        failed_count=status_counts.get("failed", 0),
        chunk_count=chunk_count or 0,
    )
