# Troubleshooting Chat and Engine Implementation Plan

> **Amendment (2026-09-22).** The hashed embedder measured 8 of 14 paraphrases, below the 80% target. Execution added a pretrained embedder behind the existing seam: `app/retrieval/st_embedder.py`, `EMBEDDING_MODEL` and `SIMILARITY_THRESHOLD` in `app/config.py`, cosine-only lookup with numpy in `plan_cache.py`, and one extra cache key per action (name plus first step). Where Tasks 7, 8, and 12 below differ, the code in the repository wins. Also added: a second held-out set (`tests/fixtures/paraphrases_holdout.json`), `tests/test_acceptance.py` (80% hit rate, 300 ms hit and 8 s cold P95, local-model loading), `scripts/dev.ps1`, `scripts/export_training_pairs.py`, and `docs/training-integration.md`. Result: 25 of 28 held-out paraphrases correct, 0 of 12 unrelated queries answered.

**Goal:** A web chat where a user types a vague Galaxy complaint and gets an ordered, validated troubleshooting plan whose auto steps have an **Open** button that drives an on-page phone simulator.

**Architecture:** A rules-only FastAPI engine turns official SIIS text into plans offline (parse sections, extract imperative steps, match each step's tapped UI label exactly to a catalog deeplink, order auto, manual, critical, validate) and serves them from a persistent semantic cache. A Vite + React chat calls `POST /v1/troubleshoot` and renders the plan; the Open button feeds a pure-function simulator. The embedder and the relevance gate each sit behind one function so the later embedding fine-tune is a swap, not a rewrite.

**Tech Stack:** Python 3.13, FastAPI, Pydantic v2, pytest, httpx (no new backend dependencies). Node 20, Vite 5, React 18, TypeScript, Vitest, Testing Library.

**Spec:** `docs/specs/2026-09-21-troubleshooting-chat-design.md`. Official contract: `../student_kit/` (PDF section numbers below refer to `Theme 2_Troubleshooting_Smart Guided Troubleshooting Engine.pdf`).

## Global Constraints

- Work inside `smartSolveTroubleGuide/` (its own git repo). Run Python as `./.venv/Scripts/python` (already created; `requirements.txt` installed). Run tests as `./.venv/Scripts/python -m pytest -q`. Baseline before this plan: 112 passed, 3 skipped.
- Official data in `data/original/` is immutable: never edit it. `schema.py` is copied unmodified to `app/models/official_schema.py`.
- Response body is pure JSON: no markdown fences, no preamble (PDF 4.2 item 4).
- `goal` is exactly `Follow these steps to perform this <Topic> Troubleshooting` (or `... Configuration`) (PDF 4.1).
- `title` is 2 to 3 words, sentence case. `score` is a float in [0.0, 1.0].
- `actionName` is Title Case and represents exactly one physical screen or feature. `description` is exactly 5 to 7 words and starts with "It will".
- `steps` are clear, imperative, one UI interaction each, with no URLs or external links. Zero URL leaks: no `http`, `https`, `www.`, or markdown links anywhere in a plan.
- `category` is `auto`, `manual`, or `critical`. `manual` actions never carry an actionable deeplink. `critical` actions are ordered last.
- `actionableDeeplink` is copied verbatim from `deeplinks.json`. Matching is done on descriptive metadata or the catalog's `validation.key` label, never on the masked URI. `bixby://dummy_positive` is used only when a step opens a Settings screen that has no catalog entry, with a self-written 5 to 7 word `description` and `message`.
- `query_variations` has 8 to 10 distinct entries.
- No hallucinated steps: every step comes from the SIIS text. No relevant text means `contexts: []` with `meta.fallback` set.
- Determinism: identical input gives identical plans (no randomness, no clock in plan content).
- Endpoints: `POST /v1/troubleshoot` and `GET /health` (PDF section 5). `meta.model` is `"rules-v1"` and `meta.cost_usd` is `0.0`.
- Do not tune test fixtures until they pass. Measured figures go into `metrics.md` as they are.

## File Structure

```
smartSolveTroubleGuide/
├── app/
│   ├── config.py                       MODIFY  add data-directory constants
│   ├── main.py                         MODIFY  lifespan builds the service; /health readiness
│   ├── api/routes.py                   MODIFY  POST /v1/troubleshoot -> service
│   ├── models/
│   │   ├── official_schema.py          CREATE  verbatim copy of student_kit/schema.py
│   │   └── schemas.py                  MODIFY  request body gains siis_response
│   └── services/
│       ├── catalog.py                  CREATE  load deeplinks.json / siis_responses.json
│       ├── plan_validator.py           MODIFY  goal syntax; dummy placeholder rule
│       ├── siis_parser.py              CREATE  SIIS text -> sections -> imperative steps
│       ├── key_matcher.py              CREATE  tapped UI label -> catalog entry (exact)
│       ├── relevance.py                CREATE  query vs article gate (swap point for embeddings)
│       ├── variations.py               CREATE  8-10 deterministic paraphrases
│       ├── plan_builder.py             CREATE  sections -> validated plan
│       ├── plan_cache.py               CREATE  semantic cache with persistence (replaces stub cache.py role)
│       ├── troubleshooting_service.py  CREATE  warm-up, online path, fallbacks
│       └── troubleshooting_engine.py   DELETE  query-driven engine that invented steps
├── scripts/build_plans.py              CREATE  warm the cache, print per-row report
├── scripts/benchmark.py                REPLACE latency + compliance + metrics.md
├── data/original/                      ADD     official files (copied, unmodified)
├── tests/                              per task below, plus fixtures/paraphrases.json
└── frontend/                           Vite + React chat and simulator
```

Existing modules kept unchanged and still used: `action_ordering.py` (`ordered_values`), `plan_validator.py` (extended), `bm25_retriever.py`, `dense_retriever.py`, `hybrid_retriever.py`, `query_enrichment.py`, `app/retrieval/embeddings.py` (`HashEmbeddingModel`, `EmbeddingModel` protocol, `cosine_similarity`). Left in place and unused by this plan: `deeplink_mapper.py`, `deeplink_mapping.py`, `screen_resolver.py`, `structure_extraction.py`, `retrieval/semantic_search.py`. Do not delete them; they are outside this plan's scope.

---

### Task 1: Official data, configuration, and loaders

**Files:**
- Create: `data/original/deeplinks.json`, `data/original/siis_responses.json`, `data/original/input.txt`, `data/original/sample_output.json` (copies of `../student_kit/*`)
- Create: `app/models/official_schema.py` (copy of `../student_kit/schema.py`)
- Modify: `app/config.py`
- Create: `app/services/catalog.py`
- Create: `tests/conftest.py`, `tests/test_official_data.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `app.config.ORIGINAL_DIR`, `PROCESSED_DIR` (`pathlib.Path`); `app.services.catalog.load_catalog(path: Path | None = None) -> list[dict]`; `load_siis_rows(path: Path | None = None) -> list[dict]`; pytest fixtures `catalog`, `siis_rows`, `catalog_by_id` (session scope); `app.models.official_schema.ContextDeeplinkResponse`.

- [ ] **Step 1: Write the failing tests**

`tests/conftest.py`:

```python
"""Shared fixtures built from the official data files."""

import pytest

from app.services.catalog import load_catalog, load_siis_rows


@pytest.fixture(scope="session")
def catalog():
    return load_catalog()


@pytest.fixture(scope="session")
def catalog_by_id(catalog):
    return {entry["id"]: entry for entry in catalog}


@pytest.fixture(scope="session")
def siis_rows():
    return load_siis_rows()
```

`tests/test_official_data.py`:

```python
"""The official inputs are present, immutable, and match the official schema."""

import json

import pytest

from app.config import ORIGINAL_DIR
from app.models.official_schema import ContextDeeplinkResponse

OFFICIAL_FILES = ("deeplinks.json", "siis_responses.json", "input.txt", "sample_output.json")


def test_catalog_has_official_entry_count_and_one_placeholder(catalog):
    assert len(catalog) == 578
    assert sum(entry["deeplink"] == "bixby://dummy_positive" for entry in catalog) == 1


def test_siis_rows_are_the_twenty_official_rows(siis_rows):
    assert len(siis_rows) == 20
    assert {"id", "original_query", "siis_response"} <= set(siis_rows[0])
    assert {"title", "content"} <= set(siis_rows[0]["siis_response"])


@pytest.mark.parametrize("name", OFFICIAL_FILES)
def test_original_files_are_byte_identical_to_the_kit(name):
    kit = ORIGINAL_DIR.parents[2] / "student_kit"
    if not kit.exists():
        pytest.skip("student_kit is not next to this repository")
    assert (ORIGINAL_DIR / name).read_bytes() == (kit / name).read_bytes()


def test_official_sample_output_matches_the_official_schema():
    sample = json.loads((ORIGINAL_DIR / "sample_output.json").read_text(encoding="utf-8"))
    ContextDeeplinkResponse.model_validate(sample["response"])
```

- [ ] **Step 2: Run to verify they fail**

Run: `./.venv/Scripts/python -m pytest tests/test_official_data.py -q`
Expected: collection error (`ModuleNotFoundError: app.services.catalog` or `ImportError: ORIGINAL_DIR`).

- [ ] **Step 3: Copy the data, extend config, add the loader**

```bash
cp ../student_kit/deeplinks.json ../student_kit/siis_responses.json ../student_kit/input.txt ../student_kit/sample_output.json data/original/
cp ../student_kit/schema.py app/models/official_schema.py
```

Replace the whole of `app/config.py`:

```python
"""Application configuration."""

from dataclasses import dataclass
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
ORIGINAL_DIR = DATA_DIR / "original"
PROCESSED_DIR = DATA_DIR / "processed"


@dataclass(frozen=True)
class Settings:
    """Runtime settings loaded from environment variables."""

    app_env: str = os.getenv("APP_ENV", "development")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")


settings = Settings()
```

Create `app/services/catalog.py`:

```python
"""Loaders for the official, immutable input files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.config import ORIGINAL_DIR
from app.utils.data_loader import load_json


def load_catalog(path: Path | None = None) -> list[dict[str, Any]]:
    """Return every entry of the official deeplink catalog, unmodified."""
    return list(load_json(path or ORIGINAL_DIR / "deeplinks.json")["deeplinks"])


def load_siis_rows(path: Path | None = None) -> list[dict[str, Any]]:
    """Return the official SIIS response rows (id, original_query, siis_response)."""
    return list(load_json(path or ORIGINAL_DIR / "siis_responses.json")["responses"])
```

- [ ] **Step 4: Run to verify they pass**

Run: `./.venv/Scripts/python -m pytest -q`
Expected: all pass (baseline 112 plus the 7 new tests; 3 skipped).

- [ ] **Step 5: Ignore generated artifacts and commit**

Append to `.gitignore`:

```
# Generated
data/processed/plan_cache.json
frontend/node_modules/
frontend/dist/
```

```bash
git add docs app tests data .gitignore
```

---

### Task 2: Align the validator to the official rules

The existing validator accepts any non-empty `goal` and requires an undocumented "fallback marker" field for `bixby://dummy_positive`. The PDF requires the exact goal syntax, and says the placeholder carries a self-written 5 to 7 word `description` and `message`.

**Files:**
- Modify: `app/services/plan_validator.py`
- Modify: `tests/test_plan_validator.py`

**Interfaces:**
- Consumes: existing `validate_plan(plan, catalog) -> PlanValidationResult` (`.valid`, `.errors`, `.plan`).
- Produces: same signature. New behaviour: rejects a `goal` that does not match `^Follow these steps to perform this .+ (?:Troubleshooting|Configuration)$`; accepts `bixby://dummy_positive` with no marker when `description` and `message` are each 5 to 7 words, rejects it otherwise.

- [ ] **Step 1: Update and add the tests**

In `tests/test_plan_validator.py`:

Change the goal in `_valid_plan()` from `"Follow these steps to troubleshoot battery performance"` to `"Follow these steps to perform this Battery Troubleshooting"`.

Replace the test `test_valid_dummy_positive_requires_mapper_fallback_marker` (the whole function) with:

```python
def test_valid_dummy_positive_with_self_written_text() -> None:
    plan = _valid_plan()
    plan["contexts"][0]["actions"][0]["stepGroups"][0]["actionableDeeplink"] = {
        "deeplink": "bixby://dummy_positive",
        "description": "Opens the Storage Settings screen",
        "message": "Open the Storage screen in Settings",
        "originalType": "placeholder",
    }
    assert _result(plan).valid is True
```

Replace the test `test_dummy_positive_without_fallback_marker_is_rejected` (the whole function) with:

```python
def test_dummy_positive_with_wrong_word_count_is_rejected() -> None:
    plan = _valid_plan()
    # The catalog description here has 8 words and the message has 3.
    plan["contexts"][0]["actions"][0]["stepGroups"][0]["actionableDeeplink"]["deeplink"] = "bixby://dummy_positive"
    assert _result(plan).valid is False
```

Add at the end of the file:

```python
@pytest.mark.parametrize("goal", [
    "Fix my battery",
    "Follow these steps to troubleshoot battery performance",
    "Follow these steps to perform this Troubleshooting",
])
def test_goal_must_follow_official_syntax(goal: str) -> None:
    plan = _valid_plan()
    plan["contexts"][0]["goal"] = goal
    assert _result(plan).valid is False


def test_goal_configuration_form_is_accepted() -> None:
    plan = _valid_plan()
    plan["contexts"][0]["goal"] = "Follow these steps to perform this Battery Configuration"
    assert _result(plan).valid is True
```

- [ ] **Step 2: Run to verify the new and changed tests fail**

Run: `./.venv/Scripts/python -m pytest tests/test_plan_validator.py -q`
Expected: `test_goal_must_follow_official_syntax` (all 3 cases) and `test_valid_dummy_positive_with_self_written_text` FAIL (the old validator accepts any non-empty goal and demands a fallback marker); the other tests pass.

- [ ] **Step 3: Apply these exact edits to `app/services/plan_validator.py`**

Each edit replaces a unique block; every "replace" text occurs exactly once in the file.

**Edit 1.** Replace:

```python
_FALLBACK_MARKER_FIELDS = ("fallback", "fallback_marker", "mapper_fallback")
```

with:

```python
_GOAL = re.compile(r"^Follow these steps to perform this .+ (?:Troubleshooting|Configuration)$")
```

**Edit 2.** Delete this block:

```python
def _fallback_marker(raw: Mapping[str, Any]) -> bool:
    """Require an explicit mapper marker for the documented dummy URI."""
    if raw.get("is_fallback") is True or raw.get("isFallback") is True:
        return True
    return any(raw.get(field) == "dummy_positive" for field in _FALLBACK_MARKER_FIELDS)


def _raw_actionable(raw_group: Mapping[str, Any]) -> Mapping[str, Any] | None:
    value = raw_group.get("actionableDeeplink")
    return value if isinstance(value, Mapping) else None
```

**Edit 3.** Replace:

```python
        if not goal.goal.strip():
            errors.append(f"{prefix}.goal must be non-empty")
```

with:

```python
        if not _GOAL.match(goal.goal.strip()):
            errors.append(f"{prefix}.goal must read 'Follow these steps to perform this <Topic> Troubleshooting' or 'Configuration'")
```

**Edit 4.** Replace:

```python
for goal_index, (goal, raw_goal) in enumerate(zip(parsed.contexts, raw_contexts)):
```

with:

```python
for goal_index, goal in enumerate(parsed.contexts):
```

**Edit 5.** Delete this block:

```python
        raw_actions = raw_goal.get("actions", []) if isinstance(raw_goal, Mapping) else []
```

**Edit 6.** Delete this block:

```python
            raw_action = raw_actions[action_index] if action_index < len(raw_actions) and isinstance(raw_actions[action_index], Mapping) else {}
```

**Edit 7.** Delete this block:

```python
                raw_groups = raw_action.get("stepGroups", []) if isinstance(raw_action, Mapping) else []
                raw_group = raw_groups[group_index] if group_index < len(raw_groups) and isinstance(raw_groups[group_index], Mapping) else {}
```

**Edit 8.** Delete this block:

```python
                raw_link = _raw_actionable(raw_group)
```

**Edit 9.** Replace:

```python
                    if uri == "bixby://dummy_positive":
                        if not _fallback_marker(raw_link or {}):
                            errors.append(f"{group_prefix}.dummy_positive requires mapper fallback marker")
```

with:

```python
                    if uri == "bixby://dummy_positive":
                        placeholder_words = (
                            len(_WORD.findall(actionable.description)),
                            len(_WORD.findall(actionable.message or "")),
                        )
                        if not all(5 <= count <= 7 for count in placeholder_words):
                            errors.append(f"{group_prefix}.dummy_positive description and message must each contain 5 to 7 words")
```


- [ ] **Step 4: Run the whole suite**

Run: `./.venv/Scripts/python -m pytest -q`
Expected: all pass. If any other test still builds a plan with the old goal wording, change that test's goal to the official syntax rather than loosening the validator.

- [ ] **Step 5: Commit**

```bash
git add app/services/plan_validator.py tests/test_plan_validator.py
```

---

### Task 3: SIIS parser (sections and imperative steps)

**Files:**
- Create: `app/services/siis_parser.py`
- Test: `tests/test_siis_parser.py`

**Interfaces:**
- Produces: `Section(heading: str, body: str, steps: tuple[str, ...])` (frozen dataclass); `clean_siis_text(content: str) -> str`; `extract_steps(body: str) -> list[str]`; `parse_sections(content: str, title: str = "") -> list[Section]`; `is_imperative(text: str) -> bool`.

- [ ] **Step 1: Write the failing tests**

```python
"""SIIS text becomes sections and imperative steps, and nothing else."""

import re

import pytest

from app.services.siis_parser import clean_siis_text, extract_steps, is_imperative, parse_sections


def test_clean_removes_category_prefix_urls_and_markdown_links():
    raw = "Smartphone,Tablet Title ( Smartphone,Tablet): ## Head\nTap https://x.example/a now [link](http://b.example) done www.c.example"
    cleaned = clean_siis_text(raw)
    assert cleaned.startswith("## Head")
    assert "http" not in cleaned and "www." not in cleaned
    assert "link" in cleaned


def test_navigation_chain_becomes_separate_steps():
    body = "Navigate to and open Settings. Tap Apps, select your email app."
    assert extract_steps(body) == ["Navigate to Settings.", "Tap Apps.", "Select your email app."]


def test_leading_condition_is_dropped_and_then_splits():
    body = "On devices with a Power button: Press and hold the Power button, then tap Restart."
    assert extract_steps(body) == ["Press and hold the Power button.", "Tap Restart."]


def test_you_can_is_turned_into_an_instruction():
    assert extract_steps("You can schedule a walk-in or mail-in repair to fix your cracked screen.") == [
        "Schedule a walk-in or mail-in repair to fix your cracked screen."
    ]


@pytest.mark.parametrize("sentence", [
    "The LDI should normally appear solid white.",
    "If the device has been exposed to moisture, the LDI will appear solid pink.",
    "If your screen protector is peeling, please remove it.",
    "Let's go through some steps to help resolve this.",
])
def test_non_instructions_are_not_steps(sentence):
    assert extract_steps(sentence) == []


def test_parse_sections_strips_numbering_and_uses_title_for_intro():
    content = "Cat Title ( Cat): Tap Settings now.\n## Step 2: Verify Your Phone's Internet Connection\nTap Wi-Fi.\n## 3. Charger Issues\nTry a different charger."
    sections = parse_sections(content, title="Title")
    assert [s.heading for s in sections] == ["Title", "Verify Your Phone's Internet Connection", "Charger Issues"]
    assert sections[1].steps == ("Tap Wi-Fi.",)


def test_parse_sections_stops_at_the_first_garbled_section():
    garbled = "enteryourcurrentpinpasswordorpatternandthentapsomething"
    content = f"Cat Title ( Cat): Tap Settings now.\n## Good\nTap Display.\n## Broken\n{garbled}\n## After\nTap Bluetooth."
    assert [s.heading for s in parse_sections(content, title="Title")] == ["Title", "Good"]


def test_is_imperative():
    assert is_imperative("Tap Display.") and is_imperative("go to Settings")
    assert not is_imperative("The screen is blank.")


def test_real_email_article_yields_clean_steps(siis_rows):
    row = next(r for r in siis_rows if r["id"] == "row_1")
    sections = parse_sections(row["siis_response"]["content"], row["siis_response"]["title"])
    clear = next(s for s in sections if "Cache and Data" in s.heading)
    assert "Tap Storage." in clear.steps
    for section in sections:
        for step in section.steps:
            assert step.endswith(".") and not re.search(r"https?://|www\.", step)


def test_real_garbled_article_keeps_only_the_clean_leading_part(siis_rows):
    row = next(r for r in siis_rows if r["id"] == "row_3")
    sections = parse_sections(row["siis_response"]["content"], row["siis_response"]["title"])
    assert len(sections) == 1
    assert "Fingerprint" not in sections[0].body
```

- [ ] **Step 2: Run to verify they fail**

Run: `./.venv/Scripts/python -m pytest tests/test_siis_parser.py -q`
Expected: collection error, `ModuleNotFoundError: app.services.siis_parser`.

- [ ] **Step 3: Create `app/services/siis_parser.py`**

```python
"""Rule-based parsing of raw SIIS knowledge text into sections and imperative steps.

Nothing is invented: a step is a sentence or clause of the source that already
begins with an imperative verb. URLs and markdown links are removed here so
they can never reach a plan.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


_CATEGORY_PREFIX = re.compile(r"\):\s")
_URL = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_HEADING = re.compile(r"(?m)^#{1,4}[ \t]+(.*)$")
_NUMBERING = re.compile(r"^(?:step\s*)?\d+\s*[:.)]\s*", re.IGNORECASE)
_GARBLED = re.compile(r"[A-Za-z,.'’-]{30,}")

_START_VERBS = (
    "tap touch swipe navigate open press select connect check restart turn enable disable "
    "clear charge contact visit schedule use ensure make increase adjust set locate insert "
    "enter remove try go pick choose toggle reset review confirm update drag hold shine "
    "eject plug disconnect reinsert uninstall install inspect examine scan sign log wipe "
    "force back send follow download perform allow reboot power"
).split()
_CHAIN_VERBS = (
    "tap touch swipe navigate open press select connect check restart turn enable disable "
    "clear charge insert enter remove try go pick choose toggle reset review confirm update "
    "drag eject plug disconnect reinsert uninstall install visit contact schedule scan"
).split()
_AND_VERBS = (
    "open|enable|disable|turn on|turn off|change|select|tap|choose|press|click|navigate|"
    "go|restart|reset|check|review"
)
_START = re.compile(rf"(?:{'|'.join(_START_VERBS)})\b", re.IGNORECASE)
_LEAD = re.compile(
    r"^(?:[-*•]\s*)?(?:please|next|then|first|now|finally|also|alternatively|simply|just)[,\s]+",
    re.IGNORECASE,
)
_MODAL = re.compile(
    r"^(?:you\s+(?:can|may|should|need\s+to|will\s+need\s+to)|you'll\s+need\s+to|let's|let\s+us)\s+(?:also\s+)?",
    re.IGNORECASE,
)
_CONDITION = re.compile(
    r"^(?:if|when|once|after|before|on|for|in\s+case|to)\b[^,:]{0,80}[,:]\s*", re.IGNORECASE
)
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])|\n+")
_NAV_AND = re.compile(r"\b(navigate|swipe|go|scroll)\s+to\s+and\s+(?:open|tap|select)\b", re.IGNORECASE)
_NOT_A_STEP = re.compile(
    r"^(?:\w+\s+(?:it|them|this|that)|go\s+through\b.*|try\s+the\s+following\b.*)\.$", re.IGNORECASE
)
_CHAIN = re.compile(
    rf",\s*(?:and\s+)?(?:then\s+)?(?=(?:{'|'.join(_CHAIN_VERBS)})\b)"
    rf"|\s+(?:and\s+)?then\s+(?=(?:{'|'.join(_CHAIN_VERBS)})\b)"
    rf"|;\s*"
    rf"|\s+and\s+(?=(?:{_AND_VERBS})\b)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Section:
    """One headed block of an article and the imperative steps found in it."""

    heading: str
    body: str
    steps: tuple[str, ...]


def clean_siis_text(content: str) -> str:
    """Drop the leading category prefix, URLs, and markdown link targets."""
    match = _CATEGORY_PREFIX.search(content[:800])
    text = content[match.end():] if match else content
    text = _MARKDOWN_LINK.sub(r"\1", text)
    return _URL.sub("", text).strip()


def _clean_piece(piece: str) -> str:
    piece = piece.strip(" \t-*•:;,")
    for _ in range(3):
        stripped = _MODAL.sub("", _LEAD.sub("", piece), count=1)
        if stripped == piece:
            break
        piece = stripped
    return piece


def is_imperative(text: str) -> bool:
    """Return whether ``text`` starts with a known instruction verb."""
    return bool(_START.match(text.strip()))


def extract_steps(body: str) -> list[str]:
    """Return the imperative clauses of ``body`` in source order."""
    steps: list[str] = []
    for sentence in _SENTENCE.split(_NAV_AND.sub(r"\1 to", body)):
        sentence = _CONDITION.sub("", sentence.strip(), count=1)
        for piece in _CHAIN.split(sentence):
            piece = _clean_piece(piece)
            if not is_imperative(piece) or len(piece.split()) < 2:
                continue
            piece = piece.rstrip(" .!?:;,") + "."
            if _NOT_A_STEP.match(piece):
                continue
            steps.append(piece[0].upper() + piece[1:])
    return steps


def parse_sections(content: str, title: str = "") -> list[Section]:
    """Split an article into sections, stopping at the first garbled section."""
    parts = _HEADING.split(clean_siis_text(content))
    raw = [("", parts[0]), *zip(parts[1::2], parts[2::2])]
    sections: list[Section] = []
    for heading, body in raw:
        body = body.strip()
        if _GARBLED.search(body):
            break
        if not body:
            continue
        heading = _NUMBERING.sub("", heading.strip()) or title
        sections.append(Section(heading, body, tuple(extract_steps(body))))
    return sections
```

- [ ] **Step 4: Run to verify they pass**

Run: `./.venv/Scripts/python -m pytest tests/test_siis_parser.py -q`
Expected: all pass. If one real-data assertion fails, fix the regexes in the parser, not the assertion.

- [ ] **Step 5: Commit**

```bash
git add app/services/siis_parser.py tests/test_siis_parser.py
```

---

### Task 4: Exact-label deeplink matching

The skeleton's hybrid retriever is not used here. Measured on real sections, its min-max normalisation gave the top hit a score near 1.0 even for unrelated screens ("Restart in Safe Mode" scored 1.0 against "One-handed mode"). The catalog's `validation.key` is the literal Settings label, so an exact label match is precise.

**Files:**
- Create: `app/services/key_matcher.py`
- Test: `tests/test_key_matcher.py`

**Interfaces:**
- Produces: `DUMMY_URI = "bixby://dummy_positive"`; `normalize_label(text) -> str`; `tap_targets(steps: Iterable[str]) -> list[str]`; `DeeplinkChoice(entry: Mapping, target: str)`; `KeyIndex(catalog).find(steps: Sequence[str], context: str) -> DeeplinkChoice | None`.

- [ ] **Step 1: Write the failing tests**

```python
"""Steps map to catalog entries by the exact Settings label they tap."""

import pytest

from app.services.key_matcher import DUMMY_URI, KeyIndex, normalize_label, tap_targets


def test_tap_targets_skip_the_settings_root():
    assert tap_targets(["Go to Settings.", "Tap Connections.", "Tap Wi-Fi."]) == ["Connections", "Wi-Fi"]


def test_tap_targets_trim_trailing_clauses():
    assert tap_targets(["Tap the switch next to Touch sensitivity to disable it."]) == ["Touch sensitivity"]


def test_tap_targets_ignore_action_buttons():
    assert tap_targets(["Tap Clear cache.", "Tap OK.", "Tap Restart again to confirm.", "Tap Safe mode."]) == []


def test_normalize_label_ignores_case_and_punctuation():
    assert normalize_label("Wi-Fi") == normalize_label("wi fi") == "wi fi"


@pytest.fixture(scope="module")
def index(catalog):
    return KeyIndex(catalog)


def test_wifi_opens_the_plain_screen_by_default(index, catalog_by_id):
    choice = index.find(["Go to Settings.", "Tap Connections.", "Tap Wi-Fi."], "")
    assert choice.entry["id"] == "DL-0313"
    assert choice.entry["deeplink"] == catalog_by_id["DL-0313"]["deeplink"]


@pytest.mark.parametrize("context, expected", [("Enable Wi-Fi", "DL-0574"), ("Disable Wi-Fi", "DL-0573")])
def test_toggle_direction_follows_the_text(index, context, expected):
    assert index.find(["Tap Wi-Fi."], context).entry["id"] == expected


def test_touch_sensitivity_on_and_off(index):
    steps = ["Tap Display.", "Tap the switch next to Touch sensitivity."]
    assert index.find(steps, "enable it").entry["id"] == "DL-0126"
    assert index.find(steps, "disable it").entry["id"] == "DL-0125"


def test_unindexed_labels_do_not_match(index):
    assert index.find(["Tap Safe mode."], "") is None
    assert index.find(["Tap Storage."], "") is None


def test_the_placeholder_is_never_a_match(index, catalog):
    for entry in catalog:
        choice = index.find([f"Tap {entry.get('message') or 'Nothing'}."], "")
        assert choice is None or choice.entry["deeplink"] != DUMMY_URI
```

- [ ] **Step 2: Run to verify they fail**

Run: `./.venv/Scripts/python -m pytest tests/test_key_matcher.py -q`
Expected: collection error, `ModuleNotFoundError: app.services.key_matcher`.

- [ ] **Step 3: Create `app/services/key_matcher.py`**

```python
"""Match SIIS steps to catalog deeplinks by the exact UI label they tap.

Catalog ``validation.key`` values are the literal Settings labels ("Wi-Fi",
"Navigation bar"). The URI itself is never a match feature and is copied
verbatim from the matched entry.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import re
from typing import Any

DUMMY_URI = "bixby://dummy_positive"

_TAP = re.compile(
    r"\b(?i:tap|select|touch|choose|open)(?:\s+(?i:and\s+hold))?(?:\s+(?i:on))?"
    r"(?:\s+(?i:the))?(?:\s+(?i:switch\s+next\s+to))?"
    r"\s+([A-Z][A-Za-z0-9+\-/()' ]*?)(?=\s*(?:[,.;:]|$))"
)
_TRIM = re.compile(
    r"\s+(?:to|again|for|if|when|and|then|in|on|from|at|until|so|because)\b.*$", re.IGNORECASE
)
_NOT_A_SCREEN = frozenset(
    {
        "ok", "settings", "restart", "reset", "delete all", "clear cache", "clear data",
        "safe mode", "power off", "power", "recents", "home",
    }
)
_TURN_OFF = re.compile(r"\b(?:turn\s+off|disable|switch\s+off|toggle\s+off)\b", re.IGNORECASE)
_TURN_ON = re.compile(
    r"\b(?:turn\s+on|enable|switch\s+on|toggle\s+on|switch\s+next\s+to)\b", re.IGNORECASE
)


def normalize_label(text: str) -> str:
    """Lower-case a UI label and collapse punctuation for exact comparison."""
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def tap_targets(steps: Iterable[str]) -> list[str]:
    """Return the UI labels tapped by ``steps`` in order, excluding action buttons."""
    targets: list[str] = []
    for step in steps:
        for match in _TAP.finditer(step):
            label = _TRIM.sub("", match.group(1)).strip()
            if label and normalize_label(label) not in _NOT_A_SCREEN:
                targets.append(label)
    return targets


@dataclass(frozen=True)
class DeeplinkChoice:
    """A catalog entry chosen for a step group and the label that matched it."""

    entry: Mapping[str, Any]
    target: str


class KeyIndex:
    """Index of catalog entries by their exact Settings label."""

    def __init__(self, catalog: Iterable[Mapping[str, Any]]) -> None:
        self._by_key: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for entry in catalog:
            validation = entry.get("validation")
            key = validation.get("key") if isinstance(validation, Mapping) else None
            if isinstance(key, str) and entry.get("deeplink") != DUMMY_URI:
                self._by_key[normalize_label(key)].append(entry)

    def find(self, steps: Sequence[str], context: str) -> DeeplinkChoice | None:
        """Pick the entry for the last tapped label that exists in the catalog."""
        for target in reversed(tap_targets(steps)):
            entries = self._by_key.get(normalize_label(target))
            if entries:
                return DeeplinkChoice(_pick(entries, context), target)
        return None


def _pick(entries: Sequence[Mapping[str, Any]], context: str) -> Mapping[str, Any]:
    """Prefer the toggle direction the text asks for, else the plain open entry."""
    order = ["onClickURL", "onURL", "updateURL", "offURL"]
    if _TURN_OFF.search(context):
        order.insert(0, "offURL")
    elif _TURN_ON.search(context):
        order.insert(0, "onURL")
    for original_type in order:
        for entry in entries:
            if entry.get("originalType") == original_type:
                return entry
    return entries[0]
```

- [ ] **Step 4: Run to verify they pass**

Run: `./.venv/Scripts/python -m pytest tests/test_key_matcher.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add app/services/key_matcher.py tests/test_key_matcher.py
```

---

### Task 5: Relevance gate and query variations

**Files:**
- Create: `app/services/relevance.py`, `app/services/variations.py`
- Test: `tests/test_relevance.py`, `tests/test_variations.py`

**Interfaces:**
- Produces: `relevance(query: str, article_text: str, title: str = "") -> float` (0.0 means unrelated; `MIN_RELEVANCE = 0.15`); `content_tokens(text) -> set[str]`; `normalize_query(query: str) -> str`; `generate_variations(query: str, topic: str) -> list[str]` (8 to 10 distinct strings, deterministic).
- Consumes: existing `QueryEnricher().enrich(query)` (`.normalized_query`, `.core_intent`).

- [ ] **Step 1: Write the failing tests**

`tests/test_relevance.py`:

```python
from app.services.relevance import MIN_RELEVANCE, content_tokens, relevance


def test_generic_device_words_are_ignored():
    assert content_tokens("my Samsung Galaxy screen is cracked") == {"crack"}


def test_unrelated_query_scores_zero():
    assert relevance("best pasta recipe", "Blank or black display Step 1 Check for physical damage") == 0.0


def test_a_title_word_alone_is_enough():
    score = relevance("my screen is blank", "check the charger", title="Blank or black display")
    assert score >= MIN_RELEVANCE


def test_one_shared_word_is_not_enough_for_a_long_query():
    assert relevance("alpha beta gamma delta epsilon zeta", "alpha only here") == 0.0


def test_short_query_needs_only_one_shared_word():
    assert relevance("cracked screen", "Cracked screen service options") > 0.0
```

`tests/test_variations.py`:

```python
from app.services.variations import generate_variations, normalize_query


def test_variations_are_eight_to_ten_distinct_and_deterministic():
    query = "My Galaxy S22 screen turns completely blank or white"
    first = generate_variations(query, "Blank Display")
    assert 8 <= len(first) <= 10
    assert len(set(first)) == len(first)
    assert first == generate_variations(query, "Blank Display")
    assert first[0] == query


def test_variations_span_registers():
    joined = " | ".join(generate_variations("phone swipe gestures wrong direction after app install", "Swipe Navigation"))
    for marker in ("annoying", "How do I fix", "Why does", "Troubleshoot swipe navigation"):
        assert marker in joined


def test_variations_contain_no_urls():
    assert not any("http" in v or "www." in v for v in generate_variations("wifi keeps dropping", "Wi-Fi"))


def test_normalize_query_is_lowercase_and_stable():
    assert normalize_query("Phone Swipe GESTURES wrong direction") == "phone swipe gestures wrong direction"
```

- [ ] **Step 2: Run to verify they fail**

Run: `./.venv/Scripts/python -m pytest tests/test_relevance.py tests/test_variations.py -q`
Expected: collection errors, modules not found.

- [ ] **Step 3: Create the modules**

`app/services/relevance.py`:

```python
"""Lexical query-to-article relevance used to refuse articles that do not fit."""

from __future__ import annotations

import re

MIN_RELEVANCE = 0.15
MIN_SHARED_TOKENS = 2
SHORT_QUERY_TOKENS = 4

_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    "a an and are as at be but by can cannot could did do does for from had has have how i if "
    "in into is it its me my no not of on or our so that the their then there this to too up "
    "was we were what when where which who why will with would you your after again all also "
    "any because before being both down each even few get got just more most much new now off "
    "only other out over own same should some such than them these they those through under "
    "until very via while".split()
)
_GENERIC = frozenset(
    "screen samsung galaxy phone mobile tablet device display app apps use using open tap try "
    "turn work make stay see give back look right need still".split()
)


def _stem(token: str) -> str:
    if len(token) > 5 and token.endswith("ing"):
        return token[:-3]
    if len(token) > 4 and token.endswith("ed"):
        return token[:-2]
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def content_tokens(text: str) -> set[str]:
    """Return stemmed, non-generic content words of ``text``."""
    return {
        _stem(token)
        for token in _TOKEN.findall(text.lower())
        if len(token) > 2 and not token.isdigit() and token not in _STOP and token not in _GENERIC
    }


def relevance(query: str, article_text: str, title: str = "") -> float:
    """Fraction of the query's content words found in the article, or 0.0 if unrelated.

    A word shared with the article title is enough on its own (the title names the
    topic); otherwise at least two words (one for very short queries) must be shared.
    """
    wanted = content_tokens(query)
    if not wanted:
        return 0.0
    shared = wanted & content_tokens(f"{title} {article_text}")
    in_title = bool(wanted & content_tokens(title))
    needed = 1 if len(wanted) <= SHORT_QUERY_TOKENS else MIN_SHARED_TOKENS
    if not in_title and len(shared) < needed:
        return 0.0
    ratio = len(shared) / len(wanted)
    return max(ratio, MIN_RELEVANCE) if in_title else (ratio if ratio >= MIN_RELEVANCE else 0.0)
```

`app/services/variations.py`:

```python
"""Deterministic query paraphrases in varied registers.

The paraphrases double as the semantic cache key set for a plan, so they must
be reproducible: no randomness, no model calls.
"""

from __future__ import annotations

from app.services.query_enrichment import QueryEnricher

_MAX_CORE_WORDS = 14
_enricher = QueryEnricher()


def normalize_query(query: str) -> str:
    """Return the canonical lower-case form used for cache keys."""
    return _enricher.enrich(query).normalized_query


def _with_typo(text: str) -> str:
    """Swap two inner letters of the longest word (first one on ties)."""
    words = text.split()
    if not words:
        return text
    index = max(range(len(words)), key=lambda i: len(words[i]))
    word = words[index]
    if len(word) >= 4:
        words[index] = word[0] + word[2] + word[1] + word[3:]
    return " ".join(words)


def _sentence(text: str) -> str:
    text = text.strip()
    return text[:1].upper() + text[1:] if text else text


def generate_variations(query: str, topic: str) -> list[str]:
    """Return 8-10 distinct paraphrases of ``query``.

    Registers: original, formal, casual, keyword-only, frustrated, typo,
    questions, and topic-only phrasings.
    """
    enriched = _enricher.enrich(query)
    core = " ".join(enriched.core_intent.split()[:_MAX_CORE_WORDS]) or enriched.normalized_query
    keywords = " ".join(core.split()[:6])
    topic_text = topic.lower()
    candidates = [
        query.strip(),
        f"I am experiencing an issue with my Galaxy: {core}.",
        f"my phone is acting up, {core}",
        keywords,
        f"This is so annoying - {core}, please help!",
        _with_typo(core),
        f"How do I fix this: {core}?",
        f"Why does this happen: {core}?",
        f"Troubleshoot {topic_text} on my Galaxy",
        f"Help with {topic_text}",
    ]
    distinct = list(dict.fromkeys(_sentence(item) for item in candidates if item.strip()))
    return distinct[:10]
```

- [ ] **Step 4: Run to verify they pass**

Run: `./.venv/Scripts/python -m pytest tests/test_relevance.py tests/test_variations.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add app/services/relevance.py app/services/variations.py tests/test_relevance.py tests/test_variations.py
```

---

### Task 6: Plan builder

**Files:**
- Create: `app/services/plan_builder.py`
- Test: `tests/test_plan_builder.py`

**Interfaces:**
- Consumes: `parse_sections`, `is_imperative` (Task 3); `KeyIndex`, `DUMMY_URI`, `tap_targets` (Task 4); `relevance` (Task 5); `generate_variations` (Task 5); `validate_plan` (Task 2); `ordered_values` (existing `app.services.action_ordering`).
- Produces: `PlanBuild(response: dict, query_variations: list[str], relevance: float, errors: tuple[str, ...])`; `PlanBuilder(catalog).build(query: str, content: str, title: str = "") -> PlanBuild | None`. `None` means "no relevant, usable steps". A `PlanBuild` with non-empty `errors` means a rule was broken and it must not be cached. `response` is `{"contexts": [Goal]}` in official-schema shape.

- [ ] **Step 1: Write the failing tests**

```python
"""End-to-end plan building over the twenty official rows."""

import re

import pytest

from app.models.official_schema import ContextDeeplinkResponse
from app.services.plan_builder import PlanBuilder

RANK = {"auto": 0, "manual": 1, "critical": 2}
GOAL = re.compile(r"^Follow these steps to perform this .+ (?:Troubleshooting|Configuration)$")
URL = re.compile(r"https?://|www\.", re.IGNORECASE)


@pytest.fixture(scope="module")
def builder(catalog):
    return PlanBuilder(catalog)


@pytest.fixture(scope="module")
def builds(builder, siis_rows):
    result = {}
    for row in siis_rows:
        siis = row["siis_response"]
        result[row["id"]] = builder.build(row["original_query"], siis["content"], siis["title"])
    return {row_id: build for row_id, build in result.items() if build is not None}


def _actions(build):
    return build.response["contexts"][0]["actions"]


def _groups(build):
    return [group for action in _actions(build) for group in action["stepGroups"]]


def test_most_rows_build_and_every_built_plan_is_rule_valid(builds):
    assert len(builds) >= 12
    for row_id, build in builds.items():
        assert build.errors == (), row_id


def test_built_plans_satisfy_the_official_schema(builds):
    for build in builds.values():
        ContextDeeplinkResponse.model_validate(build.response)


def test_goal_title_score_and_variations(builds):
    for build in builds.values():
        context = build.response["contexts"][0]
        assert GOAL.match(context["goal"])
        assert 2 <= len(context["title"].split()) <= 3
        assert 0.0 <= context["score"] <= 1.0
        assert 8 <= len(build.query_variations) <= 10


def test_actions_are_ordered_auto_manual_critical(builds):
    for build in builds.values():
        ranks = [RANK[action["category"]] for action in _actions(build)]
        assert ranks == sorted(ranks)


def test_only_auto_actions_carry_deeplinks(builds):
    for build in builds.values():
        for action in _actions(build):
            for group in action["stepGroups"]:
                assert (group["actionableDeeplink"] is not None) == (action["category"] == "auto")


def test_every_deeplink_is_verbatim_from_the_catalog(builds, catalog):
    actionable = {entry["deeplink"] for entry in catalog}
    validation = {entry["validation"]["deeplink"] for entry in catalog if entry.get("validation")}
    for build in builds.values():
        for group in _groups(build):
            if group["actionableDeeplink"]:
                assert group["actionableDeeplink"]["deeplink"] in actionable
            if group["validationDeeplink"]:
                assert group["validationDeeplink"]["deeplink"] in validation


def test_no_urls_in_any_plan_text(builds):
    for build in builds.values():
        context = build.response["contexts"][0]
        texts = [context["goal"], context["title"]]
        for action in context["actions"]:
            texts += [action["actionName"], action["description"]]
            texts += [step for group in action["stepGroups"] for step in group["steps"]]
        assert not any(URL.search(text) for text in texts)


def test_touchscreen_plan_maps_screens_exactly(builds, catalog_by_id):
    links = {g["actionableDeeplink"]["deeplink"] for g in _groups(builds["row_21"]) if g["actionableDeeplink"]}
    assert catalog_by_id["DL-0126"]["deeplink"] in links  # enable Touch sensitivity
    assert catalog_by_id["DL-0125"]["deeplink"] in links  # disable Touch sensitivity
    assert catalog_by_id["DL-0169"]["deeplink"] in links  # Navigation bar


def test_email_plan_links_wifi_first_and_ends_critical(builds, catalog_by_id):
    actions = _actions(builds["row_1"])
    group = actions[0]["stepGroups"][0]
    assert actions[0]["category"] == "auto"
    assert group["actionableDeeplink"]["deeplink"] == catalog_by_id["DL-0313"]["deeplink"]
    assert group["validationDeeplink"]["deeplink"] == catalog_by_id["DL-0313"]["validation"]["deeplink"]
    assert actions[-1]["category"] == "critical"


def test_unrelated_query_is_refused(builder, siis_rows):
    siis = siis_rows[1]["siis_response"]
    assert builder.build("best pasta recipe", siis["content"], siis["title"]) is None


def test_unindexed_settings_screen_uses_the_placeholder(builder):
    build = builder.build("check storage settings", "## Check storage\nGo to Settings. Tap Storage.", "Storage help")
    assert build is not None and build.errors == ()
    action = build.response["contexts"][0]["actions"][0]
    link = action["stepGroups"][0]["actionableDeeplink"]
    assert action["category"] == "auto"
    assert link["deeplink"] == "bixby://dummy_positive"
    assert link["description"] == "Opens the Storage Settings screen"
    assert link["message"] == "Open the Storage screen in Settings"


def test_building_is_deterministic(builder, siis_rows):
    siis = siis_rows[0]["siis_response"]
    first = builder.build(siis_rows[0]["original_query"], siis["content"], siis["title"])
    second = builder.build(siis_rows[0]["original_query"], siis["content"], siis["title"])
    assert first == second
```

- [ ] **Step 2: Run to verify they fail**

Run: `./.venv/Scripts/python -m pytest tests/test_plan_builder.py -q`
Expected: collection error, `ModuleNotFoundError: app.services.plan_builder`.

- [ ] **Step 3: Create `app/services/plan_builder.py`**

```python
"""Build a validated troubleshooting plan from a query and SIIS knowledge text.

Every step comes from the SIIS text; every deeplink comes verbatim from the
catalog (or is the documented placeholder). Nothing is generated by a model.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import re
from typing import Any

from app.services.action_ordering import ordered_values
from app.services.key_matcher import DUMMY_URI, KeyIndex, tap_targets
from app.services.plan_validator import validate_plan
from app.services.relevance import relevance
from app.services.siis_parser import Section, is_imperative, parse_sections
from app.services.variations import generate_variations

_WORD = re.compile(r"[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)*")
_SPLIT_NAME = re.compile(r"\s+(?:and|&)\s+|\s*/\s*")
_CRITICAL = re.compile(
    r"\b(?:factory\s+(?:data\s+)?reset|safe\s+mode|restart|reboot|clear\s+data|firmware|"
    r"recovery\s+mode|wipe|erase)\b",
    re.IGNORECASE,
)
_SETTINGS = re.compile(r"(?<!Quick )\bSettings\b")
_STOPWORDS = frozenset("a an the your my to of on for with in and or is are".split())
_TOPIC_STOP = _STOPWORDS | frozenset(
    "some things check first how use you can cannot samsung galaxy phone tablet".split()
)
_TOPIC_CUT = re.compile(r"\s+(?:on|when|in|for|if|not|does|do|is|are)\s+|\(")
_VALIDATION_FIELDS = ("deeplink", "key", "resultType", "condition", "value")


@dataclass(frozen=True)
class PlanBuild:
    """Outcome of one build: the response body, its paraphrases, and any rule errors."""

    response: dict[str, Any]
    query_variations: list[str]
    relevance: float
    errors: tuple[str, ...]


def _words(text: str) -> list[str]:
    return _WORD.findall(text)


def _cap(word: str) -> str:
    return word[:1].upper() + word[1:]


def _base(heading: str, steps: list[str]) -> str:
    return _SPLIT_NAME.split(heading)[0].strip() or " ".join(steps[0].split()[:4])


def _topic(title: str) -> str:
    head = _TOPIC_CUT.split(title)[0]
    words = [w for w in _words(head) if w.lower() not in _TOPIC_STOP][:3]
    return " ".join(_cap(w) for w in words) or "Device Issue"


def _title(topic: str) -> str:
    words = topic.split()
    if len(words) < 2:
        words.append("troubleshooting")
    return " ".join([_cap(words[0].lower()), *(w.lower() for w in words[1:])])


def _action_name(heading: str, steps: list[str]) -> str:
    return " ".join(_cap(w) for w in _words(_base(heading, steps))[:6]) or "Troubleshooting Step"


def _describe(heading: str, steps: list[str]) -> str:
    base = _base(heading, steps)
    core = [w.lower() for w in _words(base) if w.lower() not in _STOPWORDS][:3]
    lead = "It will help you" if is_imperative(base) else "It will help with"
    return f"{lead} " + " ".join(core or ["complete", "this", "step"])


def _catalog_link(entry: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "deeplink": entry["deeplink"],
        "description": entry["description"],
        "message": entry.get("message") or "",
        "originalType": entry.get("originalType"),
    }


def _validation_link(entry: Mapping[str, Any]) -> dict[str, Any] | None:
    validation = entry.get("validation")
    if not isinstance(validation, Mapping) or not validation.get("deeplink") or not validation.get("key"):
        return None
    return {field: validation[field] for field in _VALIDATION_FIELDS if field in validation}


def _placeholder_link(label: str) -> dict[str, Any]:
    return {
        "deeplink": DUMMY_URI,
        "description": f"Opens the {label} Settings screen",
        "message": f"Open the {label} screen in Settings",
        "originalType": "placeholder",
    }


def _build_action(section: Section, index: KeyIndex) -> dict[str, Any] | None:
    steps = list(section.steps)
    if not steps:
        return None
    critical = bool(_CRITICAL.search(" ".join([section.heading, *steps])))
    choice = None if critical else index.find(steps, section.body)
    group: dict[str, Any] = {"steps": steps, "actionableDeeplink": None, "validationDeeplink": None}
    if critical:
        category = "critical"
    elif choice is not None or any(_SETTINGS.search(step) for step in steps):
        category = "auto"
        if choice is not None:
            group["actionableDeeplink"] = _catalog_link(choice.entry)
            group["validationDeeplink"] = _validation_link(choice.entry)
        else:
            label = " ".join(next(iter(reversed(tap_targets(steps))), "relevant").split()[:2])
            group["actionableDeeplink"] = _placeholder_link(label)
    else:
        category = "manual"
    return {
        "actionName": _action_name(section.heading, steps),
        "description": _describe(section.heading, steps),
        "stepGroups": [group],
        "category": category,
    }


def _merge_same_screen(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fold adjacent actions that open the same screen into one action."""
    merged: list[dict[str, Any]] = []
    for action in actions:
        link = action["stepGroups"][0]["actionableDeeplink"]
        previous = merged[-1]["stepGroups"][-1]["actionableDeeplink"] if merged else None
        same = (
            link is not None
            and previous is not None
            and (link["deeplink"], link["message"]) == (previous["deeplink"], previous["message"])
        )
        if same:
            merged[-1]["stepGroups"].extend(action["stepGroups"])
        else:
            merged.append(action)
    return merged


class PlanBuilder:
    """Turn (query, SIIS text) into a validated plan or refuse."""

    def __init__(self, catalog: Iterable[Mapping[str, Any]]) -> None:
        self.catalog = list(catalog)
        self._index = KeyIndex(self.catalog)

    def build(self, query: str, content: str, title: str = "") -> PlanBuild | None:
        """Return a plan, or ``None`` when the text has no usable, relevant steps."""
        sections = parse_sections(content, title)
        article = " ".join(f"{s.heading} {s.body}" for s in sections)
        score = relevance(query, article, title)
        if score <= 0.0:
            return None
        actions = [a for s in sections if (a := _build_action(s, self._index)) is not None]
        if not actions:
            return None
        topic = _topic(title or sections[0].heading)
        response = {
            "contexts": [
                {
                    "goal": f"Follow these steps to perform this {topic} Troubleshooting",
                    "title": _title(topic),
                    "score": round(min(1.0, 0.5 + score), 2),
                    "actions": ordered_values(_merge_same_screen(actions)),
                }
            ]
        }
        variations = generate_variations(query, topic)
        result = validate_plan({**response, "query_variations": variations}, self.catalog)
        return PlanBuild(response, variations, score, result.errors)
```

- [ ] **Step 4: Run to verify they pass**

Run: `./.venv/Scripts/python -m pytest tests/test_plan_builder.py -q`
Expected: all pass. When run over the official rows, 17 of 20 build and rows 16, 17, and 20 are refused by the relevance gate; the tests require at least 12. If a plan has `errors`, print them (`build.errors`), fix the generator (for example a step matching the validator's multi-interaction regex), and never relax the validator.

- [ ] **Step 5: Commit**

```bash
git add app/services/plan_builder.py tests/test_plan_builder.py
```

---

### Task 7: Semantic plan cache

**Files:**
- Create: `app/services/plan_cache.py`
- Test: `tests/test_plan_cache.py`

**Interfaces:**
- Consumes: `validate_plan` (Task 2), `normalize_query` and `content_tokens` (Task 5), `EmbeddingModel` and `HashEmbeddingModel` and `cosine_similarity` from `app.retrieval.embeddings` (existing).
- Produces: `PlanCache(catalog, model: EmbeddingModel | None = None, threshold: float = 0.30)` with `add(entry_id, query, variations, response)` (raises `ValueError` if the plan breaks any rule), `lookup(query) -> CacheHit | None`, `entries() -> list[CacheEntry]`, `save(path)`, `PlanCache.load(path, catalog, **kwargs)`, `len(cache)`. `CacheHit(entry: CacheEntry, similarity: float, exact: bool)`; `CacheEntry(entry_id, query, variations: tuple[str, ...], response: dict)`.

- [ ] **Step 1: Write the failing tests**

```python
"""Only validated plans enter the cache; lookups are semantic and persistent."""

import copy
import json

import pytest

from app.services.plan_builder import PlanBuilder
from app.services.plan_cache import PlanCache


@pytest.fixture(scope="module")
def built(catalog, siis_rows):
    row = next(r for r in siis_rows if r["id"] == "row_2")
    siis = row["siis_response"]
    build = PlanBuilder(catalog).build(row["original_query"], siis["content"], siis["title"])
    assert build is not None and build.errors == ()
    return row["original_query"], build


def test_exact_query_hits_and_paraphrase_hits_semantically(catalog, built):
    query, build = built
    cache = PlanCache(catalog)
    cache.add("row_2", query, build.query_variations, build.response)
    exact = cache.lookup(query)
    assert exact.exact is True and exact.entry.entry_id == "row_2"
    paraphrase = cache.lookup("my phone screen is black and will not turn on")
    assert paraphrase is not None and paraphrase.exact is False


def test_unrelated_query_misses(catalog, built):
    query, build = built
    cache = PlanCache(catalog)
    cache.add("row_2", query, build.query_variations, build.response)
    assert cache.lookup("what is the best pasta recipe") is None


def test_invalid_plan_is_rejected_and_not_stored(catalog, built):
    query, build = built
    bad = copy.deepcopy(build.response)
    bad["contexts"][0]["goal"] = "Fix it"
    cache = PlanCache(catalog)
    with pytest.raises(ValueError):
        cache.add("row_2", query, build.query_variations, bad)
    assert len(cache) == 0


def test_save_and_load_round_trip(catalog, built, tmp_path):
    query, build = built
    cache = PlanCache(catalog)
    cache.add("row_2", query, build.query_variations, build.response)
    path = tmp_path / "cache.json"
    cache.save(path)
    loaded = PlanCache.load(path, catalog)
    assert len(loaded) == 1
    assert loaded.lookup(query).entry.response == build.response


def test_load_revalidates_every_entry(catalog, built, tmp_path):
    query, build = built
    cache = PlanCache(catalog)
    cache.add("row_2", query, build.query_variations, build.response)
    path = tmp_path / "cache.json"
    cache.save(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["entries"][0]["response"]["contexts"][0]["goal"] = "Fix it"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        PlanCache.load(path, catalog)
```

- [ ] **Step 2: Run to verify they fail**

Run: `./.venv/Scripts/python -m pytest tests/test_plan_cache.py -q`
Expected: collection error, `ModuleNotFoundError: app.services.plan_cache`.

- [ ] **Step 3: Create `app/services/plan_cache.py`**

```python
"""Persistent semantic cache of validated plans, keyed by query paraphrases.

Only plans that pass ``validate_plan`` can enter the cache, and every entry is
re-validated when a saved cache is loaded.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from app.retrieval.embeddings import EmbeddingModel, HashEmbeddingModel, cosine_similarity
from app.services.plan_validator import validate_plan
from app.services.relevance import content_tokens
from app.services.variations import normalize_query

SIMILARITY_THRESHOLD = 0.30
COSINE_WEIGHT = 0.5


@dataclass(frozen=True)
class CacheEntry:
    """One cached plan and the queries that key it."""

    entry_id: str
    query: str
    variations: tuple[str, ...]
    response: dict[str, Any]


@dataclass(frozen=True)
class CacheHit:
    """A lookup result with its similarity to the closest stored query."""

    entry: CacheEntry
    similarity: float
    exact: bool


@dataclass(frozen=True)
class _Key:
    normalized: str
    tokens: frozenset[str]
    vector: list[float]
    entry_id: str


def _plan_keys(response: Mapping[str, Any]) -> list[str]:
    """Extra lookup keys taken from the plan itself: its title and action names."""
    goal = response["contexts"][0]
    return [goal["title"], *(action["actionName"] for action in goal["actions"])]


class PlanCache:
    """In-memory semantic index over validated plans with JSON persistence."""

    def __init__(
        self,
        catalog: Iterable[Mapping[str, Any]],
        model: EmbeddingModel | None = None,
        threshold: float = SIMILARITY_THRESHOLD,
    ) -> None:
        self._catalog = list(catalog)
        self._model = model or HashEmbeddingModel()
        self.threshold = threshold
        self._entries: dict[str, CacheEntry] = {}
        self._keys: list[_Key] = []
        self._exact: dict[str, str] = {}

    def __len__(self) -> int:
        return len(self._entries)

    def entries(self) -> list[CacheEntry]:
        """Return every cached entry in insertion order."""
        return list(self._entries.values())

    def add(self, entry_id: str, query: str, variations: Iterable[str], response: dict[str, Any]) -> None:
        """Validate and store a plan; raise ``ValueError`` if it breaks any rule."""
        variations = tuple(variations)
        result = validate_plan({**response, "query_variations": list(variations)}, self._catalog)
        if not result.valid:
            raise ValueError("; ".join(result.errors))
        self._entries[entry_id] = CacheEntry(entry_id, query, variations, response)
        self._keys = [key for key in self._keys if key.entry_id != entry_id]
        self._exact = {k: v for k, v in self._exact.items() if v != entry_id}
        for text in (query, *variations, *_plan_keys(response)):
            normalized = normalize_query(text)
            if not normalized:
                continue
            self._exact.setdefault(normalized, entry_id)
            self._keys.append(
                _Key(normalized, frozenset(content_tokens(normalized)), self._model.embed(normalized), entry_id)
            )

    def lookup(self, query: str) -> CacheHit | None:
        """Return the closest cached plan at or above the similarity threshold."""
        normalized = normalize_query(query)
        if not normalized:
            return None
        exact_id = self._exact.get(normalized)
        if exact_id is not None:
            return CacheHit(self._entries[exact_id], 1.0, True)
        tokens = content_tokens(normalized)
        vector = self._model.embed(normalized)
        best_score, best_id = 0.0, None
        for key in self._keys:
            shared = len(tokens & key.tokens)
            overlap = max(shared / len(tokens), shared / len(key.tokens)) if tokens and key.tokens else 0.0
            cosine = max(0.0, cosine_similarity(vector, key.vector))
            score = COSINE_WEIGHT * cosine + (1 - COSINE_WEIGHT) * overlap
            if score > best_score:
                best_score, best_id = score, key.entry_id
        if best_id is None or best_score < self.threshold:
            return None
        return CacheHit(self._entries[best_id], round(best_score, 4), False)

    def save(self, path: Path) -> None:
        """Write all entries to ``path`` as JSON."""
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "entries": [
                {"id": e.entry_id, "query": e.query, "variations": list(e.variations), "response": e.response}
                for e in self._entries.values()
            ]
        }
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: Path, catalog: Iterable[Mapping[str, Any]], **kwargs: Any) -> "PlanCache":
        """Read a saved cache, re-validating every entry."""
        cache = cls(catalog, **kwargs)
        for item in json.loads(path.read_text(encoding="utf-8"))["entries"]:
            cache.add(item["id"], item["query"], item["variations"], item["response"])
        return cache
