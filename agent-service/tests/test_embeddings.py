import pytest
import httpx

import app.embeddings as embeddings
from app.config import Settings
from app.embeddings import (
    DashScopeEmbeddingProvider,
    LocalHashEmbeddingProvider,
    cosine_similarity,
    create_embedding_provider,
)


def test_local_hash_embedding_is_deterministic_and_normalized() -> None:
    provider = LocalHashEmbeddingProvider(dimension=16)

    first = provider.embed("经营风险提示")
    second = provider.embed("经营风险提示")

    assert first == second
    assert len(first) == 16
    assert cosine_similarity(first, second) == 1.0


def test_cosine_similarity_rejects_different_dimensions() -> None:
    assert cosine_similarity([1.0, 0.0], [1.0]) == 0.0


def dashscope_settings(api_key: str | None = "test-key") -> Settings:
    return Settings(
        deepseek_api_key=None,
        deepseek_base_url="https://api.deepseek.com",
        deepseek_model="deepseek-chat",
        deepseek_timeout_seconds=30,
        embedding_provider="dashscope",
        embedding_dimension=128,
        dashscope_api_key=api_key,
        dashscope_embedding_base_url="https://example.test/embeddings",
        dashscope_embedding_model="text-embedding-v3",
        dashscope_embedding_dimension=3,
        dashscope_embedding_timeout_seconds=30,
    )


def test_dashscope_provider_sends_batched_request_without_exposing_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "output": {
                    "embeddings": [
                        {"text_index": 1, "embedding": [0, 3, 4]},
                        {"text_index": 0, "embedding": [3, 4, 0]},
                    ]
                }
            }

    def fake_post(url: str, **kwargs) -> FakeResponse:
        captured["url"] = url
        captured.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr(embeddings.httpx, "post", fake_post)
    provider = DashScopeEmbeddingProvider(dashscope_settings())

    vectors = provider.embed_many(["第一段", "第二段"])

    assert captured["url"] == "https://example.test/embeddings"
    assert captured["headers"] == {
        "Authorization": "Bearer test-key",
        "Content-Type": "application/json",
    }
    assert captured["json"] == {
        "model": "text-embedding-v3",
        "input": {"texts": ["第一段", "第二段"]},
        "parameters": {"dimension": 3},
    }
    assert vectors == [[0.6, 0.8, 0.0], [0.0, 0.6, 0.8]]


def test_dashscope_provider_requires_key() -> None:
    with pytest.raises(ValueError, match="EMBEDDING_NOT_CONFIGURED"):
        DashScopeEmbeddingProvider(dashscope_settings(api_key=None))


def test_factory_creates_dashscope_provider() -> None:
    assert isinstance(create_embedding_provider(dashscope_settings()), DashScopeEmbeddingProvider)


def test_dashscope_arrearage_error_is_reported_without_response_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = httpx.Request("POST", "https://example.test/embeddings")
    response = httpx.Response(400, request=request, json={"code": "Arrearage"})

    def fake_post(_url: str, **_kwargs) -> httpx.Response:
        return response

    monkeypatch.setattr(embeddings.httpx, "post", fake_post)
    provider = DashScopeEmbeddingProvider(dashscope_settings())

    with pytest.raises(ValueError, match="EMBEDDING_ACCOUNT_UNAVAILABLE"):
        provider.embed("经营风险")
