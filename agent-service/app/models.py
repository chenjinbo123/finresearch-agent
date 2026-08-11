from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500, description="Research question in Chinese")


class FinancialMetricsPlan(BaseModel):
    """The only tool plan the first slice accepts."""

    intent: Literal["get_financial_metrics"]
    company_codes: list[str] = Field(min_length=1, max_length=2)
    period: Literal["2025H1"]
    metric_codes: list[Literal["revenue", "net_profit"]] = Field(min_length=1, max_length=2)


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


class ToolCallLog(BaseModel):
    tool_name: Literal["get_financial_metrics"]
    arguments: FinancialMetricsPlan
    status: Literal["success"]
    result_count: int


class ChatResponse(BaseModel):
    request_id: str
    planner: Literal["local_rule", "deepseek"]
    plan: FinancialMetricsPlan
    results: list[FinancialMetric]
    answer: str = Field(description="Deterministic, human-readable answer based only on tool results")
    tool_calls: list[ToolCallLog]
    latency_ms: int = Field(ge=0)


class ErrorResponse(BaseModel):
    code: str
    message: str
    request_id: str


class DocumentRecord(BaseModel):
    document_id: str
    title: str
    source_file_name: str
    company_code: str | None = None
    company_name: str | None = None
    document_type: str
    published_at: date | None = None
    page_count: int = Field(ge=1)
    chunk_count: int = Field(ge=1)
    ingested_at: datetime


class DocumentIngestionResponse(BaseModel):
    request_id: str
    document: DocumentRecord


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=300)
    company_code: str | None = Field(default=None, min_length=6, max_length=6)
    limit: int = Field(default=5, ge=1, le=10)


class Citation(BaseModel):
    document_id: str
    title: str
    company_code: str | None = None
    company_name: str | None = None
    document_type: str
    published_at: date | None = None
    page_number: int = Field(ge=1)
    chunk_id: str
    excerpt: str
    score: int = Field(ge=1)


class KnowledgeSearchResponse(BaseModel):
    request_id: str
    query: str
    citations: list[Citation]
