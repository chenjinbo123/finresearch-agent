"""Opt-in live evidence gate regression: python -m app.evidence_acceptance --live."""

import argparse
import json
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.knowledge import KNOWLEDGE_ROOT

CASES = [
    ("risk_supported", "贵州茅台2024年年报中公司可能面对哪些风险？请提供原文。", "sufficient"),
    ("battery_supported", "比亚迪2024年年报中刀片电池采用什么材料？请提供原文。", "sufficient"),
    ("unrelated", "请检索贵州茅台2024年年报：公司在火星建设酒厂的计划具体是什么？", "insufficient"),
    ("partial", "请检索贵州茅台2024年年报：公司可能面对哪些风险？针对每项风险董事会表决的赞成票各是多少？", "insufficient"),
]


def run_acceptance():
    results = []
    with TestClient(app) as client:
        for name, question, expected in CASES:
            response = client.post("/v1/chat", json={"question": question})
            body = response.json()
            assessment = body.get("evidence") or {}
            citations = {c["chunk_id"]: c for c in body.get("citations", [])}
            supports = assessment.get("supports", [])
            checks = {
                "http_ok": response.status_code == 200,
                "real_planner": body.get("planner") == "deepseek",
                "real_checker": assessment.get("checker") == "deepseek",
                "expected_status": assessment.get("status") == expected,
                "candidates_present": bool(citations),
                "quote_integrity": all(s["chunk_id"] in citations and s["quote"] in citations[s["chunk_id"]]["excerpt"] for s in supports),
                "supports_or_refusal": bool(supports) if expected == "sufficient" else not supports and "现有资料不足以确认" in body.get("answer", ""),
            }
            results.append({"name": name, "question": question, "checks": checks, "response": body})
    return {"verified_at": datetime.now(timezone.utc).isoformat(),
            "passed": all(all(r["checks"].values()) for r in results), "results": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Calls paid DeepSeek and embedding APIs")
    if not parser.parse_args().live:
        parser.error("Pass --live to call real paid APIs")
    report = run_acceptance()
    KNOWLEDGE_ROOT.mkdir(parents=True, exist_ok=True)
    path = KNOWLEDGE_ROOT / "evidence_acceptance.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "report": str(path),
                      "cases": [{"name": r["name"], "checks": r["checks"]} for r in report["results"]]}, ensure_ascii=False, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
