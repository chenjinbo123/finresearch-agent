# 金融 AI Agent 应用工程师转型与项目实施方案

> 目标：从 Android 开发转型为以服务端为主、具备端到端交付能力的金融 AI 应用 / Agent 工程师。
>
> 项目目标：在 16 周内完成一个可以部署、演示、写入简历的“金融研究与投研工作台 Agent”。
>
> 本文基于收集到的 AI Agent、LLM 应用、AI 应用全栈、金融 AI 等职位描述整理。职位描述通常是理想候选人能力的并集，不要求转型初期全部满足；本方案优先覆盖初中级至中级 AI 应用岗位的核心要求。

## 1. 职业定位与边界

### 1.1 推荐的目标岗位

优先投递以下岗位名称，不能只搜索“智能体工程师”：

- 金融 AI 应用工程师
- 大模型应用工程师 / LLM 应用工程师
- Agent 应用开发工程师 / 智能体开发工程师
- Python AI 应用后端工程师
- Java AI 应用工程师 / Spring AI 工程师
- AI 应用全栈工程师（选择性投递，偏中小公司和创业团队）

推荐在简历中的定位：

```text
金融 AI 应用工程师（Java/Kotlin + Python）
具备 Agent、RAG、MCP、企业系统集成、评测与端到端交付能力。
```

Android 不是丢弃项，而是差异化能力。它证明了移动端产品交付、性能、网络异常处理、线上问题定位与金融业务经验；新的主技能应逐步转为“后端 AI 工程”。

### 1.2 不建议作为第一目标的岗位

- 大模型训练、预训练、模型算法研究、论文导向岗位：与当前技能栈距离远，转型周期长。
- Agent 平台架构师、多 Agent 平台负责人：通常要求多年 AI 平台和大型企业系统经验。
- 只强调 Prompt 的岗位：门槛低，难形成长期竞争力。
- 纯传统 Android 页面开发：作为保底方向保留，但不应继续作为唯一能力投资方向。

### 1.3 对 Agent 岗位的正确理解

金融 Agent 应用工程不是“调用一个大模型 API”，而是：

```text
传统后端工程
+ LLM 的理解、规划与生成能力
+ RAG 知识检索
+ MCP / 工具调用 / 企业系统集成
+ 任务工作流、状态管理与人工确认
+ 评测、安全、审计、成本和稳定性治理
```

在真实企业项目中，数据库、鉴权、缓存、异步任务、接口、日志、部署、容错、审计等大部分工作仍是后端工程。模型只应负责语言理解、有限规划、选择受控工具和组织最终表达；数据查询、权限、计算、执行和风控必须由确定性程序控制。

## 2. 收集到的 JD 高频通用要求

### 2.1 能力全景

| 能力模块 | JD 高频关键词 | 企业真正要解决的问题 | 优先级 |
| --- | --- | --- | --- |
| 后端基础 | Python、FastAPI、Java、Go、REST、WebSocket、SQL、Redis、微服务 | 构建高并发、可维护、能接业务系统的服务 | P0 |
| LLM 应用 | Prompt、Structured Output、Function / Tool Calling、Streaming、上下文、Token | 让不稳定的模型输出变得可被程序安全消费 | P0 |
| Agent Workflow | LangGraph、Planning、ReAct、状态机、Memory、Human-in-the-loop、失败恢复 | 让多步骤业务任务可控地运行、暂停、恢复和结束 | P0 |
| RAG / 知识工程 | 文档解析、切分、Embedding、向量库、混合检索、Rerank、Query Rewrite、引用 | 基于企业资料回答，降低幻觉并可追溯 | P0 |
| 企业工具集成 | MCP、Tools、Plugins、ERP、CRM、Oracle、内部 API、权限 | 安全地让 Agent 查询资料或执行受控业务操作 | P0 |
| 评测与 Harness | Evals、测试集、回归、Trace、Prompt 版本、效果优化 | 用数据验证 Agent 是否真的有用且不回归 | P0 |
| 稳定性与安全 | 权限、审计、Prompt Injection、防幻觉、异常处理、限流、重试、幂等 | 防止越权、错误执行、成本失控和生产事故 | P0 |
| 数据与缓存 | PostgreSQL、MySQL、MongoDB、Redis、pgvector / Milvus | 存储业务数据、任务状态、缓存与向量索引 | P1 |
| 全栈交付 | TypeScript、React、Next.js、流式 UI、执行状态可视化 | 让用户能使用、能理解、敢确认 Agent 的结果 | P1 |
| 运维工程 | Docker、K8s、CI/CD、监控、日志、SLA | 让系统可部署、可观测、可扩展 | P1 |
| 多 Agent / 高阶推理 | CrewAI、AutoGen、Router、Supervisor、Reflection、ToT | 解决极复杂或多角色任务，但复杂度和成本较高 | P2 |

### 2.2 从 JD 中提炼出的核心原则

