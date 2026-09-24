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
