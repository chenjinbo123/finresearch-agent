"""Explicit, validated tool dispatch; registration does not grant write access."""

import logging
import time
from dataclasses import dataclass
from typing import Callable, Literal

from pydantic import BaseModel, Field, ValidationError

from app.errors import ToolExecutionError, public_error
from app.models import Citation, FinancialMetric, RetrievalDiagnostics, ToolCallLog
from app.market_models import MarketHistory
from app.report_models import ReportFinancialData

logger = logging.getLogger(__name__)


class ToolResult(BaseModel):
    results: list[FinancialMetric] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    answer: str
    market_data: MarketHistory | None = None
    financial_data: ReportFinancialData | None = None
    retrieval: RetrievalDiagnostics | None = None
    status: Literal["success", "no_evidence", "degraded"] = "success"


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    category: Literal["read_only", "pure_compute", "side_effect"]
    input_model: type[BaseModel]
    handler: Callable[[BaseModel, str], ToolResult]
    progress_message: str
    requires_evidence: bool = False
    data_kind: Literal["demo", "public_document", "computed", "market_history", "reported_financials"] = "computed"


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        if tool.name in self._tools:
            raise ValueError("TOOL_ALREADY_REGISTERED: 工具名称重复。")
        intent_schema = tool.input_model.model_json_schema().get("properties", {}).get("intent", {})
        if intent_schema.get("const") != tool.name:
            raise ValueError("TOOL_SCHEMA_INVALID: 参数模型 intent 必须固定为工具名称。")
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolDefinition:
        if name not in self._tools:
            raise ValueError("PLANNER_INVALID_OUTPUT: 模型选择了不支持的工具。")
        return self._tools[name]

    def parse(self, value: object) -> BaseModel:
        if not isinstance(value, dict) or not isinstance(value.get("intent"), str):
            raise ValueError("PLANNER_INVALID_OUTPUT: 模型未返回合法工具参数。")
        tool = self.get(value["intent"])
        if tool.category == "side_effect":
            raise ValueError("TOOL_NOT_ALLOWED: 当前聊天只允许查询与纯计算工具。")
        try:
            return tool.input_model.model_validate(value)
        except ValidationError as error:
            raise ValueError("PLANNER_INVALID_OUTPUT: 工具参数类型或范围不合法。") from error

    def describe(self) -> list[dict]:
        return [{"name": t.name, "description": t.description, "category": t.category,
                 "available_in_chat": t.category != "side_effect", "data_kind": t.data_kind,
                 "requires_evidence": t.requires_evidence,
                 "parameters": t.input_model.model_json_schema(),
                 "result_schema": ToolResult.model_json_schema()}
                for t in self._tools.values()]

    def execute(self, plan: BaseModel, request_id: str) -> tuple[ToolResult, ToolCallLog]:
        arguments = plan.model_dump(mode="json", warnings=False)
        name = arguments.get("intent", "unknown")
        started = time.perf_counter()
        try:
            # Revalidate even when the caller passes an already-constructed model.
            validated = self.parse(arguments)
            result = self.get(name).handler(validated, request_id)
            if not isinstance(result, ToolResult):
                raise TypeError("tool returned an invalid result")
            log = ToolCallLog(tool_name=name, arguments=arguments, status=result.status,
                              result_count=len(result.results) + len(result.citations) +
                              (len(result.market_data.bars) if result.market_data else 0) +
                              (len(result.financial_data.metrics) if result.financial_data else 0), retrieval=result.retrieval)
        except Exception as error:
            safe = public_error(error, request_id)
            log = ToolCallLog(tool_name=str(name), arguments=arguments, status="failed",
                              result_count=0, error_code=safe.code)
            logger.info("request_id=%s tool=%s status=failed error_code=%s", request_id, name, safe.code)
            raise ToolExecutionError(ValueError(f"{safe.code}: {safe.message}"), log) from error
        logger.info("request_id=%s tool=%s status=%s result_count=%s latency_ms=%s", request_id,
                    name, log.status, log.result_count, round((time.perf_counter() - started) * 1000))
        return result, log
