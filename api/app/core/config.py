from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"]
    )
    repository_backend: str | None = None
    allow_demo_auth: bool | None = None
    default_user_role: str = "INCIDENT_COORDINATOR"
    gemini_api_key: str | None = None
    google_maps_api_key: str | None = None
    firebase_project_id: str | None = None
    firebase_storage_bucket: str | None = None
    firebase_token_clock_skew_seconds: int = 10
    firestore_database: str = "(default)"
    extraction_provider: str = "auto"
    ai_provider: str | None = None
    gemini_enabled: bool = True
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "gemma4:e2b"
    ollama_timeout_seconds: float = 90
    default_max_recommendations: int = 3
    route_candidate_limit: int = 3
    duplicate_threshold: float = 0.88
    likely_duplicate_km: float = 2.0
    recent_duplicate_window_hours: int = 6

    @property
    def resolved_repository_backend(self) -> str:
        if self.repository_backend:
            return self.repository_backend
        if self.firebase_project_id:
            return "firestore"
        return "memory"

    @property
    def resolved_demo_auth(self) -> bool:
        if self.allow_demo_auth is not None:
            return self.allow_demo_auth
        return self.resolved_repository_backend == "memory"

    @property
    def resolved_ai_provider(self) -> str:
        provider = (self.ai_provider or self.extraction_provider or "auto").strip().lower()
        if provider not in {"auto", "gemini", "ollama", "heuristic", "golden"}:
            return "auto"
        return provider

    @property
    def gemini_available_for_generation(self) -> bool:
        return bool(self.gemini_enabled and self.gemini_api_key)

    @property
    def provider_fallback_order(self) -> list[str]:
        provider = self.resolved_ai_provider
        if provider == "golden":
            return ["golden", "heuristic"]
        if provider == "gemini":
            return ["gemini", "heuristic"] if self.gemini_enabled else ["heuristic"]
        if provider == "ollama":
            return ["ollama", "heuristic"]
        if provider == "heuristic":
            return ["heuristic"]
        order: list[str] = []
        if self.gemini_enabled:
            order.append("gemini")
        order.extend(["ollama", "heuristic"])
        return order


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
