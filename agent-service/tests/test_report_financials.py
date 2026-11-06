import asyncio
import json
from dataclasses import replace
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient

import app.main as main
import app.report_financials as financials
import app.services as services
from app.report_models import ReportFinancialPlan
from app.report_planner import report_plan_from_question

ROW = {
    "SECURITY_CODE": "600519", "SECURITY_NAME_ABBR": "贵州茅台", "REPORT_DATE": "2024-12-31 00:00:00",
    "REPORT_TYPE": "年报", "NOTICE_DATE": "2025-04-03 00:00:00", "UPDATE_DATE": "2026-04-17 00:00:00",
    "CURRENCY": "CNY", "OPERATE_INCOME": "170899152276.34", "PARENT_NETPROFIT": "86228146421.62",
    "TOTAL_OPERATE_INCOME": "174144069958.25", "NETPROFIT": "89334728025.90",
}


def provider(row=None, payload=None, exception=None, status=200):
    def handle(request):
        if exception:
            raise exception
        data = payload if payload is not None else {"success": True, "code": 0, "version": "test",
            "result": {"pages": 1, "count": 1, "data": [ROW if row is None else row]}}
        return httpx.Response(status, json=data)
    return financials.EastmoneyFinancialProvider(httpx.MockTransport(handle))


def plan(**kwargs):
    return ReportFinancialPlan(company_code="600519", period="2024FY", **kwargs)


def test_business_fields_are_not_replaced_by_similar_metrics():
    result = provider().fetch(plan())
    assert result.status == "ok"
    assert result.metrics[0].source_field == "OPERATE_INCOME"
    assert result.metrics[0].value == Decimal("170899152276.34")
    assert result.metrics[1].source_field == "PARENT_NETPROFIT"
    assert result.metrics[1].value == Decimal("86228146421.62")
    assert result.notice_date.isoformat() == "2025-04-03"
    assert result.source_updated_at.isoformat() == "2026-04-17"
    assert "历史时点快照" in result.warning
    assert result.source_version == "test"


def test_null_is_partial_not_zero_and_no_fallback_to_total_revenue():
    result = provider(row={**ROW, "OPERATE_INCOME": None}).fetch(plan())
    assert result.status == "partial" and result.missing_metrics == ["revenue"]
    assert [m.metric_code for m in result.metrics] == ["net_profit"]
    assert "缺失" in financials.format_report_answer(result)


@pytest.mark.parametrize("label", ["中报", "半年报"])
def test_half_year_source_labels_preserve_ytd_period(label):
    row = {**ROW, "REPORT_DATE": "2025-06-30 00:00:00", "REPORT_TYPE": label,
           "NOTICE_DATE": "2025-08-13 00:00:00", "UPDATE_DATE": "2026-08-15 00:00:00"}
    result = provider(row=row).fetch(ReportFinancialPlan(company_code="600519", period="2025H1"))
    assert result.status == "ok" and result.source_report_type == label
    assert result.period_start.isoformat() == "2025-01-01" and result.period_end.isoformat() == "2025-06-30"
    assert result.basis == "year_to_date"


def test_zero_and_negative_profit_are_valid():
    result = provider(row={**ROW, "OPERATE_INCOME": "0", "PARENT_NETPROFIT": "-123.45"}).fetch(plan())
    assert result.status == "ok"
    assert [m.value for m in result.metrics] == [Decimal(0), Decimal("-123.45")]


def test_json_decimal_tokens_do_not_round_through_float():
    text = json.dumps({"success": True, "code": 0, "result": {"pages": 1, "count": 1, "data": [ROW]}})
    text = text.replace('"170899152276.34"', '170899152276.123456789')
    source = financials.EastmoneyFinancialProvider(httpx.MockTransport(lambda _: httpx.Response(200, text=text)))
    assert source.fetch(plan()).metrics[0].value == Decimal("170899152276.123456789")


@pytest.mark.parametrize("field,value", [
    ("SECURITY_CODE", "002594"), ("REPORT_DATE", "2025-06-30"), ("REPORT_TYPE", "一季报"),
    ("CURRENCY", "USD"), ("NOTICE_DATE", "2024-01-01"), ("UPDATE_DATE", "2024-01-01"),
    ("UPDATE_DATE", "2099-01-01"), ("OPERATE_INCOME", "NaN"), ("OPERATE_INCOME", True),
    ("PARENT_NETPROFIT", "Infinity"), ("PARENT_NETPROFIT", "--"),
])
def test_identity_and_invalid_values_fail_closed(field, value):
    with pytest.raises(ValueError, match="REPORT_INVALID_RESPONSE"):
        provider(row={**ROW, field: value}).fetch(plan())


def test_missing_field_is_schema_error():
    row = dict(ROW); row.pop("OPERATE_INCOME")
    with pytest.raises(ValueError, match="REPORT_INVALID_RESPONSE"):
        provider(row=row).fetch(plan())


