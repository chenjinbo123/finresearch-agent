"""A bounded, read-only income-statement data adapter with explicit semantics."""

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Protocol

import httpx

from app.market import INSTRUMENTS
from app.market_models import market_today
from app.report_models import ReportFinancialData, ReportFinancialPlan, ReportMetric

SOURCE_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
REPORT = "RPT_F10_FINANCE_GINCOME"
FIELDS = {"revenue": ("OPERATE_INCOME", "营业收入"), "net_profit": ("PARENT_NETPROFIT", "归母净利润")}
COLUMNS = "SECURITY_CODE,SECURITY_NAME_ABBR,REPORT_DATE,REPORT_TYPE,NOTICE_DATE,UPDATE_DATE,CURRENCY,OPERATE_INCOME,PARENT_NETPROFIT"


class FinancialReportProvider(Protocol):
    def fetch(self, plan: ReportFinancialPlan) -> ReportFinancialData: ...


def source_date(value) -> date:
    if not isinstance(value, str):
        raise ValueError("invalid date type")
    # Provider uses ISO dates followed by a midnight time.
    return datetime.fromisoformat(value).date()


class EastmoneyFinancialProvider:
    def __init__(self, transport: httpx.BaseTransport | None = None):
        self.transport = transport

    def fetch(self, plan: ReportFinancialPlan) -> ReportFinancialData:
        plan = ReportFinancialPlan.model_validate(plan.model_dump())
        params = {"reportName": REPORT, "columns": COLUMNS,
                  "filter": f'(SECURITY_CODE="{plan.company_code}")(REPORT_DATE=\'{plan.period_end}\')',
                  "pageSize": "10", "pageNumber": "1", "source": "WEB", "client": "WEB"}
        try:
            with httpx.Client(timeout=httpx.Timeout(15, connect=5), transport=self.transport) as client:
                response = client.get(SOURCE_URL, params=params)
                response.raise_for_status()
        except httpx.TimeoutException as error:
            raise ValueError("REPORT_TIMEOUT: 财务数据源响应超时，请稍后重试。") from error
        except httpx.HTTPError as error:
            raise ValueError("REPORT_UNAVAILABLE: 财务数据源暂不可用，请稍后重试。") from error
        base = dict(company_code=plan.company_code, company_name=INSTRUMENTS[plan.company_code][0],
                    period=plan.period, period_start=date(int(plan.period[:4]), 1, 1), period_end=plan.period_end,
                    source_url=str(response.url), queried_at=datetime.now(timezone.utc))
        try:
            # Parse JSON decimal tokens directly; never round through binary floats.
            payload = json.loads(response.text, parse_float=Decimal)
            if (payload.get("success") is False and payload.get("code") == 9201
                    and payload.get("result") is None and payload.get("message") == "返回数据为空"):
                return ReportFinancialData(**base, status="no_data", missing_metrics=plan.metric_codes)
            if payload.get("success") is not True or payload.get("code") != 0:
                raise ValueError("upstream business failure")
            result = payload["result"]
            rows = result["data"]
            if not isinstance(rows, list) or result["count"] != len(rows) or result["pages"] not in (0, 1):
                raise ValueError("truncated or malformed result")
            if not rows:
                return ReportFinancialData(**base, status="no_data", missing_metrics=plan.metric_codes)
            # Different versions must not be chosen by arbitrary list order.
            if len(rows) != 1:
                raise ValueError("ambiguous records")
            row = rows[0]
            if (row["SECURITY_CODE"] != plan.company_code or source_date(row["REPORT_DATE"]) != plan.period_end
                    or row["CURRENCY"] != "CNY"
                    or row["REPORT_TYPE"] not in ({"年报"} if plan.period.endswith("FY") else {"中报", "半年报"})):
                raise ValueError("wrong company, period, currency or report type")
            notice, updated = source_date(row["NOTICE_DATE"]), source_date(row["UPDATE_DATE"])
            if not plan.period_end <= notice <= updated <= market_today():
                raise ValueError("inconsistent publication/update dates")
            metrics, missing = [], []
            for code in plan.metric_codes:
                field, name = FIELDS[code]
                raw = row[field]  # Missing key means schema drift; null means missing value.
                if raw is None:
                    missing.append(code)
                    continue
                if isinstance(raw, bool) or not isinstance(raw, (int, Decimal, str)):
                    raise ValueError("invalid value type")
                metric = ReportMetric(metric_code=code, metric_name=name, value=raw, source_field=field)
                metrics.append(metric)
            return ReportFinancialData(**base, status="partial" if missing else "ok", metrics=metrics,
                                       missing_metrics=missing, notice_date=notice, source_updated_at=updated,
                                       source_version=payload.get("version"), source_report_type=row["REPORT_TYPE"])
        except (ValueError, KeyError, TypeError, AttributeError, OverflowError) as error:
            raise ValueError("REPORT_INVALID_RESPONSE: 财务数据字段、口径或记录身份异常，本次不返回未经校验的指标。") from error


report_provider: FinancialReportProvider = EastmoneyFinancialProvider()


def format_report_answer(data: ReportFinancialData) -> str:
    lines = [f"【真实财报数据】{data.company_name} {data.period}，累计区间 {data.period_start} 至 {data.period_end}。"]
    for metric in data.metrics:
        lines.append(f"- {metric.metric_name}：{metric.value:,.2f} 元（{metric.value / Decimal('100000000'):,.2f} 亿元）。")
    if data.status == "no_data":
        lines.append("该公司该报告期未返回财务记录，不使用演示CSV补齐，也不能据此认定未披露。")
    elif data.missing_metrics:
        lines.append("以下指标缺失，未当作0或用相近口径替代：" + "、".join(FIELDS[c][1] for c in data.missing_metrics) + "。")
    lines.append(f"来源：东方财富利润表；公告日期 {data.notice_date or '未返回'}；数据源更新日期 {data.source_updated_at or '未返回'}；查询时间 {data.queried_at.isoformat()}。")
    lines.append(data.warning)
    return "\n".join(lines)
