# Plugging in your own trained embedding model

The engine's semantic cache is the only part that uses a learned model. It talks to it through one
small interface, so a model you train locally replaces the default without any code changes.

## How the swap works

- `EMBEDDING_MODEL` (`app/config.py`) names the model: a Hugging Face id, a **local directory**, or `hash`.
- `app/retrieval/st_embedder.py` loads it with `sentence-transformers`. A model you save with
  `model.save("models/my-embedder")` loads through exactly the same code.
- `SIMILARITY_THRESHOLD` is the minimum cosine similarity for a cached plan to answer. It depends on the
  model, so re-tune it whenever the model changes (step 4 below).
- `tests/test_acceptance.py::test_a_model_saved_to_a_local_directory_loads_and_matches` proves the
  save-then-load path works.

## Workflow

1. **Export training pairs** from the plans the engine already builds:

       python scripts/export_training_pairs.py

   This writes `data/processed/training_pairs.jsonl` (`anchor`, `positive`, `plan`). Anchors are the
   official query plus its generated paraphrases; positives are plan content. Phrasings in
   `tests/fixtures/paraphrases*.json` are excluded on purpose so evaluation stays honest.

2. **Fine-tune** with sentence-transformers (already installed). For example, start from the default model:

       from sentence_transformers import SentenceTransformer, InputExample, losses
       from torch.utils.data import DataLoader
       import json

       model = SentenceTransformer("sentence-transformers/all-mpnet-base-v2")
       rows = [json.loads(line) for line in open("data/processed/training_pairs.jsonl", encoding="utf-8")]
       examples = [InputExample(texts=[r["anchor"], r["positive"]]) for r in rows]
       loader = DataLoader(examples, shuffle=True, batch_size=16)
       loss = losses.MultipleNegativesRankingLoss(model)
       model.fit(train_objectives=[(loader, loss)], epochs=2, warmup_steps=20)
       model.save("models/my-embedder")

   `models/` at the repository root is git-ignored, so checkpoints are never committed.

3. **Evaluate on the held-out sets**, without touching the running app:

       python scripts/benchmark.py --embedding-model models/my-embedder --threshold 0.45

   This rewrites `metrics.md` with hit rate (target 80%), false answers (target 0), and latency
   (target P95 300 ms). Try a few thresholds and keep the best that still answers no unrelated query.

4. **Switch over** by setting the environment variables before starting the API:

       $env:EMBEDDING_MODEL = "models/my-embedder"
       $env:SIMILARITY_THRESHOLD = "0.5"
       .\scripts\dev.ps1

## Things to watch

- **Training data is small.** 17 plans give about 600 pairs. A model fine-tuned on that alone can easily
  overfit and score worse than the pretrained default. Compare against the default in `metrics.md` before
  switching, and consider adding more complaint phrasings or more SIIS articles.
- **Do not train on the fixtures.** The two held-out files are the only honest measure. If you add new
  training phrasings, put fresh evaluation phrasings in a new fixture file rather than reusing these.
- **A GPU is optional.** Everything runs on CPU; training on this data is quick either way.
