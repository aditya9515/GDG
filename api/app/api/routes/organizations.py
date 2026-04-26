from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.dependencies import get_repository
from app.core.security import get_current_user
from app.models.domain import (
    CreateOrganizationRequest,
    MembersResponse,
    MembershipStatus,
    OrganizationResponse,
    OrganizationsResponse,
    OrgRole,
    ResetOrganizationDataRequest,
    ResetOrganizationDataResponse,
    UpdateMemberRequest,
    UserContext,
)

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.post("", response_model=OrganizationResponse)
def create_organization(payload: CreateOrganizationRequest, actor: UserContext = Depends(get_current_user)):
    organization, membership = get_repository().create_organization(payload.name, actor)
    return OrganizationResponse(organization=organization, membership=membership)


@router.get("", response_model=OrganizationsResponse)
def list_organizations(actor: UserContext = Depends(get_current_user)):
    organizations, memberships = get_repository().list_organizations_for_user(actor.uid, actor.email)
    return OrganizationsResponse(items=organizations, memberships=memberships)


@router.get("/{org_id}", response_model=OrganizationResponse)
def get_organization(org_id: str, actor: UserContext = Depends(get_current_user)):
    repository = get_repository()
    organization = repository.get_organization(org_id)
    membership = repository.get_org_membership(org_id, uid=actor.uid, email=actor.email)
    if organization is None or membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found.")
    return OrganizationResponse(organization=organization, membership=membership)


@router.get("/{org_id}/members", response_model=MembersResponse)
def list_members(org_id: str, actor: UserContext = Depends(get_current_user)):
    repository = get_repository()
    organization = repository.get_organization(org_id)
    membership = _require_host(org_id, actor)
    if organization is None or membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found.")
    return MembersResponse(
        organization=organization,
        members=repository.list_org_members(org_id),
    )


@router.patch("/{org_id}/members/{membership_id}")
def update_member(
    org_id: str,
    membership_id: str,
    payload: UpdateMemberRequest,
    actor: UserContext = Depends(get_current_user),
):
    _require_host(org_id, actor)
    member = get_repository().update_org_member(org_id, membership_id, payload.role, payload.status, actor)
    return {"member": member}


@router.delete("/{org_id}/members/{membership_id}")
def remove_member(org_id: str, membership_id: str, actor: UserContext = Depends(get_current_user)):
    host = _require_host(org_id, actor)
    if host.membership_id == membership_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Host cannot remove themselves until ownership transfer is implemented.",
        )
    member = get_repository().update_org_member(org_id, membership_id, None, MembershipStatus.REMOVED, actor)
    return {"member": member, "status": "REMOVED"}


@router.post("/{org_id}/reset-data", response_model=ResetOrganizationDataResponse)
def reset_organization_data(
    org_id: str,
    payload: ResetOrganizationDataRequest,
    actor: UserContext = Depends(get_current_user),
):
    _require_host(org_id, actor)
    if payload.confirmation != "RESET_ORG_DATA":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Type RESET_ORG_DATA to confirm organization data reset.",
        )
    try:
        counts = get_repository().reset_organization_data(org_id, actor)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return ResetOrganizationDataResponse(
        org_id=org_id,
        deleted_counts=counts,
        request_id=f"req-{uuid.uuid4().hex[:12]}",
    )


def _require_host(org_id: str, actor: UserContext):
    membership = get_repository().get_org_membership(org_id, uid=actor.uid, email=actor.email)
    if membership is None or membership.status != MembershipStatus.ACTIVE:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not belong to this organization.")
    if membership.role != OrgRole.HOST:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the host can manage organization members.")
    return membership
