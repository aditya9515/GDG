from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
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
from app.services.ollama import OllamaClient


ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = ROOT / "docs" / "schemas" / "incident-extraction.schema.json"
GOLDEN_PATH = ROOT / "seed" / "golden_cases.json"


@dataclass
class ExtractionResult:
    extraction: IncidentExtraction
    provider_used: str
    provider_fallbacks: list[str] = field(default_factory=list)
    schema_validated: bool = True
    warnings: list[str] = field(default_factory=list)


class ExtractionService:
    def __init__(self, settings: Settings, ollama_client: OllamaClient | None = None) -> None:
        self.settings = settings
        self.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.golden_rows = json.loads(GOLDEN_PATH.read_text(encoding="utf-8")) if GOLDEN_PATH.exists() else []
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

    def extract_with_metadata(self, raw_input: str) -> ExtractionResult:
        fallbacks: list[str] = []
        warnings: list[str] = []

        for provider in self.settings.provider_fallback_order:
            try:
                if provider == "golden":
                    golden = self._find_golden(raw_input)
                    if golden is not None:
                        return ExtractionResult(golden, "Golden", fallbacks, True, warnings)
                    fallbacks.append("golden:no_match")
                    continue

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
