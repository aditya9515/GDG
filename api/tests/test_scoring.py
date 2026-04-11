from pathlib import Path
import json

from app.models.domain import IncidentExtraction, UrgencyKind
from app.services.scoring import ScoringService


def load_case(case_id: str) -> IncidentExtraction:
    rows = json.loads(Path(__file__).resolve().parents[2].joinpath("seed", "golden_cases.json").read_text(encoding="utf-8"))
    row = next(item for item in rows if item["case_id"] == case_id)
    return IncidentExtraction.model_validate(row["expected"])


def test_critical_rescue_scores_critical():
    scoring = ScoringService()
    extraction = load_case("DR-001")
    rationale = scoring.score(extraction)

    assert rationale.final_score >= 80
    assert rationale.final_urgency in {UrgencyKind.CRITICAL, UrgencyKind.HIGH}


def test_missing_location_caps_critical_to_high():
    scoring = ScoringService()
    extraction = load_case("HE-002")
    rationale = scoring.score(extraction)

    assert rationale.final_urgency == UrgencyKind.HIGH
    assert rationale.cap_reason is not None
