"""Regression tests for scripts/benchmark_paraphrase_dataset.py's exclusion accounting.

A row with no valid plan has no target title to score retrieval against and is excluded,
not silently dropped (row_17 once was, which made the benchmark's N differ from the dataset's
split_counts). These tests fail if that accounting ever stops adding up, or if any row starts
being excluded without anyone noticing.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def benchmark():
    spec = importlib.util.spec_from_file_location("benchmark_paraphrase_dataset", ROOT / "scripts" / "benchmark_paraphrase_dataset.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def dataset(benchmark):
    return benchmark._load_dataset()


def test_every_split_texts_dataset_size_equals_scored_plus_excluded(benchmark, dataset):
    for split in ("train", "val", "test"):
        size = benchmark.split_size(dataset, split)
        excluded = benchmark.excluded_examples(dataset, split)
        invalid_row_ids = {r["id"] for r in dataset["rows"] if not r["plan_valid"]}
        scored = sum(
            1
            for row in dataset["rows"]
            if row["id"] not in invalid_row_ids
            for item in row["texts"]
            if item["split"] == split
        )
        assert scored + len(excluded) == size, split


def test_no_examples_are_currently_excluded(dataset, benchmark):
    """row_17 used to be the only exclusion (its query failed the lexical relevance gate;
    see docs/siis_alignment_audit.md). With the current official wording it shares the same
    two words with its article out of fewer query words, so it now builds a valid plan and
    nothing is excluded. If this starts failing, a row has started failing its plan build --
    investigate, do not just widen this test to accept it."""
    assert benchmark.excluded_examples(dataset, "val") == []
    assert benchmark.excluded_examples(dataset, "test") == []


def test_dataset_reports_180_texts_split_84_32_64_before_any_exclusion(dataset, benchmark):
    assert benchmark.split_size(dataset, "train") == 84
    assert benchmark.split_size(dataset, "val") == 32
    assert benchmark.split_size(dataset, "test") == 64


def test_eval_split_total_matches_dataset_size_minus_excluded(benchmark, dataset):
    from app.retrieval.embeddings import HashEmbeddingModel
    from app.services.catalog import load_catalog

    catalog = load_catalog()
    cache = benchmark._build_cache(dataset, catalog, HashEmbeddingModel())
    for split in ("val", "test"):
        result = benchmark._eval_split(cache, dataset, split)
        assert result["total"] == result["dataset_size"] - len(result["excluded"])
        assert result["total"] + len(result["excluded"]) == benchmark.split_size(dataset, split)