@pytest.mark.parametrize("payload", [
    {"success": True, "code": 0, "result": {"data": [ROW, ROW], "count": 2, "pages": 1}},
    {"success": True, "code": 0, "result": {"data": [ROW], "count": 2, "pages": 2}},
    {"success": False, "code": 9201, "result": None, "message": "unknown failure"},
    {"success": True, "code": 0, "result": None},
])
def test_ambiguous_or_invalid_source_not_misreported_as_no_data(payload):
    with pytest.raises(ValueError, match="REPORT_INVALID_RESPONSE"):
        provider(payload=payload).fetch(plan())


def test_observed_no_data_business_code_has_safe_empty_result():
    data = provider(payload={"success": False, "code": 9201, "result": None, "message": "返回数据为空"}).fetch(plan())
    assert data.status == "no_data" and not data.metrics
    assert "不使用演示CSV补齐" in financials.format_report_answer(data)


@pytest.mark.parametrize("question,expected", [
    ("贵州茅台2024年报真实营业收入和归母净利润", "2024FY"),
    ("东方财富600519的2025H1营收", "2025H1"),
    ("查询比亚迪2025年上半年真实净利润", "2025H1"),
    ("查询比亚迪2025中报真实营业收入", "2025H1"),
    ("查询宁德时代2025年发布的2024年报真实营收", "2024FY"),
])
def test_explicit_real_mode_and_report_period(question, expected):
    result = asyncio.run(services.LocalResearchPlanner().create_plan(question))
    assert result.intent == "get_report_financials" and result.period == expected


@pytest.mark.parametrize("question", [
    "茅台真实营收", "茅台和比亚迪2024年报真实营收", "茅台2024年报真实扣非净利润",
    "茅台2024年报真实营业总收入和净利润", "茅台2024年报和2025半年报真实营收",
    "茅台2025Q1真实营收", "茅台2024年报真实营收同比", "茅台2024年报演示与真实营收",
    "茅台2024年报真实营业总收入",
    "比较茅台2024和2025年报真实营业收入",
])
def test_unsupported_semantics_are_rejected(question):
    with pytest.raises(ValueError):
        report_plan_from_question(question)


def test_existing_demo_request_stays_explicitly_demo():
    result = asyncio.run(services.LocalResearchPlanner().create_plan("贵州茅台2025H1营收"))
    assert result.intent == "get_financial_metrics"


def test_model_cannot_change_real_report_scope(monkeypatch):
    original = httpx.AsyncClient
    model_plan = {"intent": "get_report_financials", "company_code": "002594", "period": "2025H1", "metric_codes": ["net_profit"]}
    monkeypatch.setattr(services.httpx, "AsyncClient", lambda **kwargs: original(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(model_plan)}}]})), **kwargs))
    planner = services.DeepSeekResearchPlanner(replace(main.settings, deepseek_api_key="test-key"))
    result = asyncio.run(planner.create_plan("查询贵州茅台2024年报的真实营业收入"))
    assert result.company_code == "600519" and result.period == "2024FY" and result.metric_codes == ["revenue"]


def test_direct_chat_stream_and_missing_data_share_contract(monkeypatch):
    monkeypatch.setattr(main, "planner", services.LocalResearchPlanner())
    monkeypatch.setattr(financials, "report_provider", provider())
    with TestClient(main.app) as client:
        direct = client.post("/v1/financials/report", json=plan().model_dump(mode="json")).json()
        chat = client.post("/v1/chat", json={"question": "茅台2024年报真实营业收入和归母净利润"}).json()
        stream = client.post("/v1/chat/stream", json={"question": "茅台2024年报真实营业收入和归母净利润"})
    completed = [json.loads(line[6:]) for line in stream.text.splitlines() if line.startswith("data: ")][-1]
    assert direct["financial_data"]["metrics"] == chat["financial_data"]["metrics"] == completed["financial_data"]["metrics"]
    assert chat["results"] == [] and chat["evidence"] is None and chat["market_data"] is None
    assert chat["tool_calls"][0]["result_count"] == 2


@pytest.mark.parametrize("fault,http_status,error_code", [
    (httpx.ReadTimeout("private"), 504, "REPORT_TIMEOUT"),
    (httpx.ConnectError("private"), 503, "REPORT_UNAVAILABLE"),
    (None, 502, "REPORT_INVALID_RESPONSE"),
])
def test_failures_use_shared_http_and_stream_error_contract(monkeypatch, fault, http_status, error_code):
    monkeypatch.setattr(financials, "report_provider", provider(exception=fault, payload={}))
    monkeypatch.setattr(main, "planner", services.LocalResearchPlanner())
    with TestClient(main.app) as client:
        direct = client.post("/v1/financials/report", json=plan().model_dump(mode="json"))
        stream = client.post("/v1/chat/stream", json={"question": "茅台2024年报真实营业收入"})
    assert direct.status_code == http_status and direct.json()["code"] == error_code
    assert direct.json()["tool_calls"][0]["status"] == "failed"
    assert error_code in stream.text and "event: completed" not in stream.text
    assert "private" not in direct.text + stream.text