1. **先用简单方案解决问题。** 大部分业务先使用“检索 + 单 Agent + 受限工具调用”即可。多 Agent 不是成熟度标志，可能增加延迟、成本和故障面。
2. **模型不能直接访问生产数据或执行高风险动作。** Agent 只能通过白名单工具访问数据；工具必须做权限、参数、次数和审计控制。
3. **关键事实必须可追溯。** 金融资料的结论需要来源、发布日期、页码或原文片段；资料不足时必须明确说明，禁止模型补猜。
4. **副作用动作必须人工确认。** 例如创建提醒、加入自选、生成外发报告等，应走“提案 -> 用户确认 -> 后端校验 -> 执行 -> 审计”的闭环。
5. **评测不是锦上添花。** 模型、Prompt、文档切分、工具定义任一变化，都可能引发效果回归，必须通过自动化测试集验证。
6. **不要保存或展示模型内部思维链（CoT）。** 调试应记录结构化任务计划、工具调用、证据、耗时、错误与最终结果；这既更稳定，也更安全。

### 2.3 当前 Android 开发经验的可迁移部分

| 当前经验 | 转型后对应能力 |
| --- | --- |
| Java / Kotlin、接口请求、序列化 | Spring Boot、FastAPI、模型与业务接口集成 |
| 并发、性能、网络失败处理 | 流式响应、限流、超时、重试、熔断和降级 |
| App 生命周期与状态管理 | Agent 会话、任务状态、Checkpoint 与恢复 |
| 金融行情、公告、股票池、风险提示 | 金融 Agent 场景设计、数据时效与可解释性 |
| 用户交互和发布经验 | 流式 UI、人工确认、移动端 Agent 入口、生产交付 |

主要需要补齐的是：服务端数据库和鉴权、Python AI 生态、RAG、Agent Workflow、MCP、评测与部署。

## 3. 需要掌握的学习内容

### 3.1 P0：必须掌握

#### A. 后端工程基础

- Python 3.11+：类型标注、虚拟环境、异步 `asyncio`、包管理、日志、测试。
- FastAPI：路由、依赖注入、Pydantic 校验、SSE/WebSocket、异常处理、OpenAPI。
- PostgreSQL：表设计、索引、事务、分页、JSONB、迁移；同时了解 `pgvector`。
- Redis：缓存、限流、会话、分布式锁的基本使用和失效策略。
- Docker Compose：本地启动多服务、环境变量、数据卷、健康检查。
- Java / Spring Boot：重点补数据库、JWT、RBAC、缓存、异步任务和企业 API 集成，不必一开始学习复杂微服务全家桶。

#### B. LLM 应用基础

- 模型 API 抽象：模型地址、密钥、模型名必须由环境变量和配置文件管理，不能散落在业务代码中。
- System Prompt、用户输入、工具结果的边界与优先级。
- 流式输出：SSE 事件定义、连接中断、取消请求和前端渲染。
- 结构化输出：用 JSON Schema / Pydantic 限制模型输出，而不是用字符串解析结果。
- Tool Calling：定义清晰的工具名称、描述、参数 Schema、返回 JSON 与错误码。
- 上下文管理：会话摘要、只注入必要证据、限制 Token、敏感信息脱敏。
- 成本控制：限制最大输入输出 Token、最大工具调用次数、缓存重复请求、记录调用成本和延迟。

#### C. RAG 与知识工程

- 文档登记：原始文件、URL、文件哈希、公司、类型、发布日期、权限和入库时间。
- PDF 解析：提取文本与页码；扫描件识别失败时标记为待 OCR，不能假定所有 PDF 均可用。
- 文本切分：按标题、段落、页码组织，不只按固定字符数硬切；保留前后文和原始定位。
- 检索：向量召回 + 关键词/全文检索的混合检索；按公司、日期、文档类型和权限过滤。
- Rerank：从召回候选中挑选更相关证据；小数据集可以先不接，但要预留接口。
- 引用：回答中的每个关键事实能映射到文档、页码、原文片段和链接。
- RAG 评测：检索是否找对资料、引用是否支持结论、无资料时是否拒答。

#### D. Agent Workflow 与 MCP

- LangGraph：状态对象、节点、条件边、循环上限、Checkpoint、任务中断与恢复、人工确认。
- 单 Agent 工作流：理解问题 -> 制定结构化计划 -> 调用受限工具 -> 校验证据 -> 组织回答。
- MCP：理解 Host、Client、Server、Tool、Resource、Prompt 的职责；实现自有 MCP Server 和 Client。
- 工具设计：工具粒度要清晰，例如“查询指标”和“检索文档”分离；模型不能获得 SQL 执行权限。
- Human-in-the-loop：高风险动作要在 Agent 和执行服务之间增加确认节点。

#### E. 评测、观测与安全

- Eval Harness：问题、预期工具、预期证据、预期行为和判定规则必须版本化。
- 观测：记录模型名、Prompt 版本、输入输出 Token、延迟、工具参数、工具结果摘要、错误、用户反馈。
- 安全：Prompt Injection、越权知识检索、工具参数注入、敏感信息泄露、错误重试风暴。
- 稳定性：超时、取消、重试、退避、幂等、限流、空结果、模型不可用、工具不可用的统一收口。

