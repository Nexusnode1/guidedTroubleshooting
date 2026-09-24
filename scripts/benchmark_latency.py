"""Real REST API latency benchmark against a live uvicorn process.

IMPORTANT CAVEAT (see docs/docker_latency_benchmark.md): this measures the actual application
-- same code, same dependencies, same EMBEDDING_MODEL, same startup path the Dockerfile uses
-- running directly on this machine via uvicorn, not literally inside a Docker container.
Docker was not available to build/run in the environment this script was written in. Every
number below is a real, measured HTTP round trip against a live server; none are estimated,
guessed, or copied from an earlier run.

Runs, against ``http://127.0.0.1:<port>``:
  0. Startup: launch uvicorn, poll /health, time how long readiness takes.
  1. Smoke test: one normal request; validate schema, catalog-backed deeplinks, and that
     manual actions carry no actionableDeeplink.
  2. Cold path: N requests, each with a different (query, siis_response) pair cycled from the
     official, non-gated SIIS rows -- providing siis_response always takes the full
     enrichment -> extraction -> relevance -> deeplink-mapping -> ordering -> validation path
     (see TroubleshootingService._resolve), never the cache.
  3. Fast path: exact-repeat requests (guaranteed cache hit) and semantic-paraphrase requests
     (from the already-verified tests/fixtures/paraphrases*.json), no siis_response.
  4. API overhead: external wall-clock time minus the service's own self-reported
     meta.latency_ms, for a sample of both paths.

    python scripts/benchmark_latency.py
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.models.official_schema import ContextDeeplinkResponse  # noqa: E402
from app.services.catalog import load_catalog, load_siis_rows  # noqa: E402

PORT = 8931
BASE_URL = f"http://127.0.0.1:{PORT}"
N_COLD = 30
N_FAST_EXACT = 30
STARTUP_TIMEOUT_S = 180
DUMMY = "bixby://dummy_positive"


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    rank = max(1, min(len(ordered), int(round(q * len(ordered)))))
    return ordered[rank - 1]


def stats(values: list[float]) -> dict[str, float]:
    return {
        "n": len(values),
        "min": round(min(values), 2),
        "p50": round(percentile(values, 0.5), 2),
        "p95": round(percentile(values, 0.95), 2),
        "p99": round(percentile(values, 0.99), 2),
        "max": round(max(values), 2),
    }


def start_server(log_path: Path) -> subprocess.Popen:
    log_file = log_path.open("w", encoding="utf-8")
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(PORT), "--log-level", "warning"],
        cwd=str(ROOT),
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )


def wait_for_ready(client: httpx.Client, server: subprocess.Popen, log_path: Path) -> float:
    started = time.perf_counter()
    deadline = started + STARTUP_TIMEOUT_S
    while time.perf_counter() < deadline:
        if server.poll() is not None:
            raise SystemExit(f"server process exited early (code {server.returncode}); see {log_path}")
        try:
            response = client.get("/health", timeout=3)
            if response.status_code == 200 and response.json() == {"status": "ok"}:
                return (time.perf_counter() - started) * 1000
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise SystemExit(f"server did not become ready within {STARTUP_TIMEOUT_S}s; see {log_path}")


def timed_post(client: httpx.Client, payload: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    started = time.perf_counter()
    response = client.post("/v1/troubleshoot", json=payload, timeout=30)
    elapsed_ms = (time.perf_counter() - started) * 1000
    response.raise_for_status()
    return elapsed_ms, response.json()


def run_smoke_test(client: httpx.Client, catalog: list[dict[str, Any]]) -> dict[str, Any]:
    health = client.get("/health")
    assert health.status_code == 200 and health.json() == {"status": "ok"}, health.text

    rows = load_siis_rows()
    query = next(r for r in rows if r["id"] == "row_21")["original_query"]
    _, body = timed_post(client, {"query": query})
    assert set(body) == {"query", "query_variations", "response", "meta"}
    ContextDeeplinkResponse.model_validate(body["response"])
    contexts = body["response"]["contexts"]
    assert contexts, "expected a non-empty plan for a known-good official query"

    actionable = {entry["deeplink"] for entry in catalog}
    manual_ok = deeplinks_ok = True
    for action in contexts[0]["actions"]:
        for group in action["stepGroups"]:
            link = group["actionableDeeplink"]
            if action["category"] == "manual" and link is not None:
                manual_ok = False
            if link is not None and link["deeplink"] != DUMMY and link["deeplink"] not in actionable:
                deeplinks_ok = False
    return {
        "health_ok": True,
        "schema_ok": True,
        "manual_actions_have_no_deeplink": manual_ok,
        "deeplinks_are_catalog_backed": deeplinks_ok,
    }


def run_cold_path(client: httpx.Client, n: int) -> tuple[list[float], list[float]]:
    rows = [r for r in load_siis_rows() if r["id"] not in ("row_16", "row_17", "row_20")]  # excludes known-gated rows
    external, internal = [], []
    for i in range(n):
        row = rows[i % len(rows)]
        siis = row["siis_response"]
        elapsed_ms, body = timed_post(client, {"query": f"{row['original_query']} (cold sample {i})", "siis_response": siis["content"]})
        assert body["response"]["contexts"], f"cold path unexpectedly empty for {row['id']}"
        assert body["meta"]["cache_hit"] is False
        external.append(elapsed_ms)
        internal.append(float(body["meta"]["latency_ms"]))
    return external, internal


def run_fast_path(client: httpx.Client) -> dict[str, Any]:
    rows = load_siis_rows()
    exact_query = next(r for r in rows if r["id"] == "row_21")["original_query"]
    exact_external, exact_internal, exact_hits = [], [], 0
    for _ in range(N_FAST_EXACT):
        elapsed_ms, body = timed_post(client, {"query": exact_query})
        exact_external.append(elapsed_ms)
        exact_internal.append(float(body["meta"]["latency_ms"]))
        exact_hits += bool(body["meta"]["cache_hit"])

    paraphrase_texts = []
    for name in ("paraphrases.json", "paraphrases_holdout.json"):
        path = ROOT / "tests" / "fixtures" / name
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            paraphrase_texts += [item["query"] for item in data["positives"]]

    para_external, para_internal, para_hits = [], [], 0
    for text in paraphrase_texts:
        elapsed_ms, body = timed_post(client, {"query": text})
        para_external.append(elapsed_ms)
        para_internal.append(float(body["meta"]["latency_ms"]))
        para_hits += bool(body["meta"]["cache_hit"])

    combined_external = exact_external + para_external
    combined_internal = exact_internal + para_internal
    total_requests = len(exact_external) + len(para_external)
    total_hits = exact_hits + para_hits
    return {
        "exact_repeat": stats(exact_external),
        "paraphrase": stats(para_external) if para_external else None,
        "combined": stats(combined_external),
        "cache_hit_rate": round(total_hits / total_requests, 4) if total_requests else None,
        "n_paraphrases": len(paraphrase_texts),
        "external": combined_external,
        "internal": combined_internal,
    }


def main() -> int:
    log_path = ROOT / "data" / "processed" / "latency_benchmark_server.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    server = start_server(log_path)
    try:
        with httpx.Client(base_url=BASE_URL) as client:
            startup_ms = wait_for_ready(client, server, log_path)
            catalog = load_catalog()

            smoke = run_smoke_test(client, catalog)
            cold_external, cold_internal = run_cold_path(client, N_COLD)
            fast = run_fast_path(client)

            cold_stats = stats(cold_external)
            fast_external = fast.pop("external")
            fast_internal = fast.pop("internal")
            overhead = {
                "cold_path_ms": stats([e - i for e, i in zip(cold_external, cold_internal)]),
                "fast_path_ms": stats([e - i for e, i in zip(fast_external, fast_internal)]),
            }
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()

    fast_p95 = fast["combined"]["p95"]
    cold_p95 = cold_stats["p95"]
    result = {
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "processor": platform.processor() or "unknown",
        },
        "startup_ms_to_ready": round(startup_ms, 1),
        "smoke_test": smoke,
        "cold_path": cold_stats,
        "fast_path": fast,
        "api_overhead_ms_external_minus_internal": overhead,
        "fast_path_target_300ms": "MET" if fast_p95 < 300 else "NOT MET",
        "cold_path_target_8s": "MET" if cold_p95 <= 8000 else "NOT MET",
    }
    print(json.dumps(result, indent=2))
    (ROOT / "data" / "processed" / "latency_benchmark_result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
