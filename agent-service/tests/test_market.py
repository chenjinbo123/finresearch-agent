import asyncio
import json
import time
from dataclasses import replace
from datetime import date
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient

import app.main as main
import app.market as market
from app.market_models import MarketHistoryPlan
from app.market_planner import market_plan_from_question
from app.services import LocalResearchPlanner
import app.services as services

ROWS = [
    ["2025-01-06", "100.00", "102.00", "105.00", "99.00", "100.25"],
    ["2025-01-07", "102.00", "101.00", "103.00", "100.00", "200"],
]


def provider_for(rows=ROWS, payload=None, exception=None, status=200):
    def handler(request):
        if exception:
            raise exception
        symbol = request.url.params["param"].split(",")[0]
        body = payload if payload is not None else {"code": 0, "data": {symbol: {"day": rows}}}
        return httpx.Response(status, json=body)
    return market.TencentMarketProvider(httpx.MockTransport(handler))


def plan(**kwargs):
    return MarketHistoryPlan(company_code="600519", start_date="2025-01-06", end_date="2025-01-10", **kwargs)


def test_adapter_normalizes_order_units_and_records_source():
    result = provider_for(rows=[ROWS[1], ROWS[0], ROWS[0]]).history(plan())
    assert len(result.bars) == 2
    bar = result.bars[0]
    assert bar.close == Decimal("102") and bar.high == Decimal("105") and bar.low == Decimal("99")
    assert bar.volume == 10025
    assert result.symbol == "sh600519" and result.exchange == "SSE"
    assert result.data_as_of == date(2025, 1, 7)
    assert result.queried_at.tzinfo is not None
    assert "param=" in result.source_url


@pytest.mark.parametrize("code,symbol", [("300750", "sz300750"), ("002594", "sz002594"), ("600519", "sh600519")])
def test_explicit_market_mapping(code, symbol):
    request = plan().model_copy(update={"company_code": code})
    assert provider_for().history(request).symbol == symbol


@pytest.mark.parametrize("row", [
    ["2025-01-06", "100", "102", "99", "98", "100"],
    ["2025-01-06", "NaN", "102", "105", "99", "100"],
    ["2025-01-06", "100", "102", "105", "99", "-100"],
    ["2025-01-06", "100", "102", "105", "99", "0.001"],
    ["bad-date", "100", "102", "105", "99", "100"],
    ["2025-01-06", "100"],
])
def test_corrupt_rows_are_not_silently_dropped(row):
    with pytest.raises(ValueError, match="MARKET_INVALID_RESPONSE"):
        provider_for(rows=[row]).history(plan())


@pytest.mark.parametrize("payload", [
    {"code": 1}, {}, {"code": 0, "data": {}},
    {"code": 0, "data": {"sh600519": {"qfqday": ROWS}}},
])
def test_missing_unadjusted_series_is_not_treated_as_no_data(payload):
    with pytest.raises(ValueError, match="MARKET_INVALID_RESPONSE"):
        provider_for(payload=payload).history(plan())


def test_conflicting_duplicate_rejected():
    changed = list(ROWS[0]); changed[2] = "103"
    with pytest.raises(ValueError, match="MARKET_INVALID_RESPONSE"):
        provider_for(rows=[ROWS[0], changed]).history(plan())


def test_no_data_does_not_invent_non_trading_day_explanation():
    request = MarketHistoryPlan(company_code="600519", start_date="2025-01-11", end_date="2025-01-12")
    result = provider_for().history(request)
    assert result.status == "no_data" and result.bars == []
    assert "不能单凭空结果" in result.warning


def test_recent_counts_actual_rows_and_marks_partial_or_old(monkeypatch):
    monkeypatch.setattr(market, "market_today", lambda: date(2025, 1, 20))
    request = MarketHistoryPlan(company_code="600519", recent_trading_days=5)
    result = provider_for().history(request)
    assert result.status == "partial" and len(result.bars) == 2
    assert "超过7天" in result.warning
    assert result.requested_end == date(2025, 1, 19)
    result = provider_for().history(MarketHistoryPlan(company_code="600519", recent_trading_days=1))
    assert len(result.bars) == 1 and result.bars[0].trade_date == date(2025, 1, 7)


@pytest.mark.parametrize("args", [
    {"recent_trading_days": True}, {"recent_trading_days": 61},
    {"start_date": "2025-01-10", "end_date": "2025-01-06"},
    {"start_date": "2023-01-01", "end_date": "2025-01-01"},
    {"start_date": "2099-01-01", "end_date": "2099-01-02"},
    {"start_date": 1736121600, "end_date": "2025-01-10"},
    {"start_date": "2025-01-06T00:00:00", "end_date": "2025-01-10"},
    {"recent_trading_days": 5, "start_date": "2025-01-06", "end_date": "2025-01-10"},
])
def test_invalid_periods_fail_before_network(args):
    with pytest.raises(ValueError):
        MarketHistoryPlan(company_code="600519", **args)


