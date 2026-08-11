"""Local, source-linked PDF ingestion and keyword retrieval for the RAG learning slice.

The project intentionally uses a small local JSON index first. A later stage
can replace it with PostgreSQL and vector search without changing citations.
"""

import hashlib
import json
import re
from datetime import date, datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.models import Citation, DocumentRecord

KNOWLEDGE_ROOT = Path(__file__).resolve().parent.parent / "data" / "knowledge"
SOURCE_DOCUMENTS_DIR = KNOWLEDGE_ROOT / "source_documents"
INDEX_PATH = KNOWLEDGE_ROOT / "knowledge_index.json"
MAX_DOCUMENT_BYTES = 15 * 1024 * 1024
CHUNK_SIZE = 500
CHUNK_OVERLAP = 80


def _knowledge_error(code: str, message: str) -> ValueError:
    return ValueError(f"{code}: {message}")


def extract_pdf_pages(file_content: bytes) -> list[str]:
    """Extract page text while preserving the original, one-based page number."""
    try:
        reader = PdfReader(BytesIO(file_content))
        if reader.is_encrypted and reader.decrypt("") == 0:
            raise _knowledge_error("DOCUMENT_ENCRYPTED", "PDF 已加密，当前版本无法解析。")
        return [page.extract_text() or "" for page in reader.pages]
    except PdfReadError as error:
        raise _knowledge_error("DOCUMENT_INVALID_PDF", "文件不是可解析的 PDF。") from error


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def split_page_into_chunks(page_text: str) -> list[str]:
    """Keep every chunk inside one page so its citation is never ambiguous."""
    text = _normalize_text(page_text)
    if not text:
        return []

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + CHUNK_SIZE, len(text))
        if end < len(text):
            boundary = text.rfind(" ", start + CHUNK_SIZE // 2, end)
            if boundary > start:
                end = boundary
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(end - CHUNK_OVERLAP, start + 1)
    return chunks


def _ensure_storage() -> None:
    SOURCE_DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)


def _load_index() -> dict[str, Any]:
    if not INDEX_PATH.exists():
        return {"documents": [], "chunks": []}
    try:
        index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise _knowledge_error("KNOWLEDGE_INDEX_INVALID", "本地知识库索引无法读取。") from error
    if not isinstance(index.get("documents"), list) or not isinstance(index.get("chunks"), list):
        raise _knowledge_error("KNOWLEDGE_INDEX_INVALID", "本地知识库索引结构不合法。")
    return index


def _save_index(index: dict[str, Any]) -> None:
    _ensure_storage()
    temporary_path = INDEX_PATH.with_suffix(".tmp")
    try:
        temporary_path.write_text(
            json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary_path.replace(INDEX_PATH)
    except OSError as error:
        raise _knowledge_error("KNOWLEDGE_STORAGE_UNAVAILABLE", "本地知识库索引写入失败。") from error


def ingest_pdf_document(
    *,
    file_name: str,
    file_content: bytes,
    company_code: str | None,
    company_name: str | None,
    document_type: str,
    published_at: date | None,
) -> DocumentRecord:
    """Persist a public PDF and create page-aware chunks for retrieval."""
    if not file_name.lower().endswith(".pdf") or not file_content.startswith(b"%PDF-"):
        raise _knowledge_error("DOCUMENT_INVALID_PDF", "请上传 PDF 格式的公开资料。")
    if not file_content:
        raise _knowledge_error("DOCUMENT_EMPTY", "上传的 PDF 文件为空。")
    if len(file_content) > MAX_DOCUMENT_BYTES:
        raise _knowledge_error("DOCUMENT_TOO_LARGE", "PDF 超过 15 MB 的学习版限制。")

    pages = extract_pdf_pages(file_content)
    chunks: list[dict[str, Any]] = []
    for page_number, page_text in enumerate(pages, start=1):
        for chunk_index, content in enumerate(split_page_into_chunks(page_text)):
            chunks.append(
                {
                    "page_number": page_number,
                    "chunk_index": chunk_index,
                    "content": content,
                }
            )
    if not chunks:
        raise _knowledge_error(
            "DOCUMENT_NO_EXTRACTABLE_TEXT",
            "PDF 未提取到文本，可能是扫描件；当前版本需要先 OCR。",
        )

    document_id = hashlib.sha256(file_content).hexdigest()[:24]
    index = _load_index()
    if any(document.get("document_id") == document_id for document in index["documents"]):
        raise _knowledge_error("DOCUMENT_ALREADY_EXISTS", "该 PDF 已经入库，无需重复上传。")

    ingested_at = datetime.now(timezone.utc)
    document = DocumentRecord(
        document_id=document_id,
        title=Path(file_name).stem,
        source_file_name=Path(file_name).name,
        company_code=company_code or None,
        company_name=company_name or None,
        document_type=document_type.strip() or "other",
        published_at=published_at,
        page_count=len(pages),
        chunk_count=len(chunks),
        ingested_at=ingested_at,
    )

    _ensure_storage()
    pdf_path = SOURCE_DOCUMENTS_DIR / f"{document_id}.pdf"
    try:
        pdf_path.write_bytes(file_content)
    except OSError as error:
        raise _knowledge_error("KNOWLEDGE_STORAGE_UNAVAILABLE", "PDF 文件保存失败。") from error

    index["documents"].append(document.model_dump(mode="json"))
    index["chunks"].extend(
        {
            "chunk_id": f"{document_id}:{chunk['page_number']}:{chunk['chunk_index']}",
            "document_id": document_id,
            **chunk,
        }
        for chunk in chunks
    )
    _save_index(index)
    return document


def _search_terms(query: str) -> set[str]:
    normalized = _normalize_text(query).lower()
    terms: set[str] = set(re.findall(r"[a-z0-9_]+", normalized))
    for part in re.findall(r"[\u4e00-\u9fff]+", normalized):
        if len(part) == 1:
            terms.add(part)
        else:
            terms.update(part[index : index + 2] for index in range(len(part) - 1))
    return terms


def search_knowledge(
    *, query: str, company_code: str | None = None, limit: int = 5
) -> list[Citation]:
    """Return keyword matches as citations, never model-generated facts."""
    terms = _search_terms(query)
    if not terms:
        return []

    index = _load_index()
    documents = {
        document["document_id"]: document
        for document in index["documents"]
        if not company_code or document.get("company_code") == company_code
    }
    matches: list[Citation] = []
    for chunk in index["chunks"]:
        document = documents.get(chunk.get("document_id"))
        if document is None:
            continue
        content = str(chunk.get("content", ""))
        content_lower = content.lower()
        score = sum(content_lower.count(term) for term in terms)
        if score:
            matches.append(
                Citation(
                    document_id=document["document_id"],
                    title=document["title"],
                    company_code=document.get("company_code"),
                    company_name=document.get("company_name"),
                    document_type=document["document_type"],
                    published_at=document.get("published_at"),
                    page_number=chunk["page_number"],
                    chunk_id=chunk["chunk_id"],
                    excerpt=content,
                    score=score,
                )
            )
    return sorted(matches, key=lambda item: (-item.score, item.document_id, item.page_number))[:limit]
