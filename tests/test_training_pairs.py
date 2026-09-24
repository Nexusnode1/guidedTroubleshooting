"""Training pairs come from warm-up data and never include held-out evaluation phrasings."""

import importlib.util
from pathlib import Path

import pytest

from app.services.plan_cache import PlanCache
from app.services.troubleshooting_service import TroubleshootingService

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def exporter():
    spec = importlib.util.spec_from_file_location("export_training_pairs", ROOT / "scripts" / "export_training_pairs.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pairs_are_unique_nonempty_and_exclude_held_out_queries(exporter, catalog, siis_rows):
    service = TroubleshootingService(catalog, PlanCache(catalog))
    service.warm(siis_rows)
    pairs = exporter.build_pairs(service)
    assert len(pairs) > 500
    assert len({(p["anchor"], p["positive"]) for p in pairs}) == len(pairs)
    held = exporter.held_out_queries()
    assert held and not any(p["anchor"].strip().lower() in held for p in pairs)
    assert all(p["anchor"] and p["positive"] and p["plan"] for p in pairs)
