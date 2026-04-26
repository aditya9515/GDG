from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types

from app.core.config import Settings
from app.models.domain import (
    AvailabilityStatus,
    CategoryKind,
    DataQuality,
    DomainKind,
    ExtractedDocumentBatch,
    GeoPoint,
    IncidentExtraction,
    ReevaluationPatch,
    ResourceDraftPayload,
    ResourceNeed,
    TeamDraftPayload,
    UrgencyKind,
    VulnerableGroup,
)
from app.services.ollama import OllamaClient


def _schema_path(filename: str) -> Path:
    """Find schemas in both the repo checkout and the packaged API image."""
    current = Path(__file__).resolve()
    candidates = [parent / "docs" / "schemas" / filename for parent in current.parents]
    candidates.append(Path.cwd() / "docs" / "schemas" / filename)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    searched = ", ".join(str(candidate) for candidate in candidates)
    raise FileNotFoundError(f"Could not find schema {filename}. Searched: {searched}")


SCHEMA_PATH = _schema_path("incident-extraction.schema.json")
BATCH_SCHEMA_PATH = _schema_path("document-batch-extraction.schema.json")


@dataclass
class ExtractionResult:
    extraction: IncidentExtraction
    provider_used: str
    provider_fallbacks: list[str] = field(default_factory=list)
    schema_validated: bool = True
    warnings: list[str] = field(default_factory=list)


@dataclass
class BatchExtractionResult:
    batch: ExtractedDocumentBatch
    provider_used: str
    provider_fallbacks: list[str] = field(default_factory=list)
    schema_validated: bool = True
    warnings: list[str] = field(default_factory=list)


@dataclass
class ReevaluationPatchResult:
    patch: ReevaluationPatch
    provider_used: str
    provider_fallbacks: list[str] = field(default_factory=list)
    schema_validated: bool = True
    warnings: list[str] = field(default_factory=list)


