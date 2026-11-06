"""Local, source-linked PDF ingestion and keyword retrieval for the RAG learning slice.

The project intentionally uses a small local JSON index first. A later stage
can replace it with PostgreSQL and vector search without changing citations.
"""

import hashlib
import json
import logging
import re
from datetime import date, datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.config import get_settings
from app.embeddings import EmbeddingProvider, create_embedding_provider, cosine_similarity
from app.models import Citation, DocumentRecord, RetrievalDiagnostics

KNOWLEDGE_ROOT = Path(__file__).resolve().parent.parent / "data" / "knowledge"
SOURCE_DOCUMENTS_DIR = KNOWLEDGE_ROOT / "source_documents"
INDEX_PATH = KNOWLEDGE_ROOT / "knowledge_index.json"
MAX_DOCUMENT_BYTES = 15 * 1024 * 1024
CHUNK_SIZE = 500
CHUNK_OVERLAP = 80
EMBEDDING_BATCH_SIZE = 10
logger = logging.getLogger(__name__)


def _knowledge_error(code: str, message: str) -> ValueError:
    return ValueError(f"{code}: {message}")


def _resolve_embedding_provider(provider: EmbeddingProvider | None) -> EmbeddingProvider:
    """Read runtime configuration only when callers did not inject a provider."""
    return provider if provider is not None else create_embedding_provider(get_settings())


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
    report_year: int | None = None,
    embedding_provider: EmbeddingProvider | None = None,
) -> DocumentRecord:
    """Persist a public PDF and create page-aware chunks for retrieval."""
    if not file_name.lower().endswith(".pdf") or not file_content.startswith(b"%PDF-"):
        raise _knowledge_error("DOCUMENT_INVALID_PDF", "请上传 PDF 格式的公开资料。")
    if not file_content:
        raise _knowledge_error("DOCUMENT_EMPTY", "上传的 PDF 文件为空。")
    if len(file_content) > MAX_DOCUMENT_BYTES:
        raise _knowledge_error("DOCUMENT_TOO_LARGE", "PDF 超过 15 MB 的学习版限制。")

    # Reject duplicates before PDF parsing and billable embedding requests.
    document_id = hashlib.sha256(file_content).hexdigest()[:24]
    if any(document.get("document_id") == document_id for document in _load_index()["documents"]):
        raise _knowledge_error("DOCUMENT_ALREADY_EXISTS", "该 PDF 已经入库，无需重复上传。")

    provider = _resolve_embedding_provider(embedding_provider)
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
    if provider.dimension:
        _add_chunk_embeddings(chunks, provider)

    # Reload after slow external calls so unrelated completed uploads are retained.
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
        report_year=report_year,
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


def _add_chunk_embeddings(chunks: list[dict[str, Any]], provider: EmbeddingProvider) -> None:
    """Embed in small batches so a long report does not make one request per chunk."""
    for start in range(0, len(chunks), EMBEDDING_BATCH_SIZE):
        batch = chunks[start : start + EMBEDDING_BATCH_SIZE]
        vectors = provider.embed_many([str(chunk["content"]) for chunk in batch])
        if len(vectors) != len(batch):
            raise _knowledge_error("EMBEDDING_INVALID_RESPONSE", "向量数量与资料分块数量不一致。")
        for chunk, vector in zip(batch, vectors, strict=True):
            if len(vector) != provider.dimension:
                raise _knowledge_error("EMBEDDING_DIMENSION_MISMATCH", "返回向量维度不正确。")
            chunk["embedding"] = vector
            chunk["embedding_provider"] = provider.name
            chunk["embedding_dimension"] = provider.dimension


def rebuild_knowledge_embeddings(embedding_provider: EmbeddingProvider | None = None) -> int:
    """Generate vectors for all locally indexed chunks after enabling a provider.

    This is safe to run repeatedly. It replaces only embedding-related fields,
    preserves original PDF text/page citations, and does nothing when vectors
    are intentionally disabled.
    """
    provider = _resolve_embedding_provider(embedding_provider)
    if not provider.dimension:
        raise _knowledge_error("EMBEDDING_DISABLED", "请先配置可用的向量 Provider。")
    index = _load_index()
    chunks = index["chunks"]
    if not chunks:
        return 0
    for chunk in chunks:
        chunk.pop("embedding", None)
        chunk.pop("embedding_provider", None)
        chunk.pop("embedding_dimension", None)
    _add_chunk_embeddings(chunks, provider)
    _save_index(index)
    return len(chunks)


