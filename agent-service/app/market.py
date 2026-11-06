"""Read-only Tencent adapter: bounded requests, no fabricated missing sessions."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Protocol

import httpx

from app.market_models import MarketBar, MarketHistory, MarketHistoryPlan, market_today

SOURCE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
INSTRUMENTS = {
    "600519": ("贵州茅台", "SSE", "sh600519"),
    "300750": ("宁德时代", "SZSE", "sz300750"),
    "002594": ("比亚迪", "SZSE", "sz002594"),
}


class MarketDataProvider(Protocol):
    def history(self, plan: MarketHistoryPlan) -> MarketHistory: ...


class TencentMarketProvider:
    def __init__(self, transport: httpx.BaseTransport | None = None):
        self.transport = transport

    def history(self, plan: MarketHistoryPlan) -> MarketHistory:
        # Validation is also required when called outside the tool registry.
        plan = MarketHistoryPlan.model_validate(plan.model_dump())
        name, exchange, symbol = INSTRUMENTS[plan.company_code]
        end = plan.end_date or market_today() - timedelta(days=1)
        start = plan.start_date or end - timedelta(days=max(30, plan.recent_trading_days * 4 + 30))
        try:
            with httpx.Client(timeout=httpx.Timeout(15, connect=5), transport=self.transport) as client:
                response = client.get(SOURCE_URL, params={"param": f"{symbol},day,{start},{end},640,"})
                response.raise_for_status()
        except httpx.TimeoutException as error:
            raise ValueError("MARKET_TIMEOUT: 行情数据源超时，请稍后重试。") from error
        except httpx.HTTPError as error:
            raise ValueError("MARKET_UNAVAILABLE: 行情数据源暂不可用，请稍后重试。") from error
        try:
            payload = response.json()
            if payload.get("code") != 0:
                raise ValueError("upstream business error")
            rows = payload["data"][symbol]["day"]  # Never silently accept qfqday/hfqday.
            if not isinstance(rows, list):
                raise ValueError("invalid rows")
            by_date = {}
            for row in rows:
                if not isinstance(row, list) or len(row) < 6:
                    raise ValueError("invalid row")
                shares = Decimal(str(row[5])) * 100  # Only these three non-STAR A shares.
                if not shares.is_finite() or shares != shares.to_integral_value():
                    raise ValueError("invalid volume")
                bar = MarketBar(trade_date=row[0], open=row[1], close=row[2], high=row[3], low=row[4], volume=int(shares))
                if bar.trade_date in by_date and by_date[bar.trade_date] != bar:
                    raise ValueError("conflicting duplicate date")
                by_date[bar.trade_date] = bar
            bars = sorted((b for b in by_date.values() if start <= b.trade_date <= end), key=lambda b: b.trade_date)
        except (ValueError, KeyError, TypeError, AttributeError, InvalidOperation, OverflowError) as error:
            raise ValueError("MARKET_INVALID_RESPONSE: 行情响应字段或数值异常，本次不返回未经校验的数据。") from error
        if plan.recent_trading_days:
            bars = bars[-plan.recent_trading_days:]
        status = "ok" if bars else "no_data"
        warning = None
        if not bars:
            warning = "该区间数据源未返回交易记录；不能单凭空结果区分休市、停牌或数据缺失。"
        elif plan.recent_trading_days and len(bars) < plan.recent_trading_days:
            status = "partial"
            warning = "回看窗口内记录不足，返回实际记录，未补齐或虚构交易日。"
        if bars and plan.recent_trading_days and (end - bars[-1].trade_date).days > 7:
            warning = (warning or "") + "最新记录距离查询截止日超过7天，请核对休市、停牌或数据源延迟。"
        return MarketHistory(company_code=plan.company_code, company_name=name, exchange=exchange, symbol=symbol,
                             source_url=str(response.url), queried_at=datetime.now(timezone.utc),
                             requested_start=start, requested_end=end, requested_recent_trading_days=plan.recent_trading_days,
                             data_as_of=bars[-1].trade_date if bars else None, status=status, warning=warning, bars=bars)


market_provider: MarketDataProvider = TencentMarketProvider()


def format_market_answer(data: MarketHistory) -> str:
    lines = [f"{data.company_name}（{data.symbol}）历史日行情：不复权，价格单位为元/股，成交量单位为股。"]
    if data.bars:
        lines.append(f"共 {len(data.bars)} 条记录，实际覆盖 {data.bars[0].trade_date} 至 {data.data_as_of}。")
        for bar in data.bars[-10:]:
            lines.append(f"- {bar.trade_date}：开 {bar.open}，高 {bar.high}，低 {bar.low}，收 {bar.close}，成交量 {bar.volume} 股。")
        if len(data.bars) > 10:
            lines.append("以上展示最后10条，完整数据见 market_data.bars。")
    if data.warning:
        lines.append(data.warning)
    lines.append(f"来源：腾讯公开历史行情；查询时间：{data.queried_at.isoformat()}。这是历史数据，不是实时行情。")
    return "\n".join(lines)
