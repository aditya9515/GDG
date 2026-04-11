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
    repository_backend: str = "memory"
    allow_demo_auth: bool = True
    default_user_role: str = "INCIDENT_COORDINATOR"
    gemini_api_key: str | None = None
    google_maps_api_key: str | None = None
    firebase_project_id: str | None = None
    firestore_database: str = "(default)"
    extraction_provider: str = "auto"
    default_max_recommendations: int = 3
    duplicate_threshold: float = 0.88
    likely_duplicate_km: float = 2.0
    recent_duplicate_window_hours: int = 6


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
