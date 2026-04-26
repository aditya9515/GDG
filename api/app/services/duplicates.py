from __future__ import annotations

import math
import re
import uuid
from collections import Counter
from google import genai

from app.core.config import Settings
from app.models.domain import (
    CaseRecord,
    DuplicateCandidate,
    DuplicateLink,
    DuplicateStatus,
    DuplicateSuggestedAction,
    GeoPoint,
)
from app.services.vectors import VectorService


def _distance_km(a: GeoPoint | None, b: GeoPoint | None) -> float | None:
    if a is None or b is None:
        return None
    radius = 6371.0
    lat1 = math.radians(a.lat)
    lat2 = math.radians(b.lat)
    dlat = math.radians(b.lat - a.lat)
    dlng = math.radians(b.lng - a.lng)
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(value))


class DuplicateService:
    def __init__(self, settings: Settings, vector_service: VectorService | None = None) -> None:
        self.settings = settings
        self.client = genai.Client(api_key=settings.gemini_api_key) if settings.gemini_api_key else None
        self.vector_service = vector_service

    def find_duplicates(self, case: CaseRecord, candidates: list[CaseRecord]) -> list[DuplicateLink]:
        current_vector = self._embed_text(self.dedupe_string(case))
        links: list[DuplicateLink] = []
        for candidate in candidates:
            candidate_vector = self._embed_text(self.dedupe_string(candidate))
            similarity = self._cosine(current_vector, candidate_vector)
            if similarity < self.settings.duplicate_threshold:
                continue
            compatible_category = (
                case.extracted_json is not None
                and candidate.extracted_json is not None
                and case.extracted_json.category == candidate.extracted_json.category
            )
            if not compatible_category:
                continue
            distance = _distance_km(case.geo, candidate.geo)
            decision = DuplicateStatus.POSSIBLE_DUPLICATE
            if distance is not None and distance <= self.settings.likely_duplicate_km:
                decision = DuplicateStatus.LIKELY_DUPLICATE
            links.append(
                DuplicateLink(
                    link_id=f"dup-{uuid.uuid4().hex[:12]}",
                    case_id=case.case_id,
                    other_case_id=candidate.case_id,
                    similarity=round(similarity, 3),
                    decision=decision,
                    geo_distance_km=round(distance, 2) if distance is not None else None,
                )
            )
        return sorted(links, key=lambda item: item.similarity, reverse=True)

    def find_exact_duplicate(self, record_type: str, source_text: str, org_id: str, cases: list[CaseRecord]) -> CaseRecord | None:
        source_hash = self.source_hash(record_type, source_text)
        normalized = self.normalize_text(source_text)
        for case in cases:
            if case.org_id != org_id:
                continue
            if case.source_hash and case.source_hash == source_hash:
                return case
            if self.normalize_text(case.raw_input) == normalized:
                return case
        return None

    def find_duplicate_candidates(
        self,
        case_like: CaseRecord,
        candidates: list[CaseRecord],
        *,
        limit: int = 5,
    ) -> list[DuplicateCandidate]:
        current_vector = self._embed_text(self.dedupe_string(case_like))
        preview: list[DuplicateCandidate] = []
        for candidate in candidates:
            if candidate.case_id == case_like.case_id:
                continue
            similarity = self._cosine(current_vector, self._embed_text(self.dedupe_string(candidate)))
            exact_text = self.normalize_text(case_like.raw_input) == self.normalize_text(candidate.raw_input)
            threshold = self.settings.duplicate_threshold
            if not exact_text and similarity < max(0.72, threshold - 0.08):
                continue
            distance = _distance_km(case_like.geo, candidate.geo)
            likely = similarity >= threshold and (distance is None or distance <= self.settings.likely_duplicate_km)
            suggested_action = DuplicateSuggestedAction.REUSE_EXISTING if exact_text else DuplicateSuggestedAction.REVIEW_MANUALLY
            status = DuplicateStatus.LIKELY_DUPLICATE if likely or exact_text else DuplicateStatus.POSSIBLE_DUPLICATE
            reason_parts = ["exact normalized text match"] if exact_text else [f"semantic similarity {similarity:.2f}"]
            if distance is not None:
                reason_parts.append(f"{distance:.1f} km apart")
            preview.append(
                DuplicateCandidate(
                    record_id=candidate.case_id,
                    similarity=1.0 if exact_text else round(similarity, 3),
                    reason="; ".join(reason_parts),
                    fields_compared=["raw_input", "category", "location", "geo"],
                    suggested_action=suggested_action,
                    duplicate_status=status,
                    geo_distance_km=round(distance, 2) if distance is not None else None,
                )
            )
        return sorted(preview, key=lambda item: item.similarity, reverse=True)[:limit]

    def resolve_duplicate_decision(self, candidate: DuplicateCandidate) -> DuplicateSuggestedAction:
        if candidate.similarity >= 0.98:
            return DuplicateSuggestedAction.REUSE_EXISTING
        if candidate.similarity >= self.settings.duplicate_threshold:
            return DuplicateSuggestedAction.REVIEW_MANUALLY
        return DuplicateSuggestedAction.NOT_DUPLICATE

    def source_hash(self, record_type: str, source_text: str) -> str:
        import hashlib

        normalized = self.normalize_text(f"{record_type}:{source_text}")
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def normalize_text(self, value: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value.lower())).strip()

    def dedupe_string(self, case: CaseRecord) -> str:
        extraction = case.extracted_json
        category = extraction.category if extraction else "UNKNOWN"
        location = extraction.location_text if extraction else case.location_text
        subcategory = extraction.subcategory if extraction else "UNCLASSIFIED"
        return f"{category} {subcategory} {location} {case.raw_input}".lower()

    def _embed_text(self, text: str) -> list[float]:
        if self.vector_service is not None:
            return self.vector_service.embed(text)
        if self.client:
            response = self.client.models.embed_content(
                model="gemini-embedding-001",
                contents=text,
            )
            return response.embeddings[0].values
        return self._local_embedding(text)

    def _local_embedding(self, text: str) -> list[float]:
        cleaned = re.sub(r"[^a-z0-9\\s]+", " ", text.lower())
        counts = Counter(cleaned.split())
        vector = [0.0] * 64
        for token, count in counts.items():
            vector[hash(token) % len(vector)] += float(count)
        return vector

    def _cosine(self, left: list[float], right: list[float]) -> float:
        numerator = sum(a * b for a, b in zip(left, right, strict=False))
        left_norm = math.sqrt(sum(a * a for a in left))
        right_norm = math.sqrt(sum(b * b for b in right))
        if not left_norm or not right_norm:
            return 0.0
        return numerator / (left_norm * right_norm)