def _search_terms(query: str) -> set[str]:
    normalized = _normalize_text(query).lower()
    terms: set[str] = set(re.findall(r"[a-z0-9_]+", normalized))
    for part in re.findall(r"[\u4e00-\u9fff]+", normalized):
        if len(part) == 1:
            terms.add(part)
        else:
            terms.update(part[index : index + 2] for index in range(len(part) - 1))
    return terms


def _keyword_coverage_score(content: str, terms: set[str]) -> float:
    """Score keyword retrieval by distinct-query-term coverage, not repetition.

    Annual reports repeat company names in page headers. Counting every repeated
    hit would make those headers outweigh an otherwise more relevant semantic
    match, so each query term can contribute at most once per chunk.
    """
    if not terms:
        return 0.0
    content_lower = content.lower()
    matched_terms = sum(term in content_lower for term in terms)
    return matched_terms / len(terms)


def search_knowledge(
    *,
    query: str,
    company_code: str | None = None,
    report_year: int | None = None,
    limit: int = 5,
    embedding_provider: EmbeddingProvider | None = None,
    diagnostics: RetrievalDiagnostics | None = None,
) -> list[Citation]:
    """Return hybrid keyword/vector matches as source-linked citations.

    Missing or legacy chunk vectors fall back to keyword-only scoring, allowing
    a gradual re-index instead of breaking previously uploaded documents.
    """
    diagnostics = diagnostics if diagnostics is not None else RetrievalDiagnostics()
    terms = _search_terms(query)
    if not terms:
        diagnostics.outcome = "no_matches"
        return []

    index = _load_index()
    documents = {
        document["document_id"]: document
        for document in index["documents"]
        if (not company_code or document.get("company_code") == company_code)
        and (report_year is None or document.get("report_year") == report_year)
    }
    diagnostics.matched_document_count = len(documents)
    if not documents:
        diagnostics.outcome = "no_documents"
        return []

    provider = _resolve_embedding_provider(embedding_provider)
    try:
        query_embedding = provider.embed(query) if provider.dimension else []
    except ValueError as error:
        if not _can_fall_back_to_keyword_search(error):
            raise
        # A temporary provider outage must not make the already-ingested public
        # source text unavailable. The caller still receives page citations,
        # merely without semantic-vector ranking for this one search.
        logger.warning("Embedding unavailable; falling back to keyword retrieval: %s", error)
        query_embedding = []
        diagnostics.degraded = True
        diagnostics.warning_code = str(error).split(":", 1)[0]

    diagnostics.mode = "hybrid" if query_embedding else "keyword"
    vector_matches = False
    matches: list[tuple[float, float, Citation]] = []
    for chunk in index["chunks"]:
        document = documents.get(chunk.get("document_id"))
        if document is None:
            continue
        content = str(chunk.get("content", ""))
        keyword_score = _keyword_coverage_score(content, terms)
        vector_score = _chunk_vector_score(chunk, query_embedding, provider)
        vector_matches = vector_matches or vector_score > 0
        if keyword_score > 0 or vector_score > 0:
            matches.append(
                (
                    keyword_score,
                    vector_score,
                    Citation(
                        document_id=document["document_id"],
                        title=document["title"],
                        company_code=document.get("company_code"),
                        company_name=document.get("company_name"),
                        document_type=document["document_type"],
                        published_at=document.get("published_at"),
                        report_year=document.get("report_year"),
                        page_number=chunk["page_number"],
                        chunk_id=chunk["chunk_id"],
                        excerpt=content,
                        score=1,
                    ),
                )
            )
    if query_embedding and not vector_matches:
        diagnostics.mode = "keyword"
        diagnostics.warning_code = "NO_USABLE_VECTOR_MATCHES"
    citations = _rank_knowledge_matches(matches, limit)
    diagnostics.outcome = "candidates" if citations else "no_matches"
    return citations


