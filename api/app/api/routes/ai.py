from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.config import Settings, get_settings
from app.core.dependencies import get_ollama_client
from app.models.domain import AiStatusResponse
from app.services.ollama import OllamaClient

router = APIRouter(prefix="/ai", tags=["ai"])


@router.get("/status", response_model=AiStatusResponse)
def ai_status(
    settings: Settings = Depends(get_settings),
    ollama: OllamaClient = Depends(get_ollama_client),
) -> AiStatusResponse:
    return AiStatusResponse(
        provider_mode=settings.resolved_ai_provider,
        gemini_enabled=settings.gemini_enabled,
        gemini_configured=bool(settings.gemini_api_key),
        ollama_base_url=settings.ollama_base_url,
        ollama_model=settings.ollama_model,
        ollama_reachable=ollama.is_available(),
        fallback_order=settings.provider_fallback_order,
    )
