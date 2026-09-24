"""Deterministic quality gates for the corrected SIIS paraphrase dataset.

These import scripts/build_paraphrase_dataset.py and rebuild the dataset directly (never
reading the git-ignored, regenerable data/processed/siis_paraphrase_dataset.json off disk),
so a stale artifact can never make these pass. See docs/siis_alignment_audit.md for the
reasoning behind every alignment call and correction these tests lock in.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from app.services.relevance import content_tokens
from app.services.siis_parser import parse_sections

ROOT = Path(__file__).resolve().parents[1]

# Rows the audit found MISALIGNED with their article and corrected. A regression here means
# the correction was undone or weakened back toward the original unsupported wording.
KNOWN_GATED_ROWS = {"row_17"}  # aligned, unmodified query; a pre-existing lexical-gate limitation


def _load_builder():
    spec = importlib.util.spec_from_file_location("build_paraphrase_dataset", ROOT / "scripts" / "build_paraphrase_dataset.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def module_under_test():
    return _load_builder()


@pytest.fixture(scope="module")
def dataset(module_under_test):
    return module_under_test.build_dataset()


@pytest.fixture(scope="module")
def rows_by_id(dataset):
    return {row["id"]: row for row in dataset["rows"]}


def test_every_row_has_exactly_eight_distinct_paraphrases_not_equal_to_the_canonical(dataset):
    for row in dataset["rows"]:
        assert len(row["paraphrases"]) == 8, row["id"]
        assert len(set(row["paraphrases"])) == 8, f"{row['id']}: duplicate paraphrases"
        assert row["canonical_query"] not in row["paraphrases"], row["id"]


def test_no_duplicate_text_exists_anywhere_in_the_dataset(dataset):
    seen: dict[str, str] = {}
    for row in dataset["rows"]:
        for item in row["texts"]:
            if item["text"] in seen and seen[item["text"]] != row["id"]:
                pytest.fail(f"{item['text']!r} appears in both {seen[item['text']]} and {row['id']}")
            seen[item["text"]] = row["id"]
    assert len(seen) == sum(len(row["texts"]) for row in dataset["rows"])


def test_no_text_is_split_across_train_val_and_test(dataset):
    # A given text string must have exactly one split assignment across the whole dataset.
    split_of: dict[str, str] = {}
    for row in dataset["rows"]:
        for item in row["texts"]:
            if item["text"] in split_of:
                assert split_of[item["text"]] == item["split"], f"{item['text']!r} appears in two splits"
            split_of[item["text"]] = item["split"]


def test_rows_sharing_one_article_never_all_land_in_the_same_split_when_more_than_one_exists(dataset):
    # Guards against class-level leakage: if an article has multiple rows, at least one of
    # them must be held out of train, so the model is not evaluated only on classes it
    # trained on with the exact same underlying row.
    by_class: dict[str, list[dict]] = {}
    for row in dataset["rows"]:
        by_class.setdefault(row["class_id"], []).append(row)
    for class_id, members in by_class.items():
        if len(members) > 1:
            roles = {m["role"] for m in members}
            assert roles != {"train"}, f"class {class_id!r} has {len(members)} rows but none held out"


def test_split_sizes_match_the_documented_split_algorithm(dataset):
    counts = dataset["split_counts"]
    assert counts["total"] == 180
    assert counts["train"] == 84
    assert counts["val"] == 32
    assert counts["test"] == 64


def test_alignment_values_are_restricted_to_the_three_documented_categories(dataset):
    for row in dataset["rows"]:
        assert row["alignment"] in {"ALIGNED", "PARTIALLY_ALIGNED", "MISALIGNED"}


def test_non_aligned_rows_are_always_corrected_away_from_the_original_wording(dataset):
    for row in dataset["rows"]:
        if row["alignment"] != "ALIGNED":
            assert row["corrected"] is True, row["id"]
            assert row["canonical_query"] != row["original_query"], row["id"]


def test_every_row_but_the_known_gate_limitation_produces_a_valid_plan(dataset):
    invalid = {row["id"] for row in dataset["rows"] if not row["plan_valid"]}
    assert invalid == KNOWN_GATED_ROWS, (
        f"expected only {KNOWN_GATED_ROWS} to fail the lexical relevance gate, got {invalid}"
    )


@pytest.mark.parametrize(
    "row_id, forbidden_word",
    [
        ("row_1", "flash"),  # original miscomplaint: screen flashing when opening Gmail
        ("row_1", "flicker"),
        ("row_2", "stock"),  # original: searching a stock price while apps still work
        ("row_7", "icon"),  # original: only three app icons lit
        ("row_8", "expand"),  # original: phone's own screen won't expand to full size
        ("row_10", "unfold"),  # original: flicker when opening/unfolding the phone
        ("row_12", "floating"),  # original: floating navigation circle (not Multi Window)
        ("row_16", "charger"),  # original: momentary flash when plugging in a charger
        ("row_16", "millisecond"),
        ("row_20", "distort"),  # original: visual distortion (article is about rotation)
        ("row_22", "rings"),  # original: phone still rings/works (contradicts the article)
    ],
)
def test_corrected_canonical_queries_drop_the_original_unsupported_wording(rows_by_id, row_id, forbidden_word):
    canonical = rows_by_id[row_id]["canonical_query"].lower()
    assert forbidden_word not in canonical, f"{row_id}: still contains unsupported wording {forbidden_word!r}"


@pytest.mark.parametrize(
    "row_id, required_word",
    [
        ("row_5", "smart switch"),  # kept: the article's real domain
        ("row_8", "tv"),  # reframed into the mirroring context the article supports
        ("row_8", "mirror"),
        ("row_10", "camera"),  # reframed into the camera-flicker context the article supports
        ("row_12", "edge panel"),  # reframed into the Multi Window article's own remove-shortcut section
        ("row_20", "rotate"),  # reframed into the rotation-lock context the article supports
    ],
)
def test_corrected_canonical_queries_land_in_the_context_the_article_actually_supports(rows_by_id, row_id, required_word):
    canonical = rows_by_id[row_id]["canonical_query"].lower()
    assert required_word in canonical, f"{row_id}: missing expected supported context {required_word!r}"


@pytest.mark.parametrize("row_id", [
    "row_1", "row_2", "row_5", "row_7", "row_8", "row_9", "row_10", "row_11",
    "row_12", "row_16", "row_19", "row_20", "row_21", "row_22",
])
def test_canonical_query_shares_real_vocabulary_with_its_own_article(module_under_test, rows_by_id, row_id):
    """A cheap, deterministic proxy for 'not semantically inconsistent with the SIIS content':
    the corrected/kept query must share at least one real, non-generic word with the article
    it is now paired with (using the same lexical machinery the live relevance gate uses)."""
    row = rows_by_id[row_id]
    official = next(r for r in module_under_test.load_siis_rows() if r["id"] == row_id)
    siis = official["siis_response"]
    sections = parse_sections(siis["content"], siis["title"])
    article_tokens = content_tokens(siis["title"] + " " + " ".join(f"{s.heading} {s.body}" for s in sections))
    query_tokens = content_tokens(row["canonical_query"])
    assert query_tokens & article_tokens, f"{row_id}: no shared vocabulary with its own article at all"
