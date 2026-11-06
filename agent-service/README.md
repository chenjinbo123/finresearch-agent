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

## Live multi-company knowledge acceptance

After uploading the local 2024 annual reports for 贵州茅台 (600519), 宁德时代
(300750), and 比亚迪 (002594), run this from `agent-service`:

```powershell
python -m app.knowledge_acceptance --live
```

This explicitly calls the configured **paid** DashScope and DeepSeek APIs. It
checks complete stored vectors, company filtering, expected evidence, exact
excerpt/page correspondence against the saved PDFs, an absent-company query,
and real chat tool routing for the two added companies. It does not upload PDFs
or rebuild existing vectors. Install the development dependencies for TestClient.
Results are written to the ignored local file
`data/knowledge/multi_company_acceptance.json`; a failed check exits with code 1.

This fixed set is a smoke test, not a general retrieval-quality benchmark.
Retrieval merges independently ranked semantic and lexical candidates. For
`limit >= 4`, it reserves a result slot for the lexical leader if that candidate
would otherwise be omitted, protecting precise terms alongside semantic results.
The returned `score` remains the fusion score, not a probability; the reserved
candidate can therefore appear before a higher-scoring candidate.
Company filtering is not user authorization. Duplicate uploads are rejected before parsing or embedding so
they do not incur another embedding request. The local JSON store still assumes
serial ingestion; concurrent writes need a transactional store in a later stage.

## Filter by report year

`POST /v1/documents` accepts an optional multipart field `report_year`, e.g.
`2024`. This is the year covered by the report, **not** `published_at`: a 2024
annual report published in April 2025 has `report_year=2024`.

`POST /v1/knowledge/search` accepts:

```json
{
  "query": "公司可能面对的风险",
  "company_code": "600519",
  "report_year": 2024,
  "limit": 5
}
```

Report years must be JSON integers between 1900 and 2099. The same field is
included in knowledge plans, stored document records, and returned citations.
Company and year filtering happen before ranking. If there are no matching
documents, search returns an empty citation list without an embedding call.
Omitting the year preserves cross-year searches. Documents without known year
metadata are excluded from a year-specific query, never assigned a year from
their publication date. The three existing 2024 annual reports were explicitly
backfilled after checking their identity; their original text and vectors remain
unchanged. Other legacy documents require verified metadata before year filtering.

For chat, ask `贵州茅台2024年年报有哪些经营风险？`. Both planners support the
new field, and explicit report years in the question are preserved even if the
model omits or confuses them while shortening the query. A question such as
`2025年发布的2024年年报` uses 2024. Multiple explicit report years are not supported
in one request; ask separately. Relative dates such as “去年” or “最新” are not
resolved by this feature: use an explicit year. Year filtering alone does not
distinguish annual, half-year, or quarterly reports within the same year.

## 第一阶段：失败返回和检索状态

错误统一返回 `code`、`message`、`request_id`、`tool_calls`。JSON 或字段错误返回
422；模型不可用返回 503、超时返回 504、模型输出不合法返回 502；未知异常返回
500 和通用说明。工具已经开始执行后失败，`tool_calls` 记录 `failed` 和错误码。
SSE 已开始时 HTTP 状态仍是 200，客户端必须处理 `error` 事件；失败后不会发送
`answer` 或 `completed`。

直接检索的 `retrieval`（聊天在 `tool_calls[].retrieval`）解释检索过程：

- `mode`：`none` 未检索，`keyword` 关键词，`hybrid` 关键词和向量。
- `outcome`：`no_documents` 没有符合公司/年份的文档，`no_matches` 没有命中片段，
  `candidates` 找到候选片段。
- `degraded` 和 `warning_code`：向量服务故障后回退关键词，明确提示可能遗漏语义证据。
- 工具状态为 `success`、`no_evidence`、`degraded` 或 `failed`。

