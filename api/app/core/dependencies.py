from __future__ import annotations

from functools import lru_cache

from app.core.config import get_settings
from app.repositories.base import Repository
from app.repositories.firestore import FirestoreRepository
from app.repositories.memory import MemoryRepository
from app.services.duplicates import DuplicateService
from app.services.agent_graphs import AgentGraphService
from app.services.docling_parser import DoclingParserService
from app.services.extractor import ExtractionService
from app.services.geocoding import GeocodingService
from app.services.matching import MatchingService
from app.services.ollama import OllamaClient
from app.services.routing import RoutingService
from app.services.scoring import ScoringService
from app.services.storage_bridge import StorageBridgeService
from app.services.tokens import TokenService
from app.services.vectors import VectorService


@lru_cache(maxsize=1)
def get_repository() -> Repository:
    settings = get_settings()
    if settings.resolved_repository_backend == "firestore":
        return FirestoreRepository(settings=settings)
    return MemoryRepository()


@lru_cache(maxsize=1)
def get_extraction_service() -> ExtractionService:
    return ExtractionService(settings=get_settings(), ollama_client=get_ollama_client())


@lru_cache(maxsize=1)
def get_ollama_client() -> OllamaClient:
    return OllamaClient(settings=get_settings())


@lru_cache(maxsize=1)
def get_scoring_service() -> ScoringService:
    return ScoringService()


@lru_cache(maxsize=1)
def get_geocoding_service() -> GeocodingService:
    return GeocodingService(settings=get_settings(), repository=get_repository())


@lru_cache(maxsize=1)
def get_duplicate_service() -> DuplicateService:
    return DuplicateService(settings=get_settings(), vector_service=get_vector_service())


@lru_cache(maxsize=1)
def get_matching_service() -> MatchingService:
    return MatchingService()


@lru_cache(maxsize=1)
def get_routing_service() -> RoutingService:
    return RoutingService(settings=get_settings())


@lru_cache(maxsize=1)
def get_token_service() -> TokenService:
    return TokenService()


@lru_cache(maxsize=1)
def get_docling_parser_service() -> DoclingParserService:
    return DoclingParserService()


@lru_cache(maxsize=1)
def get_vector_service() -> VectorService:
    return VectorService(settings=get_settings())


@lru_cache(maxsize=1)
def get_agent_graph_service() -> AgentGraphService:
    return AgentGraphService(
        repository=get_repository(),
        docling=get_docling_parser_service(),
        extractor=get_extraction_service(),
        scorer=get_scoring_service(),
        matcher=get_matching_service(),
        token_service=get_token_service(),
        vector_service=get_vector_service(),
        geocoder=get_geocoding_service(),
        routing=get_routing_service(),
        duplicate_service=get_duplicate_service(),
    )


@lru_cache(maxsize=1)
def get_storage_bridge_service() -> StorageBridgeService:
    return StorageBridgeService(settings=get_settings())