### 3.2 P1：完成核心项目后再加强

- TypeScript + React + Next.js：能独立完成对话页、知识库管理页、评测/追踪后台。
- Spring AI：了解 Java 企业服务如何接模型、向量库和工具调用。
- 异步队列：Celery / RQ / Dramatiq、或 Java 中的消息队列，用于长文档解析与向量化。
- OpenTelemetry：供应商无关的 Trace、Metrics、Logs。
- Docker、CI/CD、基础 Linux；K8s 只需理解部署概念，项目第一版不强制上。

### 3.3 P2：不要过早投入

- 多 Agent（CrewAI、AutoGen、Supervisor、Router）。
- Browser Use、Computer Use、沙箱执行、Code Interpreter。
- 模型微调、模型训练、分布式推理。
- ToT、Reflection、Re-planning 等复杂推理模式。

学习这些内容前，先完成一个可评测、可审计的单 Agent 流程。否则容易停留在“框架拼装”而没有工程能力。

## 4. 项目定义：金融研究与投研工作台 Agent

### 4.1 项目定位

项目名：**金融研究与投研工作台 Agent（FinResearch Agent Workspace）**。

它是面向投研、投顾、运营和合规人员的内部研究助手，使用公开的财报、公告、研报和结构化财务指标，提供可引用的研究问答、公司对比和提醒提案。

明确不做的事情：

- 不预测股价和涨跌，不提供投资建议。
- 不爬取或使用无授权的内部数据。
- 不允许模型直接写数据库、执行 SQL、调用任意 URL。
- 不将模型生成内容直接外发或执行高风险操作。

### 4.2 核心用户故事

#### 场景一：带证据的公司对比

用户问题：

```text
对比宁德时代和比亚迪最近两期的营业收入、归母净利润变化，
结合最近半年公告说明主要风险。每条结论给出来源和日期。
```

系统行为：

```text
1. 识别公司、期间、指标、风险资料范围。
2. 调用财务指标工具获取确定性数据。
3. 调用公告检索工具找相关原文证据。
4. 校验每条重要结论都可被证据支持。
5. 返回比较表、风险摘要、数据截止日、引用卡片和不确定项。
```

#### 场景二：资料不足时安全结束

用户问题：

```text
根据最近的机构调研判断某公司明年毛利率一定会上升吗？
```

系统行为：

```text
1. 检索已有调研材料。
2. 仅归纳已披露信息，不作确定性预测。
3. 若证据不足，明确回复“现有资料不足以确认”，并展示已检索范围。
```

#### 场景三：有副作用操作的二次确认

用户问题：

```text
在某公司下次财报披露前三天提醒我复核风险项。
```

系统行为：

```text
Agent 创建提醒提案
-> 前端展示公司、日期、提醒内容和风险项
-> 用户点击确认
-> Java 业务服务再次校验登录用户、权限和参数
-> 创建提醒并写入审计记录
```

### 4.3 MVP 范围

第一版只使用 5 家公司、50 份公开文档、50 个评测问题。数据规模小不是问题，重点是数据链路完整、结论可靠、能力可展示。

MVP 功能：

- 用户登录、角色和基础数据权限。
- 文档登记、解析、分块、向量化与检索。
- 财务指标查询与两家公司对比。
- 流式研究问答，回答附引用、日期和资料不足说明。
- 单 Agent LangGraph 工作流与工具调用记录。
- 两个查询 MCP Server、一个受控提醒 MCP Server。
- 提醒提案、用户确认、审计日志。
- 自动化评测、模型调用 Trace、Token 与延迟统计。
- React/Next.js Web 工作台；Android 仅作为最后的可选入口。

## 5. 推荐架构

### 5.1 总体架构

```text
┌───────────────────────────────────────────────────────────────────┐
│ React / Next.js 工作台                                             │
│ 对话、流式输出、引用卡片、执行进度、知识库、评测、确认弹窗          │
└───────────────────────────────┬───────────────────────────────────┘
                                │ HTTPS / SSE
┌───────────────────────────────▼───────────────────────────────────┐
│ Spring Boot 业务网关                                               │
│ JWT、RBAC、用户、会话、提醒、审计、Redis 限流、业务 API             │
└───────────────────────────────┬───────────────────────────────────┘
                                │ 内部 API / 事件
┌───────────────────────────────▼───────────────────────────────────┐
│ Python FastAPI Agent 服务                                          │
│ LangGraph、LLM、结构化输出、RAG、MCP Client、Eval Harness、SSE     │
└───────┬───────────────────┬────────────────────┬──────────────────┘
        │                   │                    │
┌───────▼────────┐ ┌────────▼─────────┐ ┌────────▼─────────────────┐
│ 知识检索 MCP    │ │ 财务数据 MCP      │ │ 提醒提案 MCP             │
│ 文档/引用查询   │ │ 指标/比较查询     │ │ 仅生成提案，不直接执行    │
└───────┬────────┘ └────────┬─────────┘ └──────────────────────────┘
        │                   │
┌───────▼───────────────────▼──────────────────────────────────────┐
│ PostgreSQL + pgvector | Redis | 文档文件存储 | Langfuse/OTel        │
└───────────────────────────────────────────────────────────────────┘
```

