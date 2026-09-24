FROM python:3.11-slim

WORKDIR /app

# Unbuffered logs, no .pyc clutter, and a model cache directory inside the image so the
# embedding model is never re-downloaded on the network at container startup.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/app/.cache/huggingface \
    EMBEDDING_MODEL=sentence-transformers/all-mpnet-base-v2

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Bake the embedding model into the image at build time. This is the one network call the
# whole build makes; after this, starting or restarting a container never touches the
# network to fetch model weights. The model id must match EMBEDDING_MODEL above.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-mpnet-base-v2')"

COPY . ./

# Rebuild the plan cache from the official data at build time (deterministic: same official
# input, same rules-only pipeline, same output every time) rather than relying on whatever
# happens to be in data/processed/ on the machine the image was built on. This only bakes in
# plan content (query/variations/response); PlanCache.load() re-embeds every key with
# whichever EMBEDDING_MODEL is configured at container startup, and re-validates every entry
# against the schema, so this cannot smuggle in an unvalidated plan (see PlanCache.load/add).
RUN python scripts/build_plans.py --out data/processed/plan_cache.json

EXPOSE 8000

# Real readiness, not a fixed sleep: GET /health only returns 200 once app.state.service
# exists (see app/main.py's lifespan), i.e. once the model is loaded and the cache is ready.
HEALTHCHECK --interval=10s --timeout=5s --start-period=60s --retries=6 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
