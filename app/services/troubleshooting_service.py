"""Online path: semantic cache lookup, cold build from SIIS text, and fallbacks."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import time
from typing import Any

from app.config import EMBEDDING_MODEL, PROCESSED_DIR
from app.retrieval.embeddings import EmbeddingModel
from app.retrieval.st_embedder import load_embedder
from app.services.catalog import load_catalog, load_siis_rows
from app.services.plan_builder import PlanBuild, PlanBuilder
from app.services.plan_cache import PlanCache
from app.services.variations import generate_variations

MODEL_ID = "rules-v1"
DEFAULT_CACHE_PATH = PROCESSED_DIR / "plan_cache.json"
_GOAL_TOPIC = re.compile(r"perform this (.+) (?:Troubleshooting|Configuration)$")
_DEFAULT_TOPIC = "device issue"


@dataclass(frozen=True)
class WarmResult:
    """What warm-up did with one SIIS row: cached, gated (irrelevant), or invalid."""

    row_id: str
    status: str
    build: PlanBuild | None


def _topic_of(response: Mapping[str, Any]) -> str:
    match = _GOAL_TOPIC.search(response["contexts"][0]["goal"])
    return match.group(1) if match else _DEFAULT_TOPIC


class TroubleshootingService:
    """Answer troubleshooting queries from validated, cached plans."""

    def __init__(self, catalog: Iterable[Mapping[str, Any]], cache: PlanCache | None = None) -> None:
        self.catalog = list(catalog)
        self.builder = PlanBuilder(self.catalog)
        self.cache = cache if cache is not None else PlanCache(self.catalog)

    def warm(self, rows: Iterable[Mapping[str, Any]]) -> list[WarmResult]:
        """Build and cache one plan per SIIS row whose article fits its query."""
        results: list[WarmResult] = []
        for row in rows:
            siis = row["siis_response"]
            build = self.builder.build(row["original_query"], siis["content"], siis["title"])
            if build is None:
                results.append(WarmResult(row["id"], "gated", None))
            elif build.errors:
                results.append(WarmResult(row["id"], "invalid", build))
            else:
                self.cache.add(row["id"], row["original_query"], build.query_variations, build.response)
                results.append(WarmResult(row["id"], "cached", build))
        return results

    def troubleshoot(self, query: str, siis_response: str | None = None) -> dict[str, Any]:
        """Return the API body for ``query`` (see PDF Appendix B)."""
        started = time.perf_counter()
        response, variations, cache_hit, fallback = self._resolve(query, siis_response)
        meta: dict[str, Any] = {
            "latency_ms": int(round((time.perf_counter() - started) * 1000)),
            "cache_hit": cache_hit,
            "model": MODEL_ID,
            "cost_usd": 0.0,
        }
        if fallback:
            meta["fallback"] = fallback
        return {"query": query, "query_variations": variations, "response": response, "meta": meta}

    def _resolve(
        self, query: str, siis_response: str | None
    ) -> tuple[dict[str, Any], list[str], bool, str | None]:
        empty: dict[str, Any] = {"contexts": []}
        if siis_response and siis_response.strip():
            build = self.builder.build(query, siis_response)
            if build is None or build.errors:
                return empty, generate_variations(query, _DEFAULT_TOPIC), False, "no_match"
            entry_id = "cold-" + hashlib.sha1(f"{query}\n{siis_response}".encode()).hexdigest()[:10]
            self.cache.add(entry_id, query, build.query_variations, build.response)
            return build.response, build.query_variations, False, None
        hit = self.cache.lookup(query)
        if hit is not None:
            response = hit.entry.response
            return response, generate_variations(query, _topic_of(response)), True, None
        fallback = "no_siis_context" if len(self.cache) == 0 else "no_match"
        return empty, generate_variations(query, _DEFAULT_TOPIC), False, fallback


def build_default_service(
    cache_path: Path | None = None,
    rebuild: bool = False,
    embedder: EmbeddingModel | None = None,
) -> TroubleshootingService:
    """Load the saved cache, or warm it from the official SIIS rows and save it.

    ``embedder`` defaults to the model named by ``EMBEDDING_MODEL`` (see app/config.py).
    """
    path = cache_path or DEFAULT_CACHE_PATH
    catalog = load_catalog()
    model = embedder or load_embedder(EMBEDDING_MODEL)
    cache = PlanCache.load(path, catalog, model=model) if path.exists() and not rebuild else PlanCache(catalog, model=model)
    service = TroubleshootingService(catalog, cache)
    if len(service.cache) == 0:
        service.warm(load_siis_rows())
        service.cache.save(path)
    return service
