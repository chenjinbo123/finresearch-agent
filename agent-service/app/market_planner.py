"""Preserve explicit market-query constraints independently of LLM rewriting."""

import re
from app.market_models import MarketHistoryPlan

MARKET_WORDS = ("行情", "股价", "开盘价", "收盘价", "成交量", "日线", "最高价", "最低价")


def market_plan_from_question(question: str, force: bool = False) -> MarketHistoryPlan | None:
    if not force and not any(word in question for word in MARKET_WORDS):
        return None
    if any(word in question for word in ("营业收入", "营收", "净利润")):
        raise ValueError("MULTIPLE_TOOLS_REQUIRED: 行情与财务指标请分别提问，当前一次只执行一个工具。")
    if "复权" in question.replace("不复权", ""):
        raise ValueError("UNSUPPORTED_ADJUSTMENT: 当前行情工具仅支持不复权。")
    if any(word in question for word in ("实时", "分时", "分钟线", "周线", "月线")):
        raise ValueError("UNSUPPORTED_FREQUENCY: 当前仅支持今天之前的历史日行情。")
    codes = set(re.findall(r"(?<!\d)\d{6}(?!\d)", question))
    for name, code in (("茅台", "600519"), ("宁德时代", "300750"), ("比亚迪", "002594")):
        if name in question:
            codes.add(code)
    if len(codes) != 1 or not codes <= {"600519", "300750", "002594"}:
        raise ValueError("UNSUPPORTED_COMPANY: 行情查询每次只支持茅台、宁德时代、比亚迪中的一个标的。")
    dates = re.findall(r"(?<!\d)(\d{4})[-年](\d{1,2})[-月](\d{1,2})日?(?!\d)", question)
    recent = re.search(r"(?:最近|近)\s*(\d+|一|二|两|三|四|五|六|七|八|九|十|几)\s*个?交易日", question)
    args = {"company_code": codes.pop()}
    if recent:
        if dates:
            raise ValueError("INVALID_MARKET_PERIOD: 最近交易日数量与日期范围请勿混用。")
        numbers = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
                   "六": 6, "七": 7, "八": 8, "九": 9, "十": 10, "几": 5}
        args["recent_trading_days"] = int(recent[1]) if recent[1].isdigit() else numbers[recent[1]]
    elif len(dates) in (1, 2):
        formatted = [f"{int(y):04d}-{int(m):02d}-{int(d):02d}" for y, m, d in dates]
        args.update(start_date=formatted[0], end_date=formatted[-1])
    else:
        raise ValueError("INVALID_MARKET_PERIOD: 请给出YYYY-MM-DD日期区间，或最近N个交易日（1至60）。")
    try:
        return MarketHistoryPlan.model_validate(args)
    except ValueError as error:
        raise ValueError("INVALID_MARKET_PERIOD: 日期无效、区间过长或包含今天/未来日期，请查询过去366天跨度内的历史区间。") from error