class ExtractionService:
    def __init__(self, settings: Settings, ollama_client: OllamaClient | None = None) -> None:
        self.settings = settings
        self.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.batch_schema = self._load_batch_schema()
        self.client = (
            genai.Client(api_key=settings.gemini_api_key)
            if settings.gemini_available_for_generation
            else None
        )
        self.ollama_client = ollama_client or OllamaClient(settings)

    def extract(self, raw_input: str) -> IncidentExtraction:
        return self.extract_with_metadata(raw_input).extraction

    def extract_document(self, filename: str, content_type: str, content: bytes) -> IncidentExtraction:
        return self.extract_document_with_metadata(filename, content_type, content).extraction

    def extract_document_batch(self, source_text: str) -> ExtractedDocumentBatch:
        return self.extract_document_batch_with_metadata(source_text).batch

    def extract_with_metadata(self, raw_input: str) -> ExtractionResult:
        fallbacks: list[str] = []
        warnings: list[str] = []

        for provider in self.settings.provider_fallback_order:
            try:
                if provider == "gemini":
                    if not self.client:
                        fallbacks.append("gemini:unavailable")
                        continue
                    extraction = self._extract_with_gemini(raw_input)
                    return ExtractionResult(extraction, "Gemini", fallbacks, True, warnings)

                if provider == "ollama":
                    extraction, repair_warnings = self._extract_with_ollama(raw_input)
                    warnings.extend(repair_warnings)
                    return ExtractionResult(extraction, "Ollama", fallbacks, True, warnings)

                if provider == "heuristic":
                    extraction = self._extract_heuristically(raw_input)
                    warnings.append("Heuristic fallback used; operator should verify the draft before dispatch.")
                    return ExtractionResult(extraction, "Heuristic", fallbacks, True, warnings)
            except Exception as exc:
                fallbacks.append(f"{provider}:{exc.__class__.__name__}")

        extraction = self._extract_heuristically(raw_input)
        warnings.append("All model providers failed; heuristic fallback used.")
        return ExtractionResult(extraction, "Heuristic", fallbacks, True, warnings)

    def extract_document_batch_with_metadata(self, source_text: str, source_name: str | None = None) -> BatchExtractionResult:
        fallbacks: list[str] = []
        warnings: list[str] = []

        for provider in self.settings.provider_fallback_order:
            try:
                if provider == "gemini":
                    if not self.client:
                        fallbacks.append("gemini:unavailable")
                        continue
                    batch = self._extract_document_batch_with_gemini(source_text, source_name)
                    return BatchExtractionResult(batch, "Gemini", fallbacks, True, warnings)

                if provider == "ollama":
                    batch, repair_warnings = self._extract_document_batch_with_ollama(source_text, source_name)
                    warnings.extend(repair_warnings)
                    return BatchExtractionResult(batch, "Ollama", fallbacks, True, warnings)

                if provider == "heuristic":
                    batch = self._extract_document_batch_heuristically(source_text)
                    warnings.append("Heuristic batch fallback used; review every draft before dispatch.")
                    return BatchExtractionResult(batch, "Heuristic", fallbacks, True, warnings)
            except Exception as exc:
                fallbacks.append(f"{provider}:{exc.__class__.__name__}")

        batch = self._extract_document_batch_heuristically(source_text)
        warnings.append("All model providers failed; heuristic batch fallback used.")
        return BatchExtractionResult(batch, "Heuristic", fallbacks, True, warnings)

    def extract_row_batch_with_metadata(
        self,
        row_text: str,
        source_name: str,
        target_hint: str | None = None,
        row_context: dict[str, Any] | None = None,
    ) -> BatchExtractionResult:
        context = row_context or {}
        context_payload = {
            "target_hint": target_hint,
            "source_headers": context.get("source_headers") or [],
            "source_row_index": context.get("source_row_index"),
            "normalized_row": context.get("normalized_row") or {},
            "original_row": context.get("original_row") or {},
        }
        contextual_text = f"""
CSV row extraction task.

You are extracting one source row, but it may contain any operational entity type:
incidents, teams, resources, or nothing useful. The target hint is only a hint;
return the real entities present in the row and ignore unrelated data.

Context:
{json.dumps(context_payload, ensure_ascii=False, default=str)}

        Row fragment:
<<<{row_text[:8000]}>>>
""".strip()
        result = self.extract_document_batch_with_metadata(contextual_text, source_name)
        if result.provider_used == "Heuristic":
            # The heuristic fallback should inspect only the row contents. The
            # instruction/context wrapper is useful for models, but it can look
            # like extra operational text to a keyword extractor.
            result.batch = self._extract_document_batch_heuristically(row_text)
        result.warnings.append("Row-batch extraction used; target hint was treated as non-binding context.")
        return result

    def reevaluate_incident(
        self,
        source_text: str,
        operator_prompt: str,
        previous_extraction: dict | IncidentExtraction | None = None,
    ) -> ExtractionResult:
        previous_payload = (
            previous_extraction.model_dump(mode="json")
            if isinstance(previous_extraction, IncidentExtraction)
            else previous_extraction
        )
        transient = f"""
Original source:
<<<{source_text}>>>

Previous structured extraction:
{json.dumps(previous_payload or {}, ensure_ascii=False)}

Operator correction:
<<<{operator_prompt}>>>
""".strip()
        result = self.extract_with_metadata(transient)
        result.warnings.append("Reevaluated from original source plus operator correction; source text was preserved.")
        return result

    def reevaluate_team(
        self,
        source_text: str,
        operator_prompt: str,
        previous_structured: dict | TeamDraftPayload | None = None,
    ) -> BatchExtractionResult:
        previous_payload = (
            previous_structured.model_dump(mode="json")
            if isinstance(previous_structured, TeamDraftPayload)
            else previous_structured
        )
        transient = f"""
Original source:
<<<{source_text}>>>

Previous structured team:
{json.dumps(previous_payload or {}, ensure_ascii=False, default=str)}

Operator correction:
<<<{operator_prompt}>>>

Return the corrected team in the teams array. Do not create incidents or resources unless the source clearly contains them.
""".strip()
        result = self.extract_document_batch_with_metadata(transient, "team_reevaluation")
        result.warnings.append("Team reevaluated from original source plus operator correction; source text was preserved.")
        return result

    def reevaluate_resource(
        self,
        source_text: str,
        operator_prompt: str,
        previous_structured: dict | ResourceDraftPayload | None = None,
    ) -> BatchExtractionResult:
        previous_payload = (
            previous_structured.model_dump(mode="json")
            if isinstance(previous_structured, ResourceDraftPayload)
            else previous_structured
        )
        transient = f"""
Original source:
<<<{source_text}>>>

Previous structured resource:
{json.dumps(previous_payload or {}, ensure_ascii=False, default=str)}

Operator correction:
<<<{operator_prompt}>>>

Return the corrected resource in the resources array. Do not create incidents or teams unless the source clearly contains them.
""".strip()
        result = self.extract_document_batch_with_metadata(transient, "resource_reevaluation")
        result.warnings.append("Resource reevaluated from original source plus operator correction; source text was preserved.")
        return result

    def reevaluate_payload_patch_with_metadata(self, envelope: dict[str, Any]) -> ReevaluationPatchResult:
        """Ask the configured model for a validated merge patch over the full current payload."""
        fallbacks: list[str] = []
        warnings: list[str] = []
        for provider in self.settings.provider_fallback_order:
            try:
                if provider == "gemini":
                    if not self.client:
                        fallbacks.append("gemini:unavailable")
                        continue
                    patch = self._reevaluate_payload_patch_with_gemini(envelope)
                    return ReevaluationPatchResult(patch, "Gemini", fallbacks, True, warnings)
                if provider == "ollama":
                    # Full-context patching is intentionally Gemini-only for now; older
                    # typed reevaluators remain available as the local fallback.
                    fallbacks.append("ollama:unsupported_full_context_patch")
                    continue
                if provider == "heuristic":
                    warnings.append("Model patch unavailable; deterministic reevaluation fallback will be used.")
                    return ReevaluationPatchResult(ReevaluationPatch(), "Heuristic", fallbacks, True, warnings)
            except Exception as exc:
                fallbacks.append(f"{provider}:{exc.__class__.__name__}")
        warnings.append("All full-context reevaluation providers failed; deterministic fallback will be used.")
        return ReevaluationPatchResult(ReevaluationPatch(), "Heuristic", fallbacks, True, warnings)

    def extract_document_with_metadata(self, filename: str, content_type: str, content: bytes) -> ExtractionResult:
        if self.client and "gemini" in self.settings.provider_fallback_order:
            try:
                extraction = self._extract_document_with_gemini(filename, content_type, content)
                return ExtractionResult(extraction, "Gemini", [], True, [])
            except Exception as exc:
                fallback_text = self._decode_document_fallback(filename, content_type, content)
                result = self.extract_with_metadata(fallback_text)
                result.provider_fallbacks.insert(0, f"gemini_document:{exc.__class__.__name__}")
                return result
        fallback_text = self._decode_document_fallback(filename, content_type, content)
        return self.extract_with_metadata(fallback_text)

    def extract_document_file_batch_with_metadata(self, filename: str, content_type: str, content: bytes) -> BatchExtractionResult:
        if self.client and "gemini" in self.settings.provider_fallback_order:
            try:
                batch = self._extract_document_file_batch_with_gemini(filename, content_type, content)
                return BatchExtractionResult(batch, "Gemini", [], True, [])
            except Exception as exc:
                fallback_text = self._decode_document_fallback(filename, content_type, content)
                result = self.extract_document_batch_with_metadata(fallback_text, filename)
                result.provider_fallbacks.insert(0, f"gemini_document_batch:{exc.__class__.__name__}")
                return result
        fallback_text = self._decode_document_fallback(filename, content_type, content)
        return self.extract_document_batch_with_metadata(fallback_text, filename)

    def _extract_with_gemini(self, raw_input: str) -> IncidentExtraction:
        prompt = f"""
Task: Extract structured incident details for NGO dispatch triage from an unstructured report.

Context:
- Country: India
- Mode: disaster relief + healthcare emergency coordination
- Output: MUST follow the provided JSON schema exactly.
Rules:
- Do not invent facts not present in the input.
- If a value is unknown, use null or UNKNOWN and add follow-up questions.
- Keep notes_for_dispatch operational.
- confidence: 0-1 based on completeness and clarity.

Unstructured report:
<<<{raw_input}>>>
""".strip()

        response = self.client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_json_schema=self.schema,
            ),
        )
        return IncidentExtraction.model_validate(json.loads(response.text))

    def _reevaluate_payload_patch_with_gemini(self, envelope: dict[str, Any]) -> ReevaluationPatch:
        schema: dict[str, Any] = {
            "type": "object",
            "properties": {
                "payload_patch": {"type": "object"},
                "changed_fields": {"type": "array", "items": {"type": "string"}},
                "warnings": {"type": "array", "items": {"type": "string"}},
                "reasoning_summary": {"type": "string"},
            },
            "required": ["payload_patch", "changed_fields", "warnings", "reasoning_summary"],
        }
        envelope_json = json.dumps(envelope, ensure_ascii=False, default=str)[:60000]
        prompt = f"""
Task: Reevaluation patch for a ReliefOps operator review screen.

You are given the full current draft or dispatch plan context, not just selected fields.
Return only a JSON object matching the schema.

Rules:
- Propose a merge-style payload_patch for any mutable field the operator asked to change.
- Use nested objects when changing nested fields, for example geo.lat, team.base_geo.lng, resource.quantity_available, selected_plan.team_id, reserve_teams, conflicts, or batch_plan/planned case fields.
- Include exact changed field dot paths in changed_fields.
- Keep source text/source fragments preserved unless the operator explicitly asks to edit a user-visible summary.
- For dispatch plans, do not invent feasibility, stock, availability, ETA, or route truth. You may only select from existing recommendations or add operator notes/warnings; the backend will recompute deterministic facts.
- If the operator asks for lat/lng or location changes, include those values in payload_patch.
- If a request is unsafe or unsupported, leave payload_patch empty and explain the warning.

Full reevaluation context:
<<<{envelope_json}>>>
""".strip()

        response = self.client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_json_schema=schema,
            ),
        )
        payload = json.loads(response.text or "{}")
        if payload.get("reasoning_summary") is None:
            payload["reasoning_summary"] = ""
        return ReevaluationPatch.model_validate(payload)

    def _extract_with_ollama(self, raw_input: str) -> tuple[IncidentExtraction, list[str]]:
        warnings: list[str] = []
        prompt = self._ollama_prompt(raw_input)
        first = self.ollama_client.generate(prompt)
        try:
            return self._coerce_model_payload(self._parse_json_object(first)), warnings
        except Exception as first_error:
            warnings.append(f"Ollama JSON repair triggered: {first_error.__class__.__name__}.")

        repair_prompt = f"""
Return only a single valid JSON object matching the ReliefOps IncidentExtraction schema.
Do not include markdown, comments, explanations, or trailing text.
If a value is unknown, use null, UNKNOWN, or an empty string as appropriate.

Invalid previous response:
<<<{first}>>>

Original report:
<<<{raw_input}>>>
""".strip()
        repaired = self.ollama_client.generate(repair_prompt)
        return self._coerce_model_payload(self._parse_json_object(repaired)), warnings

    def _extract_document_with_gemini(self, filename: str, content_type: str, content: bytes) -> IncidentExtraction:
        prompt = f"""
Task: Read the attached document or image and extract a single incident report for NGO dispatch.

Rules:
- Output MUST match the provided JSON schema exactly.
- If multiple incidents appear, extract the most urgent one.
- Prefer operational summaries and avoid personal details unless required for dispatch.

Context:
- Country: India
- Filename: {filename}
""".strip()

        response = self.client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                prompt,
                types.Part.from_bytes(data=content, mime_type=content_type),
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_json_schema=self.schema,
            ),
        )
        return IncidentExtraction.model_validate(json.loads(response.text))

    def _extract_document_batch_with_gemini(self, source_text: str, source_name: str | None) -> ExtractedDocumentBatch:
        prompt = f"""
Task: Extract all distinct operational entities from a disaster relief / emergency healthcare source.

Group the output into:
- incidents: events or needs that require action
- teams: response teams, volunteer groups, medical/rescue/logistics groups
- resources: supplies, vehicles, equipment, depots, inventory rows

Rules:
- Output MUST match the provided JSON schema exactly.
- Do not invent entities.
- Ignore boilerplate, repeated headers/footers, empty rows, and unrelated text.
- Keep personal names and phone numbers out unless operationally necessary.
- If location is ambiguous, keep location_label/location_text but set confidence lower in incident extraction.
- Extract every usable entity, not only the most urgent one.

Source name: {source_name or "operator_source"}
Cleaned source:
<<<{source_text[:16000]}>>>
""".strip()

        response = self.client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_json_schema=self.batch_schema,
            ),
        )
        return self._coerce_batch_payload(json.loads(response.text))

    def _extract_document_file_batch_with_gemini(self, filename: str, content_type: str, content: bytes) -> ExtractedDocumentBatch:
        prompt = f"""
Task: Read the attached source and extract all distinct operational entities for NGO dispatch.

Return incidents, teams, and resources. Ignore boilerplate and duplicates.
Filename: {filename}
Country context: India
""".strip()

        response = self.client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                prompt,
                types.Part.from_bytes(data=content, mime_type=content_type),
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_json_schema=self.batch_schema,
            ),
        )
        return self._coerce_batch_payload(json.loads(response.text))

    def _extract_document_batch_with_ollama(self, source_text: str, source_name: str | None) -> tuple[ExtractedDocumentBatch, list[str]]:
        warnings: list[str] = []
        prompt = f"""
You are ReliefOps AI. Extract all operational records from the source.

Return ONLY valid JSON with exactly these top-level keys:
incidents, teams, resources, document_summary, warnings.

Each incident must match IncidentExtraction:
domain, category, subcategory, urgency, people_affected, vulnerable_groups,
location_text, time_to_act_hours, required_resources, notes_for_dispatch, data_quality, confidence.

        Each team:
        team_id, display_name, capability_tags, base_label, base_geo, current_label,
        current_geo, member_ids, service_radius_km, availability_status,
        active_dispatches, reliability_score, evidence_ids, notes.

        Each resource:
        resource_id, resource_type, quantity_available, location_label, location,
        current_label, current_geo, constraints, owning_team_id, evidence_ids, image_url.

Rules:
- Ignore rows/fragments unrelated to the selected operational domains.
- Do not create empty records.
- Do not invent coordinates or people.
- Use arrays even when empty.

Source name: {source_name or "operator_source"}
Source:
<<<{source_text[:12000]}>>>
""".strip()
        first = self.ollama_client.generate(prompt)
        try:
            return self._coerce_batch_payload(self._parse_json_object(first)), warnings
        except Exception as first_error:
            warnings.append(f"Ollama batch JSON repair triggered: {first_error.__class__.__name__}.")

        repair_prompt = f"""
Return only valid JSON with keys incidents, teams, resources, document_summary, warnings.
No markdown. No explanation.

Invalid previous response:
<<<{first}>>>

Original source:
<<<{source_text[:12000]}>>>
""".strip()
        repaired = self.ollama_client.generate(repair_prompt)
        return self._coerce_batch_payload(self._parse_json_object(repaired)), warnings

    def _load_batch_schema(self) -> dict:
        if not BATCH_SCHEMA_PATH.exists():
            return {}
        schema = json.loads(BATCH_SCHEMA_PATH.read_text(encoding="utf-8"))
        incident_items = schema.get("properties", {}).get("incidents", {}).get("items")
        if isinstance(incident_items, dict) and "$ref" in incident_items:
            schema["properties"]["incidents"]["items"] = self.schema
        return schema

    def _coerce_batch_payload(self, payload: dict) -> ExtractedDocumentBatch:
        incidents_payload = payload.get("incidents") if isinstance(payload.get("incidents"), list) else []
        teams_payload = payload.get("teams") if isinstance(payload.get("teams"), list) else []
        resources_payload = payload.get("resources") if isinstance(payload.get("resources"), list) else []

        incidents: list[IncidentExtraction] = []
        for item in incidents_payload:
            if not isinstance(item, dict):
                continue
            try:
                incidents.append(self._coerce_model_payload(item))
            except Exception:
                continue

        teams: list[TeamDraftPayload] = []
        for item in teams_payload:
            if not isinstance(item, dict):
                continue
            name = str(item.get("display_name") or "").strip()
            capability_tags = self._string_list(item.get("capability_tags"))
            base_label = str(item.get("base_label") or "").strip() or None
            if not name and not capability_tags and not base_label:
                continue
            teams.append(
                TeamDraftPayload(
                    team_id=str(item.get("team_id") or "").strip() or None,
                    display_name=name or None,
                    capability_tags=capability_tags,
                    base_label=base_label,
                    base_geo=self._geo_payload(item.get("base_geo")),
                    current_label=str(item.get("current_label") or "").strip() or base_label,
                    current_geo=self._geo_payload(item.get("current_geo")),
                    member_ids=self._string_list(item.get("member_ids")),
                    service_radius_km=self._bounded_float(item.get("service_radius_km"), None, minimum=0, maximum=None),
                    availability_status=self._availability_payload(item.get("availability_status")),
                    active_dispatches=self._nonnegative_int(item.get("active_dispatches")),
                    reliability_score=self._bounded_float(item.get("reliability_score"), None),
                    evidence_ids=self._string_list(item.get("evidence_ids")),
                    notes=self._string_list(item.get("notes")),
                )
            )

        resources: list[ResourceDraftPayload] = []
        for item in resources_payload:
            if not isinstance(item, dict):
                continue
            resource_type = str(item.get("resource_type") or "").strip().upper().replace(" ", "_")
            location_label = str(item.get("location_label") or "").strip() or None
            if not resource_type and not location_label:
                continue
            resources.append(
                ResourceDraftPayload(
                    resource_id=str(item.get("resource_id") or "").strip() or None,
                    resource_type=resource_type or "UNKNOWN_RESOURCE",
                    quantity_available=self._bounded_float(item.get("quantity_available"), None, minimum=0, maximum=None),
                    location_label=location_label,
                    location=self._geo_payload(item.get("location")),
                    current_label=str(item.get("current_label") or "").strip() or location_label,
                    current_geo=self._geo_payload(item.get("current_geo")),
                    constraints=self._string_list(item.get("constraints")),
                    owning_team_id=str(item.get("owning_team_id") or "").strip() or None,
                    evidence_ids=self._string_list(item.get("evidence_ids")),
                    image_url=str(item.get("image_url") or "").strip() or None,
                )
            )

        warnings = self._string_list(payload.get("warnings"))
        return ExtractedDocumentBatch(
            incidents=incidents,
            teams=teams,
            resources=resources,
            document_summary=str(payload.get("document_summary") or "").strip() or None,
            warnings=warnings,
        )

    def _extract_document_batch_heuristically(self, source_text: str) -> ExtractedDocumentBatch:
        chunks = self._split_operational_chunks(source_text)
        incidents: list[IncidentExtraction] = []
        teams: list[TeamDraftPayload] = []
        resources: list[ResourceDraftPayload] = []
        ignored = 0
        for chunk in chunks:
            lowered = chunk.lower()
            if any(token in lowered for token in ("stock", "quantity", "inventory", "warehouse", "depot", "asset", "count", "supply", "kit", "truck", "vehicle")) and any(
                token in lowered for token in ("resource", "medicine", "water", "food", "boat", "ambulance", "fuel", "shelter", "tarpaulin")
            ):
                resources.append(self._heuristic_resource_payload(chunk))
                continue
            if any(token in lowered for token in ("team", "volunteer", "responder", "ambulance unit", "crew")) and any(
                token in lowered for token in ("skill", "capability", "certified", "available", "base", "station")
            ):
                teams.append(self._heuristic_team_payload(chunk))
                continue
            incident_tokens = (
                "need",
                "trapped",
                "injured",
                "flood",
                "fire",
                "wildfire",
                "forest fire",
                "earthquake",
                "cyclone",
                "storm",
                "tsunami",
                "volcano",
                "landslide",
                "drought",
                "epidemic",
                "disaster",
                "emergency",
                "evacuation",
                "affected",
                "magnitude",
                "shelter",
                "medical",
                "rescue",
                "urgent",
                "ambulance",
            )
            if any(token in lowered for token in incident_tokens):
                incidents.append(self._extract_heuristically(chunk))
                continue
            ignored += 1

        return ExtractedDocumentBatch(
            incidents=incidents,
            teams=teams,
            resources=resources,
            document_summary=f"Heuristic batch extracted {len(incidents)} incidents, {len(teams)} teams, {len(resources)} resources.",
            warnings=[f"Ignored {ignored} low-signal chunk(s)."] if ignored else [],
        )

    def _heuristic_team_payload(self, chunk: str) -> TeamDraftPayload:
        lowered = chunk.lower()
        tags: list[str] = []
        tag_map = {
            "medical": "MEDICAL",
            "ambulance": "AMBULANCE",
            "rescue": "RESCUE",
            "boat": "WATER_RESCUE",
            "logistics": "LOGISTICS",
            "fire": "FIRE_RESPONSE",
            "translator": "TRANSLATION",
            "shelter": "SHELTER",
        }
        for needle, tag in tag_map.items():
            if needle in lowered:
                tags.append(tag)
        name = chunk.splitlines()[0][:80].strip() if chunk.splitlines() else "Team capability draft"
        return TeamDraftPayload(
            display_name=name,
            capability_tags=list(dict.fromkeys(tags or ["GENERAL_RESPONSE"])),
            base_label=self._extract_location_phrase(chunk),
            current_label=self._extract_location_phrase(chunk),
            reliability_score=0.65,
            notes=[chunk[:240]],
        )

    def _heuristic_resource_payload(self, chunk: str) -> ResourceDraftPayload:
        lowered = chunk.lower()
        resource_type = "GENERIC_RESOURCE"
        for needle, value in {
            "ambulance": "AMBULANCE",
            "boat": "RESCUE_BOAT",
            "water": "WATER_TANKER",
            "food": "FOOD_PACK",
            "medicine": "MEDICAL_KIT",
            "kit": "MEDICAL_KIT",
            "fuel": "FUEL",
            "tarpaulin": "TARPAULIN",
            "shelter": "SHELTER_KIT",
        }.items():
            if needle in lowered:
                resource_type = value
                break
        quantity = None
        match = re.search(r"(?<!\d)(\d+(?:\.\d+)?)\s*(?:units?|kits?|packs?|trucks?|vehicles?)?", lowered)
        if match:
            quantity = float(match.group(1))
        return ResourceDraftPayload(
            resource_type=resource_type,
            quantity_available=quantity,
            location_label=self._extract_location_phrase(chunk),
            current_label=self._extract_location_phrase(chunk),
            constraints=[],
        )

    def _split_operational_chunks(self, source_text: str) -> list[str]:
        paragraphs = [part.strip() for part in re.split(r"\n{2,}|(?:^|\n)\s*[-*]\s+", source_text) if part.strip()]
        if len(paragraphs) <= 1:
            paragraphs = [part.strip() for part in source_text.splitlines() if len(part.strip()) > 12]
        return paragraphs[:60]

    def _extract_location_phrase(self, text: str) -> str | None:
        for label in ("location", "base", "at", "near", "depot", "warehouse"):
            match = re.search(rf"\b{label}\b\s*(?:=|:|near|at)?\s*([^.;\n,]+(?:,\s*[^.;\n,]+)?)", text, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None

    def _string_list(self, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            raw_values = value
        else:
            raw_values = re.split(r"[,;/|]+", str(value))
        return [str(item).strip() for item in raw_values if str(item).strip()]

    def _bounded_float(self, value: object, default: float | None, minimum: float = 0.0, maximum: float | None = 1.0) -> float | None:
        if value is None or value == "":
            return default
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        if maximum is None:
            return max(minimum, parsed)
        return max(minimum, min(parsed, maximum))

    def _nonnegative_int(self, value: object) -> int | None:
        parsed = self._bounded_float(value, None, minimum=0, maximum=None)
        return int(parsed) if parsed is not None else None

    def _availability_payload(self, value: object) -> AvailabilityStatus | None:
        if value is None:
            return None
        normalized = str(value).strip().upper().replace("-", "_").replace(" ", "_")
        if not normalized:
            return None
        if normalized in AvailabilityStatus.__members__:
            return AvailabilityStatus[normalized]
        if normalized in {item.value for item in AvailabilityStatus}:
            return AvailabilityStatus(normalized)
        return None

    def _geo_payload(self, value: object) -> GeoPoint | None:
        if not isinstance(value, dict):
            return None
        lat = self._bounded_float(value.get("lat"), None, minimum=-90, maximum=90)
        lng = self._bounded_float(value.get("lng"), None, minimum=-180, maximum=180)
        if lat is None or lng is None:
            return None
        return GeoPoint(lat=lat, lng=lng)

    def _ollama_prompt(self, raw_input: str) -> str:
        schema_hint = {
            "domain": ["DISASTER_RELIEF", "HEALTHCARE_EMERGENCY"],
            "category": [
                "RESCUE",
                "MEDICAL",
                "WATER",
                "SANITATION",
                "SHELTER",
                "FOOD",
                "ESSENTIAL_ITEMS",
                "LOGISTICS",
                "PROTECTION",
                "ELECTRICITY_TELECOM",
                "MISSING_PERSONS",
                "MENTAL_HEALTH",
                "ANIMAL_LIVESTOCK",
                "COORDINATION",
            ],
            "urgency": ["CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"],
        }
        return f"""
You are ReliefOps AI. Extract one incident for NGO disaster relief or emergency healthcare dispatch.

Return ONLY valid JSON with these exact keys:
domain, category, subcategory, urgency, people_affected, vulnerable_groups, location_text,
time_to_act_hours, required_resources, notes_for_dispatch, data_quality, confidence.

Rules:
- Do not invent facts.
- Use null for unknown numbers.
- Use UNKNOWN when an enum is unknown.
- data_quality must contain missing_location, missing_quantity, needs_followup_questions.
- required_resources is an array of objects with resource_type, quantity, unit.
- confidence is a number from 0 to 1.
- Prefer India disaster-relief operational language.

Allowed enum values:
{json.dumps(schema_hint)}

Unstructured report:
<<<{raw_input}>>>
""".strip()

    def _parse_json_object(self, value: str) -> dict:
        cleaned = value.strip()
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            raise ValueError("No JSON object found in model response.")
        parsed = json.loads(match.group(0))
        if not isinstance(parsed, dict):
            raise ValueError("Model response JSON is not an object.")
        return parsed

    def _coerce_model_payload(self, payload: dict) -> IncidentExtraction:
        cleaned = dict(payload)
        enum_defaults = {
            "domain": DomainKind.DISASTER_RELIEF,
            "category": CategoryKind.LOGISTICS,
            "urgency": UrgencyKind.UNKNOWN,
        }
        enum_types = {
            "domain": DomainKind,
            "category": CategoryKind,
            "urgency": UrgencyKind,
        }
        for key, enum_type in enum_types.items():
            value = str(cleaned.get(key, "")).strip().upper()
            cleaned[key] = value if value in {item.value for item in enum_type} else enum_defaults[key].value

        groups = cleaned.get("vulnerable_groups") or []
        if not isinstance(groups, list):
            groups = [groups]
        allowed_groups = {item.value for item in VulnerableGroup}
        normalized_groups = []
        for item in groups:
            value = str(item).strip().upper()
            if value in allowed_groups:
                normalized_groups.append(value)
        cleaned["vulnerable_groups"] = list(dict.fromkeys(normalized_groups or [VulnerableGroup.UNKNOWN.value]))

        resources = cleaned.get("required_resources") or []
        if not isinstance(resources, list):
            resources = []
        normalized_resources = []
        for item in resources:
            if not isinstance(item, dict):
                continue
            normalized_resources.append(
                {
                    "resource_type": str(item.get("resource_type") or "UNKNOWN_RESOURCE").strip().upper().replace(" ", "_"),
                    "quantity": item.get("quantity"),
                    "unit": item.get("unit"),
                }
            )
        cleaned["required_resources"] = normalized_resources

        quality = cleaned.get("data_quality") if isinstance(cleaned.get("data_quality"), dict) else {}
        cleaned["data_quality"] = {
            "missing_location": bool(quality.get("missing_location", not bool(cleaned.get("location_text")))),
            "missing_quantity": bool(quality.get("missing_quantity", cleaned.get("people_affected") is None)),
            "needs_followup_questions": quality.get("needs_followup_questions") if isinstance(quality.get("needs_followup_questions"), list) else [],
        }
        try:
            cleaned["confidence"] = max(0.0, min(float(cleaned.get("confidence", 0.5)), 1.0))
        except (TypeError, ValueError):
            cleaned["confidence"] = 0.5
        cleaned["notes_for_dispatch"] = str(cleaned.get("notes_for_dispatch") or "Review local model extraction before dispatch.")
        cleaned["subcategory"] = str(cleaned.get("subcategory") or "LOCAL_MODEL_EXTRACTION")
        cleaned["location_text"] = str(cleaned.get("location_text") or "")
        return IncidentExtraction.model_validate(cleaned)

    def _decode_document_fallback(self, filename: str, content_type: str, content: bytes) -> str:
        try:
            decoded = content.decode("utf-8")
        except UnicodeDecodeError:
            decoded = ""
        return f"{filename}\n{content_type}\n{decoded[:12000]}".strip()

    def _extract_heuristically(self, raw_input: str) -> IncidentExtraction:
        lowered = raw_input.lower()
        domain = DomainKind.HEALTHCARE_EMERGENCY if any(
            token in lowered for token in ("blood", "ambulance", "oxygen", "snakebite", "dialysis", "insulin")
        ) else DomainKind.DISASTER_RELIEF
        category = CategoryKind.MEDICAL if domain == DomainKind.HEALTHCARE_EMERGENCY else CategoryKind.LOGISTICS
        urgency = UrgencyKind.MEDIUM
        location_text = ""
        notes = []
        vulnerable_groups = [VulnerableGroup.UNKNOWN]
        required_resources: list[ResourceNeed] = []

        if "boat" in lowered or "rooftop" in lowered or "trapped" in lowered:
            category = CategoryKind.RESCUE
            urgency = UrgencyKind.CRITICAL
            required_resources = [ResourceNeed(resource_type="RESCUE_BOAT", quantity=1, unit="unit")]
            notes.append("Life-threatening rescue indicators present.")
        elif any(token in lowered for token in ("wildfire", "forest fire", "fire")):
            category = CategoryKind.PROTECTION
            urgency = UrgencyKind.HIGH
            required_resources = [
                ResourceNeed(resource_type="FIRE_EXTINGUISHER", quantity=None, unit=None),
                ResourceNeed(resource_type="N95_MASKS", quantity=None, unit=None),
            ]
            notes.append("Fire or smoke exposure indicators present.")
        elif any(token in lowered for token in ("earthquake", "landslide", "collapse", "tsunami", "cyclone", "storm")):
            category = CategoryKind.RESCUE
            urgency = UrgencyKind.HIGH
            required_resources = [
                ResourceNeed(resource_type="SEARCH_AND_RESCUE_TEAM", quantity=None, unit=None),
                ResourceNeed(resource_type="MEDICAL_KIT", quantity=None, unit=None),
            ]
            notes.append("Disaster impact indicators may require rescue and medical support.")
        elif "water" in lowered:
            category = CategoryKind.WATER
            urgency = UrgencyKind.HIGH
            required_resources = [ResourceNeed(resource_type="WATER_TANKER", quantity=1, unit="unit")]
        elif "drought" in lowered:
            category = CategoryKind.WATER
            urgency = UrgencyKind.MEDIUM
            required_resources = [ResourceNeed(resource_type="WATER_TANKER", quantity=None, unit=None)]
        elif "camp" in lowered and "toilet" in lowered:
            category = CategoryKind.SANITATION
            urgency = UrgencyKind.HIGH
            required_resources = [ResourceNeed(resource_type="CLEANING_TEAM", quantity=1, unit="team")]
        elif "blanket" in lowered or "tarpaulin" in lowered:
            category = CategoryKind.SHELTER
            urgency = UrgencyKind.HIGH
        elif domain == DomainKind.HEALTHCARE_EMERGENCY:
            category = CategoryKind.MEDICAL
            urgency = UrgencyKind.HIGH

        if "red" in lowered and any(token in lowered for token in ("alert", "notification", "warning")):
            urgency = UrgencyKind.CRITICAL
        elif "orange" in lowered and urgency not in {UrgencyKind.CRITICAL}:
            urgency = UrgencyKind.HIGH
        elif "green" in lowered and urgency not in {UrgencyKind.CRITICAL, UrgencyKind.HIGH}:
            urgency = UrgencyKind.MEDIUM

        if "child" in lowered or "infant" in lowered or "kids" in lowered:
            vulnerable_groups = [VulnerableGroup.CHILDREN_UNDER5]
        elif "elderly" in lowered:
            vulnerable_groups = [VulnerableGroup.ELDERLY]
        elif "pregnant" in lowered or "labour" in lowered:
            vulnerable_groups = [VulnerableGroup.PREGNANT]
            urgency = UrgencyKind.CRITICAL

        labelled_location = self._extract_location_phrase(raw_input)
        if labelled_location:
            location_text = labelled_location
        else:
            for label in ("location_text", "country", "address", "site", "district", "region"):
                match = re.search(rf"\b{label}\b\s*:\s*([^|;\n]+)", raw_input, flags=re.IGNORECASE)
                if match:
                    location_text = match.group(1).strip()
                    break
        if not location_text:
            if "near " in lowered:
                location_text = raw_input.split("near", 1)[1].split(".")[0].strip()
            elif " at " in lowered:
                location_text = raw_input.split(" at ", 1)[1].split(".")[0].strip()

        people_affected = None
        for pattern in (
            r"(\d+(?:\.\d+)?)\s*(million|m|thousand|k)?\s+(?:people|persons|affected)",
            r"(?:affecting|affected)\s+(\d+(?:\.\d+)?)\s*(million|m|thousand|k)?",
        ):
            match = re.search(pattern, lowered)
            if not match:
                continue
            amount = float(match.group(1))
            scale = match.group(2) or ""
            if scale in {"million", "m"}:
                amount *= 1_000_000
            elif scale in {"thousand", "k"}:
                amount *= 1_000
            people_affected = int(amount)
            break

        confidence = 0.48
        if category != CategoryKind.LOGISTICS:
            confidence += 0.08
        if location_text:
            confidence += 0.1
        if people_affected is not None:
            confidence += 0.05
        if required_resources:
            confidence += 0.06
        if any(token in lowered for token in ("source", "link", "url", "provider")):
            confidence += 0.03
        if any(token in lowered for token in ("lat", "lng", "geo_lat", "geo_long", "latitude", "longitude")):
            confidence += 0.05

        return IncidentExtraction(
            domain=domain,
            category=category,
            subcategory="HEURISTIC_TRIAGE",
            urgency=urgency,
            people_affected=people_affected,
            vulnerable_groups=vulnerable_groups,
            location_text=location_text,
            time_to_act_hours=6 if urgency == UrgencyKind.CRITICAL else 24,
            required_resources=required_resources,
            notes_for_dispatch=" ".join(notes) or "Generated with heuristic fallback; review before dispatch.",
            data_quality=DataQuality(
                missing_location=not bool(location_text),
                missing_quantity=people_affected is None and any(item.quantity is None for item in required_resources),
                needs_followup_questions=["Confirm exact location and quantity."] if not location_text else [],
            ),
            confidence=round(max(0.35, min(confidence, 0.88)), 3),
        )
