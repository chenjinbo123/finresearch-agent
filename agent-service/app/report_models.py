"""Real reported financials stay separate from the demonstration CSV contract."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.market_models import market_today

MetricCode = Literal["revenue", "net_profit"]


class ReportFinancialPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent: Literal["get_report_financials"] = "get_report_financials"
    company_code: Literal["600519", "300750", "002594"]
    period: str = Field(pattern=r"^20\d{2}(FY|H1)$")
    metric_codes: list[MetricCode] = Field(default_factory=lambda: ["revenue", "net_profit"], min_length=1, max_length=2)

    @property
    def period_end(self) -> date:
        return date(int(self.period[:4]), 12, 31) if self.period.endswith("FY") else date(int(self.period[:4]), 6, 30)

    @model_validator(mode="after")
    def valid_period(self):
        if self.period_end >= market_today():
            raise ValueError("只查询已经结束的年报或半年报报告期")
        if len(set(self.metric_codes)) != len(self.metric_codes):
            raise ValueError("指标不可重复")
        return self


class ReportMetric(BaseModel):
    metric_code: MetricCode
    metric_name: str
    value: Decimal = Field(allow_inf_nan=False)
    unit: Literal["CNY"] = "CNY"
    source_field: Literal["OPERATE_INCOME", "PARENT_NETPROFIT"]


class ReportFinancialData(BaseModel):
    company_code: str
    company_name: str
    period: str
    period_start: date
    period_end: date
    basis: Literal["year_to_date"] = "year_to_date"
    source: Literal["eastmoney_income_statement"] = "eastmoney_income_statement"
    source_url: str
    source_report: Literal["RPT_F10_FINANCE_GINCOME"] = "RPT_F10_FINANCE_GINCOME"
    source_version: str | None = None
    source_report_type: Literal["年报", "中报", "半年报"] | None = None
    queried_at: datetime
    notice_date: date | None = None
    source_updated_at: date | None = None
    revision_policy: Literal["latest_source_snapshot"] = "latest_source_snapshot"
    status: Literal["ok", "no_data", "partial"]
    metrics: list[ReportMetric] = Field(default_factory=list)
    missing_metrics: list[MetricCode] = Field(default_factory=list)
    warning: str = "数据为查询时数据源提供的最新版本，可能含后续修订；不是历史时点快照，不能直接用于无前视偏差回测。"
