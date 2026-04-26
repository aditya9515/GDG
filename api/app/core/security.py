from __future__ import annotations

import logging
from functools import lru_cache

import firebase_admin
from fastapi import Header, HTTPException, status
from firebase_admin import auth, credentials

from app.core.config import get_settings
from app.core.dependencies import get_repository
from app.models.domain import MembershipStatus, OrgMembership, OrgRole, UserContext, UserProfile

logger = logging.getLogger("reliefops.auth")


@lru_cache(maxsize=1)
def get_firebase_app() -> firebase_admin.App | None:
    settings = get_settings()
    if not settings.firebase_project_id:
        return None
    if firebase_admin._apps:
        return firebase_admin.get_app()
    return firebase_admin.initialize_app(
        credentials.ApplicationDefault(),
        {"projectId": settings.firebase_project_id},
    )


async def get_current_user(
    authorization: str | None = Header(default=None),
    x_demo_user: str | None = Header(default=None),
    x_org_id: str | None = Header(default=None),
) -> UserContext:
    settings = get_settings()
    repository = get_repository()

    if settings.resolved_demo_auth and x_demo_user:
        profile = repository.get_user_profile(x_demo_user)
        if profile is None or not profile.enabled:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Demo user is not allowed to access this environment.",
            )
        _, memberships = repository.list_organizations_for_user(profile.uid, profile.email)
        active_membership = _select_membership(memberships, x_org_id or profile.default_org_id)
        return _context_from_profile(profile, active_membership, memberships)

    decoded = _verify_bearer_token(authorization)
    firebase_uid = decoded["uid"]
    email = decoded.get("email")
    profile = repository.get_user_profile(firebase_uid)
    if profile is None:
        invited_profile = repository.get_user_profile_by_email(email) if email else None
        profile = repository.save_user_profile(
            UserProfile(
                uid=firebase_uid,
                email=email,
                role=invited_profile.role if invited_profile is not None else OrgRole.VIEWER,
                enabled=invited_profile.enabled if invited_profile is not None else True,
                team_scope=invited_profile.team_scope if invited_profile is not None else [],
            )
        )

    if not profile.enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"User access is disabled for {profile.email or email or firebase_uid}.",
        )

    _, memberships = repository.list_organizations_for_user(firebase_uid, email)
    active_membership = _select_membership(memberships, x_org_id or profile.default_org_id)
    if active_membership is not None and active_membership.uid is None:
        active_membership = repository.bind_membership_uid(active_membership, firebase_uid)

    if memberships:
        profile.org_ids = [membership.org_id for membership in memberships]
        profile.role_by_org = {membership.org_id: membership.role for membership in memberships}
        profile.default_org_id = active_membership.org_id if active_membership else profile.default_org_id or memberships[0].org_id
        repository.save_user_profile(profile)

    return _context_from_profile(profile, active_membership, memberships)


async def get_current_org_user(
    authorization: str | None = Header(default=None),
    x_demo_user: str | None = Header(default=None),
    x_org_id: str | None = Header(default=None),
) -> UserContext:
    actor = await get_current_user(authorization=authorization, x_demo_user=x_demo_user, x_org_id=x_org_id)
    if not actor.active_org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No active organization selected. Create an organization or ask your host to invite this Gmail.",
        )
    membership = get_repository().get_org_membership(actor.active_org_id, uid=actor.uid, email=actor.email)
    if membership is None or membership.status != MembershipStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your organization membership is not active.",
        )
    actor.active_org_role = membership.role
    actor.role = str(membership.role)
    return actor


def require_host(actor: UserContext) -> None:
    if actor.active_org_role != OrgRole.HOST:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the organization host can manage members.",
        )


def _verify_bearer_token(authorization: str | None) -> dict:
    settings = get_settings()
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Bearer token or demo user header.",
        )

    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token is empty.",
        )

    app = get_firebase_app()
    if app is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Firebase is not configured for token verification.",
        )

    clock_skew_seconds = max(0, min(settings.firebase_token_clock_skew_seconds, 60))
    try:
        return auth.verify_id_token(
            token,
            app=app,
            clock_skew_seconds=clock_skew_seconds,
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("Firebase token verification failed: %s: %s", type(exc).__name__, exc)
        detail = "Firebase token verification failed."
        if settings.app_env != "production":
            detail = f"{detail} {type(exc).__name__}: {exc}"
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
        ) from exc


def _select_membership(memberships: list[OrgMembership], requested_org_id: str | None) -> OrgMembership | None:
    active = [membership for membership in memberships if membership.status == MembershipStatus.ACTIVE]
    if requested_org_id:
        for membership in active:
            if membership.org_id == requested_org_id:
                return membership
    return active[0] if active else None


def _context_from_profile(
    profile: UserProfile,
    active_membership: OrgMembership | None,
    memberships: list[OrgMembership],
) -> UserContext:
    return UserContext(
        uid=profile.uid,
        email=profile.email,
        role=str(active_membership.role if active_membership else profile.role),
        team_scope=profile.team_scope,
        active_org_id=active_membership.org_id if active_membership else None,
        active_org_role=active_membership.role if active_membership else None,
        org_ids=[membership.org_id for membership in memberships],
    )
