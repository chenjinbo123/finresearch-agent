"""A small, explicit contract for historical A-share daily bars."""

import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def market_today() -> date:
    return datetime.now(timezone(timedelta(hours=8))).date()


class MarketHistoryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent: Literal["get_market_history"] = "get_market_history"
    company_code: Literal["600519", "300750", "002594"]
    start_date: date | None = None
    end_date: date | None = None
    recent_trading_days: int | None = Field(default=None, ge=1, le=60, strict=True)
    adjustment: Literal["none"] = "none"

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def date_only(cls, value):
        if value is None or (isinstance(value, date) and not isinstance(value, datetime)):
            return value
        if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return value
        raise ValueError("日期必须为 YYYY-MM-DD")

    @model_validator(mode="after")
    def validate_window(self):
        if self.recent_trading_days is not None:
            if self.start_date is not None or self.end_date is not None:
                raise ValueError("最近交易日数量与日期区间不可混用")
        else:
            if self.start_date is None or self.end_date is None:
                raise ValueError("必须提供完整日期区间或最近交易日数量")
            if not date(1990, 1, 1) <= self.start_date <= self.end_date < market_today():
                raise ValueError("仅支持1990年起、今天之前的历史日期，开始日不得晚于结束日")
            if (self.end_date - self.start_date).days > 366:
                raise ValueError("单次日期跨度不可超过366天")
        return self


class MarketBar(BaseModel):
    trade_date: date
    open: Decimal = Field(gt=0, allow_inf_nan=False)
    high: Decimal = Field(gt=0, allow_inf_nan=False)
    low: Decimal = Field(gt=0, allow_inf_nan=False)
    close: Decimal = Field(gt=0, allow_inf_nan=False)
    volume: int = Field(ge=0, strict=True)

    @model_validator(mode="after")
    def valid_ohlc(self):
        if not self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high:
            raise ValueError("OHLC价格关系不合法")
        return self


class MarketHistory(BaseModel):
    company_code: str
    company_name: str
    exchange: Literal["SSE", "SZSE"]
    symbol: str
    currency: Literal["CNY"] = "CNY"
    price_unit: Literal["CNY/share"] = "CNY/share"
    volume_unit: Literal["share"] = "share"
    adjustment: Literal["none"] = "none"
    source: Literal["tencent_public_history"] = "tencent_public_history"
    source_url: str
    queried_at: datetime
    requested_start: date
    requested_end: date
    requested_recent_trading_days: int | None = None
    data_as_of: date | None = None
    status: Literal["ok", "no_data", "partial"]
    warning: str | None = None
    bars: list[MarketBar]
