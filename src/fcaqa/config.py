"""Settings, read once from environment variables (and a local .env file).

Everything that differs between your laptop, CI and a deployed app lives here,
so no other module reads os.environ directly.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[2]
EMBED_DIM = 384  # must match vector(384) in sql/schema.sql


@dataclass(frozen=True)
class Settings:
    database_url: str
    embedder: str
    embed_model: str
    llm_provider: str
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    top_k: int
    min_similarity: float
    fca_api_base_url: str
    fca_api_token: str
    fca_api_provisions_path: str
    fca_api_auth_header: str
    fca_api_auth_prefix: str
    fca_api_delay_seconds: float
    raw_dir: Path


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        database_url=_env("DATABASE_URL", "postgresql://fca:fca@localhost:5432/fca"),
        embedder=_env("EMBEDDER", "hash"),
        embed_model=_env("EMBED_MODEL", "BAAI/bge-small-en-v1.5"),
        llm_provider=_env("LLM_PROVIDER", "fake"),
        llm_base_url=_env("LLM_BASE_URL"),
        llm_api_key=_env("LLM_API_KEY"),
        llm_model=_env("LLM_MODEL"),
        top_k=int(_env("TOP_K", "5")),
        min_similarity=float(_env("MIN_SIMILARITY", "0")),
        fca_api_base_url=_env("FCA_API_BASE_URL"),
        fca_api_token=_env("FCA_API_TOKEN"),
        fca_api_provisions_path=_env("FCA_API_PROVISIONS_PATH"),
        fca_api_auth_header=_env("FCA_API_AUTH_HEADER", "Authorization"),
        fca_api_auth_prefix=_env("FCA_API_AUTH_PREFIX", "Bearer"),
        fca_api_delay_seconds=float(_env("FCA_API_DELAY_SECONDS", "1.0")),
        raw_dir=Path(_env("RAW_DIR", str(ROOT / "data" / "raw"))),
    )
