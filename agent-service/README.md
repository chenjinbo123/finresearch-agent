# Agent Service

This is the first executable slice of FinResearch Agent. A local planner (or
optionally DeepSeek) turns a Chinese research question into one validated,
allowlisted tool plan. It can query either deterministic financial metrics from
CSV or source-linked excerpts from uploaded public PDFs.

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

At this stage, each chat request uses exactly one tool:

```text
"查询贵州茅台 2025H1 营收"
-> get_financial_metrics
-> CSV data, numerical result and source page

"贵州茅台公告中提到哪些经营风险？"
-> search_knowledge
-> uploaded PDF excerpts, document title and page number
```

The model only selects a Pydantic-validated plan. It never reads CSV/PDF files
itself, calculates financial figures, or invents citations. When no matching
PDF excerpt is found, chat returns a clear "现有资料不足以确认" response.

## Ingest and search public PDFs

The second learning slice stores a public PDF locally, extracts text per page,
splits it into page-aware chunks, and returns keyword-search results as
citations. It is intentionally **not** a complete RAG implementation yet:
there is no vector database or reranker yet, and a scanned PDF must first be
OCR'd.

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

## Vector-retrieval boundary

Keyword retrieval is still the default. The project now has an
`EmbeddingProvider` boundary: when enabled, a vector is generated at PDF
ingestion time and stored beside each page-aware chunk in the local index.
Search then combines keyword score and vector similarity; old documents
without vectors continue to use keyword retrieval.

The only included offline provider is deliberately educational:

```text
EMBEDDING_PROVIDER=none        # default: keyword retrieval only
EMBEDDING_PROVIDER=local_hash  # local vector lifecycle demonstration, no key
```

`local_hash` is deterministic but is **not a real semantic embedding model**.
It exists to exercise the same lifecycle a real provider needs:

```text
PDF chunk -> embedding vector -> store with chunk -> query vector -> similarity ranking
```

After changing the provider, re-upload a public PDF to create vectors for its
chunks. Or, for PDFs already in the local index, run
`python -m app.embeddings` to rebuild their vectors. A future real embedding
provider will implement the same interface and obtain its endpoint/model/key
from environment variables; it will not require rewriting the PDF, citation,
or chat code.

## Enable DashScope Embedding

The project includes `DashScopeEmbeddingProvider` for Alibaba Cloud Model
Studio / DashScope. Fill only this line in local `.env`:

```text
DASHSCOPE_API_KEY=your_key_here
```

When a DashScope key exists, the service automatically uses `dashscope` even
if an older `.env` has `EMBEDDING_PROVIDER=none`; you do not need to add an
`EMBEDDING_PROVIDER` line. Defaults are already in `.env.example`; optionally
override the API model name only if your Model Studio model details page says
to use a different API identifier.

Restart Uvicorn and then run:

```powershell
python -m app.embeddings
```

This sends existing local PDF chunks to the configured embedding model in
batches of 10, stores their vectors in the ignored local knowledge index, and
keeps page/original-text citations unchanged. It uses your Model Studio quota,
so run it only after adding the key; never paste that key into chat or Git.

Run tests with:

```powershell
python -m pytest
```

## Regression evaluation

`evals/tool_routing.jsonl` is a small, versioned evaluation dataset. Each line
defines one user question and its expected tool selection, key parameters, and
safe result behavior. It currently covers financial queries, document queries,
unsupported companies/periods, and the "no evidence" path.

Run it without consuming DeepSeek credits:

```powershell
python -m app.evals
```

The report includes total, passed, failed, tool counts, and failure reasons. A
failure exits with status code `1`, so the same command can later run in CI.
When you change a planner rule, prompt, tool schema, or retrieval behavior,
run this before committing and add a new JSONL case for the behavior you changed.

## What this slice demonstrates

- `POST /v1/chat` accepts a research question.
- The planner creates either a `FinancialMetricsPlan` or `KnowledgeSearchPlan`,
  both validated by Pydantic.
- The fixed `get_financial_metrics` tool reads deterministic demo data from
  `data/financial_metrics.csv`.
- The fixed `search_knowledge` tool retrieves original, page-linked PDF text.
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

The next iteration is to add a small versioned evaluation set for both tools,
then improve retrieval with embeddings and a vector database.