```

- [ ] **Step 4: Run to verify they pass**

Run: `./.venv/Scripts/python -m pytest tests/test_plan_cache.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add app/services/plan_cache.py tests/test_plan_cache.py
```

---

### Task 8: Troubleshooting service and warm-up script

**Files:**
- Create: `app/services/troubleshooting_service.py`, `scripts/build_plans.py`
- Create: `tests/fixtures/paraphrases.json`
- Test: `tests/test_troubleshooting_service.py`

**Interfaces:**
- Consumes: `PlanBuilder` (Task 6), `PlanCache` (Task 7), `generate_variations` (Task 5), `load_catalog` and `load_siis_rows` (Task 1), `PROCESSED_DIR` (Task 1).
- Produces: `TroubleshootingService(catalog, cache: PlanCache | None = None)` with `warm(rows) -> list[WarmResult]` and `troubleshoot(query: str, siis_response: str | None = None) -> dict`. `WarmResult(row_id, status: "cached" | "gated" | "invalid", build)`. The body is `{"query", "query_variations", "response": {"contexts": [...]}, "meta": {"latency_ms", "cache_hit", "model", "cost_usd", "fallback"?}}`. `build_default_service(cache_path: Path | None = None, rebuild: bool = False) -> TroubleshootingService`; `DEFAULT_CACHE_PATH`; `MODEL_ID = "rules-v1"`.

- [ ] **Step 1: Write the fixture and the failing tests**

`tests/fixtures/paraphrases.json` (held-out phrasings written before measuring; never edit them to make a test pass):

```json
{
  "positives": [
    {"expect": "Email server", "query": "I can't open my email and the app says the server is not responding"},
    {"expect": "Email server", "query": "gmail keeps failing to sync on my galaxy tablet"},
    {"expect": "Blank black display", "query": "my phone screen is black and will not turn on"},
    {"expect": "Blank black display", "query": "screen is completely dark, nothing shows up when I press the power button"},
    {"expect": "Access phone's data", "query": "how do I back up my data when the screen is not working"},
    {"expect": "Access phone's data", "query": "phone screen is smashed and I can't see anything, how do I get my photos off"},
    {"expect": "Cracked bleeding screen", "query": "my phone screen is cracked and broken"},
    {"expect": "Cracked bleeding screen", "query": "there are lines and dead pixels on my display after I dropped it"},
    {"expect": "Touchscreen issues", "query": "touchscreen is laggy and not responding to my taps"},
    {"expect": "Touchscreen issues", "query": "phone does not react when I touch the screen"},
    {"expect": "Transfer secure folder", "query": "how do I transfer data using smart switch with a QR code"},
    {"expect": "Transfer secure folder", "query": "smart switch wireless transfer from old phone to new phone"},
    {"expect": "Screen flickers", "query": "screen flickers when I record video with the camera"},
    {"expect": "Screen flickers", "query": "camera video has black bars and flicker"}
  ],
  "negatives": [
    "what is the best pasta recipe",
    "how tall is mount everest",
    "book me a flight to paris",
    "play some music",
    "what is the weather tomorrow",
    "translate hello into french"
  ]
}
```

`tests/test_troubleshooting_service.py`:

```python
"""Online path: cache hits, fallbacks, cold builds, determinism."""

