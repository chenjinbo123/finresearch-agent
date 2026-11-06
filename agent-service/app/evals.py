"""Small, versioned regression harness for the first two Agent tools.

The suite deliberately uses LocalResearchPlanner and deterministic knowledge
fixtures. It checks workflow contracts without API cost or dependence on a
developer's local PDF uploads.
"""

import asyncio
import json
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from app.knowledge import search_knowledge
from app.models import Citation, ToolPlan
from app.services import (
    LocalResearchPlanner,
    format_financial_research_answer,
    format_knowledge_research_answer,
    get_financial_metrics,
)

EVAL_DATA_PATH = Path(__file__).resolve().parent.parent / "evals" / "tool_routing.jsonl"
NO_EVIDENCE_ANSWER = "现有资料不足以确认：在已入库的公开资料中未检索到相关原文证据。"


class EvalExpectation(BaseModel):
    outcome: Literal["success", "error"]
    intent: Literal["get_financial_metrics", "search_knowledge"] | None = None
    company_codes: list[str] | None = None
    company_code: str | None = None
    period: str | None = None
    metric_codes: list[str] | None = None
    error_code: str | None = None
    result_behavior: Literal[
        "financial_results", "citation_required", "safe_no_evidence"
    ] | None = None


class EvalCase(BaseModel):
    id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    expected: EvalExpectation


class EvalResult(BaseModel):
    id: str
    passed: bool
    expected_intent: str | None = None
    actual_intent: str | None = None
    failures: list[str] = Field(default_factory=list)


class EvalReport(BaseModel):
    total: int
    passed: int
    failed: int
    passed_by_intent: dict[str, int]
    results: list[EvalResult]


def load_eval_cases(path: Path = EVAL_DATA_PATH) -> list[EvalCase]:
    """Load strict JSONL so every evaluation change is reviewed in Git."""
    if not path.is_file():
        raise ValueError(f"EVAL_DATA_UNAVAILABLE: 未找到评测数据文件：{path}。")

    cases: list[EvalCase] = []
    case_ids: set[str] = set()
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            case = EvalCase.model_validate_json(line)
        except ValidationError as error:
            raise ValueError(f"EVAL_DATA_INVALID: 第 {line_number} 行格式不合法。") from error
        if case.id in case_ids:
            raise ValueError(f"EVAL_DATA_INVALID: 评测用例 ID 重复：{case.id}。")
        case_ids.add(case.id)
        cases.append(case)
    if not cases:
        raise ValueError("EVAL_DATA_INVALID: 评测数据为空。")
    return cases


def _fixture_citation(plan: ToolPlan) -> list[Citation]:
    """Stable evidence fixture for testing chat's citation branch, not retrieval quality."""
    if plan.intent != "search_knowledge":
        return []
    return [
        Citation(
            document_id="eval-public-document",
            title="评测用公开资料",
            company_code=plan.company_code,
            company_name=None,
            document_type="announcement",
            published_at="2025-08-20",
            page_number=1,
            chunk_id="eval-public-document:1:0",
            excerpt="公开资料中的经营风险提示原文。",
            score=1,
        )
    ]


def _error_code(error: ValueError) -> str:
    return str(error).split(":", maxsplit=1)[0]


def _check_plan(case: EvalCase, plan: ToolPlan) -> list[str]:
    expected = case.expected
    failures: list[str] = []
    if plan.intent != expected.intent:
        failures.append(f"工具应为 {expected.intent}，实际为 {plan.intent}")
        return failures
    if expected.company_codes is not None and getattr(plan, "company_codes", None) != expected.company_codes:
        failures.append("公司代码列表与预期不一致")
    if expected.company_code != getattr(plan, "company_code", None):
        failures.append("公司代码与预期不一致")
    if expected.period is not None and getattr(plan, "period", None) != expected.period:
        failures.append("报告期与预期不一致")
    if expected.metric_codes is not None and getattr(plan, "metric_codes", None) != expected.metric_codes:
        failures.append("指标列表与预期不一致")
    return failures


def _execute_for_eval(plan: ToolPlan, behavior: str | None) -> tuple[int, int, str]:
    """Run the same tools/formatters as chat, with controlled PDF-search data."""
    if plan.intent == "get_financial_metrics":
        results, _tool_call = get_financial_metrics(plan, request_id="eval")
        return len(results), 0, format_financial_research_answer(results)

    knowledge_searcher: Callable[..., list[Citation]]
    if behavior == "citation_required":
        knowledge_searcher = lambda **_kwargs: _fixture_citation(plan)
    elif behavior == "safe_no_evidence":
        knowledge_searcher = lambda **_kwargs: []
    else:
        knowledge_searcher = search_knowledge
    citations = knowledge_searcher(
        query=plan.query, company_code=plan.company_code, report_year=plan.report_year
    )
    return 0, len(citations), format_knowledge_research_answer(len(citations))


async def run_eval_case(case: EvalCase) -> EvalResult:
    """Evaluate one case without calling DeepSeek or requiring uploaded PDFs."""
    planner = LocalResearchPlanner()
    expected = case.expected
    try:
        plan = await planner.create_plan(case.question)
    except ValueError as error:
        actual_error = _error_code(error)
        failures = []
        if expected.outcome != "error":
            failures.append(f"不应报错，实际错误为 {actual_error}")
        elif actual_error != expected.error_code:
            failures.append(f"错误码应为 {expected.error_code}，实际为 {actual_error}")
        return EvalResult(
            id=case.id,
            passed=not failures,
            expected_intent=expected.intent,
            failures=failures,
        )

    failures = []
    if expected.outcome != "success":
        failures.append("预期应报错，但实际成功生成计划")
    failures.extend(_check_plan(case, plan))
    if not failures:
        result_count, citation_count, answer = _execute_for_eval(plan, expected.result_behavior)
        if expected.result_behavior == "financial_results" and result_count == 0:
            failures.append("财务工具未返回指标结果")
        if expected.result_behavior == "citation_required" and citation_count == 0:
            failures.append("资料工具未返回引用")
        if expected.result_behavior == "safe_no_evidence" and answer != NO_EVIDENCE_ANSWER:
            failures.append("资料不足时未返回标准安全答复")
    return EvalResult(
        id=case.id,
        passed=not failures,
        expected_intent=expected.intent,
        actual_intent=plan.intent,
        failures=failures,
    )


async def run_eval_suite(path: Path = EVAL_DATA_PATH) -> EvalReport:
    cases = load_eval_cases(path)
    results = [await run_eval_case(case) for case in cases]
    passed_by_intent = Counter(
        result.actual_intent for result in results if result.passed and result.actual_intent
    )
    passed = sum(result.passed for result in results)
    return EvalReport(
        total=len(results),
        passed=passed,
        failed=len(results) - passed,
        passed_by_intent=dict(passed_by_intent),
        results=results,
    )


def main() -> None:
    report = asyncio.run(run_eval_suite())
    print(report.model_dump_json(indent=2))
    if report.failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
