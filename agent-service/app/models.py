from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field
from app.market_models import MarketHistory, MarketHistoryPlan
from app.report_models import ReportFinancialData, ReportFinancialPlan


ReportYear = Annotated[int, Field(strict=True, ge=1900, le=2099)]


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500, description="Research question in Chinese")


class FinancialMetricsPlan(BaseModel):
    """A validated plan for the deterministic financial-metrics tool."""
    model_config = ConfigDict(extra="forbid")

    intent: Literal["get_financial_metrics"]
    company_codes: list[str] = Field(min_length=1, max_length=2)
    period: Literal["2025H1"]
    metric_codes: list[Literal["revenue", "net_profit"]] = Field(min_length=1, max_length=2)


class KnowledgeSearchPlan(BaseModel):
    """A validated plan for searching source-linked document excerpts."""
    model_config = ConfigDict(extra="forbid")

    intent: Literal["search_knowledge"]
    query: str = Field(min_length=2, max_length=300)
    company_code: str | None = Field(default=None, min_length=6, max_length=6)
    report_year: ReportYear | None = None


ToolPlan = Annotated[
    FinancialMetricsPlan | KnowledgeSearchPlan | MarketHistoryPlan | ReportFinancialPlan,
    Field(discriminator="intent"),
]


class FinancialMetric(BaseModel):
    company_code: str
    company_name: str
    report_period: str
    metric_code: Literal["revenue", "net_profit"]
    metric_name: str
    metric_value: float
    unit: str
    source_document: str
    source_page_number: int
    published_at: date


class RetrievalDiagnostics(BaseModel):
    mode: Literal["none", "keyword", "hybrid"] = "none"
    outcome: Literal["not_started", "no_documents", "no_matches", "candidates"] = "not_started"
    matched_document_count: int = 0
    context_chunk_count: int = 0
    degraded: bool = False
    warning_code: str | None = None


class ToolCallLog(BaseModel):
    tool_name: str
    arguments: ToolPlan | dict[str, object]
    status: Literal["success", "no_evidence", "degraded", "failed"]
    result_count: int
    error_code: str | None = None
    retrieval: RetrievalDiagnostics | None = None


class EvidenceQuote(BaseModel):
    chunk_id: str = Field(min_length=1)
    quote: str = Field(min_length=6, max_length=1500)


class EvidenceAssessment(BaseModel):
    status: Literal["sufficient", "insufficient", "unavailable"]
    checker: Literal["deepseek", "none"]
    reason_code: str
    supports: list[EvidenceQuote] = Field(default_factory=list)


class ChatResponse(BaseModel):
    request_id: str
    planner: Literal["local_rule", "deepseek"]
    plan: ToolPlan | dict[str, object]
    results: list[FinancialMetric] = Field(default_factory=list)
    citations: list["Citation"] = Field(default_factory=list)
    answer: str = Field(description="Human-readable answer based only on tool results")
    tool_calls: list[ToolCallLog]
    evidence: EvidenceAssessment | None = None
    market_data: MarketHistory | None = None
    financial_data: ReportFinancialData | None = None
    latency_ms: int = Field(ge=0)


class ErrorResponse(BaseModel):
    code: str
    message: str
    request_id: str
    tool_calls: list[ToolCallLog] = Field(default_factory=list)


class MarketHistoryResponse(BaseModel):
    request_id: str
    market_data: MarketHistory
    tool_calls: list[ToolCallLog]


class ReportFinancialResponse(BaseModel):
    request_id: str
    financial_data: ReportFinancialData
    tool_calls: list[ToolCallLog]


class DocumentRecord(BaseModel):
    document_id: str
    title: str
    source_file_name: str
    company_code: str | None = None
    company_name: str | None = None
    document_type: str
    published_at: date | None = None
    report_year: ReportYear | None = None
    page_count: int = Field(ge=1)
    chunk_count: int = Field(ge=1)
    ingested_at: datetime


class DocumentIngestionResponse(BaseModel):
    request_id: str
    document: DocumentRecord


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=300)
    company_code: str | None = Field(default=None, min_length=6, max_length=6)
    report_year: ReportYear | None = None
    limit: int = Field(default=5, ge=1, le=10)


class Citation(BaseModel):
    document_id: str
    title: str
    company_code: str | None = None
    company_name: str | None = None
    document_type: str
    published_at: date | None = None
    report_year: ReportYear | None = None
    page_number: int = Field(ge=1)
    chunk_id: str
    excerpt: str
    score: int = Field(ge=1)


class KnowledgeSearchResponse(BaseModel):
    request_id: str
    query: str
    citations: list[Citation]
    retrieval: RetrievalDiagnostics = Field(default_factory=RetrievalDiagnostics)


ChatResponse.model_rebuild()