import json
from pathlib import Path

import pytest

from app.services.plan_cache import PlanCache
from app.services.troubleshooting_service import MODEL_ID, TroubleshootingService, build_default_service

FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "paraphrases.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def service(catalog, siis_rows):
    instance = TroubleshootingService(catalog)
    instance.warm(siis_rows)
    return instance


def test_warm_caches_most_rows_and_reports_the_rest(catalog, siis_rows):
    results = TroubleshootingService(catalog).warm(siis_rows)
    statuses = [result.status for result in results]
    assert statuses.count("cached") >= 12
    assert "invalid" not in statuses


def test_exact_original_query_is_a_cache_hit(service, siis_rows):
    row = next(r for r in siis_rows if r["id"] == "row_2")
    body = service.troubleshoot(row["original_query"])
    assert body["meta"]["cache_hit"] is True
    assert body["meta"]["model"] == MODEL_ID and body["meta"]["cost_usd"] == 0.0
    assert "fallback" not in body["meta"]
    assert len(body["response"]["contexts"]) == 1
    assert 8 <= len(body["query_variations"]) <= 10


def test_every_cached_plan_answers_its_own_query(service, siis_rows):
    cached_ids = {entry.entry_id for entry in service.cache.entries()}
    for row in siis_rows:
        if row["id"] in cached_ids:
            assert service.troubleshoot(row["original_query"])["response"]["contexts"], row["id"]


