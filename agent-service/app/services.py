import csv
import json
import logging
import math
import re
from functools import lru_cache
from pathlib import Path
from typing import Protocol

import httpx

from app.config import Settings
from app.models import FinancialMetric, FinancialMetricsPlan, KnowledgeSearchPlan, ToolCallLog, ToolPlan
from app.prompts import FINANCIAL_PLANNER_SYSTEM_PROMPT
from app.market_planner import market_plan_from_question
from app.market_models import MarketHistoryPlan
from app.report_planner import report_plan_from_question
from app.report_models import ReportFinancialPlan

logger = logging.getLogger("finresearch.agent.tool")

COMPANIES = {
    "宁德时代": "300750",
    "比亚迪": "002594",
    "贵州茅台":"600519"
}

METRICS = {
    "营收": "revenue",
    "营业收入": "revenue",
    "归母净利润": "net_profit",
    "净利润": "net_profit",
}

FINANCIAL_METRICS_CSV_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "financial_metrics.csv"
)
FINANCIAL_METRICS_COLUMNS = {
    "company_code",
    "company_name",
    "report_period",
    "metric_code",
    "metric_value",
    "unit",
    "source_document",
    "source_page_number",
    "published_at",
}


def _financial_data_error(code: str, message: str) -> ValueError:
    """Create one API-safe error shape for the CSV-backed data tool."""
    return ValueError(f"{code}: {message}")


def _required_csv_value(row: dict[str, str | None], column: str, row_number: int) -> str:
    value = (row.get(column) or "").strip()
    if not value:
        raise _financial_data_error(
            "FINANCIAL_DATA_INVALID", f"财务数据第 {row_number} 行缺少 {column}。"
        )
    return value