### 5.2 组件职责与技术选型

| 组件 | 推荐技术 | 职责 | 为什么这样拆分 |
| --- | --- | --- | --- |
| Web 工作台 | TypeScript、React、Next.js | 用户界面、SSE、引用和执行状态展示 | 满足全栈 JD，但不把项目重心放在页面 |
| 业务网关 | Java 17+、Spring Boot、Spring Security | 鉴权、RBAC、提醒、审计、对接企业业务 | 复用 Java/Kotlin 背景，体现企业集成能力 |
| Agent 服务 | Python 3.11+、FastAPI、Pydantic、LangGraph | LLM 编排、RAG、工具调用、评测 | Python AI 生态成熟，适合快速实现 |
| 向量检索 | PostgreSQL + pgvector | 文档元数据、业务数据与向量查询 | MVP 只维护一种主要数据库，部署简单 |
| 缓存 | Redis | 限流、会话/检索缓存、短期任务状态 | 贴合企业后端高频要求 |
| 可观测 | Langfuse 或 OpenTelemetry | Trace、Prompt 版本、Token、耗时、错误 | 体现 Harness 与工程化能力 |
| 部署 | Docker Compose | 本地和演示环境一键启动 | 第一版比 K8s 更务实 |

### 5.3 服务边界

#### Spring Boot 服务负责

- 账号、登录、JWT、角色与文档访问权限。
- 会话元数据、提醒、确认记录、业务审计。
- 限流、幂等键、重要业务动作的最终执行。
- 向 Agent 服务下发已验证的用户身份和允许访问的知识范围。

#### FastAPI Agent 服务负责

- 输入分类、结构化任务计划、工作流状态。
- LLM 调用、工具选择、RAG 检索、证据校验和流式事件。
- MCP Client、工具调用上限、模型错误收口。
- 评测运行与 Agent Trace 关联。

#### MCP Server 负责

- 向 Agent 暴露受限且可审计的业务能力。
- 对工具参数、权限范围和返回结构做确定性校验。
- 不把数据库账号、SQL 或内部网络能力直接交给模型。

## 6. 数据设计

### 6.1 文档与 RAG 元数据

每一个文档和分块都必须可追溯：

```text
documents
- id
- company_code
- company_name
- title
- document_type          # annual_report / quarterly_report / announcement / research_note
- published_at
- source_url
- source_file_hash
- storage_path
- permission_scope
- parse_status
- created_at

document_chunks
- id
- document_id
- page_number
- section_title
- chunk_index
- content
- token_count
- embedding
- metadata_json
```

检索返回的证据对象建议统一为：

```json
{
  "document_id": "doc_2025_001",
  "title": "2025 年半年度报告",
  "document_type": "quarterly_report",
  "published_at": "2025-08-20",
  "source_url": "https://example.com/report.pdf",
  "page_number": 31,
  "excerpt": "归属于上市公司股东的净利润为……",
  "score": 0.92
}
```

### 6.2 结构化财务数据

模型不得自行计算核心财务指标。指标应由程序从 CSV 或手工整理的数据表读取：

```text
financial_metrics
- id
- company_code
- report_period
- metric_code            # revenue / net_profit / gross_margin
- metric_value
- unit
- source_document_id
- source_page_number
- published_at
```

### 6.3 会话、任务、审计与提醒

```text
conversations
- id, user_id, title, created_at

agent_runs
- id, conversation_id, status, graph_state, model_name
- prompt_version, input_tokens, output_tokens, latency_ms, error_code

tool_calls
- id, agent_run_id, tool_name, arguments_json, result_summary
- status, latency_ms, created_at

action_proposals
- id, user_id, action_type, payload_json, status, expires_at

audit_logs
- id, user_id, event_type, resource_type, resource_id
- request_id, result, created_at
```

审计日志记录的是必要的业务事实和工具调用摘要，不应保存模型内部思维链或无必要的敏感内容。

## 7. Agent Workflow 详细设计

### 7.1 LangGraph 状态对象

```text
AgentState
- user_id
- conversation_id
- user_query
- allowed_company_codes
- intent                     # research / compare / reminder / unsupported
- plan                       # 结构化计划，不保存 CoT
- tool_call_count
- collected_evidence
- financial_results
- action_proposal
- final_answer
- citations
- errors
- status
```

### 7.2 状态机流程