财务答案明确标注 CSV 为演示数据。检索有候选不等于足够回答问题，聊天在检索后
另做证据核验（见下节）；融合分数不是可信度概率。
离线异常回归：`python -m pytest -q`；真实接口验收：
`python -m app.knowledge_acceptance --live`（调用外部服务，消耗额度）。

## 第一阶段：证据充分性核验与拒答

`POST /v1/chat` 和 `/v1/chat/stream` 的资料查询现在按以下顺序执行：

1. 规划检索 → 公司/年份过滤 → 召回前 5 个候选片段。
2. 补充同文档、同页的直接相邻片段，上限合计 15 个，避免命中章节标题却漏掉正文。
   保留原候选在前，补充片段在后；补充片段的 score 沿用其来源候选，不代表独立排序。
   `tool_calls[].retrieval.context_chunk_count` 表示补充数量。
3. DeepSeek 对照**用户完整原始问题**判断是否有足够直接证据。不能只覆盖一部分要求，
   不能用常识补全，不能把没有披露当成不存在。核验输入不包含检索分数。
4. 模型只返回判断和片段编号；代码校验编号属于本次候选，直接从本地原文提取引文与页码。
   不让模型编写研究结论或转抄引文。

响应新增 `evidence`（财务 CSV 查询为 null）：

| status | 含义与回答行为 |
| --- | --- |
| sufficient | 模型认为证据充分，展示代码提取的原文和出处 |
| insufficient | 无候选或候选不足以回答完整问题，明确说明资料不足 |
| unavailable | 未配置模型、网络故障、超时或输出非法，说明核验不可用，不默认通过 |

`evidence.supports` 是选中片段的 `chunk_id` 与原文 `quote`；`citations` 仍保留所有
候选用于排查，不能把这整个列表视为已通过核验的证据。检索工具的 `success` 仅表示
执行成功，是否有足够证据看 `evidence.status`。SSE 增加 `evidence_check` 进度；正常
拒答和核验不可用通过 answer/completed 返回，不是 HTTP 故障。

直接检索接口 `/v1/knowledge/search` 仍只返回候选，不做证据核验或拒答。
有候选的聊天新增一次 DeepSeek 调用，使用现有 Key/模型，会增加耗时与费用；无候选
不调用核验模型。无需重新生成文档向量。没有 Key 的离线模式可检索，但核验为 unavailable。

固定真实验收：`python -m app.evidence_acceptance --live`。包含茅台风险、比亚迪刀片电池
材料两个应通过的问题，以及火星建厂、风险加具体表决票数两个应拒答的问题。报告写入
`data/knowledge/evidence_acceptance.json`。这是一组可复现样例，不证明所有提问都不会
误判；语义充分性仍依赖模型，代码只能保证引文来自本次候选。当前上下文补充不跨页，
不完整召回仍可能导致保守拒答。

## 第二阶段第一步：统一工具注册

`GET /v1/tools` 返回当前工具目录：名称、描述、类别、参数 JSON Schema、结果 Schema、
数据类别及是否需要证据核验。目录不暴露处理函数或密钥。

- `app/tool_registry.py`：注册、参数校验、执行、结果检查、失败记录。
- `app/tools.py`：财务查询和资料检索适配器，以及唯一的内置工具注册表。
- `app/services.py`：模型输出交给同一注册表校验；额外未知参数被拒绝。
- `app/main.py`：根据注册表执行工具、显示进度、决定是否核验证据，不再按工具名分支执行。

工具类别为 read_only、pure_compute、side_effect。当前注册四个只读工具；有副作用的
工具即使注册也不允许通过当前聊天入口执行。未注册名称、非法参数、重复注册、模型构造
绕过校验、非法工具结果均有自动测试。查询结果继续区分 demo 与 public_document。

新增工具需定义 Pydantic 参数模型（intent 固定为工具名）、实现返回 ToolResult 的处理函数，
并注册 ToolDefinition；使模型能选择该工具还需更新规划提示词/本地规则和对应测试。
现阶段 ToolResult 保留财务指标、文档引用和文本答案；新数据类型需要扩展结果模型。
这一步不等于已接入真实行情或真实财务数据，也不包含 PostgreSQL、pgvector 和多步 Agent。

