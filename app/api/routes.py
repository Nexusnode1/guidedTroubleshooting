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