@pytest.mark.parametrize("query", FIXTURES["negatives"])
def test_unrelated_queries_fall_back_to_no_match(service, query):
    body = service.troubleshoot(query)
    assert body["response"] == {"contexts": []}
    assert body["meta"]["fallback"] == "no_match"
    assert body["meta"]["cache_hit"] is False


def test_empty_cache_reports_no_siis_context(catalog):
    body = TroubleshootingService(catalog).troubleshoot("screen is blank")
    assert body["response"] == {"contexts": []}
    assert body["meta"]["fallback"] == "no_siis_context"


def test_cold_path_builds_from_supplied_siis_text_then_caches_it(catalog):
    service = TroubleshootingService(catalog)
    siis = "## Adjust brightness\nGo to Settings.\nTap Display.\nTap Brightness.\n"
    cold = service.troubleshoot("adjust screen brightness", siis_response=siis)
    assert cold["response"]["contexts"] and cold["meta"]["cache_hit"] is False
    warm = service.troubleshoot("adjust screen brightness")
    assert warm["meta"]["cache_hit"] is True
    assert warm["response"] == cold["response"]


def test_supplied_siis_text_with_nothing_relevant_is_no_match(catalog):
    body = TroubleshootingService(catalog).troubleshoot("best pasta recipe", siis_response="## Charge\nConnect the charger.")
    assert body["response"] == {"contexts": []}
    assert body["meta"]["fallback"] == "no_match"


