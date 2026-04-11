from __future__ import annotations

from fastapi import APIRouter

from app.core.dependencies import get_repository
from app.models.domain import ResourcesResponse, VolunteersResponse

router = APIRouter(tags=["lookups"])


@router.get("/volunteers", response_model=VolunteersResponse)
def list_volunteers():
    return VolunteersResponse(items=get_repository().list_volunteers())


@router.get("/resources", response_model=ResourcesResponse)
def list_resources():
    return ResourcesResponse(items=get_repository().list_resources())
