from __future__ import annotations

import re
import uuid

from app.models.domain import (
    CaseRecord,
    IncidentExtraction,
    InfoToken,
    InfoTokenType,
    LocationConfidence,
)


PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+91[-\s]?)?[6-9]\d{9}(?!\d)")
LOW_SIGNAL_PATTERN = re.compile(r"^(page \d+|confidential|draft|report)$", re.IGNORECASE)


class TokenService:
    def from_incident(self, case: CaseRecord, extraction: IncidentExtraction) -> list[InfoToken]:
        tokens: list[InfoToken] = []
        normalized_summary = self._normalize(
            f"{extraction.category} {extraction.subcategory} {extraction.location_text} {extraction.notes_for_dispatch}"
        )
        tokens.append(
            InfoToken(
                token_id=f"tok-{uuid.uuid4().hex[:12]}",
                org_id=case.org_id,
                token_type=InfoTokenType.NEED,
                source_kind=case.source_channel,
                source_ref=case.case_id,
                summary=extraction.notes_for_dispatch,
                normalized_text=normalized_summary,
                redacted_text=self._redact(extraction.notes_for_dispatch),
                language=self._infer_language(case.raw_input),
                confidence=extraction.confidence,
                case_id=case.case_id,
                linked_entity_type="INCIDENT",
                linked_entity_id=case.case_id,
                category=extraction.category,
                urgency_hint=extraction.urgency,
                location_text=extraction.location_text or case.location_text,
                geo=case.geo,
                location_confidence=case.location_confidence,
                quantity=extraction.people_affected,
                unit="people" if extraction.people_affected else None,
                time_window_hours=extraction.time_to_act_hours,
                metadata={
                    "vulnerable_groups": [str(item) for item in extraction.vulnerable_groups],
                    "required_resources": [item.model_dump(mode="json") for item in extraction.required_resources],
                },
            )
        )

        if extraction.location_text:
            tokens.append(
                InfoToken(
                    token_id=f"tok-{uuid.uuid4().hex[:12]}",
                    org_id=case.org_id,
                    token_type=InfoTokenType.LOCATION_HINT,
                    source_kind=case.source_channel,
                    source_ref=case.case_id,
                    summary=extraction.location_text,
                    normalized_text=self._normalize(extraction.location_text),
                    redacted_text=self._redact(extraction.location_text),
                    language=self._infer_language(extraction.location_text),
                    confidence=max(extraction.confidence - 0.08, 0.1),
                    case_id=case.case_id,
                    linked_entity_type="INCIDENT",
                    linked_entity_id=case.case_id,
                    location_text=extraction.location_text,
                    geo=case.geo,
                    location_confidence=case.location_confidence,
                )
            )
        return self.prune(tokens)

    def from_csv_row(
        self,
        source_ref: str,
        row: dict[str, str],
        token_type: InfoTokenType,
        linked_entity_type: str,
        linked_entity_id: str | None = None,
    ) -> list[InfoToken]:
        summary_parts = [value.strip() for value in row.values() if value and value.strip()]
        summary = " | ".join(summary_parts[:4])
        token = InfoToken(
            token_id=f"tok-{uuid.uuid4().hex[:12]}",
            token_type=token_type,
            source_kind="CSV",
            source_ref=source_ref,
            summary=summary,
            normalized_text=self._normalize(summary),
            redacted_text=self._redact(summary),
            language=self._infer_language(summary),
            confidence=0.74,
            linked_entity_type=linked_entity_type,
            linked_entity_id=linked_entity_id,
            category=row.get("category") or row.get("resource_type") or row.get("capability"),
            urgency_hint=row.get("urgency"),
            location_text=row.get("location_text") or row.get("location") or row.get("base_label"),
            location_confidence=LocationConfidence.APPROXIMATE,
            quantity=self._parse_number(row.get("quantity") or row.get("quantity_available")),
            unit=row.get("unit"),
            metadata={key: value for key, value in row.items() if value},
        )
        return self.prune([token])

    def prune(self, tokens: list[InfoToken]) -> list[InfoToken]:
        seen: set[str] = set()
        kept: list[InfoToken] = []
        for token in tokens:
            if not token.normalized_text or len(token.normalized_text) < 5:
                continue
            if LOW_SIGNAL_PATTERN.match(token.normalized_text):
                continue
            if token.normalized_text in seen:
                continue
            seen.add(token.normalized_text)
            kept.append(token)
        return kept

    def _normalize(self, value: str) -> str:
        collapsed = re.sub(r"\s+", " ", value.strip().lower())
        collapsed = re.sub(r"[^\w\s:/,\-.]+", " ", collapsed)
        return re.sub(r"\s+", " ", collapsed).strip()

    def _redact(self, value: str) -> str:
        return PHONE_PATTERN.sub("[REDACTED_PHONE]", value)

    def _infer_language(self, value: str) -> str:
        for char in value:
            if "\u0900" <= char <= "\u097F":
                return "hi"
        return "en"

    def _parse_number(self, value: str | None) -> float | None:
        if not value:
            return None
        try:
            return float(value)
        except ValueError:
            return None