def test_identical_queries_give_identical_plans(service):
    query = "my phone screen is black and will not turn on"
    first, second = service.troubleshoot(query), service.troubleshoot(query)
    assert first["response"] == second["response"]
    assert first["query_variations"] == second["query_variations"]


def test_default_service_warms_then_reloads_from_disk(tmp_path):
    path = tmp_path / "plan_cache.json"
    first = build_default_service(cache_path=path)
    assert path.exists() and len(first.cache) >= 12
    second = build_default_service(cache_path=path)
    assert len(second.cache) == len(first.cache)
    assert isinstance(second.cache, PlanCache)
```

- [ ] **Step 2: Run to verify they fail**

Run: `./.venv/Scripts/python -m pytest tests/test_troubleshooting_service.py -q`
Expected: collection error, `ModuleNotFoundError: app.services.troubleshooting_service`.

- [ ] **Step 3: Create the service and the warm-up script**

`app/services/troubleshooting_service.py`:

```python
"""Online path: semantic cache lookup, cold build from SIIS text, and fallbacks."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import time
from typing import Any

from app.config import PROCESSED_DIR
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


def build_default_service(cache_path: Path | None = None, rebuild: bool = False) -> TroubleshootingService:
    """Load the saved cache, or warm it from the official SIIS rows and save it."""
    path = cache_path or DEFAULT_CACHE_PATH
    catalog = load_catalog()
    cache = PlanCache.load(path, catalog) if path.exists() and not rebuild else None
    service = TroubleshootingService(catalog, cache)
    if len(service.cache) == 0:
        service.warm(load_siis_rows())
        service.cache.save(path)
    return service
```

`scripts/build_plans.py`:

```python
"""Warm the plan cache from the official SIIS rows and print what happened to each row."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.catalog import load_catalog, load_siis_rows  # noqa: E402
from app.services.troubleshooting_service import DEFAULT_CACHE_PATH, TroubleshootingService  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_CACHE_PATH, help="where to write the cache")
    args = parser.parse_args()
    service = TroubleshootingService(load_catalog())
    for result in service.warm(load_siis_rows()):
        detail = ""
        if result.build is not None:
            context = result.build.response["contexts"][0]
            categories = [action["category"] for action in context["actions"]]
            detail = f"{context['title']!r} relevance={result.build.relevance:.2f} actions={categories}"
            detail += "".join(f"\n            ! {error}" for error in result.build.errors)
        print(f"{result.row_id:8}{result.status:9}{detail}")
    service.cache.save(args.out)
    print(f"saved {len(service.cache)} plans to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run to verify they pass, then run the script**

Run: `./.venv/Scripts/python -m pytest tests/test_troubleshooting_service.py -q`
Expected: all pass.

Run: `./.venv/Scripts/python scripts/build_plans.py`
Expected: one line per row (`cached` or `gated`), no `invalid`, ending `saved 17 plans to ...plan_cache.json`. Rows 16, 17, and 20 are `gated`.

- [ ] **Step 5: Commit**

```bash
git add app/services/troubleshooting_service.py scripts/build_plans.py tests/fixtures tests/test_troubleshooting_service.py
```

---

### Task 9: REST API

Replaces the placeholder route and removes the old query-driven engine (it invented steps and violates "no hallucinated steps").

**Files:**
- Modify: `app/main.py`, `app/api/routes.py`, `app/models/schemas.py`
- Delete: `app/services/troubleshooting_engine.py`, `tests/test_troubleshooting_engine.py`
- Replace: `tests/test_api.py`

**Interfaces:**
- Consumes: `build_default_service` and `TroubleshootingService.troubleshoot` (Task 8).
- Produces: `POST /v1/troubleshoot` (body `{"query": str, "siis_response": str | null}`, returns the service body); `GET /health` returns 200 `{"status": "ok"}` once the service exists and 503 `{"status": "initializing"}` otherwise. The service lives at `app.state.service`.

- [ ] **Step 1: Write the failing tests**

Replace all of `tests/test_api.py`:

```python
"""HTTP contract tests (PDF section 5)."""

import json

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.models.official_schema import ContextDeeplinkResponse


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    path = tmp_path_factory.mktemp("cache") / "plan_cache.json"
    original = main.build_default_service
    main.build_default_service = lambda: original(cache_path=path)
    with TestClient(main.app) as test_client:
        yield test_client
    main.build_default_service = original


def test_health_is_ok_when_initialised(client):
    response = client.get("/health")
    assert response.status_code == 200 and response.json() == {"status": "ok"}


def test_health_is_503_before_initialisation(client):
    service = main.app.state.service
    main.app.state.service = None
    try:
        response = TestClient(main.app).get("/health")
    finally:
        main.app.state.service = service
    assert response.status_code == 503 and response.json() == {"status": "initializing"}


def test_troubleshoot_returns_a_plan_as_pure_json(client, siis_rows):
    query = next(r for r in siis_rows if r["id"] == "row_21")["original_query"]
    response = client.post("/v1/troubleshoot", json={"query": query})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.text.lstrip().startswith("{") and "```" not in response.text
    body = response.json()
    assert set(body) == {"query", "query_variations", "response", "meta"}
    ContextDeeplinkResponse.model_validate(body["response"])
    assert body["meta"]["cache_hit"] is True


def test_unrelated_query_returns_empty_contexts_and_fallback(client):
    body = client.post("/v1/troubleshoot", json={"query": "what is the best pasta recipe"}).json()
    assert body["response"] == {"contexts": []}
    assert body["meta"]["fallback"] == "no_match"


def test_supplied_siis_response_is_used(client):
    siis = "## Adjust brightness\nGo to Settings.\nTap Display.\nTap Brightness.\n"
    body = client.post("/v1/troubleshoot", json={"query": "adjust screen brightness", "siis_response": siis}).json()
    assert body["response"]["contexts"] and body["meta"]["cache_hit"] is False


def test_empty_query_is_rejected(client):
    assert client.post("/v1/troubleshoot", json={"query": ""}).status_code == 422
    assert client.post("/v1/troubleshoot", json={}).status_code == 422


def test_response_has_no_urls_outside_deeplinks(client, siis_rows):
    query = next(r for r in siis_rows if r["id"] == "row_14")["original_query"]
    text = json.dumps(client.post("/v1/troubleshoot", json={"query": query}).json()["response"])
    assert "http" not in text and "www." not in text
```

- [ ] **Step 2: Run to verify it fails**

Run: `./.venv/Scripts/python -m pytest tests/test_api.py -q`
Expected: FAIL (`AttributeError: module 'app.main' has no attribute 'build_default_service'`).

- [ ] **Step 3: Implement**

`app/models/schemas.py`: replace the `TroubleshootRequest` and `PlaceholderTroubleshootResponse` classes with:

```python
class TroubleshootRequest(BaseModel):
    """Body of POST /v1/troubleshoot (PDF section 5)."""

    query: str = Field(min_length=1, description="User-provided troubleshooting query.")
    siis_response: str | None = Field(
        default=None, description="Optional raw SIIS knowledge text to build a plan from."
    )
```

`app/api/routes.py` (whole file):

```python
"""HTTP routes for the troubleshooting API."""

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app.models.schemas import TroubleshootRequest

router = APIRouter(tags=["troubleshooting"])


@router.post("/troubleshoot")
def troubleshoot(payload: TroubleshootRequest, request: Request) -> dict[str, Any]:
    """Process a customer complaint and return an actionable plan."""
    service = getattr(request.app.state, "service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Service is initializing")
    return service.troubleshoot(payload.query, payload.siis_response)
```

`app/main.py` (whole file):

```python
"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.services.troubleshooting_service import build_default_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Build the service (cache, embedder, indexes) before serving traffic."""
    app.state.service = build_default_service()
    yield
    app.state.service = None


app = FastAPI(title="Smart Guided Troubleshooting Engine", lifespan=lifespan)
app.include_router(router, prefix="/v1")


@app.get("/health")
def health(request: Request):
    """Return 200 only once the caching layer and indexes are initialised."""
    if getattr(request.app.state, "service", None) is None:
        return JSONResponse({"status": "initializing"}, status_code=503)
    return {"status": "ok"}
```

Remove the old engine and its tests, then check nothing else imported them:

```bash
git rm app/services/troubleshooting_engine.py tests/test_troubleshooting_engine.py
```

Run `grep -rn "troubleshooting_engine\|PlaceholderTroubleshootResponse" app scripts tests`. Expected: no output. If a script such as `scripts/benchmark.py` or `scripts/test_query_enrichment.py` still imports the old engine, replace that import with `TroubleshootingService` (Task 8) or delete the dead lines.

- [ ] **Step 4: Run the whole suite**

Run: `./.venv/Scripts/python -m pytest -q`
Expected: all pass.

Run the server and check by hand:

```bash
./.venv/Scripts/python -m uvicorn app.main:app --port 8000
```

In a second terminal: `curl -s localhost:8000/health` should print `{"status":"ok"}`, and:

```bash
curl -s -X POST localhost:8000/v1/troubleshoot -H "Content-Type: application/json" -d "{\"query\": \"my phone screen is cracked\"}"
```

should print a JSON plan with `"cache_hit": true`. Stop the server.

- [ ] **Step 5: Commit**

```bash
git add -A app tests
```

---

### Task 10: Frontend scaffold, API client, and simulator logic

**Files:**
- Create: `frontend/package.json`, `frontend/tsconfig.json`, `frontend/vite.config.ts`, `frontend/index.html`
- Create: `frontend/src/setupTests.ts`, `frontend/src/types.ts`, `frontend/src/api.ts`, `frontend/src/simulator.ts`
- Test: `frontend/src/simulator.test.ts`
- Delete: `frontend/.gitkeep`

**Interfaces:**
- Produces: types in `types.ts` (`Goal`, `Action`, `StepGroup`, `ActionableDeeplink`, `ValidationDeeplink`, `Meta`, `TroubleshootResponse`); `troubleshoot(query: string, signal?: AbortSignal): Promise<TroubleshootResponse>`; `openDeeplink(link: ActionableDeeplink, validation?: ValidationDeeplink | null): SimScreen` where `SimScreen = { uri: string; title: string; kind: "toggle" | "page" | "slider"; on: boolean | null; verifiedKey: string | null; note: string }`.

- [ ] **Step 1: Create the project files**

`frontend/package.json`:

```json
{
  "name": "prism-troubleshooting-chat",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc --noEmit && vite build",
    "test": "vitest run"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  },
  "devDependencies": {
    "@testing-library/dom": "^10.4.0",
    "@testing-library/jest-dom": "^6.4.8",
    "@testing-library/react": "^16.0.0",
    "@testing-library/user-event": "^14.5.2",
    "@types/react": "^18.3.3",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.1",
    "jsdom": "^24.1.1",
    "typescript": "^5.5.4",
    "vite": "^5.4.0",
    "vitest": "^2.0.5"
  }
}
```

`frontend/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "skipLibCheck": true,
    "noEmit": true,
    "isolatedModules": true,
    "types": ["vitest/globals", "@testing-library/jest-dom"]
  },
  "include": ["src", "vite.config.ts"]
}
```

`frontend/vite.config.ts`:

```ts
/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/v1": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/setupTests.ts"],
  },
});
```

`frontend/index.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Galaxy Troubleshooter</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

