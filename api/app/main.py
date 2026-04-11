from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import cases, dashboard, evals, incidents, operations
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(
    title="ReliefOps API",
    version="0.1.0",
    description="Smart Resource Allocation API for disaster relief and emergency healthcare.",
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


@app.get("/health", tags=["system"])
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}