@lru_cache
def load_financial_metrics() -> dict[tuple[str, str, str], FinancialMetric]:
    """Load and validate the small demo dataset once per process.

    CSV is an intermediate storage layer for the learning project. Keeping this
    validation boundary means the tool can later switch to PostgreSQL without
    changing its API contract or allowing the LLM to access raw storage.
    """
    if not FINANCIAL_METRICS_CSV_PATH.is_file():
        raise _financial_data_error(
            "FINANCIAL_DATA_UNAVAILABLE", "未找到财务指标数据文件。"
        )

    try:
        with FINANCIAL_METRICS_CSV_PATH.open("r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            actual_columns = set(reader.fieldnames or [])
            missing_columns = FINANCIAL_METRICS_COLUMNS - actual_columns
            if missing_columns:
                raise _financial_data_error(
                    "FINANCIAL_DATA_INVALID",
                    f"财务数据文件缺少字段：{', '.join(sorted(missing_columns))}。",
                )

            metrics: dict[tuple[str, str, str], FinancialMetric] = {}
            for row_number, row in enumerate(reader, start=2):
                company_code = _required_csv_value(row, "company_code", row_number)
                company_name = _required_csv_value(row, "company_name", row_number)
                report_period = _required_csv_value(row, "report_period", row_number)
                metric_code = _required_csv_value(row, "metric_code", row_number)
                metric_value_text = _required_csv_value(row, "metric_value", row_number)
                unit = _required_csv_value(row, "unit", row_number)
                source_document = _required_csv_value(row, "source_document", row_number)
                page_number_text = _required_csv_value(row, "source_page_number", row_number)
                published_at = _required_csv_value(row, "published_at", row_number)

                try:
                    metric_value = float(metric_value_text)
                    page_number = int(page_number_text)
                    metric = FinancialMetric(
                        company_code=company_code,
                        company_name=company_name,
                        report_period=report_period,
                        metric_code=metric_code,
                        metric_name={"revenue": "营业收入", "net_profit": "归母净利润"}[metric_code],
                        metric_value=metric_value,
                        unit=unit,
                        source_document=source_document,
                        source_page_number=page_number,
                        published_at=published_at,
                    )
                except (KeyError, TypeError, ValueError) as error:
                    raise _financial_data_error(
                        "FINANCIAL_DATA_INVALID", f"财务数据第 {row_number} 行字段格式不合法。"
                    ) from error

                if not math.isfinite(metric_value) or page_number < 1:
                    raise _financial_data_error(
                        "FINANCIAL_DATA_INVALID",
                        f"财务数据第 {row_number} 行金额或页码不合法。",
                    )

                key = (company_code, report_period, metric_code)
                if key in metrics:
                    raise _financial_data_error(
                        "FINANCIAL_DATA_INVALID",
                        f"财务数据第 {row_number} 行存在重复指标：{company_code}/{report_period}/{metric_code}。",
                    )
                metrics[key] = metric
    except OSError as error:
        raise _financial_data_error(
            "FINANCIAL_DATA_UNAVAILABLE", "无法读取财务指标数据文件。"
        ) from error

    if not metrics:
        raise _financial_data_error("FINANCIAL_DATA_INVALID", "财务指标数据文件为空。")
    return metrics


def explicit_report_year(question: str) -> int | None:
    """Extract an explicitly named report year, never its publication date."""
    shared = re.search(
        r"((?:19|20)\d{2})\s*年?\s*(?:和|与|、|至|到|-)\s*((?:19|20)\d{2})\s*年?\s*(?:年度报告|年报)",
        question,
    )
    if shared and shared[1] != shared[2]:
        raise ValueError("MULTIPLE_REPORT_YEARS: 当前每次只能检索一个报告年份，请分别提问。")
    years = set(re.findall(
        r"(?<!\d)((?:19|20)\d{2})\s*年?\s*(?:年度报告|年报|半年度报告|半年报|季度报告|季报)",
        question,
    ))
    if len(years) > 1:
        raise ValueError("MULTIPLE_REPORT_YEARS: 当前每次只能检索一个报告年份，请分别提问。")
    return int(next(iter(years))) if years else None


class LocalResearchPlanner:
    """Deterministic planner used in offline learning and automated tests."""

    planner_name = "local_rule"

    async def create_plan(self, question: str) -> ToolPlan:
        market_plan = market_plan_from_question(question)
        if market_plan is not None:
            return market_plan
        report_plan = report_plan_from_question(question)
        if report_plan is not None:
            return report_plan
        company_codes = [code for name, code in COMPANIES.items() if name in question]
        metric_codes = list(dict.fromkeys(code for name, code in METRICS.items() if name in question))
        if metric_codes:
            if not company_codes:
                raise ValueError("UNSUPPORTED_COMPANY: 目前只支持宁德时代、比亚迪和贵州茅台。")
            if "2025H1" not in question and "2025年上半年" not in question:
                raise ValueError("UNSUPPORTED_PERIOD: 第一版仅支持 2025H1。")
            return FinancialMetricsPlan(
                intent="get_financial_metrics",
                company_codes=company_codes,
                period="2025H1",
                metric_codes=metric_codes,
            )

        return KnowledgeSearchPlan(
            intent="search_knowledge",
            query=question,
            company_code=company_codes[0] if len(company_codes) == 1 else None,
            report_year=explicit_report_year(question),
        )


class ResearchPlanner(Protocol):
    planner_name: str

    async def create_plan(self, question: str) -> ToolPlan: ...


class DeepSeekResearchPlanner:
    """Use DeepSeek only to turn a question into a validated tool plan.

    The model never receives database credentials and never queries financial
    data itself. It returns a plan which is validated before the tool runs.
    """

    planner_name = "deepseek"

    def __init__(self, settings: Settings) -> None:
        if not settings.deepseek_api_key:
            raise ValueError("DEEPSEEK_NOT_CONFIGURED: 未配置 DEEPSEEK_API_KEY。")
        self._settings = settings

    async def create_plan(self, question: str) -> ToolPlan:
        market_constraints = market_plan_from_question(question)
        report_constraints = report_plan_from_question(question)
        payload = {
            "model": self._settings.deepseek_model,
            "messages": [
                {"role": "system", "content": FINANCIAL_PLANNER_SYSTEM_PROMPT},
                {"role": "user", "content": question},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
            "max_tokens": 300,
        }
        headers = {
            "Authorization": f"Bearer {self._settings.deepseek_api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=self._settings.deepseek_timeout_seconds) as client:
                response = await client.post(
                    f"{self._settings.deepseek_base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
        except httpx.TimeoutException as error:
            raise ValueError("MODEL_TIMEOUT: DeepSeek 响应超时，请稍后重试。") from error
        except httpx.HTTPStatusError as error:
            logger.warning("deepseek_status=%s", error.response.status_code)
            raise ValueError("MODEL_UNAVAILABLE: DeepSeek 请求失败，请检查 Key、余额或模型配置。") from error
        except httpx.HTTPError as error:
            raise ValueError("MODEL_UNAVAILABLE: 无法连接 DeepSeek 服务，请检查网络和配置。") from error

        try:
            content = response.json()["choices"][0]["message"]["content"]
            plan = validate_tool_plan(json.loads(content))
            if report_constraints is not None:
                return report_constraints
            if isinstance(plan, ReportFinancialPlan):
                raise ValueError("真实财报查询需明确真实数据模式")
            if market_constraints is not None:
                return market_constraints
            if isinstance(plan, MarketHistoryPlan):
                return market_plan_from_question(question, force=True)
            if isinstance(plan, KnowledgeSearchPlan):
                year = explicit_report_year(question)
                if year is not None:
                    # Preserve explicit user constraints even if the model omitted
                    # the year while shortening the query into search keywords.
                    plan = plan.model_copy(update={"report_year": year})
            return plan
        except (KeyError, IndexError, TypeError, json.JSONDecodeError, ValueError) as error:
            logger.warning("deepseek_invalid_plan error_type=%s", type(error).__name__)
            raise ValueError("PLANNER_INVALID_OUTPUT: 模型未返回合法的查询计划，请重试。") from error


def create_planner(settings: Settings) -> ResearchPlanner:
    """Use DeepSeek only when a key is configured; otherwise keep local learning mode."""
    if settings.deepseek_enabled:
        return DeepSeekResearchPlanner(settings)
    return LocalResearchPlanner()


def validate_tool_plan(value: object) -> ToolPlan:
    """Validate that a planner chose exactly one tool from the fixed allowlist."""
    # Lazy import keeps tool adapters independent from planner initialization.
    from app.tools import tool_registry
    return tool_registry.parse(value)


def get_financial_metrics(
    plan: FinancialMetricsPlan, request_id: str
) -> tuple[list[FinancialMetric], ToolCallLog]:
    """Return deterministic, source-linked values for a validated tool plan."""
    results: list[FinancialMetric] = []
    metrics = load_financial_metrics()

    for company_code in plan.company_codes:
        for metric_code in plan.metric_codes:
            key = (company_code, plan.period, metric_code)
            metric = metrics.get(key)
            if metric is None:
                raise _financial_data_error(
                    "FINANCIAL_DATA_NOT_FOUND",
                    f"未找到 {company_code} 在 {plan.period} 的 {metric_code} 数据。",
                )
            results.append(metric)

    tool_call = ToolCallLog(
        tool_name="get_financial_metrics",
        arguments=plan,
        status="success",
        result_count=len(results),
    )
    logger.info(
        "request_id=%s tool=%s arguments=%s status=%s result_count=%s",
        request_id,
        tool_call.tool_name,
        plan.model_dump_json(),
        tool_call.status,
        tool_call.result_count,
    )
    return results, tool_call


def format_financial_research_answer(results: list[FinancialMetric]) -> str:
    """Build a readable answer from tool results without asking an LLM to recalculate facts."""
    if not results:
        return "现有资料不足以确认：未查询到符合条件的财务指标。"

    company_metrics: dict[str, list[FinancialMetric]] = {}
    for metric in results:
        company_metrics.setdefault(metric.company_name, []).append(metric)

    summary_lines = ["【演示数据】以下数字来自本地示例数据集，不代表已核验的真实财务结果。",
                     f"已查询到 {results[0].report_period} 的结构化财务数据："]
    for company_name, metrics in company_metrics.items():
        metric_text = "；".join(
            f"{metric.metric_name} {metric.metric_value / 100_000_000:,.2f} 亿元"
            for metric in metrics
        )
        summary_lines.append(f"- {company_name}：{metric_text}。")

    source_lines = []
    seen_sources: set[tuple[str, int, str]] = set()
    for metric in results:
        source = (metric.source_document, metric.source_page_number, metric.published_at)
        if source not in seen_sources:
            seen_sources.add(source)
            source_lines.append(f"- {source[0]}，第 {source[1]} 页，发布日期 {source[2]}。")

    return "\n".join([*summary_lines, "", "数据来源：", *source_lines])


def format_knowledge_research_answer(citation_count: int) -> str:
    """Describe retrieval status without letting the model invent a conclusion."""
    if citation_count == 0:
        return "现有资料不足以确认：在已入库的公开资料中未检索到相关原文证据。"
    return f"已检索到 {citation_count} 条候选公开资料原文，请结合下方引用中的页码和原文片段复核。候选片段不代表已经充分回答问题。"
