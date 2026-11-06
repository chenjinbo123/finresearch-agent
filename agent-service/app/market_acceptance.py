"""Live market regression: python -m app.market_acceptance --live.

Uses public market HTTP requests and one paid DeepSeek planning request.
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from app.main import app


def run_acceptance():
    results = []
    with TestClient(app) as client:
        cases = [
            ("moutai", {"company_code": "600519", "start_date": "2025-01-06", "end_date": "2025-01-10"}, 5),
            ("catl", {"company_code": "300750", "start_date": "2025-01-06", "end_date": "2025-01-10"}, 5),
            ("byd", {"company_code": "002594", "start_date": "2025-01-06", "end_date": "2025-01-10"}, 5),
            ("weekend", {"company_code": "600519", "start_date": "2025-01-11", "end_date": "2025-01-12"}, 0),
            ("recent", {"company_code": "600519", "recent_trading_days": 5}, 5),
        ]
        for name, request, count in cases:
            response = client.post("/v1/market/history", json=request)
            body = response.json()
            data = body.get("market_data") or {}
            bars = data.get("bars", [])
            checks = {
                "http_ok": response.status_code == 200,
                "source": data.get("source") == "tencent_public_history",
                "symbol": data.get("company_code") == request["company_code"],
                "count": len(bars) == count,
                "units": data.get("volume_unit") == "share" and data.get("currency") == "CNY" and data.get("adjustment") == "none",
                "dates": all(data["requested_start"] <= b["trade_date"] <= data["requested_end"] for b in bars),
                "ordered_unique": [b["trade_date"] for b in bars] == sorted({b["trade_date"] for b in bars}),
                "status": data.get("status") == ("ok" if count else "no_data"),
            }
            results.append({"name": name, "checks": checks, "response": body})
        response = client.post("/v1/chat", json={"question": "查询贵州茅台2025-01-06至2025-01-10的不复权日行情"})
        body = response.json()
        data = body.get("market_data") or {}
        results.append({"name": "real_chat", "checks": {
            "http_ok": response.status_code == 200,
            "real_planner": body.get("planner") == "deepseek",
            "right_tool": body.get("plan", {}).get("intent") == "get_market_history",
            "same_bars_as_direct": bool(data.get("bars")) and data.get("bars") == results[0]["response"].get("market_data", {}).get("bars"),
            "no_demo_or_rag": body.get("results") == [] and body.get("citations") == [] and body.get("evidence") is None,
        }, "response": body})
    return {"verified_at": datetime.now(timezone.utc).isoformat(),
            "passed": all(all(r["checks"].values()) for r in results), "results": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    if not parser.parse_args().live:
        parser.error("Pass --live to call public market and paid model APIs")
    report = run_acceptance()
    root = Path(__file__).resolve().parent.parent / "data" / "market"
    root.mkdir(parents=True, exist_ok=True)
    path = root / "market_acceptance.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "report": str(path),
                      "cases": [{"name": r["name"], "checks": r["checks"]} for r in report["results"]]}, ensure_ascii=False, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
