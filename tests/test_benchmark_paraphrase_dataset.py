"""Regression tests for scripts/benchmark_paraphrase_dataset.py's exclusion accounting.

Guards the discrepancy found between the dataset's split_counts (64 test texts) and the
benchmark's reported N (55): a row with no valid plan has no target title to score retrieval
against and is excluded, not silently dropped. These tests fail if that accounting ever stops
adding up, or if the specific known exclusion (row_17, the pre-existing lexical relevance-gate
limitation) changes without anyone noticing.
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


def test_the_only_currently_excluded_examples_are_row_17s_nine_test_texts(dataset, benchmark):
    """Locks in the specific, already-documented reason for the N=64-vs-55 discrepancy
    (docs/siis_alignment_audit.md, docs/siis_paraphrase_baseline_benchmark.md). If this
    starts failing, a *different* row has started failing its plan build -- investigate,
    do not just widen this test to accept it."""
    val_excluded = benchmark.excluded_examples(dataset, "val")
    test_excluded = benchmark.excluded_examples(dataset, "test")
    assert val_excluded == []
    assert {item["row_id"] for item in test_excluded} == {"row_17"}
    assert len(test_excluded) == 9
    for item in test_excluded:
        assert "gated" in item["reason"]


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
