from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.routes.cases import (
    assign_case as assign_dispatch,
    create_case as create_incident,
    extract_case as extract_incident,
    get_case as get_incident,
    merge_case as merge_incident,
    score_case as score_incident,
    update_case_location as update_incident_location,
    recommend_case as dispatch_options,
)
from app.core.dependencies import get_repository
from app.core.security import get_current_org_user
from app.models.domain import (
    AssignCaseRequest,
    AssignCaseResponse,
    CaseDetailResponse,
    CaseListResponse,
    CreateCaseRequest,
    CreateCaseResponse,
    ExtractCaseResponse,
    MergeCaseRequest,
    MergeCaseResponse,
    RecommendationsResponse,
    ScoreCaseResponse,
    UpdateLocationRequest,
    UserContext,
)

router = APIRouter(prefix="/incidents", tags=["incidents"])


@router.post("", response_model=CreateCaseResponse)
def create_incident_route(payload: CreateCaseRequest, actor: UserContext = Depends(get_current_org_user)):
    return create_incident(payload, actor)


@router.get("", response_model=CaseListResponse)
def list_incidents(
    status: str | None = Query(default=None),
    urgency: str | None = Query(default=None),
    location_confidence: str | None = Query(default=None),
    actor: UserContext = Depends(get_current_org_user),
):
    items = get_repository().list_cases(status=status, urgency=urgency)
    items = [item for item in items if item.org_id in {None, actor.active_org_id}]
    if location_confidence:
        items = [item for item in items if item.location_confidence == location_confidence]
    return CaseListResponse(items=items)


@router.get("/{case_id}", response_model=CaseDetailResponse)
def get_incident_route(case_id: str, actor: UserContext = Depends(get_current_org_user)):
    return get_incident(case_id, actor)


@router.post("/{case_id}/extract", response_model=ExtractCaseResponse)
async def extract_incident_route(case_id: str, actor: UserContext = Depends(get_current_org_user)):
    return await extract_incident(case_id, actor)


@router.post("/{case_id}/score", response_model=ScoreCaseResponse)
def score_incident_route(case_id: str, actor: UserContext = Depends(get_current_org_user)):
    return score_incident(case_id, actor)


@router.post("/{case_id}/dispatch-options", response_model=RecommendationsResponse)
async def incident_dispatch_options(case_id: str, actor: UserContext = Depends(get_current_org_user)):
    return await dispatch_options(case_id, actor=actor)


@router.post("/{case_id}/dispatch", response_model=AssignCaseResponse)
def dispatch_incident(case_id: str, payload: AssignCaseRequest, actor: UserContext = Depends(get_current_org_user)):
    return assign_dispatch(case_id, payload, actor)


@router.post("/{case_id}/location", response_model=CaseDetailResponse)
def incident_location(case_id: str, payload: UpdateLocationRequest, actor: UserContext = Depends(get_current_org_user)):
    return update_incident_location(case_id, payload, actor)


@router.post("/{case_id}/merge", response_model=MergeCaseResponse)
def merge_incident_route(case_id: str, payload: MergeCaseRequest, actor: UserContext = Depends(get_current_org_user)):
    return merge_incident(case_id, payload, actor)
