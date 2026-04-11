from __future__ import annotations

from functools import lru_cache

from app.core.config import get_settings
from app.repositories.base import Repository
from app.repositories.firestore import FirestoreRepository
from app.repositories.memory import MemoryRepository
from app.services.duplicates import DuplicateService
from app.services.extractor import ExtractionService
from app.services.geocoding import GeocodingService
from app.services.matching import MatchingService
from app.services.routing import RoutingService
from app.services.scoring import ScoringService
from app.services.tokens import TokenService


@lru_cache(maxsize=1)
def get_repository() -> Repository:
    settings = get_settings()
    if settings.repository_backend == "firestore":
        return FirestoreRepository(settings=settings)
    return MemoryRepository()


@lru_cache(maxsize=1)
def get_extraction_service() -> ExtractionService:
    return ExtractionService(settings=get_settings())


@lru_cache(maxsize=1)
def get_scoring_service() -> ScoringService:
    return ScoringService()


@lru_cache(maxsize=1)
def get_geocoding_service() -> GeocodingService:
    return GeocodingService(settings=get_settings())


@lru_cache(maxsize=1)
def get_duplicate_service() -> DuplicateService:
    return DuplicateService(settings=get_settings())


@lru_cache(maxsize=1)
def get_matching_service() -> MatchingService:
    return MatchingService()


@lru_cache(maxsize=1)
def get_routing_service() -> RoutingService:
    return RoutingService(settings=get_settings())


@lru_cache(maxsize=1)
def get_token_service() -> TokenService:
    return TokenService()
