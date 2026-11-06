"""Runtime configuration. Secrets are read from environment variables only."""

import os
from dataclasses import dataclass
from pathlib import Path


def load_dotenv(path: Path = Path(".env")) -> None:
    """Load local development variables without adding a dependency.

    Existing environment variables always win, which is important in deployment.
    The supported .env format is deliberately minimal: KEY=VALUE, one per line.
    """
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", maxsplit=1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    deepseek_api_key: str | None
    deepseek_base_url: str
    deepseek_model: str
    deepseek_timeout_seconds: float
    embedding_provider: str
    embedding_dimension: int
    dashscope_api_key: str | None
    dashscope_embedding_base_url: str
    dashscope_embedding_model: str
    dashscope_embedding_dimension: int
    dashscope_embedding_timeout_seconds: float

    @property
    def deepseek_enabled(self) -> bool:
        return bool(self.deepseek_api_key)


def get_settings() -> Settings:
    load_dotenv()
    dashscope_api_key = os.getenv("DASHSCOPE_API_KEY") or None
    configured_embedding_provider = os.getenv("EMBEDDING_PROVIDER", "").strip().lower()
    embedding_provider = (
        configured_embedding_provider
        if configured_embedding_provider not in {"", "none"}
        else ("dashscope" if dashscope_api_key else "none")
    )
    return Settings(
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY") or None,
        deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/"),
        deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        deepseek_timeout_seconds=float(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "30")),
        embedding_provider=embedding_provider,
        embedding_dimension=int(os.getenv("EMBEDDING_DIMENSION", "128")),
        dashscope_api_key=dashscope_api_key,
        dashscope_embedding_base_url=os.getenv(
            "DASHSCOPE_EMBEDDING_BASE_URL",
            "https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding",
        ).rstrip("/"),
        dashscope_embedding_model=os.getenv("DASHSCOPE_EMBEDDING_MODEL", "text-embedding-v3"),
        dashscope_embedding_dimension=int(os.getenv("DASHSCOPE_EMBEDDING_DIMENSION", "1024")),
        dashscope_embedding_timeout_seconds=float(
            os.getenv("DASHSCOPE_EMBEDDING_TIMEOUT_SECONDS", "30")
        ),
    )
