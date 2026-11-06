"""Live financial reporting acceptance: python -m app.report_acceptance --live."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from app.main import app


def run_acceptance():
    results = []
    with TestClient(app) as client:
        for code, period, expected in [("600519", "2024FY", "ok"), ("300750", "2024FY", "ok"),
                                       ("002594", "2024FY", "ok"), ("600519", "2025H1", "ok"),
                                       ("002594", "2000FY", "no_data")]:
            response = client.post("/v1/financials/report", json={"company_code": code, "period": period})
            body = response.json()
            data = body.get("financial_data") or {}
            checks = {
                "http_ok": response.status_code == 200,
                "identity": data.get("company_code") == code and data.get("period") == period,
                "status": data.get("status") == expected,
                "source": data.get("source_report") == "RPT_F10_FINANCE_GINCOME",
                "fields": [m["source_field"] for m in data.get("metrics", [])] == (["OPERATE_INCOME", "PARENT_NETPROFIT"] if expected == "ok" else []),
                "dates": bool(data.get("notice_date")) and bool(data.get("source_updated_at")) if expected == "ok" else not data.get("notice_date"),
            }
            results.append({"name": f"{code}_{period}", "checks": checks, "response": body})
        response = client.post("/v1/chat", json={"question": "查询贵州茅台2024年报的真实营业收入和归母净利润"})
        body = response.json()
        data = body.get("financial_data") or {}
        results.append({"name": "real_chat", "checks": {
            "http_ok": response.status_code == 200,
            "real_planner": body.get("planner") == "deepseek",
            "correct_tool": body.get("plan", {}).get("intent") == "get_report_financials",
            "same_values_as_direct": bool(data.get("metrics")) and data.get("metrics") == results[0]["response"].get("financial_data", {}).get("metrics"),
            "separate_from_demo": body.get("results") == [] and body.get("evidence") is None,
        }, "response": body})
    return {"verified_at": datetime.now(timezone.utc).isoformat(),
            "passed": all(all(r["checks"].values()) for r in results), "results": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    if not parser.parse_args().live:
        parser.error("Pass --live to query the public provider and paid planning model")
    report = run_acceptance()
    root = Path(__file__).resolve().parent.parent / "data" / "financials"
    root.mkdir(parents=True, exist_ok=True)
    path = root / "report_acceptance.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "report": str(path),
                      "cases": [{"name": r["name"], "checks": r["checks"]} for r in report["results"]]}, ensure_ascii=False, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
