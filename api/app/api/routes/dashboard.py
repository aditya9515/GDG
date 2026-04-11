from __future__ import annotations

from fastapi import APIRouter

from app.core.dependencies import get_repository
from app.models.domain import DashboardSummary

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummary)
def dashboard_summary():
    return get_repository().get_dashboard_summary()