`frontend/src/setupTests.ts`:

```ts
import "@testing-library/jest-dom/vitest";
```

`frontend/src/types.ts`:

```ts
export interface ActionableDeeplink {
  deeplink: string;
  description: string;
  message?: string | null;
  originalType?: string | null;
}

export interface ValidationDeeplink {
  deeplink: string;
  key: string;
  resultType?: string | null;
  condition?: string | null;
  value?: string | null;
}

export interface StepGroup {
  steps: string[];
  actionableDeeplink?: ActionableDeeplink | null;
  validationDeeplink?: ValidationDeeplink | null;
}

export type Category = "auto" | "manual" | "critical";

export interface Action {
  actionName: string;
  description: string;
  stepGroups: StepGroup[];
  category: Category;
}

export interface Goal {
  goal: string;
  title: string;
  score: number;
  actions: Action[];
}

export interface Meta {
  latency_ms: number;
  cache_hit: boolean;
  model: string;
  cost_usd: number;
  fallback?: string;
}

export interface TroubleshootResponse {
  query: string;
  query_variations: string[];
  response: { contexts: Goal[] };
  meta: Meta;
}
```

`frontend/src/api.ts`:

```ts
import type { TroubleshootResponse } from "./types";

export async function troubleshoot(query: string, signal?: AbortSignal): Promise<TroubleshootResponse> {
  const response = await fetch("/v1/troubleshoot", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query }),
    signal,
  });
  if (!response.ok) {
    throw new Error(`The engine returned an error (${response.status}).`);
  }
  return (await response.json()) as TroubleshootResponse;
}
```

- [ ] **Step 2: Write the failing test**

`frontend/src/simulator.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { openDeeplink } from "./simulator";

const base = { deeplink: "bixby://masked/act/14eb42b895", description: "d" };

describe("openDeeplink", () => {
  it("turns a toggle on for onURL and names the setting", () => {
    const screen = openDeeplink({ ...base, message: "Enable Touch sensitivity", originalType: "onURL" });
    expect(screen).toMatchObject({ title: "Touch sensitivity", kind: "toggle", on: true, note: "Turned on" });
  });

  it("turns a toggle off for offURL", () => {
    const screen = openDeeplink({ ...base, message: "Disable Touch sensitivity", originalType: "offURL" });
    expect(screen).toMatchObject({ kind: "toggle", on: false, note: "Turned off" });
  });

  it("opens a plain page for onClickURL", () => {
    const screen = openDeeplink({ ...base, message: "View Navigation bar", originalType: "onClickURL" });
    expect(screen).toMatchObject({ title: "Navigation bar", kind: "page", on: null, note: "Opened" });
  });

  it("shows a slider for updateURL", () => {
    const screen = openDeeplink({ ...base, message: "Adjust Brightness", originalType: "updateURL" });
    expect(screen).toMatchObject({ title: "Brightness", kind: "slider", note: "Adjusted" });
  });

  it("carries the validation label and the untouched URI", () => {
    const screen = openDeeplink(
      { ...base, message: "View Wi-Fi", originalType: "onClickURL" },
      { deeplink: "bixby://masked/val/x", key: "Wi-Fi" },
    );
    expect(screen.verifiedKey).toBe("Wi-Fi");
    expect(screen.uri).toBe("bixby://masked/act/14eb42b895");
  });

  it("falls back to the description, then to Settings, when there is no message", () => {
    expect(openDeeplink({ ...base, description: "Opens the Storage Settings screen", originalType: "placeholder" }).title)
      .toBe("Storage Settings screen");
    expect(openDeeplink({ deeplink: "bixby://x", description: "", message: "" }).title).toBe("Settings");
  });
});
```

- [ ] **Step 3: Install and run to verify it fails**

```bash
git rm -f frontend/.gitkeep
cd frontend && npm install && npm test
```

Expected: FAIL, `Failed to resolve import "./simulator"`.

- [ ] **Step 4: Create `frontend/src/simulator.ts`**

```ts
import type { ActionableDeeplink, ValidationDeeplink } from "./types";

export type ScreenKind = "toggle" | "page" | "slider";

export interface SimScreen {
  uri: string;
  title: string;
  kind: ScreenKind;
  on: boolean | null;
  verifiedKey: string | null;
  note: string;
}

const VERB_PREFIX = /^(?:view|enables?|disables?|adjust|increase|check|opens?|sets?)\s+(?:the\s+)?/i;

/** Pure model of what a deeplink does on a Galaxy Settings screen. The URI is carried, never navigated to. */
export function openDeeplink(link: ActionableDeeplink, validation?: ValidationDeeplink | null): SimScreen {
  const type = link.originalType ?? "";
  const title = (link.message || link.description).replace(VERB_PREFIX, "").trim() || "Settings";
  const kind: ScreenKind = type === "onURL" || type === "offURL" ? "toggle" : type === "updateURL" ? "slider" : "page";
  const on = type === "onURL" ? true : type === "offURL" ? false : null;
  const note = kind === "toggle" ? (on ? "Turned on" : "Turned off") : kind === "slider" ? "Adjusted" : "Opened";
  return { uri: link.deeplink, title, kind, on, verifiedKey: validation?.key ?? null, note };
}
```

- [ ] **Step 5: Run to verify it passes, then commit**

Run (in `frontend/`): `npm test`
Expected: 6 passed.

```bash
```

---

### Task 11: Chat, plan card, and phone simulator

**Files:**
- Create: `frontend/src/PlanCard.tsx`, `frontend/src/PhoneSimulator.tsx`, `frontend/src/App.tsx`, `frontend/src/main.tsx`, `frontend/src/styles.css`
- Test: `frontend/src/PlanCard.test.tsx`, `frontend/src/App.test.tsx`

**Interfaces:**
- Consumes: `troubleshoot` (`api.ts`), `openDeeplink` and `SimScreen` (`simulator.ts`), types (`types.ts`).
- Produces: `PlanCard({ goal, activeUri, onOpen })` where `onOpen(link: ActionableDeeplink, validation: ValidationDeeplink | null | undefined)`; `PhoneSimulator({ screen: SimScreen | null })`; default export `App`.

- [ ] **Step 1: Write the failing tests**

`frontend/src/PlanCard.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { PlanCard } from "./PlanCard";
import type { Goal } from "./types";

const link = {
  deeplink: "bixby://masked/act/14eb42b895",
  description: "Enables touch sensitivity via device Settings on the device.",
  message: "Enable Touch sensitivity",
  originalType: "onURL",
};
const validation = { deeplink: "bixby://masked/val/6451858b28", key: "Touch sensitivity", resultType: "boolean", condition: "equal", value: "True" };

const goal: Goal = {
  goal: "Follow these steps to perform this Touchscreen Issues Troubleshooting",
  title: "Touchscreen issues",
  score: 0.9,
  actions: [
    { actionName: "Touch Sensitivity Setting", description: "It will help with touch sensitivity setting", category: "auto",
      stepGroups: [{ steps: ["Go to Settings.", "Tap Display."], actionableDeeplink: link, validationDeeplink: validation }] },
    { actionName: "Charger Issues", description: "It will help with charger issues", category: "manual",
      stepGroups: [{ steps: ["Try using a different, undamaged charger."], actionableDeeplink: null, validationDeeplink: null }] },
    { actionName: "Factory Data Reset", description: "It will help you factory data reset", category: "critical",
      stepGroups: [{ steps: ["Tap Reset."], actionableDeeplink: null, validationDeeplink: null }] },
  ],
};

describe("PlanCard", () => {
  it("shows the goal, every action, and its numbered steps", () => {
    render(<PlanCard goal={goal} activeUri={null} onOpen={() => {}} />);
    expect(screen.getByText(goal.goal)).toBeInTheDocument();
    expect(screen.getByText("Touch Sensitivity Setting")).toBeInTheDocument();
    expect(screen.getByText("Tap Display.")).toBeInTheDocument();
    expect(screen.getByText("auto")).toBeInTheDocument();
    expect(screen.getByText("manual")).toBeInTheDocument();
    expect(screen.getByText("critical")).toBeInTheDocument();
  });

  it("offers Open only on actions that carry a deeplink, and reports it with its validation", async () => {
    const onOpen = vi.fn();
    render(<PlanCard goal={goal} activeUri={null} onOpen={onOpen} />);
    const buttons = screen.getAllByRole("button");
    expect(buttons).toHaveLength(1);
    await userEvent.click(screen.getByRole("button", { name: "Open Enable Touch sensitivity" }));
    expect(onOpen).toHaveBeenCalledWith(link, validation);
  });

  it("warns before a critical action", () => {
    render(<PlanCard goal={goal} activeUri={null} onOpen={() => {}} />);
    expect(screen.getByText(/back up your data first/i)).toBeInTheDocument();
  });

  it("marks the open step as pressed", () => {
    render(<PlanCard goal={goal} activeUri={link.deeplink} onOpen={() => {}} />);
    expect(screen.getByRole("button", { name: "Open Enable Touch sensitivity" })).toHaveAttribute("aria-pressed", "true");
  });
});
```

`frontend/src/App.test.tsx`:

```tsx
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

const plan = {
  query: "touch is laggy",
  query_variations: ["a", "b", "c", "d", "e", "f", "g", "h"],
  response: {
    contexts: [{
      goal: "Follow these steps to perform this Touchscreen Issues Troubleshooting",
      title: "Touchscreen issues",
      score: 0.9,
      actions: [{
        actionName: "Touch Sensitivity Setting",
        description: "It will help with touch sensitivity setting",
        category: "auto",
        stepGroups: [{
          steps: ["Go to Settings.", "Tap Display."],
          actionableDeeplink: { deeplink: "bixby://masked/act/14eb42b895", description: "d", message: "Enable Touch sensitivity", originalType: "onURL" },
          validationDeeplink: { deeplink: "bixby://masked/val/6451858b28", key: "Touch sensitivity" },
        }],
      }],
    }],
  },
  meta: { latency_ms: 12, cache_hit: true, model: "rules-v1", cost_usd: 0 },
};

function mockFetch(body: unknown, ok = true) {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok, status: ok ? 200 : 500, json: async () => body }));
}

beforeEach(() => mockFetch(plan));
afterEach(() => vi.unstubAllGlobals());

async function send(text: string) {
  await userEvent.type(screen.getByLabelText("Describe your problem"), text);
  await userEvent.click(screen.getByRole("button", { name: "Send" }));
}

describe("App", () => {
  it("sends the message, renders the plan and its meta strip", async () => {
    render(<App />);
    await send("touch is laggy");
    expect(await screen.findByText(plan.response.contexts[0].goal)).toBeInTheDocument();
    expect(screen.getByText(/12 ms/)).toBeInTheDocument();
    expect(screen.getByText(/cache hit/)).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith("/v1/troubleshoot", expect.objectContaining({ method: "POST" }));
  });

  it("drives the phone simulator from the Open button", async () => {
    render(<App />);
    await send("touch is laggy");
    await userEvent.click(await screen.findByRole("button", { name: "Open Enable Touch sensitivity" }));
    const phone = screen.getByLabelText("Phone simulator");
    expect(within(phone).getByText("Touch sensitivity")).toBeInTheDocument();
    expect(within(phone).getByText("Turned on")).toBeInTheDocument();
    expect(within(phone).getByText(/Verified: Touch sensitivity/)).toBeInTheDocument();
  });

  it("explains an empty result", async () => {
    mockFetch({ ...plan, response: { contexts: [] }, meta: { ...plan.meta, fallback: "no_match", cache_hit: false } });
    render(<App />);
    await send("best pasta recipe");
    expect(await screen.findByText(/couldn't find a verified fix/i)).toBeInTheDocument();
  });

  it("shows a friendly error when the engine is unreachable", async () => {
    mockFetch({}, false);
    render(<App />);
    await send("touch is laggy");
    expect(await screen.findByRole("alert")).toHaveTextContent(/engine/i);
  });
});
```

- [ ] **Step 2: Run to verify they fail**

Run (in `frontend/`): `npm test`
Expected: FAIL, imports of `./PlanCard` and `./App` cannot be resolved.

- [ ] **Step 3: Create the components**

