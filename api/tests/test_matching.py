from app.models.domain import AvailabilityStatus, CaseRecord, Team
from app.repositories.memory import MemoryRepository
from app.services.matching import MatchingService


def test_recommendations_prioritize_matching_rescue_team():
    repository = MemoryRepository()
    case = repository.get_case("DR-001")
    service = MatchingService()

    recommendations, reason = service.recommend(case, repository.list_volunteers(), repository.list_resources())

    assert reason is None
    assert recommendations
    assert recommendations[0].volunteer_ids[0] == "VOL-001"


def test_unextracted_case_returns_reason():
    repository = MemoryRepository()
    case = CaseRecord(case_id="CASE-X", raw_input="Unknown report", source_channel="MANUAL")
    service = MatchingService()

    recommendations, reason = service.recommend(case, repository.list_volunteers(), repository.list_resources())

    assert recommendations == []
    assert reason is not None


def test_team_level_recommendation_when_volunteer_roster_is_missing():
    repository = MemoryRepository()
    case = repository.get_case("DR-001")
    assert case.extracted_json is not None
    required_tags = [
        str(case.extracted_json.category),
        case.extracted_json.subcategory,
        *[need.resource_type for need in case.extracted_json.required_resources],
    ]
    team = Team(
        team_id="TEAM-ROSTERLESS",
        display_name="Rosterless rescue unit",
        capability_tags=required_tags,
        member_ids=["VOL-MISSING-1", "VOL-MISSING-2"],
        service_radius_km=80,
        base_label="Rescue base",
        base_geo=case.geo,
        current_geo=case.geo,
        availability_status=AvailabilityStatus.AVAILABLE,
    )
    service = MatchingService()

    result = service.generate_candidates_for_case(case, [team], [], repository.list_resources())

    assert result.recommendations
    assert result.recommendations[0].team_id == "TEAM-ROSTERLESS"
    assert result.recommendations[0].volunteer_ids == []
    assert result.unassigned_reason is None
