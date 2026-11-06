import asyncio

from app.evals import load_eval_cases, run_eval_suite


def test_eval_dataset_has_ten_versioned_cases() -> None:
    cases = load_eval_cases()

    assert len(cases) == 10
    assert len({case.id for case in cases}) == 10
    assert {case.expected.outcome for case in cases} == {"success", "error"}


def test_local_eval_suite_passes_without_model_or_uploaded_pdf() -> None:
    report = asyncio.run(run_eval_suite())

    assert report.total == 10
    assert report.passed == 10
    assert report.failed == 0
    assert report.passed_by_intent == {
        "get_financial_metrics": 4,
        "search_knowledge": 4,
    }