```text
START
  -> 输入校验与权限上下文注入
  -> 意图识别
  -> 是否在支持范围？
       否 -> 安全结束并说明能力边界
       是 -> 生成 JSON 格式任务计划
  -> 根据计划调用查询工具
  -> 工具是否成功且有结果？
       否 -> 资料不足 / 工具失败收口
       是 -> 证据校验
  -> 是否要求有副作用操作？
       是 -> 创建操作提案 -> INTERRUPT 等待用户确认
       否 -> 生成带引用答案
  -> 输出校验（引用、日期、免责声明）
  -> END
```

### 7.3 任务计划结构化输出

计划必须是可校验 JSON，不允许模型返回自由格式的“思考过程”：

```json
{
  "intent": "compare_company",
  "companies": ["300750", "002594"],
  "periods": ["2025H1", "2024H1"],
  "metrics": ["revenue", "net_profit"],
  "document_query": {
    "keywords": ["风险", "产能", "减持"],
    "date_from": "2025-01-01",
    "document_types": ["announcement", "quarterly_report"]
  },
  "requires_confirmation": false
}
```

Pydantic 校验失败时，最多重试一次要求模型修正；仍失败则返回可理解的错误，不能无限重试。

### 7.4 工具调用控制

建议配置：

```text
MAX_TOOL_CALLS_PER_RUN = 4
MAX_MODEL_RETRIES = 1
MAX_TOOL_TIMEOUT_SECONDS = 10
MAX_TOTAL_RUN_SECONDS = 45
```

工具调用错误必须分为：参数非法、无权限、无数据、依赖超时、内部异常。对用户展示简洁说明；对日志记录完整错误码和 Trace ID。

## 8. MCP 设计

### 8.1 MCP Server 一：research-knowledge-mcp

作用：查询已经授权的公告、财报和研报文本，不直接把向量库查询权交给模型。

```text
工具：search_documents
参数：company_codes, keywords, date_range, document_types, top_k
返回：标准证据数组（标题、日期、页码、片段、链接）
控制：按用户权限过滤；top_k 不超过 8；不返回无权文档
```

### 8.2 MCP Server 二：financial-data-mcp

作用：查询和对比确定性财务数据，计算逻辑在程序中而不是模型中。

```text
工具：get_financial_metrics
参数：company_code, period, metric_codes
返回：指标、单位、来源文档和页码

工具：compare_companies
参数：company_codes, periods, metric_codes
返回：比较表、同比/环比计算结果、来源
```

### 8.3 MCP Server 三：watchlist-reminder-mcp

作用：只创建提醒提案，禁止 Agent 直接执行提醒创建。

```text
工具：propose_reminder
参数：company_code, trigger_date, content
返回：proposal_id, preview, expires_at

真实执行：由前端确认后调用 Spring Boot 的 confirm 接口完成。
```

### 8.4 工具安全规则

- Tool 参数由 JSON Schema 校验，不允许拼接 SQL、文件路径或 URL。
- 所有工具都带上经过网关认证的 `user_id` 和 `permission_scope`，但不让模型自行填写它们。
- 高风险工具必须只返回提案 ID，最终动作由独立业务接口执行。
- 每次调用记录 Agent Run、工具名、参数摘要、耗时、状态和错误码。
- 工具返回空数据应被视为正常业务结果，由 Workflow 收口为“资料不足”，不能假装成功。

## 9. RAG 实现方案

### 9.1 文档入库管道

```text
上传 / 登记公开 URL
-> 文件校验、哈希去重、记录来源
-> PDF 文本和页码提取
-> 按标题/段落/页码切分
-> 生成 Embedding
-> 写入 PostgreSQL + pgvector
-> 标记入库成功或待 OCR / 失败原因
```

长文档解析和向量化应放入异步任务，避免阻塞聊天接口。MVP 可以使用 FastAPI BackgroundTasks；后续再升级为任务队列。

### 9.2 检索策略

```text
用户问题
-> 权限 / 公司 / 日期 / 文档类型过滤
-> 向量召回 Top 20
-> 关键词或全文检索 Top 20
-> 合并、去重
-> Rerank Top 8
-> 返回证据对象
```

第一版如果没有 Rerank 模型，可以先实现“混合检索 + 元数据过滤 + Top K 控制”，但接口必须预留重排步骤，便于迭代。

### 9.3 回答生成约束

系统 Prompt 应包含这些原则：

```text
1. 只能依据提供的财务工具结果和证据回答事实性结论。
2. 每个关键事实标记对应引用编号。
3. 证据不充分时写“现有资料不足以确认”，不能猜测。
4. 不生成买卖建议或确定性价格预测。
5. 显示资料发布日期和数据截止日。
```

最终答案应区分：结论、数据表、风险提示、引用、局限性。这样既适合金融场景，也方便前端渲染和评测。

## 10. 前端与 Android 的实现边界

### 10.1 Web 工作台必须实现

- 登录页和基础角色信息。
- 研究对话页：流式文本、停止生成、重试、会话历史。
- Agent 执行状态：正在检索、正在查询指标、资料不足、等待确认、已完成。
- 引用卡片：标题、日期、页码、原文片段、来源链接。
- 提醒提案确认弹窗。
- 知识库文档状态页。
- 评测结果和单次 Trace 查看页（至少管理员可见）。