`frontend/src/PlanCard.tsx`:

```tsx
import type { Action, ActionableDeeplink, Goal, ValidationDeeplink } from "./types";

type OpenHandler = (link: ActionableDeeplink, validation: ValidationDeeplink | null | undefined) => void;

interface PlanCardProps {
  goal: Goal;
  activeUri: string | null;
  onOpen: OpenHandler;
}

function ActionItem({ action, activeUri, onOpen }: { action: Action; activeUri: string | null; onOpen: OpenHandler }) {
  return (
    <li className={`action action--${action.category}`}>
      <header className="action__head">
        <span className={`badge badge--${action.category}`}>{action.category}</span>
        <h4 className="action__name">{action.actionName}</h4>
      </header>
      <p className="action__desc">{action.description}</p>
      {action.category === "critical" && (
        <p className="action__warn">This step is disruptive. Back up your data first.</p>
      )}
      {action.stepGroups.map((group, index) => {
        const link = group.actionableDeeplink;
        return (
          <div className="group" key={index}>
            <ol className="steps">
              {group.steps.map((step, stepIndex) => (
                <li key={stepIndex}>{step}</li>
              ))}
            </ol>
            {link && (
              <button
                type="button"
                className="open"
                aria-label={`Open ${link.message || action.actionName}`}
                aria-pressed={activeUri === link.deeplink}
                onClick={() => onOpen(link, group.validationDeeplink)}
              >
                Open
              </button>
            )}
          </div>
        );
      })}
    </li>
  );
}

export function PlanCard({ goal, activeUri, onOpen }: PlanCardProps) {
  return (
    <article className="plan">
      <h3 className="plan__goal">{goal.goal}</h3>
      <ol className="plan__actions">
        {goal.actions.map((action, index) => (
          <ActionItem key={`${index}-${action.actionName}`} action={action} activeUri={activeUri} onOpen={onOpen} />
        ))}
      </ol>
    </article>
  );
}
```

`frontend/src/PhoneSimulator.tsx`:

```tsx
import type { SimScreen } from "./simulator";

export function PhoneSimulator({ screen }: { screen: SimScreen | null }) {
  return (
    <section className="phone" aria-label="Phone simulator">
      <div className="phone__frame">
        <div className="phone__status">
          <span>9:41</span>
          <span>5G</span>
        </div>
        <div className="phone__screen">
          <h2 className="phone__app">Settings</h2>
          {screen === null ? (
            <p className="phone__empty">Press Open on a step and the screen it points to appears here.</p>
          ) : (
            <div key={screen.uri} className="phone__panel">
              <h3 className="phone__title">{screen.title}</h3>
              {screen.kind === "toggle" && (
                <label className="switch">
                  <input type="checkbox" role="switch" checked={screen.on === true} readOnly aria-label={screen.title} />
                  <span className="switch__track" />
                </label>
              )}
              {screen.kind === "slider" && <input type="range" className="slider" defaultValue={60} aria-label={screen.title} />}
              <p className="phone__note">{screen.note}</p>
              {screen.verifiedKey && <p className="phone__verified">Verified: {screen.verifiedKey}</p>}
              <code className="phone__uri">{screen.uri}</code>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
```

`frontend/src/App.tsx`:

```tsx
import { FormEvent, useEffect, useRef, useState } from "react";
import { troubleshoot } from "./api";
import { PhoneSimulator } from "./PhoneSimulator";
import { PlanCard } from "./PlanCard";
import { openDeeplink, type SimScreen } from "./simulator";
import type { TroubleshootResponse } from "./types";

type Message =
  | { id: number; role: "user"; text: string }
  | { id: number; role: "bot"; data: TroubleshootResponse }
  | { id: number; role: "error"; text: string };

const EXAMPLES = [
  "My screen is cracked and flickers",
  "Touch responses are laggy",
  "Screen stays black when I turn it on",
];

function MetaStrip({ data }: { data: TroubleshootResponse }) {
  const { latency_ms, cache_hit, model, cost_usd } = data.meta;
  return (
    <p className="meta">
      {latency_ms} ms · {cache_hit ? "cache hit" : "cache miss"} · {model} · ${cost_usd.toFixed(2)}
    </p>
  );
}

export default function App() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [screen, setScreen] = useState<SimScreen | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const nextId = useRef(1);

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ behavior: "smooth", block: "end" });
  }, [messages, busy]);

  async function send(text: string) {
    const query = text.trim();
    if (!query || busy) return;
    setDraft("");
    setBusy(true);
    setMessages((current) => [...current, { id: nextId.current++, role: "user", text: query }]);
    try {
      const data = await troubleshoot(query);
      setMessages((current) => [...current, { id: nextId.current++, role: "bot", data }]);
    } catch (error) {
      const text = error instanceof Error ? error.message : "The engine could not be reached.";
      setMessages((current) => [...current, { id: nextId.current++, role: "error", text }]);
    } finally {
      setBusy(false);
    }
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    void send(draft);
  }

  return (
    <div className="app">
      <main className="chat">
        <header className="chat__head">
          <h1>Galaxy Troubleshooter</h1>
          <p>Describe what's wrong in your own words. You'll get an ordered plan you can open step by step.</p>
        </header>

        <div className="thread" aria-live="polite">
          {messages.length === 0 && (
            <div className="examples">
              {EXAMPLES.map((example) => (
                <button key={example} type="button" className="chip" onClick={() => void send(example)}>
                  {example}
                </button>
              ))}
            </div>
          )}
          {messages.map((message) => {
            if (message.role === "user") return <p key={message.id} className="bubble bubble--user">{message.text}</p>;
            if (message.role === "error") return <p key={message.id} role="alert" className="bubble bubble--error">{message.text}</p>;
            const contexts = message.data.response.contexts;
            return (
              <div key={message.id} className="bubble bubble--bot">
                {contexts.length === 0 ? (
                  <p>I couldn't find a verified fix for that. Try describing the symptom or the screen you're on.</p>
                ) : (
                  contexts.map((goal) => (
                    <PlanCard
                      key={goal.goal}
                      goal={goal}
                      activeUri={screen?.uri ?? null}
                      onOpen={(link, validation) => setScreen(openDeeplink(link, validation))}
                    />
                  ))
                )}
                <MetaStrip data={message.data} />
              </div>
            );
          })}
          {busy && <p className="bubble bubble--bot bubble--pending">Working on it…</p>}
          <div ref={endRef} />
        </div>

        <form className="composer" onSubmit={onSubmit}>
          <input
            aria-label="Describe your problem"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="e.g. my screen flickers after the update"
            autoComplete="off"
          />
          <button type="submit" disabled={busy || draft.trim() === ""}>Send</button>
        </form>
      </main>

      <aside className="side">
        <PhoneSimulator screen={screen} />
      </aside>
    </div>
  );
}
```

`frontend/src/main.tsx`:

```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
```

`frontend/src/styles.css`:

```css
:root {
  --bg: #f6f7f9;
  --surface: #ffffff;
  --ink: #16181d;
  --muted: #5d6470;
  --line: #dfe3e8;
  --accent: #1a56db;
  --auto: #146c43;
  --manual: #6b4f00;
  --critical: #b42318;
  color-scheme: light;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0f1216;
    --surface: #171b21;
    --ink: #eceff4;
    --muted: #9aa3b0;
    --line: #2a303a;
    --accent: #7aa2ff;
    --auto: #5fd39a;
    --manual: #e5c05c;
    --critical: #ff8a80;
    color-scheme: dark;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink); font: 16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
button, input { font: inherit; color: inherit; }

.app { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 24px; max-width: 1180px; margin: 0 auto; padding: 24px 16px; min-height: 100vh; }
.chat { display: flex; flex-direction: column; min-width: 0; }
.chat__head h1 { margin: 0 0 4px; font-size: 1.5rem; }
.chat__head p { margin: 0 0 16px; color: var(--muted); }
.thread { flex: 1; display: flex; flex-direction: column; gap: 12px; padding-bottom: 16px; }
.examples { display: flex; flex-wrap: wrap; gap: 8px; }
.chip { border: 1px solid var(--line); background: var(--surface); border-radius: 999px; padding: 6px 14px; cursor: pointer; }
.chip:hover { border-color: var(--accent); }

.bubble { margin: 0; padding: 12px 14px; border-radius: 14px; max-width: 100%; }
.bubble--user { align-self: flex-end; background: var(--accent); color: #fff; max-width: 85%; }
.bubble--bot { background: var(--surface); border: 1px solid var(--line); }
.bubble--error { background: color-mix(in srgb, var(--critical) 12%, var(--surface)); border: 1px solid var(--critical); }
.bubble--pending { color: var(--muted); }
.meta { margin: 10px 0 0; color: var(--muted); font-size: 0.8rem; }

.plan__goal { margin: 0 0 10px; font-size: 1.05rem; }
.plan__actions { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 10px; }
.action { border: 1px solid var(--line); border-left-width: 4px; border-radius: 10px; padding: 10px 12px; }
.action--auto { border-left-color: var(--auto); }
.action--manual { border-left-color: var(--manual); }
.action--critical { border-left-color: var(--critical); }
.action__head { display: flex; align-items: center; gap: 8px; }
.action__name { margin: 0; font-size: 1rem; }
.action__desc { margin: 4px 0 6px; color: var(--muted); font-size: 0.9rem; }
.action__warn { margin: 0 0 6px; color: var(--critical); font-size: 0.9rem; font-weight: 600; }
.badge { font-size: 0.7rem; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; padding: 2px 8px; border-radius: 999px; border: 1px solid currentColor; }
.badge--auto { color: var(--auto); }
.badge--manual { color: var(--manual); }
.badge--critical { color: var(--critical); }
.group { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.steps { margin: 4px 0 8px; padding-left: 1.3rem; }
.open { flex: none; border: 1px solid var(--accent); background: transparent; color: var(--accent); border-radius: 8px; padding: 4px 14px; cursor: pointer; }
.open:hover, .open[aria-pressed="true"] { background: var(--accent); color: #fff; }

.composer { position: sticky; bottom: 0; display: flex; gap: 8px; padding: 12px 0; background: var(--bg); }
.composer input { flex: 1; min-width: 0; border: 1px solid var(--line); background: var(--surface); border-radius: 10px; padding: 10px 12px; }
.composer button { border: 0; border-radius: 10px; background: var(--accent); color: #fff; padding: 0 18px; cursor: pointer; }
.composer button:disabled { opacity: 0.5; cursor: not-allowed; }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }

.side { position: sticky; top: 24px; align-self: start; }
.phone__frame { width: 320px; margin: 0 auto; border: 10px solid #20242b; border-radius: 36px; background: var(--surface); overflow: hidden; min-height: 560px; }
.phone__status { display: flex; justify-content: space-between; padding: 8px 18px; font-size: 0.8rem; color: var(--muted); }
.phone__screen { padding: 8px 18px 24px; }
.phone__app { margin: 0 0 16px; font-size: 1.6rem; }
.phone__empty { color: var(--muted); }
.phone__panel { animation: rise 180ms ease-out; }
@keyframes rise { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
@media (prefers-reduced-motion: reduce) { .phone__panel { animation: none; } }
.phone__title { margin: 0 0 12px; font-size: 1.15rem; }
.phone__note { margin: 12px 0 4px; font-weight: 600; }
.phone__verified { margin: 0 0 12px; color: var(--auto); font-size: 0.9rem; }
.phone__uri { display: block; color: var(--muted); font-size: 0.75rem; word-break: break-all; }
.switch { display: inline-block; position: relative; }
.switch input { position: absolute; opacity: 0; width: 100%; height: 100%; margin: 0; }
.switch__track { display: block; width: 52px; height: 30px; border-radius: 999px; background: var(--line); position: relative; transition: background 150ms; }
.switch__track::after { content: ""; position: absolute; top: 3px; left: 3px; width: 24px; height: 24px; border-radius: 50%; background: #fff; transition: transform 150ms; }
.switch input:checked + .switch__track { background: var(--auto); }
.switch input:checked + .switch__track::after { transform: translateX(22px); }
.slider { width: 100%; }

@media (max-width: 900px) {
  .app { grid-template-columns: 1fr; }
  .side { position: static; }
}
```

- [ ] **Step 4: Run to verify they pass**

Run (in `frontend/`): `npm test && npm run build`
Expected: all tests pass (6 simulator, 4 plan card, 4 app); `tsc --noEmit` and the Vite build succeed with no type errors.

- [ ] **Step 5: Verify in a real browser, then commit**

Start both servers (two terminals):

```bash
./.venv/Scripts/python -m uvicorn app.main:app --port 8000
cd frontend && npm run dev
```

Open the printed URL (default `http://localhost:5173`). Check each of these and note the result:

1. The three example chips show; clicking "My screen is cracked and flickers" sends it and a plan card appears with a meta strip.
2. Type "touch is laggy" and send: a Touchscreen plan appears with an `auto` action first and `critical` actions last.
3. Press **Open** on the Touch sensitivity step: the phone shows "Touch sensitivity" with the switch turned on and "Verified: Touch sensitivity".
4. Press **Open** on the Navigation bar step: the phone shows "Navigation bar" with "Opened".
5. Send "best pasta recipe": the reply says it couldn't find a verified fix.
6. Stop the backend and send a message: an error bubble appears.
7. Narrow the window below 900px: the phone moves under the chat and nothing scrolls sideways.

Fix any failure before committing.

```bash
```

---

### Task 12: Benchmark and metrics report

**Files:**
- Replace: `scripts/benchmark.py`
- Create (generated): `metrics.md`
- Test: `tests/test_benchmark.py`

**Interfaces:**
- Consumes: `TroubleshootingService`, `PlanCache.entries()`, `validate_plan`, `ContextDeeplinkResponse`, `tests/fixtures/paraphrases.json`.
- Produces: `scripts/benchmark.py` exposing `percentile(values: list[float], q: float) -> float` and `collect_metrics(service, fixtures, requests_per_path: int) -> dict`, and `main()` which writes `metrics.md` in the layout of PDF Appendix C.

- [ ] **Step 1: Write the failing test**

```python
"""The benchmark reports real measurements and fills the Appendix C template."""

import importlib.util
import json
from pathlib import Path

import pytest

from app.services.troubleshooting_service import TroubleshootingService

ROOT = Path(__file__).resolve().parents[1]


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


def test_collect_metrics_reports_compliance_and_paths(benchmark, catalog, siis_rows):
    service = TroubleshootingService(catalog)
    service.warm(siis_rows)
    fixtures = json.loads((ROOT / "tests" / "fixtures" / "paraphrases.json").read_text(encoding="utf-8"))
    metrics = benchmark.collect_metrics(service, fixtures, requests_per_path=5)
    assert metrics["schema_valid_pct"] == 100.0
    assert metrics["url_leaks"] == 0
    assert metrics["catalog_valid_pct"] == 100.0
    assert metrics["negative_false_hits"] == 0
    assert set(metrics["latency"]) == {"exact", "paraphrase", "cold"}
    assert metrics["paraphrase_total"] == len(fixtures["positives"])
    assert 0 <= metrics["paraphrase_correct"] <= metrics["paraphrase_total"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `./.venv/Scripts/python -m pytest tests/test_benchmark.py -q`
Expected: FAIL (the existing `scripts/benchmark.py` is a placeholder with no `percentile`).

- [ ] **Step 3: Replace `scripts/benchmark.py`**

```python
"""Measure compliance and latency of the engine and write metrics.md (PDF Appendix C)."""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.models.official_schema import ContextDeeplinkResponse  # noqa: E402
from app.services.catalog import load_catalog, load_siis_rows  # noqa: E402
from app.services.plan_validator import validate_plan  # noqa: E402
from app.services.troubleshooting_service import TroubleshootingService  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "paraphrases.json"
REQUESTS_PER_PATH = 30
_URL = re.compile(r"https?://|www\.", re.IGNORECASE)


