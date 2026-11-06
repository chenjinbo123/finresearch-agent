"""Replaceable embedding boundary for the document-retrieval pipeline.

`LocalHashEmbeddingProvider` is deliberately offline and deterministic. It
teaches the vector lifecycle without pretending to be an actual semantic model.
A real provider can later implement the same protocol and use an environment
configured API key, while PostgreSQL + pgvector can store the vectors.
"""

import hashlib
import json
import math
import re
import sys
from typing import Protocol

import httpx

from app.config import Settings, get_settings


class EmbeddingProvider(Protocol):
    name: str
    dimension: int

    def embed(self, text: str) -> list[float]: ...

    def embed_many(self, texts: list[str]) -> list[list[float]]: ...


class DisabledEmbeddingProvider:
    """Explicitly disables vector generation and keeps keyword search active."""

    name = "none"
    dimension = 0

    def embed(self, text: str) -> list[float]:
        raise RuntimeError("EMBEDDING_DISABLED: 当前未启用向量检索。")

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("EMBEDDING_DISABLED: 当前未启用向量检索。")


class LocalHashEmbeddingProvider:
    """A no-key, deterministic vectorizer used only to exercise retrieval plumbing."""

    name = "local_hash"

    def __init__(self, dimension: int = 128) -> None:
        if dimension < 8:
            raise ValueError("EMBEDDING_CONFIG_INVALID: 向量维度至少为 8。")
        self.dimension = dimension

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        for token in _vector_tokens(text):
            index = int.from_bytes(
                hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest(), "big"
            ) % self.dimension
            vector[index] += 1.0
        return _l2_normalize(vector)

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]


class DashScopeEmbeddingProvider:
    """DashScope text-embedding client, configured only through Settings/.env."""

    name = "dashscope"

    def __init__(self, settings: Settings) -> None:
        if not settings.dashscope_api_key:
            raise ValueError(
                "EMBEDDING_NOT_CONFIGURED: 未配置 DASHSCOPE_API_KEY，无法使用百炼向量模型。"
            )
        self._api_key = settings.dashscope_api_key
        self._base_url = settings.dashscope_embedding_base_url
        self._model = settings.dashscope_embedding_model
        self._timeout_seconds = settings.dashscope_embedding_timeout_seconds
        self._requested_dimension = settings.dashscope_embedding_dimension
        if self._requested_dimension < 1:
            raise ValueError("EMBEDDING_CONFIG_INVALID: DASHSCOPE_EMBEDDING_DIMENSION 必须为正整数。")
        self.dimension = self._requested_dimension

    def embed(self, text: str) -> list[float]:
        return self.embed_many([text])[0]

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        normalized_texts = [text.strip() for text in texts]
        if not normalized_texts or any(not text for text in normalized_texts):
            raise ValueError("EMBEDDING_INVALID_INPUT: 待向量化文本不能为空。")

        payload = {
            "model": self._model,
            "input": {"texts": normalized_texts},
            "parameters": {"dimension": self._requested_dimension},
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        try:
            response = httpx.post(
                self._base_url,
                headers=headers,
                json=payload,
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
        except httpx.TimeoutException as error:
            raise ValueError("EMBEDDING_TIMEOUT: 百炼向量请求超时，请稍后重试。") from error
        except httpx.HTTPStatusError as error:
            error_code = _dashscope_error_code(error.response)
            if error_code == "Arrearage":
                raise ValueError(
                    "EMBEDDING_ACCOUNT_UNAVAILABLE: 百炼账户当前不可用（Arrearage）。"
                    "请在模型服务平台确认账户状态、开通模型或可用免费额度后重试。"
                ) from error
            raise ValueError(
                "EMBEDDING_UNAVAILABLE: 百炼向量请求失败，请检查 Key、模型权限或免费额度。"
            ) from error
        except httpx.HTTPError as error:
            raise ValueError("EMBEDDING_UNAVAILABLE: 无法连接百炼向量服务，请检查网络。") from error

        try:
            embeddings = response.json()["output"]["embeddings"]
            vectors = [
                [float(value) for value in item["embedding"]]
                for item in sorted(embeddings, key=lambda item: item.get("text_index", 0))
            ]
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise ValueError("EMBEDDING_INVALID_RESPONSE: 百炼未返回合法向量。") from error
        if len(vectors) != len(normalized_texts):
            raise ValueError("EMBEDDING_INVALID_RESPONSE: 百炼返回向量数量与输入不一致。")
        if any(not vector or not all(math.isfinite(value) for value in vector) for vector in vectors):
            raise ValueError("EMBEDDING_INVALID_RESPONSE: 百炼返回的向量不合法。")
        if any(len(vector) != self.dimension for vector in vectors):
            raise ValueError(
                "EMBEDDING_DIMENSION_MISMATCH: 返回向量维度与 DASHSCOPE_EMBEDDING_DIMENSION 不一致。"
            )
        return [_l2_normalize(vector) for vector in vectors]


def create_embedding_provider(settings: Settings) -> EmbeddingProvider:
    if settings.embedding_provider == "none":
        return DisabledEmbeddingProvider()
    if settings.embedding_provider == "local_hash":
        return LocalHashEmbeddingProvider(settings.embedding_dimension)
    if settings.embedding_provider == "dashscope":
        return DashScopeEmbeddingProvider(settings)
    raise ValueError(
        "EMBEDDING_CONFIG_INVALID: 仅支持 EMBEDDING_PROVIDER=none、local_hash 或 dashscope。"
    )


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True))


def _vector_tokens(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", text.lower()).strip()
    tokens = re.findall(r"[a-z0-9_]+", normalized)
    for chinese_group in re.findall(r"[\u4e00-\u9fff]+", normalized):
        if len(chinese_group) == 1:
            tokens.append(chinese_group)
        else:
            tokens.extend(
                chinese_group[index : index + 2]
                for index in range(len(chinese_group) - 1)
            )
    return tokens


def _l2_normalize(vector: list[float]) -> list[float]:
    magnitude = math.sqrt(sum(value * value for value in vector))
    if magnitude == 0:
        return vector
    return [value / magnitude for value in vector]


def _dashscope_error_code(response: httpx.Response) -> str | None:
    """Read only the public provider error code; never log response headers or keys."""
    try:
        body = response.json()
    except (json.JSONDecodeError, ValueError):
        return None
    code = body.get("code") if isinstance(body, dict) else None
    return code if isinstance(code, str) else None


def main() -> None:
    """Rebuild vectors for already-uploaded local documents after configuration."""
    from app.knowledge import rebuild_knowledge_embeddings

    provider = create_embedding_provider(get_settings())
    try:
        chunk_count = rebuild_knowledge_embeddings(provider)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from error
    print(f"已为 {chunk_count} 个资料分块重建 {provider.name} 向量。")


if __name__ == "__main__":
    main()