### 10.2 Android 的可选加分实现

不要在核心项目未完成前开发 Android 客户端。最后可用 Kotlin 做极简客户端展示：

- SSE 流式问答；
- 引用与原文跳转；
- 会话历史与提醒确认；
- 拍照或文件上传入口（可选）。

这部分作为“移动端 AI 交付能力”加分，不应挤占后端 AI 工程的学习时间。

## 11. 评测 Harness 与观测方案

### 11.1 评测集目录建议

```text
tests/evals/
├── retrieval_cases.jsonl       # 问题应命中的证据
├── tool_cases.jsonl            # 应调用的工具和关键参数
├── citation_cases.jsonl        # 关键结论是否有支持证据
├── safety_cases.jsonl          # 注入、越权、空结果、超时
├── action_cases.jsonl          # 提案与确认流程
└── regression_cases.jsonl      # 模型 / Prompt / RAG 变化后的回归
```

### 11.2 单条评测样例

```json
{
  "id": "compare_metrics_001",
  "input": "对比 A 公司和 B 公司 2025H1 营收和归母净利润",
  "expected_tools": ["compare_companies"],
  "expected_companies": ["A", "B"],
  "expected_metrics": ["revenue", "net_profit"],
  "must_have_citations": true,
  "expected_behavior": "answer_with_evidence"
}
```

### 11.3 核心指标

| 指标 | 定义 | 第一版目标 |
| --- | --- | ---: |
| 检索命中率 | 预期证据是否出现在 Top K 中 | >= 80% |
| 工具调用正确率 | 工具和关键参数是否正确 | >= 85% |
| 引用覆盖率 | 关键事实是否带有引用 | >= 90% |
| 引用支持率 | 引用是否真正支撑结论 | >= 85% |
| 安全拦截率 | 注入、越权、危险动作是否被拦截 | 100% |
| 平均延迟 | 端到端回答耗时 | 记录并持续优化 |
| 平均成本 | 单请求 Token 和人民币/美元估算成本 | 记录并设置上限 |

### 11.4 Trace 记录字段

每次运行至少记录：

```text
request_id、user_id、conversation_id、agent_run_id、模型名、Prompt 版本、
开始结束时间、输入输出 Token、工具调用列表、检索结果数量、引用数量、
异常码、最终状态、用户反馈。
```

推荐第 15 周接入 Langfuse；若不使用第三方平台，也要先将上述关键字段写入数据库和结构化日志。

## 12. 安全、稳定性与合规设计

### 12.1 必须防住的风险

| 风险 | 设计措施 |
| --- | --- |
| Prompt Injection | 系统指令隔离；文档内容只当数据，不当指令；工具白名单；安全评测用例 |
| 越权资料访问 | 网关下发权限范围；检索层强制过滤；引用再次校验权限 |
| 模型幻觉 | 结构化指标由工具返回；关键结论强制引用；无证据即说明资料不足 |
| 错误业务操作 | 提案与确认分离；RBAC；幂等键；审计；过期提案不可执行 |
| 超时或工具失败 | 调用超时；有限重试；错误分类；保留旧数据或明确失败，不解析空结果 |
| Token 成本失控 | 上下文裁剪；Top K 限制；缓存；最大 Token / 工具次数 / 运行时长限制 |
| 敏感信息泄露 | 密钥只走环境变量；日志脱敏；最小化保存；不提交 `.env` |

### 12.2 金融场景输出边界

- 显示数据截止日和资料来源。
- 对不确定信息使用“资料显示”“公开披露提及”“现有资料不足”等措辞。
- 不输出确定性投资建议、收益承诺和价格预测。
- 重要结论与引用绑定，方便人工复核。
- 业务执行动作必须保留审计记录。

## 13. 16 周详细实施计划

### 第 1-2 周：FastAPI 与 LLM 基础

交付：FastAPI 服务，提供 `POST /v1/chat/stream`，能调用模型并 SSE 流式返回。

学习：Python 类型、Pydantic、异常处理、环境变量、HTTP、SSE、模型 API、结构化 JSON。

验收：输入一个问题，服务返回符合 Pydantic Schema 的“意图 + 计划”JSON；错误输出和空结果可控收口。

### 第 3-4 周：文档入库与基础 RAG

交付：登记 20 份公开 PDF，解析页码、切分、入库并检索；返回引用证据。

学习：PDF 解析、Embedding、pgvector、元数据过滤、混合检索、异步任务。

验收：至少 20 个资料问题能返回正确文档、页码和原文片段。

### 第 5-6 周：结构化财务工具

交付：财务数据表、`get_financial_metrics` 和 `compare_companies` 工具。

学习：PostgreSQL 表设计、事务、查询、指标计算、JSON Schema、工具错误码。

