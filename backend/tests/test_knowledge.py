from __future__ import annotations

from fastapi.testclient import TestClient
from pmaa_web.knowledge.chunking import split_sections
from pmaa_web.knowledge.parsing import parse_document
from pmaa_web.main import app


def test_text_document_is_parsed_and_chunked() -> None:
    sections = parse_document(
        "agentic-rag.md",
        "Agentic RAG 会规划查询、检索证据并验证答案。".encode(),
    )
    chunks = split_sections(sections, chunk_size=100, overlap=20)

    assert len(sections) == 1
    assert len(chunks) == 1
    assert "验证答案" in chunks[0].content


def test_document_upload_creates_queued_record(monkeypatch) -> None:
    async def fake_upload(*args, **kwargs) -> None:
        return None

    async def fake_dispatch(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr("pmaa_web.api.knowledge.upload_object", fake_upload)
    monkeypatch.setattr("pmaa_web.api.knowledge.dispatch_document_ingestion", fake_dispatch)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/knowledge/documents",
            files={"file": ("knowledge.md", b"Agentic RAG evidence", "text/markdown")},
        )
        assert response.status_code == 202, response.text
        document = response.json()
        assert document["filename"] == "knowledge.md"
        assert document["status"] == "queued"

        listed = client.get("/api/v1/knowledge/documents")
        assert listed.status_code == 200
        assert len(listed.json()) == 1
