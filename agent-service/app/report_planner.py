"""Explicit real-data mode avoids silently replacing the learning CSV tool."""

import re
from app.report_models import ReportFinancialPlan


def report_plan_from_question(question: str, force: bool = False) -> ReportFinancialPlan | None:
    requested = any(word in question for word in ("真实", "东方财富", "在线财报"))
    if not force and not requested:
        return None
    if "营业总收入" in question:
        raise ValueError("UNSUPPORTED_REPORT_METRIC: 当前真实财报支持营业收入，不支持营业总收入。")
    if not any(word in question for word in ("营收", "营业收入", "净利润")):
        if not force:
            return None
        raise ValueError("UNSUPPORTED_REPORT_METRIC: 请明确查询营业收入或归母净利润。")
    if "演示" in question:
        raise ValueError("AMBIGUOUS_DATA_MODE: 请分别查询真实财报或演示数据。")
    if any(word in question for word in ("单季度", "一季度", "三季度", "四季度", "二季度", "Q1", "Q2", "Q3", "Q4", "扣非", "营业总收入", "同比", "环比")):
        raise ValueError("UNSUPPORTED_REPORT_METRIC: 当前真实财报只支持年报或半年报累计营业收入、归母净利润，不计算增速。")
    codes = set(re.findall(r"(?<!\d)\d{6}(?!\d)", question))
    for name, code in (("茅台", "600519"), ("宁德时代", "300750"), ("比亚迪", "002594")):
        if name in question:
            codes.add(code)
    if len(codes) != 1 or not codes <= {"600519", "300750", "002594"}:
        raise ValueError("UNSUPPORTED_COMPANY: 真实财报每次只支持茅台、宁德时代、比亚迪中的一个标的。")
    shared_years = re.search(r"(20\d{2})\s*年?\s*(?:和|与|、|至|到|-)\s*(20\d{2})\s*(?:FY|H1|年?年报|年?中报|年?半年报)", question)
    if shared_years and shared_years[1] != shared_years[2]:
        raise ValueError("INVALID_REPORT_PERIOD: 当前真实财报一次只查询一个报告期，请分开提问。")
    periods = []
    for match in re.finditer(r"(?<!\d)(20\d{2})\s*(FY|H1|年?上半年|年?半年报|年?半年度报告|年?中报|年?年度报告|年?年报|年?全年)", question):
        periods.append(match[1] + ("H1" if any(word in match[2] for word in ("H1", "半年", "中报")) else "FY"))
    if len(set(periods)) != 1:
        raise ValueError("INVALID_REPORT_PERIOD: 请明确一个报告期，例如2024年报、2025年上半年、2024FY或2025H1。")
    codes_requested = []
    if "营收" in question or "营业收入" in question:
        codes_requested.append("revenue")
    if "净利润" in question:
        codes_requested.append("net_profit")
    try:
        return ReportFinancialPlan(company_code=codes.pop(), period=periods[0], metric_codes=codes_requested)
    except ValueError as error:
        raise ValueError("INVALID_REPORT_PERIOD: 真实财报仅支持2000年起已经结束的年报和半年报报告期。") from error