@pytest.mark.parametrize("question", [
    "茅台最近5个交易日股价", "查询600519最近五个交易日行情", "贵州茅台最近几个交易日行情",
])
def test_local_recent_planning(question):
    result = asyncio.run(LocalResearchPlanner().create_plan(question))
    assert result.intent == "get_market_history" and result.recent_trading_days == 5


@pytest.mark.parametrize("model_plan", [
    {"intent": "get_market_history", "company_code": "002594", "recent_trading_days": 20},
    {"intent": "search_knowledge", "query": "股价", "company_code": "002594"},
])
def test_deepseek_cannot_change_explicit_market_constraints(monkeypatch, model_plan):
    real_client = httpx.AsyncClient
    def handle(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(model_plan)}}]})
    monkeypatch.setattr(services.httpx, "AsyncClient", lambda **kwargs: real_client(
        transport=httpx.MockTransport(handle), **kwargs))
    planner = services.DeepSeekResearchPlanner(replace(main.settings, deepseek_api_key="test-not-real"))
    result = asyncio.run(planner.create_plan("贵州茅台2025-01-06至2025-01-10行情"))
    assert result.company_code == "600519" and result.intent == "get_market_history"
    assert result.start_date == date(2025, 1, 6) and result.end_date == date(2025, 1, 10)
    assert result.recent_trading_days is None


@pytest.mark.parametrize("question,code", [
    ("招商银行最近5个交易日行情", "UNSUPPORTED_COMPANY"),
    ("茅台与比亚迪最近5个交易日行情", "UNSUPPORTED_COMPANY"),
    ("茅台最近5个交易日前复权行情", "UNSUPPORTED_ADJUSTMENT"),
    ("茅台实时股价", "UNSUPPORTED_FREQUENCY"),
    ("茅台行情", "INVALID_MARKET_PERIOD"),
    ("茅台2025-01-01至2025-01-05行情及营收", "MULTIPLE_TOOLS_REQUIRED"),
])
def test_unsupported_questions_are_not_silently_reinterpreted(question, code):
    with pytest.raises(ValueError, match=code):
        market_plan_from_question(question)


@pytest.mark.parametrize("fault,status,code", [
    ("timeout", 504, "MARKET_TIMEOUT"), ("network", 503, "MARKET_UNAVAILABLE"),
    ("malformed", 502, "MARKET_INVALID_RESPONSE"),
])
def test_market_failure_http_and_sse(monkeypatch, fault, status, code):
    exception = httpx.ReadTimeout("secret") if fault == "timeout" else httpx.ConnectError("secret") if fault == "network" else None
    monkeypatch.setattr(market, "market_provider", provider_for(exception=exception, payload={} if fault == "malformed" else None))
    monkeypatch.setattr(main, "planner", LocalResearchPlanner())
    with TestClient(main.app) as client:
        response = client.post("/v1/market/history", json=plan().model_dump(mode="json"))
        stream = client.post("/v1/chat/stream", json={"question": "茅台2025-01-06至2025-01-10行情"})
    assert response.status_code == status and response.json()["code"] == code
    assert response.json()["tool_calls"][0]["status"] == "failed"
    assert code in stream.text and "event: completed" not in stream.text
    assert "secret" not in response.text + stream.text


def test_direct_chat_and_stream_share_actual_market_result(monkeypatch):
    monkeypatch.setattr(market, "market_provider", provider_for())
    monkeypatch.setattr(main, "planner", LocalResearchPlanner())
    with TestClient(main.app) as client:
        direct = client.post("/v1/market/history", json=plan().model_dump(mode="json")).json()
        chat = client.post("/v1/chat", json={"question": "茅台2025年1月6日至2025年1月10日行情"}).json()
        stream = client.post("/v1/chat/stream", json={"question": "茅台2025-01-06至2025-01-10行情"})
        invalid = client.post("/v1/market/history", json={"company_code": "000001", "recent_trading_days": 5})
    completed = [json.loads(line[6:]) for line in stream.text.splitlines() if line.startswith("data: ")][-1]
    assert direct["market_data"]["bars"] == chat["market_data"]["bars"] == completed["market_data"]["bars"]
    assert chat["results"] == [] and chat["citations"] == [] and chat["evidence"] is None
    assert chat["tool_calls"][0]["result_count"] == 2
    assert invalid.status_code == 422


def test_slow_market_io_does_not_block_event_loop(monkeypatch):
    class SlowProvider:
        def history(self, request):
            time.sleep(0.5)
            return provider_for().history(request)
    monkeypatch.setattr(market, "market_provider", SlowProvider())

    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
            started = time.monotonic()
            task = asyncio.create_task(client.post("/v1/market/history", json=plan().model_dump(mode="json")))
            await asyncio.sleep(0.05)
            health = await client.get("/health")
            elapsed = time.monotonic() - started
            response = await task
            assert health.status_code == response.status_code == 200
            assert elapsed < 0.4
    asyncio.run(check())