## 第二阶段第二步：真实 A 股历史日行情

已新增 get_market_history，接入腾讯公开历史行情。支持600519、300750、002594，返回
不复权历史日线，价格单位元/股、成交量单位股；价格以Decimal处理，JSON序列化为字符串。
这是行情数据，财务 CSV 仍是演示数据。无需新增 Key，聊天规划沿用现有 DeepSeek。

直接查询 `POST /v1/market/history`（不调用大模型）：

```json
{"company_code":"600519","start_date":"2025-01-06","end_date":"2025-01-10"}
```

或查询最近N个交易记录：

```json
{"company_code":"600519","recent_trading_days":5}
```

聊天 `/v1/chat` 或 `/v1/chat/stream`：

```json
{"question":"查询贵州茅台2025-01-06至2025-01-10的不复权日行情"}
```

亦支持“查询宁德时代最近5个交易日行情”。完整记录位于 market_data.bars；元数据包含
symbol、exchange、currency、source_url、queried_at、data_as_of。答案最多展示最后10条。
状态 ok 表示拿到记录，不保证数据源绝对完整；no_data 表示未取得区间记录，partial 表示
最近交易日模式实际记录数不足。空数据不自动归因于休市，旧数据会提示核对。

一次一个标的；区间不超过366天；最近数量1至60；仅今天之前的历史数据。暂不支持实时、
前后复权、分钟/周/月线、跨工具综合任务、权威交易日历、缓存和数据库。同步工具执行已移
到线程池，但未做生产级并发压测。公开数据接口没有稳定性承诺。

真实验收：`python -m app.market_acceptance --live`，报告保存在
data/market/market_acceptance.json。问题与面试复盘见项目根目录 [agent.md](../agent.md)。

## 第二阶段第三步：真实财报指标

新增 get_report_financials，直接访问东方财富利润表 RPT_F10_FINANCE_GINCOME；无需新增Key。
支持三家公司的营业收入（OPERATE_INCOME）与归母净利润（PARENT_NETPROFIT），不替换成
营业总收入或含少数股东损益的净利润。FY表示全年累计，H1表示1至6月累计，起始年份2000。
每次一个公司和一个已结束报告期；不支持单季度、扣非、同比环比、多公司多期比较。

直接调用 `POST /v1/financials/report`，不消耗模型额度：

```json
{"company_code":"600519","period":"2024FY","metric_codes":["revenue","net_profit"]}
```

聊天 `/v1/chat` 或 `/v1/chat/stream` 中明确说“真实”“东方财富”或“在线财报”：

```json
{"question":"查询贵州茅台2024年报的真实营业收入和归母净利润"}
```

也支持“查询比亚迪2025年上半年真实营业收入”。为保留已有教学演示，不含真实模式标记的
2025H1财务查询仍走原 get_financial_metrics，并标注演示数据。真正查询实际指标时请使用
上面的真实模式或专用接口，不要把演示结果用于分析。

真实结果位于 financial_data，演示 results 为空；保留报告起止日期、单位CNY、公告日
notice_date、源更新日source_updated_at、查询时间queried_at、源字段及URL。金额使用
Decimal，JSON输出十进制字符串。缺值为partial并列出missing_metrics，不填0、不代用
相近字段；没有报告为no_data，异常结构为502、网络故障503、超时504。

数据是查询时数据源的最新版本，可能已被后续修订，**不代表历史时点当时已知的数据**。
本轮没有实现版本快照或无前视偏差回测；原始PDF页码核对也不是该工具的功能。数据源
更新时间晚于公告日，只证明源元数据不同，不能单凭它断定金额实际发生了重述。

复现：`python -m app.report_acceptance --live`。报告写入
data/financials/report_acceptance.json；首次半年报名称映射失败报告保留在
report_acceptance.before_half_year_fix.json。此命令调用公开数据源和一次付费模型规划。
