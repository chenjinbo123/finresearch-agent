"""Behavioral regressions for paraphrases competing with lexical boilerplate."""

import math

import app.knowledge as knowledge
from app.embeddings import DisabledEmbeddingProvider


class QueryEmbedding:
    name = "fixture"
    dimension = 2

    def embed(self, _text):
        return [1.0, 0.0]


def install_index(monkeypatch, entries):
    documents = [
        {"document_id": company, "company_code": company, "company_name": company,
         "title": "公开报告", "document_type": "annual_report", "published_at": None}
        for company in {entry[0] for entry in entries}
    ]
    chunks = [
        {"document_id": company, "chunk_id": f"{company}:{i}:0", "page_number": i,
         "content": content, "embedding_provider": "fixture", "embedding_dimension": 2,
         "embedding": [similarity, math.sqrt(1 - similarity ** 2)] if similarity else []}
        for i, (company, content, similarity) in enumerate(entries, 1)
    ]
    monkeypatch.setattr(knowledge, "_load_index", lambda: {"documents": documents, "chunks": chunks})


def test_paraphrased_evidence_survives_keyword_heavy_boilerplate(monkeypatch):
    # Previously: 0.59 semantic evidence loses to 0.54 + full lexical coverage.
    install_index(monkeypatch, [
        ("600519", "业务持续性和财务压力说明", 0.65),
        ("600519", "安全生产管理措施", 0.63),
        ("600519", "宏观经济变化、舆情及环境保护风险", 0.59),
        ("600519", "公司经营挑战隐患：审计人员履行核查程序", 0.54),
        ("600519", "公司经营挑战隐患：通用免责声明", 0.53),
        ("600519", "公司经营挑战隐患：目录提示", 0.52),
    ])
    results = knowledge.search_knowledge(
        query="公司经营挑战隐患", company_code="600519", limit=3,
        embedding_provider=QueryEmbedding(),
    )
    assert len(results) == 3
    assert any("宏观经济变化" in result.excerpt for result in results)
    assert all("通用免责声明" not in result.excerpt for result in results)


def test_keyword_only_search_keeps_exact_matches_and_company_isolation(monkeypatch):
    install_index(monkeypatch, [
        ("600519", "产品渠道由直销和经销构成", 0),
        ("600519", "产品生产安排", 0),
        ("002594", "产品渠道完整说明", 0),
    ])
    results = knowledge.search_knowledge(
        query="产品渠道", company_code="600519", limit=1,
        embedding_provider=DisabledEmbeddingProvider(),
    )
    assert len(results) == 1
    assert results[0].company_code == "600519"
    assert "直销和经销" in results[0].excerpt


def test_legacy_keyword_candidate_remains_available_with_vector_candidates(monkeypatch):
    install_index(monkeypatch, [
        ("600519", "产品通过网络平台销售", 0.8),
        ("600519", "销售渠道包括直营和经销", 0),
        ("002594", "销售渠道", 1.0),
    ])
    results = knowledge.search_knowledge(
        query="销售渠道", company_code="600519", limit=3,
        embedding_provider=QueryEmbedding(),
    )
    assert len(results) == 2
    assert any("直营和经销" in result.excerpt for result in results)
    assert all(result.company_code == "600519" for result in results)


def test_no_keyword_or_vector_match_returns_no_evidence(monkeypatch):
    install_index(monkeypatch, [("600519", "天气晴朗", 0)])
    assert knowledge.search_knowledge(
        query="经营风险", company_code="600519", embedding_provider=QueryEmbedding()
    ) == []


def test_larger_evidence_set_retains_exact_term_despite_lower_semantic_rank(monkeypatch):
    install_index(monkeypatch, [
        ("600519", "相关主题甲", 0.9),
        ("600519", "相关主题乙", 0.85),
        ("600519", "相关主题丙", 0.8),
        ("600519", "相关主题丁", 0.75),
        ("600519", "相关主题戊", 0.7),
        ("600519", "宏观经济与市场波动风险：需求下滑可能影响业务", 0.5),
    ])
    results = knowledge.search_knowledge(
        query="宏观经济与市场波动风险", company_code="600519", limit=5,
        embedding_provider=QueryEmbedding(),
    )
    assert len(results) == 5
    assert [r.excerpt for r in results[:3]] == ["相关主题甲", "相关主题乙", "相关主题丙"]
    assert any("需求下滑" in r.excerpt for r in results)