验收：模型能正确选择指标工具；计算结果与源数据一致，并给出来源文档与页码。

### 第 7-8 周：LangGraph 单 Agent Workflow

交付：支持“研究问答、公司对比、资料不足”的状态机。

学习：StateGraph、条件边、Checkpoint、最大循环次数、结构化任务计划、工具调用限制。

验收：复杂问题能调用检索和指标工具；工具失败、空结果和不支持问题均安全结束。

### 第 9-10 周：MCP 与操作确认

交付：三个自建 MCP Server；提醒提案、确认、审计闭环。

学习：MCP SDK、Server/Client、Tool Schema、鉴权上下文、幂等、RBAC。

验收：Agent 无法绕过确认直接创建提醒；越权与参数非法请求被拒绝并有审计。

### 第 11-12 周：Spring Boot 业务层

交付：用户、JWT、角色、会话、提醒、审计、Redis 限流等服务。

学习：Spring Security、JPA/MyBatis、Redis、接口契约、API 网关思路。

验收：不同角色获得不同文档检索范围；高频请求被限流；确认动作具备幂等性。

### 第 13 周：React / Next.js 工作台

交付：研究对话、SSE、引用卡片、执行状态、确认弹窗和基础管理页。

学习：TypeScript、React 状态、SSE、组件拆分、接口错误处理。

验收：用户能完成“提问 -> 看 Agent 状态 -> 看引用 -> 确认提醒”的全流程。

### 第 14 周：Eval Harness

交付：至少 50 条版本化评测数据与自动报告。

学习：pytest、fixture、JSONL、指标计算、回归测试。

验收：输出检索命中率、工具调用正确率、引用覆盖率、安全拦截率、平均延迟和成本。

### 第 15 周：观测与成本治理

交付：Langfuse 或 OpenTelemetry Trace；Prompt 版本、Token、延迟、错误、工具调用可查询。

学习：Trace、Span、日志脱敏、指标、缓存、成本估算。

验收：能定位一次失败请求是模型、检索、工具还是权限导致，并能看到成本数据。

### 第 16 周：部署与作品集

交付：Docker Compose、一键启动说明、架构图、演示数据、README、3 分钟演示视频、项目复盘。

验收：在新环境根据文档可启动；完成“上传/登记资料 -> 提问 -> 引用 -> 提醒提案 -> 确认 -> 审计”的演示。

## 14. 推荐项目目录

```text
finresearch-agent/
├── apps/
│   ├── web/                         # Next.js 工作台
│   ├── business-service/            # Spring Boot 业务网关
│   └── agent-service/               # FastAPI + LangGraph
├── mcp-servers/
│   ├── research-knowledge-mcp/
│   ├── financial-data-mcp/
│   └── reminder-mcp/
├── packages/
│   ├── contracts/                   # OpenAPI / JSON Schema / DTO 定义
│   └── prompts/                     # Prompt 版本文件
├── data/
│   ├── source-manifest/             # 文档来源清单，不提交受限原文
│   └── seed/                        # 可公开演示的指标数据
├── tests/
│   ├── unit/
│   ├── integration/
│   └── evals/
├── infra/
│   ├── docker-compose.yml
│   └── db/migrations/
└── docs/
    ├── architecture.md
    ├── api-contract.md
    ├── threat-model.md
    └── demo-script.md
```

每次开发只完成一个纵向切片，不要先把所有目录和空接口搭好。例如第一切片应是：一条用户问题 -> 一个工具 -> 一段结果 -> 一条 Trace；再逐渐增加文档、工作流、权限和前端。

## 15. API 初稿

```text
POST /v1/auth/login
POST /v1/documents
POST /v1/ingestions
GET  /v1/documents/{id}
POST /v1/chat/stream
GET  /v1/conversations/{id}
POST /v1/actions/proposals
POST /v1/actions/{id}/confirm
GET  /v1/agent-runs/{id}
POST /v1/evals/run
GET  /v1/evals/runs/{id}
```

`POST /v1/chat/stream` 的 SSE 事件建议：

```text
event: status       # 正在分析 / 正在检索 / 正在查询指标 / 等待确认
event: token        # 流式文本片段
event: citation     # 新增引用对象
event: proposal     # 操作提案
event: completed    # 最终答案与统计
event: error        # 用户可理解的错误码和请求 ID
```

## 16. 开源项目学习清单

不要直接复制一个完整 AI 平台。每个项目只为解决当前阶段的一个具体问题而学习，理解设计后自己实现最小版本。

