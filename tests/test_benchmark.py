"""The benchmark reports real measurements and fills the Appendix C template."""

import importlib.util
import json
from pathlib import Path

import pytest

from app.services.troubleshooting_service import TroubleshootingService

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"


@pytest.fixture(scope="module")
def benchmark():
    spec = importlib.util.spec_from_file_location("benchmark", ROOT / "scripts" / "benchmark.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_percentile(benchmark):
    values = [float(n) for n in range(1, 101)]
    assert benchmark.percentile(values, 0.5) == 50.0
    assert benchmark.percentile(values, 0.95) == 95.0


def test_collect_metrics_and_render(benchmark, catalog, siis_rows):
    service = TroubleshootingService(catalog)  # hashed fallback embedder keeps this test fast
    service.warm(siis_rows)
    sets = {name: json.loads((FIXTURES / name).read_text(encoding="utf-8")) for name in benchmark.FIXTURE_SETS}
    metrics = benchmark.collect_metrics(service, sets, requests_per_path=5)
    assert metrics["schema_valid_pct"] == 100.0
    assert metrics["url_leaks"] == 0
    assert metrics["catalog_valid_pct"] == 100.0
    assert metrics["negative_false_hits"] == 0
    assert set(metrics["latency"]) == {"exact", "paraphrase", "cold"}
    assert metrics["paraphrase_total"] == sum(len(s["positives"]) for s in sets.values())
    report = benchmark.render(metrics, service.cache.embedder_name, 0.45)
    assert "# System Performance Metrics & Evaluation Report" in report
    assert "Semantic cache hit rate" in report
