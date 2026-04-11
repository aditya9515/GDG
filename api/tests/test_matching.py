from app.models.domain import CaseRecord
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
