import asyncio
import json
from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient

import app.evidence as evidence
import app.main as main
import app.tools as tool_module
import app.knowledge as knowledge
from app.models import Citation, KnowledgeSearchPlan


@pytest.fixture
def citation():
    return Citation(document_id="report", title="贵州茅台2024年报", company_code="600519",
                    company_name="贵州茅台", document_type="annual_report", report_year=2024,
                    page_number=22, chunk_id="report:22:3", score=1000,
                    excerpt="可能面对的风险：一是宏观经济风险；二是安全风险；三是舆情风险；四是环境保护风险。")


@pytest.fixture
def checker():
    return evidence.EvidenceChecker(replace(main.settings, deepseek_api_key="test-not-a-real-key"))


@pytest.fixture
def mock_model(monkeypatch):
    real_client = httpx.AsyncClient

    def install(decision=None, error=None, status=200, raw=None):
        requests = []

        def handler(request):
            requests.append(json.loads(request.content))
            if error:
                raise error
            return httpx.Response(status, json={"choices": [{"message": {
                "content": raw if raw is not None else json.dumps(decision, ensure_ascii=False),
            }}]})

        monkeypatch.setattr(evidence.httpx, "AsyncClient", lambda **kwargs: real_client(
            transport=httpx.MockTransport(handler), **kwargs))
        return requests

    return install


def test_verified_quotes_keep_original_question_and_ignore_rank(checker, citation, mock_model):
    requests = mock_model({"status": "sufficient", "support_chunk_ids": [citation.chunk_id]})
    result = asyncio.run(checker.assess("贵州茅台2024年报有哪些风险？", [citation]))
    assert result.status == "sufficient"
    user = json.loads(requests[0]["messages"][1]["content"])
    assert user["question"] == "贵州茅台2024年报有哪些风险？"
    assert "score" not in user["candidates"][0]
    answer = evidence.evidence_answer(result, [citation])
    assert "第 22 页" in answer
    assert result.supports[0].quote in citation.excerpt


@pytest.mark.parametrize("decision", [
    {"status": "sufficient", "support_chunk_ids": []},
    {"status": "sufficient", "support_chunk_ids": ["invented"]},
    {"status": "sufficient", "support_chunk_ids": ["report:22:3", "report:22:3"]},
    {"status": "insufficient", "support_chunk_ids": ["report:22:3"]},
    {"status": "certain", "support_chunk_ids": []},
    {"status": "sufficient", "support_chunk_ids": ["report:22:3"], "answer": "伪造结论"},
])
def test_invalid_decisions_never_pass(checker, citation, mock_model, decision):
    mock_model(decision)
    result = asyncio.run(checker.assess("问题", [citation]))
    assert result.status == "unavailable"
    assert result.reason_code == "CHECKER_INVALID_OUTPUT"
    assert result.supports == []


@pytest.mark.parametrize("kind,expected", [("timeout", "CHECKER_TIMEOUT"), ("http", "CHECKER_UNAVAILABLE"), ("json", "CHECKER_INVALID_OUTPUT")])
def test_checker_failures_fail_closed(checker, citation, mock_model, kind, expected, caplog):
    mock_model(error=httpx.ReadTimeout("secret") if kind == "timeout" else None,
               status=503 if kind == "http" else 200, raw="secret-not-json")
    result = asyncio.run(checker.assess("问题", [citation]))
    assert result.status == "unavailable"
    assert result.reason_code == expected
    assert "secret" not in caplog.text


def test_no_candidates_and_no_key_skip_network(checker, citation, mock_model):
    requests = mock_model(raw="should-not-be-called")
    assert asyncio.run(checker.assess("问题", [])).reason_code == "NO_CANDIDATES"
    checker.settings = replace(checker.settings, deepseek_api_key=None)
    assert asyncio.run(checker.assess("问题", [citation])).reason_code == "CHECKER_NOT_CONFIGURED"
    assert requests == []


def test_context_adds_only_immediate_same_page_neighbors(monkeypatch, citation):
    chunks = [
        {"document_id": doc, "page_number": page, "chunk_id": key, "content": content}
        for doc, page, key, content in [
            ("report", 22, "previous", "前一个片段原文"),
            ("report", 22, citation.chunk_id, citation.excerpt),
            ("report", 22, "next", "后一个片段包含具体风险清单"),
            ("report", 22, "too-far", "同页更远的片段"),
            ("report", 23, "other-page", "下一页不能混入"),
            ("other", 22, "other-company", "其他公司不能混入"),
        ]
    ]
    monkeypatch.setattr(knowledge, "_load_index", lambda: {"documents": [], "chunks": chunks})
    result = knowledge.expand_evidence_context([citation])
    assert [c.chunk_id for c in result] == [citation.chunk_id, "previous", "next"]
    assert result[-1].excerpt == "后一个片段包含具体风险清单"
    assert all(c.company_code == "600519" and c.page_number == 22 for c in result)
    assert len(knowledge.expand_evidence_context([citation], max_chunks=2)) == 2


@pytest.mark.parametrize("decision_status", ["sufficient", "insufficient", "unavailable"])
def test_chat_and_stream_share_gate_and_use_full_question(monkeypatch, checker, citation, mock_model, decision_status):
    class Planner:
        planner_name = "local_rule"

        async def create_plan(self, question):
            return KnowledgeSearchPlan(intent="search_knowledge", query="风险", company_code="600519", report_year=2024)

    supports = [citation.chunk_id] if decision_status == "sufficient" else []
    requests = mock_model({"status": decision_status, "support_chunk_ids": supports})
    monkeypatch.setattr(main, "planner", Planner())
    monkeypatch.setattr(main, "evidence_checker", checker)
    monkeypatch.setattr(tool_module, "search_knowledge", lambda **kwargs: [citation])
    monkeypatch.setattr(tool_module, "expand_evidence_context", lambda candidates: candidates)
    question = "贵州茅台2024年有哪些风险，董事会针对这些风险的表决票数是多少？"
    with TestClient(main.app) as client:
        response = client.post("/v1/chat", json={"question": question})
        stream = client.post("/v1/chat/stream", json={"question": question})
    body = response.json()
    assert response.status_code == 200
    assert body["evidence"]["status"] == decision_status
    assert len(body["citations"]) == 1  # Candidates remain inspectable, even on refusal.
    for request in requests:
        assert json.loads(request["messages"][1]["content"])["question"] == question
    events = [json.loads(line[6:]) for line in stream.text.splitlines() if line.startswith("data: ")]
    assert any(event.get("stage") == "evidence_check" for event in events)
    assert events[-1]["evidence"] == body["evidence"]
    assert events[-1]["answer"] == body["answer"]
    if decision_status != "sufficient":
        assert "本次不生成研究结论" in body["answer"]
        assert body["evidence"]["supports"] == []
