import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from datetime import date

from fastapi import FastAPI, File, Form, Request, UploadFile, status
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from app.config import get_settings
from app.errors import error_status, public_error
from app.evidence import EvidenceChecker, evidence_answer
from app.knowledge import ingest_pdf_document, search_knowledge
from app.tools import tool_registry
from app.tool_registry import ToolResult
from app.market_models import MarketHistoryPlan
from app.report_models import ReportFinancialPlan
from starlette.concurrency import run_in_threadpool
from app.models import (
    ChatRequest,
    MarketHistoryResponse,
    ReportFinancialResponse,
    ChatResponse,
    Citation,
    EvidenceAssessment,
    DocumentIngestionResponse,
    ErrorResponse,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    RetrievalDiagnostics,
    ToolCallLog,
    ToolPlan,
)
from app.services import create_planner

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("finresearch.agent")

app = FastAPI(
    title="FinResearch Agent Service",
    version="0.1.0",
    description="First learning slice: validated financial-metrics tool calling.",
    responses={code: {"model": ErrorResponse} for code in (400, 422, 500, 502, 503, 504)},
)
settings = get_settings()
planner = create_planner(settings)
evidence_checker = EvidenceChecker(settings)


async def assess_chat_evidence(
    question: str, plan: ToolPlan, citations: list[Citation], tool_call: ToolCallLog,
    answer: str, request_id: str,
) -> tuple[EvidenceAssessment | None, str]:
    if not tool_registry.get(plan.intent).requires_evidence:
        return None, answer
    assessment = await evidence_checker.assess(question, citations)
    answer = evidence_answer(assessment, citations)
    if tool_call.retrieval and tool_call.retrieval.degraded:
        answer = "向量服务暂不可用，本次已降级为关键词检索，可能遗漏语义相关资料。\n" + answer
    logger.info("request_id=%s evidence_status=%s reason_code=%s", request_id,
                assessment.status, assessment.reason_code)
    return assessment, answer


def error_response(error: Exception, request_id: str) -> JSONResponse:
    body = public_error(error, request_id)
    logger.info("request_id=%s status=failed error_code=%s", request_id, body.code)
    return JSONResponse(status_code=error_status(body.code), content=body.model_dump(mode="json"))


@app.exception_handler(RequestValidationError)
async def invalid_request(_request: Request, error: RequestValidationError) -> JSONResponse:
    invalid_json = any(item["type"] == "json_invalid" for item in error.errors())
    body = ErrorResponse(
        code="INVALID_JSON" if invalid_json else "VALIDATION_ERROR",
        message="请求体不是合法 JSON，请检查引号、逗号和括号。" if invalid_json else "请求参数不合法，请按接口文档检查字段类型与范围。",
        request_id=str(uuid.uuid4()),
    )
    return JSONResponse(status_code=422, content=body.model_dump(mode="json"))


@app.exception_handler(HTTPException)
async def http_error(_request: Request, error: HTTPException) -> JSONResponse:
    body = ErrorResponse(code=f"HTTP_{error.status_code}", message="请求的接口不存在或不允许该操作。",
                         request_id=str(uuid.uuid4()))
    return JSONResponse(status_code=error.status_code, content=body.model_dump(mode="json"), headers=error.headers)


@app.exception_handler(Exception)
async def unexpected_error(_request: Request, error: Exception) -> JSONResponse:
    return error_response(error, str(uuid.uuid4()))


