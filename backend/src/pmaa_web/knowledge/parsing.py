from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from docx import Document as DocxDocument
from pypdf import PdfReader


@dataclass(frozen=True)
class ParsedSection:
    text: str
    page_number: int | None = None


SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".md", ".markdown", ".txt"}


def parse_document(filename: str, data: bytes) -> list[ParsedSection]:
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported document type: {extension or 'unknown'}")

    if extension == ".pdf":
        reader = PdfReader(BytesIO(data))
        sections = [
            ParsedSection(text=(page.extract_text() or "").strip(), page_number=index + 1)
            for index, page in enumerate(reader.pages)
        ]
    elif extension == ".docx":
        document = DocxDocument(BytesIO(data))
        sections = [ParsedSection(text="\n".join(p.text for p in document.paragraphs).strip())]
    else:
        sections = [ParsedSection(text=_decode_text(data).strip())]

    result = [section for section in sections if section.text]
    if not result:
        raise ValueError("No extractable text was found in the document")
    return result


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("Text encoding is not supported")