| 阶段 | 开源项目 | 学习目的 | 重点看什么 | 不要做什么 |
| --- | --- | --- | --- | --- |
| Workflow | [LangGraph](https://github.com/langchain-ai/langgraph) | 有状态 Agent、条件分支、中断恢复、人工介入 | State、Node、Edge、Checkpoint、Human-in-the-loop 示例 | 不一开始做多 Agent |
| MCP | [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) | MCP Server/Client、Tool 和 Resource 定义 | 最小 Server、工具参数 Schema、传输方式 | 不把数据库执行权暴露给工具 |
| Agent SDK | [OpenAI Agents SDK](https://github.com/openai/openai-agents-python) | Tool、Guardrail、Tracing 的 API 设计 | 工具调用与追踪思路 | 不同时用多套 Agent 主框架 |
| 观测 | [Langfuse](https://github.com/langfuse/langfuse) | Prompt 版本、Trace、Token、用户反馈 | Trace、Span、成本、Dataset/Eval | 不把它当作业务数据库 |
| RAG | [RAGFlow](https://github.com/infiniflow/ragflow) | 企业文档解析、分块、检索与引用体验 | Ingestion、检索 Pipeline、引用 UI | 不作为项目核心依赖直接套壳 |
| RAG 组件 | [LlamaIndex](https://github.com/run-llama/llama_index) | Loader、Index、Retriever、Rerank | 文档索引和检索抽象 | 不因框架而失去对 SQL 的理解 |
| 研究 Agent | [Open Deep Research](https://github.com/langchain-ai/open_deep_research) | 研究型任务分解与结果组织 | 任务规划、资料收集、最终报告结构 | 不照搬复杂流程 |
| 对话 UI | [Chatbot UI](https://github.com/mckaywrigley/chatbot-ui) | 流式对话、会话管理、前端体验 | 流式渲染、消息列表、停止生成 | 不把聊天界面当项目核心 |
| 平台产品 | [Dify](https://github.com/langgenius/dify) | 工作流、知识库、工具平台的产品思路 | 权限、工作流和知识库产品设计 | 不直接部署替代自己的实现 |

建议学习顺序：

```text
FastAPI / Pydantic / PostgreSQL
-> 直接调用模型 API + 结构化输出 + Tool Calling
-> 基础 RAG
-> LangGraph
-> MCP
-> Eval Harness + Langfuse
-> Spring Boot / Next.js 整合
```

## 17. 项目最终验收与简历表达

### 17.1 最终验收清单

- [ ] 至少支持 5 家公司、50 份公开文档、50 条评测问题。
- [ ] 关键事实带来源、日期、页码或原文片段。
- [ ] 没有证据时明确说明资料不足，不编造。
- [ ] 指标由确定性工具查询或计算，模型不自行计算。
- [ ] 工具调用、用户确认和业务操作都有审计记录。
- [ ] 支持权限过滤，用户无权文档不会被检索或引用。
- [ ] 提醒等副作用操作必须二次确认，并具备幂等处理。
- [ ] 评测报告包含检索、工具、引用、安全、延迟和成本指标。
- [ ] Prompt、模型和工具变更后可运行回归评测。
- [ ] Docker Compose 可启动演示环境；密钥全部由环境变量注入。

### 17.2 简历项目描述参考

```text
金融研究与投研工作台 Agent | Java/Spring Boot、Python/FastAPI、LangGraph、MCP、PostgreSQL/pgvector、Redis、React/Next.js

- 独立设计并实现面向财报、公告与结构化财务指标的金融研究 Agent，提供带页码、发布日期和原文片段的可追溯回答。
- 基于 LangGraph 构建状态化单 Agent Workflow，完成任务计划、受限工具调用、证据校验、资料不足收口及人工确认中断恢复。
- 实现公告检索、财务指标比较、提醒提案 3 个 MCP Server；通过 RBAC、参数 Schema、幂等确认和审计日志保障业务动作安全。
- 建设 Eval Harness 与 Trace 体系，量化检索命中、工具调用、引用覆盖、安全拦截、Token 成本和响应延迟，并支持 Prompt/模型回归验证。
- 使用 Docker Compose 完成多服务部署，Web 工作台支持流式输出、引用查看、执行状态可视化和提醒确认。
```

### 17.3 面试中应能讲清楚的问题

- 为什么模型不能直接访问数据库？MCP 工具如何限制权限？
- RAG 检索错误、空结果、资料过期时系统如何处理？
- 如何证明回答不是幻觉？引用如何和结论绑定？
- 为什么选择单 Agent，而不是多 Agent？
- 工具调用有副作用时如何二次确认、幂等和审计？
- 如何评测 Prompt、模型或文档分块的改动是否造成回归？
- 如何控制 Token、延迟和高并发下的成本？
- 为什么 Java 服务和 Python Agent 服务需要拆分？

## 18. 第一个可执行任务

不要先建全栈项目、不要先搭多 Agent、不要先做页面。第一个任务只做一个纵向切片：

```text
Python FastAPI
-> 接收一个研究问题
-> 调用一个固定的 get_financial_metrics 工具
-> 使用 Pydantic 校验模型返回的工具选择和参数
-> 返回结构化 JSON 与错误码
-> 写一条最小的工具调用日志
```

跑通后，再扩展为“财务指标工具 + 文档检索工具 + 带引用回答”。每周都应留下可运行的功能、测试数据和复盘记录；这比连续几周只看教程更能形成可迁移能力。