def sse_event(event: str, data: dict[str, object]) -> str:
    """Serialize one Server-Sent Event without exposing Python objects to clients."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def execute_plan(plan: ToolPlan, request_id: str) -> tuple[ToolResult, ToolCallLog]:
    return tool_registry.execute(plan, request_id)


def tool_stage_message(plan: ToolPlan) -> str:
    return tool_registry.get(plan.intent).progress_message


@app.get("/v1/tools")
async def list_tools() -> dict:
    """Read-only catalog; handlers and credentials are never exposed."""
    return {"tools": tool_registry.describe()}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "planner": planner.planner_name}


@app.post(
    "/v1/documents",
    response_model=DocumentIngestionResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}},
)
async def ingest_document(
    file: UploadFile = File(...),
    company_code: str | None = Form(default=None),
    company_name: str | None = Form(default=None),
    document_type: str = Form(default="other"),
    published_at: date | None = Form(default=None),
    report_year: int | None = Form(
        default=None, ge=1900, le=2099, description="报告所属年份，不是发布日期年份，例如 2024"
    ),
) -> DocumentIngestionResponse | JSONResponse:
    """Ingest one public PDF into the local, page-aware knowledge index."""
    request_id = str(uuid.uuid4())
    file_content = await file.read()
    try:
        document = ingest_pdf_document(
            file_name=file.filename or "unnamed.pdf",
            file_content=file_content,
            company_code=company_code,
            company_name=company_name,
            document_type=document_type,
            published_at=published_at,
            report_year=report_year,
        )
    except ValueError as error:
        return error_response(error, request_id)
    return DocumentIngestionResponse(request_id=request_id, document=document)


@app.post(
    "/v1/knowledge/search",
    response_model=KnowledgeSearchResponse,
    responses={400: {"model": ErrorResponse}},
)
async def knowledge_search(
    request: KnowledgeSearchRequest,
) -> KnowledgeSearchResponse | JSONResponse:
    """Search uploaded document chunks and return only original source excerpts."""
    request_id = str(uuid.uuid4())
    diagnostics = RetrievalDiagnostics()
    try:
        citations = search_knowledge(
            query=request.query, company_code=request.company_code, limit=request.limit,
            report_year=request.report_year,
            diagnostics=diagnostics,
        )
    except ValueError as error:
        return error_response(error, request_id)
    return KnowledgeSearchResponse(
        request_id=request_id, query=request.query, citations=citations, retrieval=diagnostics
    )


@app.post(
    "/v1/chat",
    response_model=ChatResponse,
    responses={400: {"model": ErrorResponse}},
)
async def chat(request: ChatRequest) -> ChatResponse | JSONResponse:
    """Create a validated plan and execute one fixed, source-safe tool."""
    request_id = str(uuid.uuid4())
    started_at = time.perf_counter()

    try:
        plan = await planner.create_plan(request.question)
        result, tool_call = await run_in_threadpool(execute_plan, plan, request_id)
        results, citations, answer = result.results, result.citations, result.answer
        evidence, answer = await assess_chat_evidence(
            request.question, plan, citations, tool_call, answer, request_id,
        )
    except Exception as error:
        return error_response(error, request_id)

    latency_ms = round((time.perf_counter() - started_at) * 1000)
    return ChatResponse(
        request_id=request_id,
        planner=planner.planner_name,
        plan=plan.model_dump(mode="json"),
        results=results,
        citations=citations,
        answer=answer,
        tool_calls=[tool_call],
        evidence=evidence,
        market_data=result.market_data,
        financial_data=result.financial_data,
        latency_ms=latency_ms,
    )


@app.post("/v1/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    """Stream Agent progress and finish with the same data returned by /v1/chat."""

    async def generate_events() -> AsyncIterator[str]:
        request_id = str(uuid.uuid4())
        started_at = time.perf_counter()
        yield sse_event(
            "status",
            {"request_id": request_id, "stage": "planning", "message": "正在理解研究问题"},
        )

        try:
            plan = await planner.create_plan(request.question)
            yield sse_event(
                "status",
                {
                    "request_id": request_id,
                    "stage": "tool_call",
                    "message": tool_stage_message(plan),
                },
            )
            result, tool_call = await run_in_threadpool(execute_plan, plan, request_id)
            results, citations, answer = result.results, result.citations, result.answer
            if tool_registry.get(plan.intent).requires_evidence:
                yield sse_event("status", {"request_id": request_id, "stage": "evidence_check",
                                          "message": "正在核对原文是否足以回答问题"})
            evidence, answer = await assess_chat_evidence(
                request.question, plan, citations, tool_call, answer, request_id,
            )
        except Exception as error:
            body = public_error(error, request_id)
            logger.info("request_id=%s status=failed error_code=%s", request_id, body.code)
            yield sse_event("error", body.model_dump(mode="json"))
            return

        response = ChatResponse(
            request_id=request_id,
            planner=planner.planner_name,
            plan=plan.model_dump(mode="json"),
            results=results,
            citations=citations,
            answer=answer,
            tool_calls=[tool_call],
            evidence=evidence,
            market_data=result.market_data,
            financial_data=result.financial_data,
            latency_ms=round((time.perf_counter() - started_at) * 1000),
        )
        yield sse_event(
            "answer",
            {"request_id": request_id, "text": answer},
        )
        yield sse_event("completed", response.model_dump(mode="json"))

    return StreamingResponse(
        generate_events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/v1/market/history", response_model=MarketHistoryResponse)
async def market_history(request: MarketHistoryPlan) -> MarketHistoryResponse | JSONResponse:
    """Direct validated historical-data query; no planner/model cost."""
    request_id = str(uuid.uuid4())
    try:
        result, log = await run_in_threadpool(execute_plan, request, request_id)
        return MarketHistoryResponse(request_id=request_id, market_data=result.market_data, tool_calls=[log])
    except Exception as error:
        return error_response(error, request_id)


@app.post("/v1/financials/report", response_model=ReportFinancialResponse)
async def report_financials(request: ReportFinancialPlan) -> ReportFinancialResponse | JSONResponse:
    """Read real reported financials directly without a model planning call."""
    request_id = str(uuid.uuid4())
    try:
        result, log = await run_in_threadpool(execute_plan, request, request_id)
        return ReportFinancialResponse(request_id=request_id, financial_data=result.financial_data, tool_calls=[log])
    except Exception as error:
        return error_response(error, request_id)
