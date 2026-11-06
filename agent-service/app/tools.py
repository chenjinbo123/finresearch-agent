"""Built-in tool adapters and their explicit catalog."""

from app.knowledge import expand_evidence_context, search_knowledge
from app.models import FinancialMetricsPlan, KnowledgeSearchPlan, RetrievalDiagnostics
from app.services import get_financial_metrics, format_financial_research_answer, format_knowledge_research_answer
from app.tool_registry import ToolDefinition, ToolRegistry, ToolResult
from app import market
from app.market_models import MarketHistoryPlan
from app import report_financials
from app.report_models import ReportFinancialPlan


def financial_tool(plan: FinancialMetricsPlan, request_id: str) -> ToolResult:
    results, _ = get_financial_metrics(plan, request_id)
    return ToolResult(results=results, answer=format_financial_research_answer(results))


def knowledge_tool(plan: KnowledgeSearchPlan, request_id: str) -> ToolResult:
    diagnostics = RetrievalDiagnostics()
    citations = search_knowledge(query=plan.query, company_code=plan.company_code,
                                 report_year=plan.report_year, diagnostics=diagnostics)
    ranked_count = len(citations)
    citations = expand_evidence_context(citations)
    diagnostics.context_chunk_count = len(citations) - ranked_count
    return ToolResult(citations=citations, retrieval=diagnostics,
                      status="degraded" if diagnostics.degraded else ("success" if citations else "no_evidence"),
                      answer=format_knowledge_research_answer(len(citations)))


def market_tool(plan: MarketHistoryPlan, request_id: str) -> ToolResult:
    data = market.market_provider.history(plan)
    return ToolResult(market_data=data, answer=market.format_market_answer(data),
                      status="no_evidence" if not data.bars else "success")


def report_financial_tool(plan: ReportFinancialPlan, request_id: str) -> ToolResult:
    data = report_financials.report_provider.fetch(plan)
    return ToolResult(financial_data=data, answer=report_financials.format_report_answer(data),
                      status="no_evidence" if not data.metrics else "success")


tool_registry = ToolRegistry()
tool_registry.register(ToolDefinition(
    name="get_financial_metrics", description="查询本地演示 CSV 中 2025H1 的营业收入与归母净利润。",
    category="read_only", input_model=FinancialMetricsPlan, handler=financial_tool,
    progress_message="正在查询财务指标", data_kind="demo",
))
tool_registry.register(ToolDefinition(
    name="search_knowledge", description="按公司及报告年份检索已入库公开资料，返回原文与出处。",
    category="read_only", input_model=KnowledgeSearchPlan, handler=knowledge_tool,
    progress_message="正在检索公开资料证据", data_kind="public_document", requires_evidence=True,
))
tool_registry.register(ToolDefinition(
    name="get_market_history", description="查询茅台、宁德时代、比亚迪的真实不复权A股历史日行情，明确日期区间或最近交易日数量。",
    category="read_only", input_model=MarketHistoryPlan, handler=market_tool,
    progress_message="正在查询真实历史行情", data_kind="market_history",
))
tool_registry.register(ToolDefinition(
    name="get_report_financials", description="查询东方财富真实年报/半年报累计营业收入与归母净利润；当前源最新版本，不是历史时点快照。",
    category="read_only", input_model=ReportFinancialPlan, handler=report_financial_tool,
    progress_message="正在查询真实财报指标", data_kind="reported_financials",
))
