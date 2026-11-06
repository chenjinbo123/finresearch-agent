import asyncio
from dataclasses import replace

import httpx
import pytest

import app.services as services
from app.config import get_settings


@pytest.mark.parametrize("question, expected", [
    ("2024年年报经营风险", 2024),
    ("2024年度报告的主要业务", 2024),
    ("2025年发布的2024年年报", 2024),
    ("年报有哪些风险", None),
    ("2025年发布的公告", None),
])
def test_explicit_report_year_is_not_publication_date(question, expected):
    assert services.explicit_report_year(question) == expected


@pytest.mark.parametrize("question", ["比较2023年年报和2024年年报", "比较2023和2024年报"])
def test_multiple_explicit_report_years_are_not_silently_collapsed(question):
    with pytest.raises(ValueError, match="MULTIPLE_REPORT_YEARS"):
        services.explicit_report_year(question)


@pytest.mark.parametrize("model_year", [None, 2025, 2024])
def test_deepseek_preserves_explicit_year_when_model_omits_or_confuses_it(monkeypatch, model_year):
    settings = replace(get_settings(), deepseek_api_key="test-key", deepseek_base_url="https://example.test")
    real_client = httpx.AsyncClient
    def handle(_request):
        import json
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({
            "intent": "search_knowledge", "query": "经营风险", "company_code": "600519",
            "report_year": model_year,
        })}}]})
    monkeypatch.setattr(services.httpx, "AsyncClient", lambda **kwargs: real_client(
        transport=httpx.MockTransport(handle), trust_env=False, **kwargs,
    ))
    plan = asyncio.run(services.DeepSeekResearchPlanner(settings).create_plan(
        "贵州茅台2025年发布的2024年年报有哪些风险？"
    ))
    assert plan.report_year == 2024
