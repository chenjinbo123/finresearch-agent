"""Explicit live acceptance for the three local public annual reports.

Run `python -m app.knowledge_acceptance --live`. This calls paid model APIs but
never ingests documents or rebuilds their vectors. Reports stay in ignored local
knowledge storage. Requires the development dependencies for FastAPI TestClient.
"""

import argparse
import json
import math
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient
from pypdf import PdfReader

import app.knowledge as knowledge
import app.main as main
from app.config import get_settings
from app.embeddings import create_embedding_provider


CASES = [
    ("600519", "贵州茅台", "公司可能面对的风险", (22,), "宏观经济风险"),
    ("300750", "宁德时代", "宏观经济与市场波动风险", (39,), "市场需求下滑"),
    # Both the business overview (22) and technical discussion (28) explicitly
    # link blade batteries to LFP. Accept either independently verified passage.
    ("002594", "比亚迪", "刀片电池采用什么材料？", (22, 28), "磷酸铁锂"),
]


class ObservedEmbedding:
    def __init__(self, provider):
        self.provider = provider
        self.name = provider.name
        self.dimension = provider.dimension
        self.successful_calls = 0

    def embed(self, text):
        result = self.provider.embed(text)
        self.successful_calls += 1
        return result


def run_acceptance() -> dict:
    provider = ObservedEmbedding(create_embedding_provider(get_settings()))
    if provider.name != "dashscope":
        raise ValueError("ACCEPTANCE_CONFIG: Real DashScope embeddings are required")
    index = knowledge._load_index()
    documents = {doc["document_id"]: doc for doc in index["documents"]}
    chunks = {chunk["chunk_id"]: chunk for chunk in index["chunks"]}
    readers = {}
    results = []

    for code, name, _, _, _ in CASES:
        selected = [doc for doc in documents.values() if doc.get("company_code") == code]
        selected_ids = {doc["document_id"] for doc in selected}
        selected_chunks = [chunk for chunk in chunks.values() if chunk["document_id"] in selected_ids]
        results.append({"kind": "inventory", "company": name, "checks": {
            "document_present": bool(selected),
            "chunk_count": bool(selected_chunks) and len(selected_chunks) == sum(doc["chunk_count"] for doc in selected),
            "vectors_complete": bool(selected_chunks) and all(
                chunk.get("embedding_provider") == provider.name
                and len(chunk.get("embedding", [])) == provider.dimension
                and all(math.isfinite(value) for value in chunk["embedding"])
                for chunk in selected_chunks
            ),
            "report_year": bool(selected) and all(doc.get("report_year") == 2024 for doc in selected),
        }})

    def verify_citations(citations, company_code):
        for citation in citations:
            if citation["company_code"] != company_code:
                return False
            doc_id = citation["document_id"]
            if doc_id not in documents or documents[doc_id].get("company_code") != company_code:
                return False
            chunk = chunks.get(citation["chunk_id"])
            if not chunk or chunk["content"] != citation["excerpt"]:
                return False
            if doc_id not in readers:
                readers[doc_id] = PdfReader(knowledge.SOURCE_DOCUMENTS_DIR / f"{doc_id}.pdf")
            page = citation["page_number"]
            reader = readers[doc_id]
            if not 1 <= page <= len(reader.pages):
                return False
            page_text = knowledge._normalize_text(reader.pages[page - 1].extract_text() or "")
            if citation["excerpt"] not in page_text:
                return False
        return True

    with patch.object(knowledge, "_resolve_embedding_provider", lambda supplied: supplied or provider):
        with TestClient(main.app) as client:
            for code, name, query, expected_pages, phrase in CASES:
                before = provider.successful_calls
                response = client.post("/v1/knowledge/search", json={
                    "query": query, "company_code": code, "report_year": 2024, "limit": 5,
                })
                body = response.json()
                citations = body.get("citations", [])
                checks = {
                    "http_ok": response.status_code == 200,
                    "real_embedding": provider.successful_calls == before + 1,
                    "company_and_pdf_evidence": bool(citations) and verify_citations(citations, code),
                    "report_year": bool(citations) and all(c.get("report_year") == 2024 for c in citations),
                    "expected_evidence": any(
                        c["page_number"] in expected_pages and phrase in c["excerpt"]
                        for c in citations
                    ),
                }
                results.append({"kind": "retrieval", "company": name, "query": query,
                                "checks": checks, "response": body})

            # Absent-company queries must not borrow evidence from any existing report.
            response = client.post("/v1/knowledge/search", json={
                "query": "公司可能面对的风险", "company_code": "000001", "limit": 5,
            })
            results.append({"kind": "absent_company", "checks": {
                "empty_result": response.status_code == 200 and response.json().get("citations") == [],
            }, "response": response.json()})

            response = client.post("/v1/knowledge/search", json={
                "query": "公司可能面对的风险", "company_code": "600519",
                "report_year": 2023, "limit": 5,
            })
            results.append({"kind": "absent_year", "checks": {
                "empty_result": response.status_code == 200 and response.json().get("citations") == [],
            }, "response": response.json()})

            for code, name, _, _, _ in CASES[1:]:
                before = provider.successful_calls
                response = client.post("/v1/chat", json={
                    "question": f"请检索{name}2024年年报中的主要业务原文，并提供出处。",
                })
                body = response.json()
                citations = body.get("citations", [])
                plan = body.get("plan", {})
                checks = {
                    "http_ok": response.status_code == 200,
                    "real_planner": body.get("planner") == "deepseek",
                    "correct_plan": plan.get("intent") == "search_knowledge" and plan.get("company_code") == code,
                    "report_year": plan.get("report_year") == 2024 and bool(citations)
                    and all(c.get("report_year") == 2024 for c in citations),
                    "real_embedding": provider.successful_calls == before + 1,
                    "company_and_pdf_evidence": bool(citations) and verify_citations(citations, code),
                }
                results.append({"kind": "chat_routing", "company": name,
                                "checks": checks, "response": body})

    return {
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "passed": all(all(result["checks"].values()) for result in results),
        "inventory": [{key: doc.get(key) for key in (
            "company_code", "title", "page_count", "chunk_count",
        )} for doc in documents.values()],
        "results": results,
    }


def main_cli() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Call real paid embedding and planner APIs")
    args = parser.parse_args()
    if not args.live:
        parser.error("Pass --live to run the real API acceptance checks")
    report = run_acceptance()
    destination = knowledge.KNOWLEDGE_ROOT / "multi_company_acceptance.json"
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "report": str(destination),
                      "cases": [{key: item[key] for key in ("kind", "checks")} for item in report["results"]]},
                     ensure_ascii=False, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main_cli()
