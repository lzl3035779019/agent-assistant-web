from __future__ import annotations

import re
from dataclasses import dataclass

from pmaa_web.knowledge.parsing import ParsedSection


@dataclass(frozen=True)
class TextChunk:
    index: int
    content: str
    page_number: int | None


def split_sections(
    sections: list[ParsedSection], *, chunk_size: int, overlap: int
) -> list[TextChunk]:
    if chunk_size < 100 or overlap < 0 or overlap >= chunk_size:
        raise ValueError("Invalid chunk configuration")

    chunks: list[TextChunk] = []
    for section in sections:
        normalized = re.sub(r"[ \t]+", " ", section.text)
        normalized = re.sub(r"\n{3,}", "\n\n", normalized).strip()
        start = 0
        while start < len(normalized):
            hard_end = min(start + chunk_size, len(normalized))
            end = _natural_boundary(normalized, start, hard_end)
            content = normalized[start:end].strip()
            if content:
                chunks.append(
                    TextChunk(
                        index=len(chunks),
                        content=content,
                        page_number=section.page_number,
                    )
                )
            if end >= len(normalized):
                break
            start = max(end - overlap, start + 1)
    return chunks


def _natural_boundary(text: str, start: int, hard_end: int) -> int:
    if hard_end >= len(text):
        return len(text)
    floor = start + int((hard_end - start) * 0.65)
    candidates = [
        text.rfind(separator, floor, hard_end) for separator in ("\n\n", "。", "！", "？", ". ")
    ]
    boundary = max(candidates)
    return boundary + 1 if boundary >= floor else hard_end
