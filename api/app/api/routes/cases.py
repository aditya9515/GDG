from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.dependencies import (
    get_duplicate_service,
    get_extraction_service,
    get_geocoding_service,
    get_matching_service,
    get_repository,
    get_routing_service,
    get_scoring_service,
    get_token_service,
)
from app.core.security import get_current_user
from app.models.domain import (
    AssignCaseRequest,
    AssignCaseResponse,
    AssignmentDecision,
    CaseDetailResponse,
    CaseEvent,
    CaseListResponse,
    CaseStatus,
    CreateCaseRequest,
    CreateCaseResponse,
    ExtractCaseResponse,
    LocationConfidence,
    MergeCaseRequest,
    MergeCaseResponse,
    RecommendationsResponse,
    ScoreCaseResponse,
    UpdateLocationRequest,
    UserContext,
)

router = APIRouter(prefix="/cases", tags=["cases"])


@router.post("", response_model=CreateCaseResponse)
def create_case(
    payload: CreateCaseRequest,
    actor: UserContext = Depends(get_current_user),
):
    repository = get_repository()
    case = repository.create_case(payload.raw_input, payload.source_channel, actor)
    return CreateCaseResponse(
        case_id=case.case_id,
        incident_id=case.incident_id,
        status=case.status,
        request_id=f"req-{uuid.uuid4().hex[:12]}",
    )


@router.get("", response_model=CaseListResponse)
def list_cases(
    status: str | None = Query(default=None),
    urgency: str | None = Query(default=None),
):
    repository = get_repository()
    return CaseListResponse(items=repository.list_cases(status=status, urgency=urgency))


@router.get("/{case_id}", response_model=CaseDetailResponse)
def get_case(case_id: str):
    repository = get_repository()
    return repository.get_case_detail(case_id)


@router.post("/{case_id}/extract", response_model=ExtractCaseResponse)
async def extract_case(
    case_id: str,
    actor: UserContext = Depends(get_current_user),
):
    repository = get_repository()
    extractor = get_extraction_service()
    geocoder = get_geocoding_service()
    duplicate_service = get_duplicate_service()
    token_service = get_token_service()

    case = repository.get_case(case_id)
    extraction = extractor.extract(case.raw_input)
    case = repository.save_extraction(
        case_id,
        extraction,
        status=CaseStatus.NEEDS_REVIEW if extraction.confidence < 0.4 else CaseStatus.EXTRACTED,
    )
    geo = await geocoder.geocode(extraction.location_text)
    if geo is not None:
        case = repository.update_case_location(
            case_id,
            extraction.location_text,
            geo.lat,
            geo.lng,
            LocationConfidence.APPROXIMATE if extraction.data_quality.missing_location else LocationConfidence.EXACT,
        )
    tokens = token_service.from_incident(case, extraction)
    repository.save_info_tokens(case_id, tokens)
    repository.record_event(
        CaseEvent(
            event_id=f"evt-{uuid.uuid4().hex[:10]}",
            case_id=case_id,
            event_type="CASE_EXTRACTED",
            actor_uid=actor.uid,
            payload={"confidence": extraction.confidence, "token_count": len(tokens)},
        )
    )
    duplicates = duplicate_service.find_duplicates(case, repository.list_recent_open_cases(case_id))
    repository.save_duplicate_links(case_id, duplicates)
    return ExtractCaseResponse(
        case_id=case.case_id,
        incident_id=case.incident_id,
        extracted=extraction,
        confidence=extraction.confidence,
        duplicate_candidates=duplicates,
        request_id=f"req-{uuid.uuid4().hex[:12]}",
    )


@router.post("/{case_id}/score", response_model=ScoreCaseResponse)
def score_case(
    case_id: str,
    actor: UserContext = Depends(get_current_user),
):
    repository = get_repository()
    scorer = get_scoring_service()
    case = repository.get_case(case_id)
    if case.extracted_json is None:
        raise HTTPException(status_code=400, detail="Case must be extracted before it can be scored.")
    rationale = scorer.score(case.extracted_json)
    repository.save_scoring(case_id, rationale.final_score, rationale, rationale.final_urgency)
    repository.record_event(
        CaseEvent(
            event_id=f"evt-{uuid.uuid4().hex[:10]}",
            case_id=case_id,
            event_type="CASE_SCORED",
            actor_uid=actor.uid,
            payload={"priority_score": rationale.final_score, "urgency": rationale.final_urgency},
        )
    )
    return ScoreCaseResponse(
        case_id=case_id,
        incident_id=case.incident_id,
        priority_score=rationale.final_score,
        urgency=rationale.final_urgency,
        rationale=rationale,
        request_id=f"req-{uuid.uuid4().hex[:12]}",
    )


