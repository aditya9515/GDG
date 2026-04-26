from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

from google import genai

from app.core.config import Settings
from app.models.domain import CaseRecord, IncidentExtraction, ResourceInventory, Team


@dataclass
class EmbeddingResult:
    embedding: list[float]
    provider_used: str
    dimensions: int


class VectorService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = genai.Client(api_key=settings.gemini_api_key) if settings.gemini_api_key else None

    def embed(self, text: str) -> list[float]:
        return self.embed_with_metadata(text).embedding

    def embed_with_metadata(self, text: str) -> EmbeddingResult:
        if self.client and self.settings.gemini_enabled and "gemini" in self.settings.provider_fallback_order:
            try:
                response = self.client.models.embed_content(
                    model="gemini-embedding-001",
                    contents=text,
                )
                embedding = response.embeddings[0].values
                vector = [float(item) for item in embedding]
                return EmbeddingResult(vector, "gemini-embedding-001", len(vector))
            except Exception:
                vector = self._fallback_embedding(text)
                return EmbeddingResult(vector, "hash-fallback", len(vector))
        vector = self._fallback_embedding(text)
        return EmbeddingResult(vector, "hash-fallback", len(vector))

    def build_incident_embedding_text(self, case: CaseRecord, extraction: IncidentExtraction | None = None) -> str:
        extraction = extraction or case.extracted_json
        if extraction is None:
            return f"incident {case.case_id}\n{case.raw_input}\n{case.location_text}"
        resources = ", ".join(item.resource_type for item in extraction.required_resources)
        return "\n".join(
            [
                f"incident {case.case_id}",
                f"category {extraction.category} {extraction.subcategory}",
                f"urgency {extraction.urgency}",
                f"location {extraction.location_text or case.location_text}",
                f"resources {resources}",
                extraction.notes_for_dispatch,
                case.raw_input,
            ]
        )

    def build_team_embedding_text(self, team: Team) -> str:
        return "\n".join(
            [
                f"team {team.team_id} {team.display_name}",
                f"capabilities {', '.join(team.capability_tags)}",
                f"base {team.base_label}",
                f"current {team.current_label or team.base_label}",
                f"availability {team.availability_status}",
                f"radius {team.service_radius_km}",
            ]
        )

    def build_resource_embedding_text(self, resource: ResourceInventory) -> str:
        return "\n".join(
            [
                f"resource {resource.resource_id} {resource.resource_type}",
                f"quantity {resource.quantity_available}",
                f"location {resource.location_label}",
                f"current {resource.current_label or resource.location_label}",
                f"owner {resource.owning_team_id or 'unassigned'}",
                f"constraints {', '.join(resource.constraints)}",
            ]
        )

    def _fallback_embedding(self, text: str, dimensions: int = 64) -> list[float]:
        vector = [0.0] * dimensions
        for token in text.lower().split():
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:2], "big") % dimensions
            vector[index] += 1.0
        magnitude = math.sqrt(sum(item * item for item in vector))
        if magnitude == 0:
            return vector
        return [round(item / magnitude, 6) for item in vector]
