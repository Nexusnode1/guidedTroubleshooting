"""Application configuration."""

from dataclasses import dataclass
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
ORIGINAL_DIR = DATA_DIR / "original"
PROCESSED_DIR = DATA_DIR / "processed"

# Which embedding model powers the semantic cache. A Hugging Face model id, a local
# directory (for example a model you fine-tuned and saved to models/my-embedder), or
# "hash" for the dependency-free fallback used in fast tests.
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-mpnet-base-v2")
# Minimum cosine similarity for a cached plan to answer a query. It is specific to the
# embedding model: tune it with scripts/benchmark.py whenever the model changes.
SIMILARITY_THRESHOLD = float(os.getenv("SIMILARITY_THRESHOLD", "0.45"))


@dataclass(frozen=True)
class Settings:
    """Runtime settings loaded from environment variables."""

    app_env: str = os.getenv("APP_ENV", "development")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")


settings = Settings()