@router.post("/{case_id}/recommendations", response_model=RecommendationsResponse)
async def recommend_case(
    case_id: str,
    max_results: int = 3,
    actor: UserContext = Depends(get_current_user),
):
    repository = get_repository()
    matcher = get_matching_service()
    routing = get_routing_service()
    case = repository.get_case(case_id)
    teams = repository.list_teams()
    team_lookup = {item.team_id: item for item in teams}
    recommendations, reason = matcher.recommend(
        case,
        teams,
        repository.list_volunteers(),
        repository.list_resources(),
        max_results,
    )

    for recommendation in recommendations:
        if recommendation.team_id is None:
            continue
        team = team_lookup.get(recommendation.team_id)
        if team is None:
            continue
        route = await routing.route(team.current_geo or team.base_geo, case.geo)
        recommendation.route_summary = route
        recommendation.eta_minutes = route.duration_minutes

    repository.save_recommendations(case_id, recommendations)
    repository.record_event(
        CaseEvent(
            event_id=f"evt-{uuid.uuid4().hex[:10]}",
            case_id=case_id,
            event_type="RECOMMENDATIONS_GENERATED",
            actor_uid=actor.uid,
            payload={"count": len(recommendations), "unassigned_reason": reason},
        )
    )
    return RecommendationsResponse(
        case_id=case_id,
        incident_id=case.incident_id,
        recommendations=recommendations,
        unassigned_reason=reason,
        request_id=f"req-{uuid.uuid4().hex[:12]}",
    )


@router.post("/{case_id}/location", response_model=CaseDetailResponse)
def update_case_location(
    case_id: str,
    payload: UpdateLocationRequest,
    actor: UserContext = Depends(get_current_user),
):
    repository = get_repository()
    repository.update_case_location(
        case_id,
        payload.location_text,
        payload.lat,
        payload.lng,
        payload.location_confidence,
    )
    repository.record_event(
        CaseEvent(
            event_id=f"evt-{uuid.uuid4().hex[:10]}",
            case_id=case_id,
            event_type="LOCATION_CONFIRMED",
            actor_uid=actor.uid,
            payload={
                "location_text": payload.location_text,
                "lat": payload.lat,
                "lng": payload.lng,
                "location_confidence": payload.location_confidence,
            },
        )
    )
    return repository.get_case_detail(case_id)


@router.post("/{case_id}/assign", response_model=AssignCaseResponse)
def assign_case(
    case_id: str,
    payload: AssignCaseRequest,
    actor: UserContext = Depends(get_current_user),
):
    repository = get_repository()
    recommendation = getattr(repository, "recommendations", {}).get(case_id, [None])[0] if hasattr(repository, "recommendations") else None
    team_id = payload.team_id or (recommendation.team_id if recommendation else None)
    resource_ids = payload.resource_ids or (recommendation.resource_ids if recommendation else [])
    assignment = AssignmentDecision(
        assignment_id=f"asg-{uuid.uuid4().hex[:10]}",
        case_id=case_id,
        incident_id=case_id,
        team_id=team_id,
        volunteer_ids=payload.volunteer_ids or (recommendation.volunteer_ids if recommendation else []),
        resource_ids=resource_ids,
        resource_allocations=payload.resource_allocations or (recommendation.resource_allocations if recommendation else []),
        match_score=recommendation.match_score if recommendation else 0.5,
        eta_minutes=recommendation.eta_minutes if recommendation else None,
        route_summary=recommendation.route_summary if recommendation else None,
        confirmed_by=actor.uid,
    )
    repository.create_assignment(assignment)
    repository.record_event(
        CaseEvent(
            event_id=f"evt-{uuid.uuid4().hex[:10]}",
            case_id=case_id,
            event_type="CASE_ASSIGNED",
            actor_uid=actor.uid,
            payload={"assignment_id": assignment.assignment_id, "team_id": team_id},
        )
    )
    return AssignCaseResponse(
        assignment_id=assignment.assignment_id,
        status=assignment.status,
        request_id=f"req-{uuid.uuid4().hex[:12]}",
    )


@router.post("/{case_id}/merge", response_model=MergeCaseResponse)
def merge_case(
    case_id: str,
    payload: MergeCaseRequest,
    actor: UserContext = Depends(get_current_user),
):
    repository = get_repository()
    repository.merge_case(case_id, payload.merge_into_case_id, actor)
    return MergeCaseResponse(
        status="MERGED",
        merged_case_id=payload.merge_into_case_id,
        request_id=f"req-{uuid.uuid4().hex[:12]}",
    )
