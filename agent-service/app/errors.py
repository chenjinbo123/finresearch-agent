"""Shared public error contract for JSON and SSE; never include raw exceptions."""

import re

from app.models import ErrorResponse, ToolCallLog


class ToolExecutionError(ValueError):
    def __init__(self, error: ValueError, tool_call: ToolCallLog):
        super().__init__(str(error))
        self.tool_call = tool_call


def public_error(error: Exception, request_id: str) -> ErrorResponse:
    code, separator, message = str(error).partition(":")
    if not isinstance(error, ValueError) or not separator or not re.fullmatch(r"[A-Z][A-Z0-9_]+", code):
        code, message = "INTERNAL_ERROR", "服务处理失败，请凭请求编号排查。"
    return ErrorResponse(
        code=code, message=message.strip(), request_id=request_id,
        tool_calls=[error.tool_call] if isinstance(error, ToolExecutionError) else [],
    )


def error_status(code: str) -> int:
    if code == "INTERNAL_ERROR":
        return 500
    if code.endswith("_TIMEOUT"):
        return 504
    if code in {"MODEL_UNAVAILABLE", "EMBEDDING_UNAVAILABLE", "EMBEDDING_ACCOUNT_UNAVAILABLE", "MARKET_UNAVAILABLE", "REPORT_UNAVAILABLE"}:
        return 503
    if code in {"PLANNER_INVALID_OUTPUT", "EMBEDDING_INVALID_RESPONSE", "EMBEDDING_DIMENSION_MISMATCH", "MARKET_INVALID_RESPONSE", "REPORT_INVALID_RESPONSE"}:
        return 502
    return 400
