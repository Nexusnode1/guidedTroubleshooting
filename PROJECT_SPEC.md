# Project Specification

The official Theme 2 materials are in `data/original/` (copied unmodified from the participant kit). The contract is the PDF "Smart Guided Troubleshooting Engine"; the response schema is `app/models/official_schema.py`.

The design, including the measured limits of the rules-only engine, is `docs/superpowers/specs/2026-09-21-troubleshooting-chat-design.md`. The implementation plan is `docs/superpowers/plans/2026-09-21-troubleshooting-chat.md`. Training your own embedding model: `docs/training-integration.md`. Testing beyond the Display domain the official rows cover: `docs/domain-coverage.md`.

Non-negotiable rules (PDF 4.2): zero URL leaks; deeplinks copied verbatim from the catalog; no hallucinated steps (no relevant text means `contexts: []` with a fallback); pure JSON responses.