def percentile(values: list[float], q: float) -> float:
    """Nearest-rank percentile of ``values`` for ``q`` in (0, 1]."""
    ordered = sorted(values)
    rank = max(1, min(len(ordered), int(round(q * len(ordered)))))
    return ordered[rank - 1]


def _strings(value: Any, key: str = "") -> list[str]:
    """All strings in ``value`` except deeplink URIs."""
    if isinstance(value, str):
        return [] if key == "deeplink" else [value]
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in _strings(v, k)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v, key)]
    return []


def _time_calls(call, queries: list[str]) -> list[float]:
    timings = []
    for query in queries:
        started = time.perf_counter()
        call(query)
        timings.append((time.perf_counter() - started) * 1000)
    return timings


def collect_metrics(service: TroubleshootingService, fixtures: dict, requests_per_path: int) -> dict[str, Any]:
    """Run every measurement and return plain numbers."""
    catalog = service.catalog
    actionable = {entry["deeplink"] for entry in catalog}
    entries = service.cache.entries()

    schema_valid = url_leaks = auto_actions = auto_linked = links = links_in_catalog = 0
    for entry in entries:
        ContextDeeplinkResponse.model_validate(entry.response)
        if validate_plan({**entry.response, "query_variations": list(entry.variations)}, catalog).valid:
            schema_valid += 1
        url_leaks += sum(bool(_URL.search(text)) for text in _strings(entry.response))
        for action in entry.response["contexts"][0]["actions"]:
            for group in action["stepGroups"]:
                link = group["actionableDeeplink"]
                if link:
                    links += 1
                    links_in_catalog += link["deeplink"] in actionable
            if action["category"] == "auto":
                auto_actions += 1
                auto_linked += any(group["actionableDeeplink"] for group in action["stepGroups"])

    positives, negatives = fixtures["positives"], fixtures["negatives"]
    correct = wrong = 0
    for item in positives:
        contexts = service.troubleshoot(item["query"])["response"]["contexts"]
        if contexts and contexts[0]["title"] == item["expect"]:
            correct += 1
        elif contexts:
            wrong += 1
    false_hits = sum(bool(service.troubleshoot(query)["response"]["contexts"]) for query in negatives)

    exact_query = entries[0].query
    hitting = [p["query"] for p in positives if service.cache.lookup(p["query"]) is not None] or [exact_query]
    cold_row = next(row for row in load_siis_rows() if row["id"] == entries[0].entry_id)
    cold_content = cold_row["siis_response"]["content"]
    cold_queries = [f"{exact_query} variant {index}" for index in range(requests_per_path)]
    latency = {
        "exact": _time_calls(service.troubleshoot, [exact_query] * requests_per_path),
        "paraphrase": _time_calls(service.troubleshoot, [hitting[i % len(hitting)] for i in range(requests_per_path)]),
        "cold": _time_calls(lambda q: service.troubleshoot(q, siis_response=cold_content), cold_queries),
    }
    return {
        "plans": len(entries),
        "schema_valid_pct": round(100 * schema_valid / max(1, len(entries)), 1),
        "url_leaks": url_leaks,
        "catalog_valid_pct": round(100 * links_in_catalog / max(1, links), 1),
        "auto_linked_pct": round(100 * auto_linked / max(1, auto_actions), 1),
        "paraphrase_correct": correct,
        "paraphrase_wrong": wrong,
        "paraphrase_total": len(positives),
        "negative_false_hits": false_hits,
        "negative_total": len(negatives),
        "latency": {
            path: {"p50": round(percentile(values, 0.5), 1), "p95": round(percentile(values, 0.95), 1), "n": len(values)}
            for path, values in latency.items()
        },
    }


def render(metrics: dict[str, Any]) -> str:
    """Fill the Appendix C template with measured values; unmeasured cells say so."""
    lat = metrics["latency"]
    rate = round(100 * metrics["paraphrase_correct"] / max(1, metrics["paraphrase_total"]), 1)
    return f"""# System Performance Metrics & Evaluation Report
**Model(s):** none (rules-v1: deterministic parsing, exact-label deeplink matching)
**Embeddings:** HashEmbeddingModel (dependency-free hashed bag of words; replaced by the fine-tuned model in the next phase)
**Environment:** {sys.platform}, Python {sys.version.split()[0]}

---

## 1. Schema & Rule Compliance
Evaluated over the {metrics['plans']} plans built from the official sample rows.

| Metric | Target | Measured Value |
| :--- | :--- | :--- |
| Schema-valid output lines | >= 99% | {metrics['schema_valid_pct']}% |
| Rule compliance (Goal / Title / Description syntax) | >= 95% | {metrics['schema_valid_pct']}% |
| Absolute URL leaks | 0 | {metrics['url_leaks']} |
| Deeplink catalog validity (exact URI match) | 100% | {metrics['catalog_valid_pct']}% |
| Auto actions carrying valid actionable deeplink | >= 90% | {metrics['auto_linked_pct']}% |

---

## 2. Accuracy Benchmarks
No ground-truth plans were supplied, so step accuracy and deeplink relevance were not scored.

| Evaluation Metric | Scale / Anchor | Score |
| :--- | :--- | :--- |
| Step accuracy (completeness, correctness, ordering) | 0.0 - 3.0 | not scored |
| Deeplink relevance (exact target screen vs. parent menu) | 0.0 - 2.0 | not scored |

---

## 3. Latency Benchmarks (N = {lat['exact']['n']} requests per path)

| Execution Path | Target (P95) | P50 (ms) | P95 (ms) |
| :--- | :--- | :--- | :--- |
| Cache hit - exact query match | <= 300 ms | {lat['exact']['p50']} | {lat['exact']['p95']} |
| Cache hit - unseen semantic paraphrase | <= 300 ms | {lat['paraphrase']['p50']} | {lat['paraphrase']['p95']} |
| Cold query - full pipeline extraction & mapping | <= 8000 ms | {lat['cold']['p50']} | {lat['cold']['p95']} |

---

## 4. Operational Cost & Cache Efficacy

| Metric Item | Target | Measured Value |
| :--- | :--- | :--- |
| Cold query average inference cost | Tracked | $0.00 |
| Cache hit inference cost | $0.00 | $0.00 |
| Semantic cache hit rate (on unseen paraphrases, correct plan) | >= 80% | {rate}% ({metrics['paraphrase_correct']} of {metrics['paraphrase_total']}; {metrics['paraphrase_wrong']} hit a wrong plan) |
| Unrelated queries wrongly answered | 0 | {metrics['negative_false_hits']} of {metrics['negative_total']} |
| Cost derivation method | - | no model calls, so (prompt tokens + completion tokens) x rate = 0 |

---

## 5. Architectural Ablation Analysis

| Architecture Variant | Step Accuracy | Latency (P95) | Cost / Query | Key Observations |
| :--- | :--- | :--- | :--- | :--- |
| Baseline: Full LLM Deeplink Mapping | not run | not run | not run | No LLM in this version. |
| Variant A: Hybrid BM25 + Dense Embedding Retrieval | not scored | not run | $0.00 | Tried on real sections and rejected: min-max fusion scores the top hit near 1.0 even for unrelated screens (for example "Restart in Safe Mode" against "One-handed mode"). |
| Variant B: Pure Rules-Based Deeplink Mapping | not scored | {lat['cold']['p95']} ms cold | $0.00 | Exact match of the tapped UI label to the catalog's `validation.key`. This is what ships. |

---

## 6. Known Edge Cases & System Limitations
* The relevance gate is lexical. Rows 8 and 20 (article does not fit the complaint) are refused, but rows 7 and 12 share ordinary words with their article and still receive a plan. Fixing this needs semantic similarity (embedding fine-tune).
* Paraphrase recall is limited by the hashed embedding; the figure in section 4 is the honest measurement and is below the 80% target.
* Multi-intent complaints (row 19) are answered for the dominant intent only.
* Rows 6 and 18 do not exist in `siis_responses.json`. Rows 16, 17, and 20 are refused by the relevance gate.
* The official `sample_output.json` has action descriptions of 9 and 11 words, against the written 5 to 7 word rule; this engine follows the written rule.
"""


def main() -> int:
    service = TroubleshootingService(load_catalog())
    service.warm(load_siis_rows())
    fixtures = json.loads(FIXTURES.read_text(encoding="utf-8"))
    metrics = collect_metrics(service, fixtures, REQUESTS_PER_PATH)
    (ROOT / "metrics.md").write_text(render(metrics), encoding="utf-8")
    print(json.dumps(metrics, indent=2))
    print(f"wrote {ROOT / 'metrics.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run to verify it passes, then run the benchmark**

Run: `./.venv/Scripts/python -m pytest tests/test_benchmark.py -q`
Expected: all pass.

Run: `./.venv/Scripts/python scripts/benchmark.py`
Expected: prints the metrics JSON and `wrote ...metrics.md`. Read `metrics.md` and confirm: schema-valid 100%, URL leaks 0, catalog validity 100%, exact and paraphrase P95 at or below 300 ms, cold P95 at or below 8000 ms, 0 negatives wrongly answered. The paraphrase hit rate is expected to be below 80% in this version (around 8 of 14). Report it as measured; do not edit fixtures or the threshold to move it.

- [ ] **Step 5: Commit**

```bash
git add scripts/benchmark.py tests/test_benchmark.py metrics.md
```

---

### Task 13: Documentation and final verification

The bootstrap docs still claim no official spec exists and describe a placeholder endpoint.

**Files:**
- Replace: `PROJECT_SPEC.md`, `DATA_MODEL.md`, `README_PROJECT.md`
- Modify: `ARCHITECTURE.md`

- [ ] **Step 1: Replace `PROJECT_SPEC.md`**

```markdown
# Project Specification

The official Theme 2 materials are in `data/original/` (copied unmodified from the participant kit). The contract is the PDF "Smart Guided Troubleshooting Engine"; the response schema is `app/models/official_schema.py`.

The design for the current build, including the measured limits of the rules-only engine, is `docs/specs/2026-09-21-troubleshooting-chat-design.md`. The implementation plan is `docs/plans/2026-09-21-troubleshooting-chat.md`.

Non-negotiable rules (PDF 4.2): zero URL leaks; deeplinks copied verbatim from the catalog; no hallucinated steps (no relevant text means `contexts: []` with a fallback); pure JSON responses.
```

- [ ] **Step 2: Replace `DATA_MODEL.md`**

```markdown
# Data Model

Output shape: `app/models/official_schema.py` (verbatim copy of the participant kit's `schema.py`): `ContextDeeplinkResponse` holds `Goal`s, each with `Action`s, each with `StepGroup`s carrying an optional `actionableDeeplink` and `validationDeeplink`.

Response body of `POST /v1/troubleshoot`:

    {"query", "query_variations": [8-10], "response": {"contexts": [...]}, "meta": {"latency_ms", "cache_hit", "model", "cost_usd", "fallback"?}}

`meta.fallback` is `"no_match"` (nothing relevant cached) or `"no_siis_context"` (cache empty), with `contexts: []`.

Inputs: `data/original/deeplinks.json` (578 masked deeplinks), `siis_responses.json` (20 rows), `input.txt`, `sample_output.json`. Generated: `data/processed/plan_cache.json` (git-ignored).
```

- [ ] **Step 3: Replace `README_PROJECT.md`**

```markdown
# Smart Guided Troubleshooting Engine

Turns a vague Galaxy complaint into an ordered, validated plan with deeplinks, and shows it in a chat with a phone simulator.

## Run

Backend (Python 3.11+):

    py -3.11 -m venv .venv
    .\.venv\Scripts\Activate.ps1
    pip install -r requirements.txt
    uvicorn app.main:app --port 8000

The first start builds `data/processed/plan_cache.json` from the official SIIS rows. Rebuild with `python scripts/build_plans.py`.

Frontend (Node 20):

    cd frontend
    npm install
    npm run dev

Open the printed URL. The dev server proxies `/v1` to port 8000.

## Test and measure

    pytest
    cd frontend && npm test
    python scripts/benchmark.py     # writes metrics.md

## API

    GET  /health                 200 {"status":"ok"} once ready, else 503
    POST /v1/troubleshoot        {"query": "...", "siis_response": "<optional raw text>"}

## Layout

    app/services/   siis_parser, key_matcher, plan_builder, plan_cache, troubleshooting_service
    frontend/       Vite + React chat, plan card, phone simulator
    scripts/        build_plans.py (warm-up report), benchmark.py
    docs/           design spec and implementation plan
```

- [ ] **Step 4: Update `ARCHITECTURE.md`**

Replace its content with:

```markdown
# Architecture

Offline warm-up, per SIIS row:

    SIIS text -> parse sections/steps -> relevance gate -> exact-label deeplink match
              -> order auto/manual/critical -> validate -> semantic cache (persisted)

Online, per request:

    query -> normalise -> semantic lookup -> cached plan | fallback (no_match / no_siis_context)
    (with siis_response supplied: cold build, validate, cache, return)

Swap points for the embedding fine-tune: `EmbeddingModel` (`app/retrieval/embeddings.py`, used by `PlanCache`) and `relevance()` (`app/services/relevance.py`).
```

- [ ] **Step 5: Run everything and confirm**

```bash
./.venv/Scripts/python -m pytest -q
cd frontend && npm test && npm run build && cd ..
git status --short
```

Expected: every Python test passes, every frontend test passes, the build succeeds, and `git status` shows only the four doc files as modified. Then:

```bash
git add PROJECT_SPEC.md DATA_MODEL.md README_PROJECT.md ARCHITECTURE.md
```

---

## Self-Review Notes

Spec coverage: API and health (Task 9); warm-up steps 1 to 5 (Tasks 3 to 8); online path and fallbacks (Task 8); validators (Task 2, Task 6 property tests); determinism (Tasks 6, 8 tests); frontend chat, plan card, simulator, meta strip, empty and error states (Tasks 10, 11); testing and benchmarks (Task 12); data caveats: mismatched rows and garbled tails (Tasks 3, 5, 6), missing rows 6 and 18 and multi-intent (Task 12 report); training seam: `EmbeddingModel` in `PlanCache` and `relevance()` (documented in Task 13). Deviations from the spec, all recorded in the spec itself: exact-label deeplink matching instead of hybrid retrieval, and no trim-and-correct loop (invalid plans are rejected and reported).

Known result to expect: the semantic paraphrase hit rate is below the 80% target with the hashed embedding. That is a measured limitation to close with the embedding fine-tune, not a bug to tune away.
