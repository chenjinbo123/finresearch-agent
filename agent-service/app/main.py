import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from datetime import date

from fastapi import FastAPI, File, Form, UploadFile, status
from fastapi.responses import JSONResponse, StreamingResponse

from app.config import get_settings
from app.knowledge import ingest_pdf_document, search_knowledge
from app.models import (
    ChatRequest,
    ChatResponse,
    DocumentIngestionResponse,
    ErrorResponse,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    ToolCallLog,
    ToolPlan,
)
from app.services import (
    create_planner,
    format_financial_research_answer,
    format_knowledge_research_answer,
    get_financial_metrics,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("finresearch.agent")

app = FastAPI(
    title="FinResearch Agent Service",
    version="0.1.0",
    description="First learning slice: validated financial-metrics tool calling.",
)
settings = get_settings()
planner = create_planner(settings)


def sse_event(event: str, data: dict[str, object]) -> str:
    """Serialize one Server-Sent Event without exposing Python objects to clients."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def execute_plan(plan: ToolPlan, request_id: str) -> tuple[list, list, ToolCallLog, str]:
    """Execute exactly one validated, allowlisted tool chosen by the planner."""
    if plan.intent == "get_financial_metrics":
        results, tool_call = get_financial_metrics(plan, request_id)
        return results, [], tool_call, format_financial_research_answer(results)

    citations = search_knowledge(query=plan.query, company_code=plan.company_code)
    tool_call = ToolCallLog(
        tool_name="search_knowledge",
        arguments=plan,
        status="success",
        result_count=len(citations),
    )
    logger.info(
        "request_id=%s tool=%s arguments=%s status=%s result_count=%s",
        request_id,
        tool_call.tool_name,
        plan.model_dump_json(),
        tool_call.status,
        tool_call.result_count,
    )
    return [], citations, tool_call, format_knowledge_research_answer(len(citations))


def tool_stage_message(plan: ToolPlan) -> str:
    if plan.intent == "get_financial_metrics":
        return "正在查询财务指标"
    return "正在检索公开资料证据"


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
        )
    except ValueError as error:
        code, message = str(error).split(":", maxsplit=1)
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"code": code, "message": message.strip(), "request_id": request_id},
        )
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
    try:
        citations = search_knowledge(
            query=request.query, company_code=request.company_code, limit=request.limit
        )
    except ValueError as error:
        code, message = str(error).split(":", maxsplit=1)
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"code": code, "message": message.strip(), "request_id": request_id},
        )
    return KnowledgeSearchResponse(
        request_id=request_id, query=request.query, citations=citations
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
        results, citations, tool_call, answer = execute_plan(plan, request_id)
    except ValueError as error:
        code, message = str(error).split(":", maxsplit=1)
        logger.info(
            "request_id=%s status=failed error_code=%s question=%r",
            request_id,
            code,
            request.question,
        )
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"code": code, "message": message.strip(), "request_id": request_id},
        )

    latency_ms = round((time.perf_counter() - started_at) * 1000)
    return ChatResponse(
        request_id=request_id,
        planner=planner.planner_name,
        plan=plan,
        results=results,
        citations=citations,
        answer=answer,
        tool_calls=[tool_call],
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
            results, citations, tool_call, answer = execute_plan(plan, request_id)
        except ValueError as error:
            code, message = str(error).split(":", maxsplit=1)
            logger.info(
                "request_id=%s status=failed error_code=%s question=%r",
                request_id,
                code,
                request.question,
            )
            yield sse_event(
                "error",
                {"request_id": request_id, "code": code, "message": message.strip()},
            )
            return

        response = ChatResponse(
            request_id=request_id,
            planner=planner.planner_name,
            plan=plan,
            results=results,
            citations=citations,
            answer=answer,
            tool_calls=[tool_call],
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
