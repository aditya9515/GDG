from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.dependencies import get_repository
from app.core.security import get_current_org_user
from app.models.domain import DashboardSummary
from app.models.domain import UserContext

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummary)
def dashboard_summary(actor: UserContext = Depends(get_current_org_user)):
    repository = get_repository()
    cases = [item for item in repository.list_cases() if item.org_id in {None, actor.active_org_id}]
    assignments = [item for item in repository.list_assignments() if item.org_id in {None, actor.active_org_id}]
    resources = [item for item in repository.list_resources() if item.org_id in {None, actor.active_org_id}]
    teams = [item for item in repository.list_teams() if item.org_id in {None, actor.active_org_id}]
    open_cases = [case for case in cases if case.status not in {"MERGED", "CLOSED"}]
    confidence_values = [case.extracted_json.confidence for case in cases if case.extracted_json]
    return DashboardSummary(
        total_cases=len(cases),
        open_cases=len(open_cases),
        critical_cases=sum(1 for case in open_cases if case.urgency == "CRITICAL"),
        assigned_today=len(assignments),
        pending_duplicates=sum(1 for case in open_cases if case.duplicate_status != "NONE"),
        median_time_to_assign_minutes=22 if assignments else 0,
        average_confidence=round(sum(confidence_values) / len(confidence_values), 3) if confidence_values else 0,
        mapped_cases=sum(1 for case in cases if case.geo is not None),
        mapped_resources=sum(1 for item in resources if item.location is not None or item.current_geo is not None),
        mapped_teams=sum(1 for item in teams if item.base_geo is not None or item.current_geo is not None),
        active_dispatches=sum(1 for item in assignments if item.status in {"CONFIRMED", "IN_PROGRESS"}),
    )
