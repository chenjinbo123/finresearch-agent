# Agent Service

This is the first executable slice of FinResearch Agent. A local planner (or
optionally DeepSeek) turns a limited set of Chinese research questions into a
validated tool plan. The restricted financial-data tool reads a validated CSV
dataset and returns source-linked results.

## Run locally

From this directory in the VS Code terminal:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -e ".[dev]"
python -m uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/docs` and call `POST /v1/chat` with:

```json
{
  "question": "对比宁德时代和比亚迪 2025H1 营收和归母净利润"
}
```

`POST /v1/chat/stream` provides the same research flow as Server-Sent Events
(SSE). It emits `status`, `answer`, and `completed` events so a future Web or
Android client can show the Agent's progress while it works.

## Ingest and search public PDFs

The second learning slice stores a public PDF locally, extracts text per page,
splits it into page-aware chunks, and returns keyword-search results as
citations. It is intentionally **not** a complete RAG implementation yet:
there is no embedding model or vector database, and a scanned PDF must first
be OCR'd.

Start the service, then upload a public PDF through `POST /v1/documents` in
Swagger (`/docs`). Fill in optional company metadata and the publication date.
The service stores the original PDF and local index under `data/knowledge/`,
which is ignored by Git.

Search its original text with `POST /v1/knowledge/search`:

```json
{
  "query": "公司经营风险提示",
  "company_code": "600519",
  "limit": 5
}
```

Each result includes the original excerpt, document title, page number, and
publication date. Upload only public, authorized material.

Run tests with:

```powershell
python -m pytest
```

## What this slice demonstrates

- `POST /v1/chat` accepts a research question.
- The planner creates a `FinancialMetricsPlan` validated by Pydantic.
- The fixed `get_financial_metrics` tool reads deterministic demo data from
  `data/financial_metrics.csv`.
- A deterministic formatter produces a readable answer and source list from tool results.
- Every tool call emits a structured log and is included in the response.
- Unsupported companies and metrics return explicit error codes.

## Financial-metrics dataset

`data/financial_metrics.csv` is an intentionally small, demo-only version of
the future `financial_metrics` database table. Each row records one company,
one reporting period, one metric, and its source location. The service loads it
once per process and rejects missing columns, invalid values, duplicate keys,
or missing query results with explicit business error codes.

The CSV data is not live or investment-grade. A production deployment should
replace this loader with a verified, licensed data source or PostgreSQL query
while preserving the same tool boundary.

## Enable DeepSeek later

The service is deliberately runnable without an API key. When no key is set,
the response contains `"planner": "local_rule"` and the deterministic
learning planner is used.

After creating a DeepSeek API key, copy `.env.example` to `.env` and set only
this value:

```text
DEEPSEEK_API_KEY=your_key_here
```

Restart Uvicorn. `/health` and each chat response will then contain
`"planner": "deepseek"`. The model is used only to generate a JSON tool plan;
Pydantic validates that plan before the financial-data tool is called. Never
commit `.env` or paste its API key into chat, source code, or screenshots.

The next iteration is to let the Agent choose between the financial-metrics
tool and this source-linked document retrieval tool.
