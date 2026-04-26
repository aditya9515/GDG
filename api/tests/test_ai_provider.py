import json

from app.api.routes.ai import ai_status
from app.core.config import Settings
from app.models.domain import IncidentExtraction
from app.services.extractor import ExtractionService


def valid_extraction(category: str = "RESCUE") -> str:
    return json.dumps(
        {
            "domain": "DISASTER_RELIEF",
            "category": category,
            "subcategory": "TEST",
            "urgency": "HIGH",
            "people_affected": 3,
            "vulnerable_groups": ["UNKNOWN"],
            "location_text": "Test bridge",
            "time_to_act_hours": 6,
            "required_resources": [{"resource_type": "RESCUE_BOAT", "quantity": 1, "unit": "unit"}],
            "notes_for_dispatch": "Local model extracted this test case.",
            "data_quality": {
                "missing_location": False,
                "missing_quantity": False,
                "needs_followup_questions": [],
            },
            "confidence": 0.71,
        }
    )


class FakeOllama:
    def __init__(self, responses: list[str]):
        self.responses = responses
        self.calls = 0

    def generate(self, _: str) -> str:
        self.calls += 1
        index = min(self.calls - 1, len(self.responses) - 1)
        return self.responses[index]

    def is_available(self) -> bool:
        return True


def test_ollama_provider_never_requires_gemini(monkeypatch):
    service = ExtractionService(
        Settings(ai_provider="ollama", gemini_enabled=False, gemini_api_key="unused", gemma4_enabled=True),
        ollama_client=FakeOllama([valid_extraction()]),
    )

    def fail_gemini(_: str):
        raise AssertionError("Gemini should not be called when AI_PROVIDER=ollama")

    monkeypatch.setattr(service, "_extract_with_gemini", fail_gemini)

    result = service.extract_with_metadata("Flood rescue near bridge")

    assert result.provider_used == "Ollama"
    assert result.extraction.category == "RESCUE"


def test_auto_falls_from_gemini_to_ollama(monkeypatch):
    service = ExtractionService(
        Settings(ai_provider="auto", gemini_enabled=True, gemini_api_key="test-key", gemma4_enabled=True),
        ollama_client=FakeOllama([valid_extraction("MEDICAL")]),
    )
    service.client = object()

    def fail_gemini(_: str):
        raise RuntimeError("quota exhausted")

    monkeypatch.setattr(service, "_extract_with_gemini", fail_gemini)

    result = service.extract_with_metadata("Ambulance needed")

    assert result.provider_used == "Ollama"
    assert result.extraction.category == "MEDICAL"
    assert any(item.startswith("gemini:") for item in result.provider_fallbacks)


def test_gemma4_disabled_removes_ollama_from_auto_fallback_order():
    settings = Settings(ai_provider="auto", gemini_enabled=True, gemini_api_key="test-key", gemma4_enabled=False)

    assert settings.provider_fallback_order == ["gemini", "heuristic"]


def test_gemini_provider_with_gemma4_disabled_never_calls_ollama(monkeypatch):
    fake_ollama = FakeOllama([valid_extraction("MEDICAL")])
    service = ExtractionService(
        Settings(ai_provider="gemini", gemini_enabled=True, gemini_api_key="test-key", gemma4_enabled=False),
        ollama_client=fake_ollama,
    )
    service.client = object()

    monkeypatch.setattr(service, "_extract_with_gemini", lambda _: IncidentExtraction.model_validate(json.loads(valid_extraction("MEDICAL"))))

    result = service.extract_with_metadata("Ambulance needed")

    assert result.provider_used == "Gemini"
    assert result.extraction.category == "MEDICAL"
    assert fake_ollama.calls == 0


def test_ollama_provider_becomes_heuristic_when_gemma4_disabled():
    settings = Settings(ai_provider="ollama", gemini_enabled=True, gemini_api_key="test-key", gemma4_enabled=False)

    assert settings.resolved_ai_provider == "heuristic"
    assert settings.provider_fallback_order == ["heuristic"]


def test_ai_status_reports_gemini_ready_and_gemma4_disabled():
    settings = Settings(ai_provider="gemini", gemini_enabled=True, gemini_api_key="test-key", gemma4_enabled=False)
    status = ai_status(settings=settings, ollama=FakeOllama([valid_extraction()]))

    assert status.provider_mode == "gemini"
    assert status.gemini_enabled is True
    assert status.gemini_configured is True
    assert status.gemma4_enabled is False
    assert status.ollama_reachable is False
    assert status.fallback_order == ["gemini", "heuristic"]


def test_invalid_ollama_json_repairs_once():
    fake = FakeOllama(["not json", valid_extraction()])
    service = ExtractionService(
        Settings(ai_provider="ollama", gemini_enabled=False, gemma4_enabled=True),
        ollama_client=fake,
    )

    result = service.extract_with_metadata("Flood rescue near bridge")

    assert fake.calls == 2
    assert result.provider_used == "Ollama"
    assert result.warnings


def test_invalid_ollama_json_falls_to_heuristic():
    service = ExtractionService(
        Settings(ai_provider="ollama", gemini_enabled=False, gemma4_enabled=True),
        ollama_client=FakeOllama(["not json", "still not json"]),
    )

    result = service.extract_with_metadata("Need water tanker at camp")

    assert result.provider_used == "Heuristic"
    assert any(item.startswith("ollama:") for item in result.provider_fallbacks)
    assert result.extraction.category == "WATER"
