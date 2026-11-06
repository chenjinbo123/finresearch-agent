from datetime import date

import pytest
from fastapi.testclient import TestClient

import app.knowledge as knowledge
import app.main as main
import app.services as services
from app.embeddings import DisabledEmbeddingProvider
from app.models import FinancialMetricsPlan
from app.services import LocalResearchPlanner

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def use_local_planner(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests stay free and deterministic even when a local .env has a DeepSeek key."""
    monkeypatch.setattr(main, "planner", LocalResearchPlanner())


@pytest.fixture
def knowledge_storage(monkeypatch: pytest.MonkeyPatch, tmp_path):
    knowledge_root = tmp_path / "knowledge"
    monkeypatch.setattr(knowledge, "KNOWLEDGE_ROOT", knowledge_root)
    monkeypatch.setattr(knowledge, "SOURCE_DOCUMENTS_DIR", knowledge_root / "source_documents")
    monkeypatch.setattr(knowledge, "INDEX_PATH", knowledge_root / "knowledge_index.json")
    # Unit tests must never use a developer's real local API key or quota.
    monkeypatch.setattr(
        knowledge,
        "_resolve_embedding_provider",
        lambda provider: provider if provider is not None else DisabledEmbeddingProvider(),
    )
    return knowledge_root


def make_text_pdf_bytes(monkeypatch: pytest.MonkeyPatch, page_texts: list[str]) -> bytes:
    """Test the ingestion pipeline without needing a committed binary PDF fixture."""
    class FakePage:
        def __init__(self, text: str) -> None:
            self._text = text

        def extract_text(self) -> str:
            return self._text

    class FakeReader:
        is_encrypted = False

        def __init__(self, _source) -> None:
            self.pages = [FakePage(text) for text in page_texts]

    monkeypatch.setattr(knowledge, "PdfReader", FakeReader)
    return b"%PDF-1.4 test document"


class SemanticFixtureEmbeddingProvider:
    """A controlled provider proving retrieval can use vectors, not word overlap."""

    name = "semantic_fixture"
    dimension = 2

    def embed(self, text: str) -> list[float]:
        if "上游压力" in text or "供应链采购成本" in text:
            return [1.0, 0.0]
        return [0.0, 1.0]

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]


class UnavailableEmbeddingProvider:
    """Controlled remote outage fixture: search must still return source text."""

    name = "unavailable"
    dimension = 2

    def embed(self, _text: str) -> list[float]:
        raise ValueError("EMBEDDING_ACCOUNT_UNAVAILABLE: test provider is unavailable")

    def embed_many(self, _texts: list[str]) -> list[list[float]]:
        raise ValueError("EMBEDDING_ACCOUNT_UNAVAILABLE: test provider is unavailable")


def test_health() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "planner": "local_rule"}


def test_chat_returns_validated_metrics() -> None:
    response = client.post(
        "/v1/chat",
        json={"question": "对比宁德时代和比亚迪 2025H1 营收和归母净利润"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["planner"] == "local_rule"
    assert body["plan"]["intent"] == "get_financial_metrics"
    assert body["plan"]["company_codes"] == ["300750", "002594"]
    assert body["plan"]["metric_codes"] == ["revenue", "net_profit"]
    assert len(body["results"]) == 4
    assert "宁德时代：营业收入 1,789.00 亿元；归母净利润 305.00 亿元。" in body["answer"]
    assert "数据来源：" in body["answer"]
    assert body["tool_calls"][0]["result_count"] == 4


def test_chat_rejects_unknown_company() -> None:
    response = client.post("/v1/chat", json={"question": "查询招商银行 2025H1 营收"})

    assert response.status_code == 400
    assert response.json()["code"] == "UNSUPPORTED_COMPANY"

def test_chat_supports_kweichow_moutai() -> None:
    response = client.post(
        "/v1/chat",
        json={"question": "查询贵州茅台 2025H1 营收和归母净利润"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["plan"]["company_codes"] == ["600519"]
    assert len(body["results"]) == 2
    assert "贵州茅台：营业收入 900.00 亿元；归母净利润 450.00 亿元。" in body["answer"]


def test_chat_stream_reports_progress_and_completes() -> None:
    response = client.post(
        "/v1/chat/stream",
        json={"question": "查询贵州茅台 2025H1 营收"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: status" in response.text
    assert "正在理解研究问题" in response.text
    assert "正在查询财务指标" in response.text
    assert "event: answer" in response.text
    assert "贵州茅台：营业收入 900.00 亿元。" in response.text
    assert "event: completed" in response.text


def test_chat_uses_knowledge_search_for_risk_question(monkeypatch: pytest.MonkeyPatch) -> None:
    expected_citation = {
        "document_id": "document-001",
        "title": "贵州茅台公开报告",
        "company_code": "600519",
        "company_name": "贵州茅台",
        "document_type": "annual_report",
        "published_at": "2025-08-20",
        "page_number": 18,
        "chunk_id": "document-001:18:0",
        "excerpt": "公司经营面临原材料价格波动等风险。",
        "score": 2,
    }
    monkeypatch.setattr(main, "search_knowledge", lambda **_kwargs: [expected_citation])

    response = client.post("/v1/chat", json={"question": "贵州茅台有哪些经营风险？"})

    assert response.status_code == 200
    body = response.json()
    assert body["plan"] == {
        "intent": "search_knowledge",
        "query": "贵州茅台有哪些经营风险？",
        "company_code": "600519",
    }
    assert body["results"] == []
    assert body["tool_calls"][0]["tool_name"] == "search_knowledge"
    assert body["tool_calls"][0]["result_count"] == 1
    assert body["citations"] == [expected_citation]
    assert "请结合下方引用" in body["answer"]


def test_chat_returns_safe_answer_when_knowledge_search_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(main, "search_knowledge", lambda **_kwargs: [])

    response = client.post("/v1/chat", json={"question": "公告中提到了哪些风险？"})

    assert response.status_code == 200
    body = response.json()
    assert body["plan"]["intent"] == "search_knowledge"
    assert body["citations"] == []
    assert body["tool_calls"][0]["result_count"] == 0
    assert body["answer"] == "现有资料不足以确认：在已入库的公开资料中未检索到相关原文证据。"


def test_chat_stream_reports_knowledge_retrieval_stage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "search_knowledge", lambda **_kwargs: [])

    response = client.post("/v1/chat/stream", json={"question": "公告中提到了哪些风险？"})

    assert response.status_code == 200
    assert "正在检索公开资料证据" in response.text
    assert "event: completed" in response.text


def test_loads_six_validated_metrics_from_csv() -> None:
    services.load_financial_metrics.cache_clear()

    metrics = services.load_financial_metrics()

    assert len(metrics) == 6
    metric = metrics[("600519", "2025H1", "revenue")]
    assert metric.company_name == "贵州茅台"
    assert metric.metric_value == 90_000_000_000
    assert metric.source_page_number == 30
    assert metric.published_at.isoformat() == "2025-08-20"


def test_financial_data_missing_returns_controlled_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(services, "load_financial_metrics", lambda: {})
    plan = FinancialMetricsPlan(
        intent="get_financial_metrics",
        company_codes=["300750"],
        period="2025H1",
        metric_codes=["revenue"],
    )

    with pytest.raises(ValueError, match="FINANCIAL_DATA_NOT_FOUND"):
        services.get_financial_metrics(plan, request_id="test-request")


def test_invalid_csv_columns_are_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    invalid_csv = tmp_path / "financial_metrics.csv"
    invalid_csv.write_text("company_code,company_name\n300750,宁德时代\n", encoding="utf-8")
    monkeypatch.setattr(services, "FINANCIAL_METRICS_CSV_PATH", invalid_csv)
    services.load_financial_metrics.cache_clear()

    with pytest.raises(ValueError, match="FINANCIAL_DATA_INVALID"):
        services.load_financial_metrics()


def test_pdf_ingestion_and_keyword_search(
    monkeypatch: pytest.MonkeyPatch, knowledge_storage
) -> None:
    file_content = make_text_pdf_bytes(
        monkeypatch,
        [
            "第一章 公司概况。",
            "公司经营面临原材料价格波动和市场竞争加剧等风险提示。",
        ],
    )

    document = knowledge.ingest_pdf_document(
        file_name="贵州茅台公开报告.pdf",
        file_content=file_content,
        company_code="600519",
        company_name="贵州茅台",
        document_type="annual_report",
        published_at=date(2025, 8, 20),
    )
    citations = knowledge.search_knowledge(query="经营风险", company_code="600519")

    assert document.page_count == 2
    assert document.chunk_count == 2
    assert len(citations) == 1
    assert citations[0].page_number == 2
    assert "原材料价格波动" in citations[0].excerpt
    assert citations[0].published_at == date(2025, 8, 20)


def test_pdf_ingestion_rejects_duplicate_document(
    monkeypatch: pytest.MonkeyPatch, knowledge_storage
) -> None:
    file_content = make_text_pdf_bytes(monkeypatch, ["公开资料的经营风险提示。"])
    ingestion_arguments = {
        "file_name": "public-report.pdf",
        "file_content": file_content,
        "company_code": "600519",
        "company_name": "贵州茅台",
        "document_type": "annual_report",
        "published_at": None,
    }
    knowledge.ingest_pdf_document(**ingestion_arguments)

    with pytest.raises(ValueError, match="DOCUMENT_ALREADY_EXISTS"):
        knowledge.ingest_pdf_document(**ingestion_arguments)


def test_pdf_ingestion_reports_no_extractable_text(
    monkeypatch: pytest.MonkeyPatch, knowledge_storage
) -> None:
    file_content = make_text_pdf_bytes(monkeypatch, ["", ""])

    with pytest.raises(ValueError, match="DOCUMENT_NO_EXTRACTABLE_TEXT"):
        knowledge.ingest_pdf_document(
            file_name="scanned-report.pdf",
            file_content=file_content,
            company_code=None,
            company_name=None,
            document_type="other",
            published_at=None,
        )


def test_vector_retrieval_can_return_related_chunk_without_keyword_overlap(
    monkeypatch: pytest.MonkeyPatch, knowledge_storage
) -> None:
    file_content = make_text_pdf_bytes(
        monkeypatch,
        [
            "供应链采购成本上升可能影响公司经营。",
            "市场竞争变化需要持续关注。",
        ],
    )
    provider = SemanticFixtureEmbeddingProvider()
    knowledge.ingest_pdf_document(
        file_name="公开资料.pdf",
        file_content=file_content,
        company_code="600519",
        company_name="贵州茅台",
        document_type="announcement",
        published_at=None,
        embedding_provider=provider,
    )

    citations = knowledge.search_knowledge(
        query="上游压力", company_code="600519", embedding_provider=provider
    )

    assert len(citations) == 1
    assert citations[0].page_number == 1
    assert "供应链采购成本" in citations[0].excerpt
    assert citations[0].score == 1000


def test_keyword_score_does_not_reward_repeated_page_headers() -> None:
    terms = knowledge._search_terms("贵州茅台经营风险")

    once = knowledge._keyword_coverage_score("贵州茅台提示经营风险。", terms)
    repeated = knowledge._keyword_coverage_score("贵州茅台 " * 100, terms)

    assert once > repeated
    # "贵州茅台" produces three two-character terms. Repeating the header
    # cannot increase that fixed coverage score.
    assert repeated == 3 / len(terms)


def test_search_falls_back_to_keywords_when_remote_embedding_is_unavailable(
    monkeypatch: pytest.MonkeyPatch, knowledge_storage
) -> None:
    file_content = make_text_pdf_bytes(monkeypatch, ["公司经营面临原材料价格波动风险提示。"])
    knowledge.ingest_pdf_document(
        file_name="公开资料.pdf",
        file_content=file_content,
        company_code="600519",
        company_name="贵州茅台",
        document_type="annual_report",
        published_at=None,
    )

    citations = knowledge.search_knowledge(
        query="原材料风险",
        company_code="600519",
        embedding_provider=UnavailableEmbeddingProvider(),
    )

    assert len(citations) == 1
    assert "原材料价格波动" in citations[0].excerpt


def test_rebuild_embeddings_adds_vectors_to_existing_chunks(
    monkeypatch: pytest.MonkeyPatch, knowledge_storage
) -> None:
    file_content = make_text_pdf_bytes(monkeypatch, ["供应链采购成本上升可能影响公司经营。"])
    knowledge.ingest_pdf_document(
        file_name="公开资料.pdf",
        file_content=file_content,
        company_code="600519",
        company_name="贵州茅台",
        document_type="announcement",
        published_at=None,
    )
    provider = SemanticFixtureEmbeddingProvider()

    count = knowledge.rebuild_knowledge_embeddings(provider)
    index = knowledge._load_index()

    assert count == 1
    assert index["chunks"][0]["embedding_provider"] == "semantic_fixture"
    assert index["chunks"][0]["embedding"] == [1.0, 0.0]
