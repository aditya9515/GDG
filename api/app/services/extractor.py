from __future__ import annotations

import json
from pathlib import Path

from google import genai
from google.genai import types

from app.core.config import Settings
from app.models.domain import (
    CategoryKind,
    DataQuality,
    DomainKind,
    IncidentExtraction,
    ResourceNeed,
    UrgencyKind,
    VulnerableGroup,
)


ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = ROOT / "docs" / "schemas" / "incident-extraction.schema.json"
GOLDEN_PATH = ROOT / "seed" / "golden_cases.json"


class ExtractionService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.golden_rows = json.loads(GOLDEN_PATH.read_text(encoding="utf-8")) if GOLDEN_PATH.exists() else []
        self.client = genai.Client(api_key=settings.gemini_api_key) if settings.gemini_api_key else None

    def extract(self, raw_input: str) -> IncidentExtraction:
        if self.settings.extraction_provider in {"auto", "golden"}:
            golden = self._find_golden(raw_input)
            if golden is not None:
                return golden

        if self.client and self.settings.extraction_provider in {"auto", "gemini"}:
            return self._extract_with_gemini(raw_input)

        return self._extract_heuristically(raw_input)

    def extract_document(self, filename: str, content_type: str, content: bytes) -> IncidentExtraction:
        if self.client and self.settings.extraction_provider in {"auto", "gemini"}:
            return self._extract_document_with_gemini(filename, content_type, content)
        fallback_text = f"{filename} {content_type}".strip()
        return self._extract_heuristically(fallback_text)

    def _find_golden(self, raw_input: str) -> IncidentExtraction | None:
        for row in self.golden_rows:
            if row["raw_input"].strip() == raw_input.strip():
                return IncidentExtraction.model_validate(row["expected"])
        return None

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
        elif "water" in lowered:
            category = CategoryKind.WATER
            urgency = UrgencyKind.HIGH
            required_resources = [ResourceNeed(resource_type="WATER_TANKER", quantity=1, unit="unit")]
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

        if "child" in lowered or "infant" in lowered or "kids" in lowered:
            vulnerable_groups = [VulnerableGroup.CHILDREN_UNDER5]
        elif "elderly" in lowered:
            vulnerable_groups = [VulnerableGroup.ELDERLY]
        elif "pregnant" in lowered or "labour" in lowered:
            vulnerable_groups = [VulnerableGroup.PREGNANT]
            urgency = UrgencyKind.CRITICAL

        if "near " in lowered:
            location_text = raw_input.split("near", 1)[1].split(".")[0].strip()
        elif "at " in lowered:
            location_text = raw_input.split("at", 1)[1].split(".")[0].strip()

        return IncidentExtraction(
            domain=domain,
            category=category,
            subcategory="HEURISTIC_TRIAGE",
            urgency=urgency,
            people_affected=None,
            vulnerable_groups=vulnerable_groups,
            location_text=location_text,
            time_to_act_hours=6 if urgency == UrgencyKind.CRITICAL else 24,
            required_resources=required_resources,
            notes_for_dispatch=" ".join(notes) or "Generated with heuristic fallback; review before dispatch.",
            data_quality=DataQuality(
                missing_location=not bool(location_text),
                missing_quantity=True,
                needs_followup_questions=["Confirm exact location and quantity."] if not location_text else [],
            ),
            confidence=0.52,
        )
