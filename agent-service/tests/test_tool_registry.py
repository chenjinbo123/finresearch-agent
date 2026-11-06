from typing import Literal

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict

import app.main as main
from app.errors import ToolExecutionError
from app.models import FinancialMetricsPlan
from app.tool_registry import ToolDefinition, ToolRegistry, ToolResult
from app.tools import tool_registry


class AddPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    intent: Literal["add_numbers"] = "add_numbers"
    left: int
    right: int


def make_tool(handler=None, category="pure_compute"):
    return ToolDefinition(name="add_numbers", description="测试用纯计算工具", category=category,
                          input_model=AddPlan, handler=handler or (lambda p, _: ToolResult(answer=str(p.left + p.right))),
                          progress_message="正在计算")


def test_new_tool_works_in_chat_and_stream_without_controller_branch(monkeypatch):
    registry = ToolRegistry()
    registry.register(make_tool())

    class Planner:
        planner_name = "local_rule"

        async def create_plan(self, question):
            return registry.parse({"intent": "add_numbers", "left": 2, "right": 3})

    monkeypatch.setattr(main, "tool_registry", registry)
    monkeypatch.setattr(main, "planner", Planner())
    with TestClient(main.app) as client:
        response = client.post("/v1/chat", json={"question": "计算 2 加 3"})
        stream = client.post("/v1/chat/stream", json={"question": "计算 2 加 3"})
    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "5"
    assert body["plan"]["intent"] == "add_numbers"
    assert body["tool_calls"][0]["tool_name"] == "add_numbers"
    assert body["evidence"] is None
    assert '"stage": "evidence_check"' not in stream.text
    assert '"text": "5"' in stream.text
    assert "event: completed" in stream.text


@pytest.mark.parametrize("arguments", [
    {"intent": "unknown"},
    {"intent": "add_numbers", "left": "2", "right": 3},
    {"intent": "add_numbers", "left": 2},
    {"intent": "add_numbers", "left": 2, "right": 3, "command": "unexpected"},
    None,
])
def test_bad_arguments_never_reach_handler(arguments):
    registry = ToolRegistry()
    registry.register(make_tool(lambda *_: pytest.fail("invalid tool must not execute")))
    with pytest.raises(ValueError, match="PLANNER_INVALID_OUTPUT"):
        registry.parse(arguments)


def test_execute_revalidates_constructed_models_and_logs_failure():
    registry = ToolRegistry()
    registry.register(make_tool(lambda *_: pytest.fail("invalid tool must not execute")))
    forged = AddPlan.model_construct(left="not-an-int", right=3)
    with pytest.raises(ToolExecutionError) as failure:
        registry.execute(forged, "request-test")
    assert failure.value.tool_call.status == "failed"
    assert failure.value.tool_call.error_code == "PLANNER_INVALID_OUTPUT"


def test_side_effect_tools_are_described_but_not_executable():
    registry = ToolRegistry()
    registry.register(make_tool(lambda *_: pytest.fail("side effect must not execute"), category="side_effect"))
    assert registry.describe()[0]["available_in_chat"] is False
    with pytest.raises(ToolExecutionError, match="TOOL_NOT_ALLOWED"):
        registry.execute(AddPlan(left=1, right=2), "request-test")


def test_duplicate_registration_is_rejected():
    registry = ToolRegistry()
    registry.register(make_tool())
    with pytest.raises(ValueError, match="TOOL_ALREADY_REGISTERED"):
        registry.register(make_tool())


def test_catalog_name_must_match_parameter_schema():
    registry = ToolRegistry()
    with pytest.raises(ValueError, match="TOOL_SCHEMA_INVALID"):
        registry.register(ToolDefinition(name="wrong", description="invalid", category="read_only",
                                         input_model=AddPlan, handler=lambda *_: None, progress_message="invalid"))


@pytest.mark.parametrize("result", [None, {"answer": "not validated"}])
def test_invalid_tool_result_is_sanitized(result):
    registry = ToolRegistry()
    registry.register(make_tool(lambda *_: result))
    with pytest.raises(ToolExecutionError) as failure:
        registry.execute(AddPlan(left=1, right=2), "request-test")
    assert failure.value.tool_call.error_code == "INTERNAL_ERROR"


def test_tools_catalog_exposes_schemas_not_handlers_or_credentials():
    with TestClient(main.app) as client:
        response = client.get("/v1/tools")
    assert response.status_code == 200
    catalog = {tool["name"]: tool for tool in response.json()["tools"]}
    assert set(catalog) == {"get_financial_metrics", "search_knowledge", "get_market_history", "get_report_financials"}
    assert catalog["get_financial_metrics"]["data_kind"] == "demo"
    assert catalog["search_knowledge"]["requires_evidence"] is True
    assert "report_year" in catalog["search_knowledge"]["parameters"]["properties"]
    assert "handler" not in response.text
    assert "api_key" not in response.text


def test_builtin_rejects_extra_model_arguments():
    with pytest.raises(ValueError, match="PLANNER_INVALID_OUTPUT"):
        tool_registry.parse({"intent": "get_financial_metrics", "company_codes": ["600519"],
                             "period": "2025H1", "metric_codes": ["revenue"], "sql": "SELECT *"})
    result, log = tool_registry.execute(FinancialMetricsPlan(intent="get_financial_metrics",
        company_codes=["600519"], period="2025H1", metric_codes=["revenue"]), "test")
    assert log.result_count == 1
    assert "演示数据" in result.answer
