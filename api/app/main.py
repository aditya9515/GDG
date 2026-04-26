from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import agents, ai, cases, dashboard, evals, incidents, operations, organizations
from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger("reliefops.api")


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.setLevel(logging.INFO)
    logger.info(
        "ReliefOps API starting with repository=%s auth_mode=%s firestore_project=%s maps=%s storage=%s",
        settings.resolved_repository_backend,
        "demo-enabled" if settings.resolved_demo_auth else "firebase-only",
        settings.firebase_project_id or "unset",
        "configured" if settings.google_maps_api_key else "unset",
        settings.firebase_storage_bucket or "unset",
    )
    logger.info(
        "AI provider=%s fallback_order=%s gemini=%s ollama_model=%s ollama_url=%s",
        settings.resolved_ai_provider,
        " -> ".join(settings.provider_fallback_order),
        "enabled" if settings.gemini_enabled else "disabled",
        settings.ollama_model,
        settings.ollama_base_url,
    )
    if settings.firebase_project_id and settings.resolved_repository_backend != "firestore":
        logger.warning(
            "Firebase project is configured but repository backend resolved to %s. Set REPOSITORY_BACKEND=firestore to avoid memory-mode drift.",
            settings.resolved_repository_backend,
        )
    if settings.google_maps_api_key and settings.route_candidate_limit < settings.default_max_recommendations:
        logger.warning(
            "Route candidate limit (%s) is below default recommendations (%s); some recommendations will use fallback ETA.",
            settings.route_candidate_limit,
            settings.default_max_recommendations,
        )
    yield


app = FastAPI(
    title="ReliefOps API",
    version="0.1.0",
    description="Smart Resource Allocation API for disaster relief and emergency healthcare.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(cases.router)
app.include_router(incidents.router)
app.include_router(dashboard.router)
app.include_router(evals.router)
app.include_router(operations.router)
app.include_router(organizations.router)
app.include_router(agents.router)
app.include_router(ai.router)


@app.get("/health", tags=["system"])
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}
