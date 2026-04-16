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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