def expand_evidence_context(citations: list[Citation], max_chunks: int = 15) -> list[Citation]:
    """Add immediate same-page neighbors for chat assessment, without re-embedding.

    Preserve ranked candidates first. Context inherits the seed's ranking score;
    it is not a new independently ranked search result.
    """
    if not citations:
        return []
    index = _load_index()
    pages: dict[tuple[str, int], list[dict]] = {}
    for chunk in index["chunks"]:
        pages.setdefault((chunk["document_id"], chunk["page_number"]), []).append(chunk)
    result = list(citations)
    seen = {c.chunk_id for c in citations}
    for seed in citations:
        chunks = pages.get((seed.document_id, seed.page_number), [])
        position = next((i for i, chunk in enumerate(chunks) if chunk["chunk_id"] == seed.chunk_id), None)
        if position is None:
            continue
        for neighbor in chunks[max(0, position - 1):position + 2]:
            if len(result) >= max_chunks:
                return result
            if neighbor["chunk_id"] in seen:
                continue
            result.append(seed.model_copy(update={"chunk_id": neighbor["chunk_id"], "excerpt": neighbor["content"]}))
            seen.add(neighbor["chunk_id"])
    return result


def _rank_knowledge_matches(
    matches: list[tuple[float, float, Citation]], limit: int
) -> list[Citation]:
    """Fuse independent candidate ranks instead of adding incomparable raw scores.

    Chinese bigram coverage can reward boilerplate more than actual evidence.
    Prefer semantic ranks (12:1), while retaining a lexical candidate channel for
    exact terms and legacy chunks. These are retrieval heuristics, not confidence
    probabilities. Keep keyword-only behavior when vectors are unavailable.
    """
    if limit <= 0:
        return []

    def stable_key(item: tuple[float, float, Citation]) -> tuple[str, int, str]:
        citation = item[2]
        return citation.document_id, citation.page_number, citation.chunk_id

    if not any(vector > 0 for _, vector, _ in matches):
        ranked = sorted(matches, key=lambda item: (-item[0], stable_key(item)))
        return [
            citation.model_copy(update={"score": max(1, round(keyword * 1000))})
            for keyword, _, citation in ranked[:limit]
        ]

    candidate_count = max(20, limit * 4)
    scores: dict[str, float] = {}
    citations: dict[str, Citation] = {}
    active_weight = 0
    lexical_leader: str | None = None
    # With this weight, a keyword-only boost cannot displace the semantic top
    # three with a fourth-or-lower semantic candidate. Larger result sets still
    # allow lexical ranks to refine the ordering of lower-confidence candidates.
    for channel, weight in ((0, 1), (1, 12)):
        candidates = sorted(
            (item for item in matches if item[channel] > 0),
            key=lambda item: (-item[channel], stable_key(item)),
        )[:candidate_count]
        if not candidates:
            continue
        if channel == 0:
            lexical_leader = candidates[0][2].chunk_id
        active_weight += weight
        # Equal scores share a rank rather than gaining an arbitrary tie-break bonus.
        rank = 0
        previous = None
        for position, item in enumerate(candidates, start=1):
            if item[channel] != previous:
                rank = position
                previous = item[channel]
            citation = item[2]
            citations[citation.chunk_id] = citation
            scores[citation.chunk_id] = scores.get(citation.chunk_id, 0.0) + weight / (1 + rank)

    ranked_ids = sorted(
        scores,
        key=lambda key: (
            -scores[key], citations[key].document_id,
            citations[key].page_number, key,
        ),
    )
    # For larger evidence sets reserve one slot for the best lexical candidate.
    # This protects explicit terminology when semantic search prefers a nearby
    # topic, while keeping the first three semantic-heavy results intact.
    if limit >= 4 and lexical_leader and lexical_leader not in ranked_ids[:limit]:
        ranked_ids.remove(lexical_leader)
        ranked_ids.insert(3, lexical_leader)
    return [
        citations[key].model_copy(
            update={"score": max(1, round(1000 * scores[key] / (active_weight / 2)))}
        )
        for key in ranked_ids[:limit]
    ]


def _chunk_vector_score(
    chunk: dict[str, Any], query_embedding: list[float], provider: EmbeddingProvider
) -> float:
    stored_embedding = chunk.get("embedding")
    if (
        not query_embedding
        or chunk.get("embedding_provider") != provider.name
        or not isinstance(stored_embedding, list)
        or len(stored_embedding) != provider.dimension
        or not all(isinstance(value, (int, float)) for value in stored_embedding)
    ):
        return 0.0
    return max(0.0, cosine_similarity(query_embedding, [float(value) for value in stored_embedding]))


def _can_fall_back_to_keyword_search(error: ValueError) -> bool:
    """Only treat temporary remote-provider problems as safe retrieval degradation."""
    return str(error).startswith(
        (
            "EMBEDDING_TIMEOUT:",
            "EMBEDDING_UNAVAILABLE:",
            "EMBEDDING_ACCOUNT_UNAVAILABLE:",
        )
    )
