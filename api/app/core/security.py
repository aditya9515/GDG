from __future__ import annotations

from functools import lru_cache

import firebase_admin
from fastapi import Header, HTTPException, status
from firebase_admin import auth, credentials

from app.core.config import get_settings
from app.core.dependencies import get_repository
from app.models.domain import UserContext


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
) -> UserContext:
    settings = get_settings()
    repository = get_repository()

    if settings.allow_demo_auth and x_demo_user:
        profile = repository.get_user_profile(x_demo_user)
        if profile is None or not profile.enabled:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Demo user is not allowed to access this environment.",
            )
        return UserContext(uid=profile.uid, email=profile.email, role=profile.role)

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

    try:
        decoded = auth.verify_id_token(token, app=app)
    except Exception as exc:  # pragma: no cover
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Firebase token verification failed.",
        ) from exc

    profile = repository.get_user_profile(decoded["uid"])
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not provisioned for ReliefOps.",
        )
    if not profile.enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User access is disabled.",
        )

    return UserContext(uid=profile.uid, email=profile.email or decoded.get("email"), role=profile.role)
