from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import UTC, datetime
from pathlib import Path

import firebase_admin
from firebase_admin import auth, credentials
from google.cloud import firestore

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.core.config import get_settings
from app.models.domain import OrgRole, UserProfile


ROLES = {item.value for item in OrgRole}


def get_firebase_app(project_id: str) -> firebase_admin.App:
    if firebase_admin._apps:
        return firebase_admin.get_app()
    return firebase_admin.initialize_app(
        credentials.ApplicationDefault(),
        {"projectId": project_id},
    )


def invite_uid_for_email(email: str) -> str:
    digest = hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()[:16]
    return f"invite-{digest}"


def stable_id(prefix: str, value: str, size: int = 12) -> str:
    digest = hashlib.sha256(value.strip().lower().encode("utf-8")).hexdigest()[:size]
    return f"{prefix}-{digest}"


def resolve_uid(email: str, project_id: str, require_auth_user: bool) -> tuple[str, bool]:
    app = get_firebase_app(project_id)
    try:
        user = auth.get_user_by_email(email, app=app)
        return user.uid, True
    except auth.UserNotFoundError:
        if require_auth_user:
            raise SystemExit(
                f"No Firebase Auth user exists for {email}. Sign in once with Google, then rerun this command."
            )
        return invite_uid_for_email(email), False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Provision a Google account for ReliefOps access.")
    parser.add_argument("--email", required=True, help="Google account email to authorize.")
    parser.add_argument(
        "--role",
        default="INCIDENT_COORDINATOR",
        choices=sorted(ROLES),
        help="Operator role to assign.",
    )
    parser.add_argument(
        "--team-scope",
        default="",
        help="Optional comma-separated team ids this operator can manage.",
    )
    parser.add_argument(
        "--disabled",
        action="store_true",
        help="Create or update the user as disabled.",
    )
    parser.add_argument(
        "--require-auth-user",
        action="store_true",
        help="Fail unless the Google account already exists in Firebase Auth.",
    )
    parser.add_argument(
        "--org-id",
        default="",
        help="Optional organization id to add this Gmail to.",
    )
    parser.add_argument(
        "--org-name",
        default="",
        help="Create the organization with this name if --org-id is missing or not found.",
    )
    parser.add_argument(
        "--make-host",
        action="store_true",
        help="Assign HOST role for the organization membership.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    if not settings.firebase_project_id:
        raise SystemExit("Set FIREBASE_PROJECT_ID before provisioning an operator.")

    email = args.email.strip().lower()
    uid, matched_auth_user = resolve_uid(email, settings.firebase_project_id, args.require_auth_user)
    org_id = args.org_id.strip()
    if not org_id and args.org_name.strip():
        org_id = stable_id("org", args.org_name)
    role = "HOST" if args.make_host else args.role
    profile = UserProfile(
        uid=uid,
        email=email,
        role=role,
        enabled=not args.disabled,
        team_scope=[item.strip() for item in args.team_scope.split(",") if item.strip()],
        default_org_id=org_id or None,
        org_ids=[org_id] if org_id else [],
        role_by_org={org_id: role} if org_id else {},
    )
    payload = profile.model_dump(mode="json")
    payload["email_normalized"] = email

    client = firestore.Client(project=settings.firebase_project_id, database=settings.firestore_database)
    client.collection("users").document(uid).set(payload, merge=True)

    if org_id:
        org_ref = client.collection("organizations").document(org_id)
        org_doc = org_ref.get()
        if not org_doc.exists:
            if not args.org_name.strip():
                raise SystemExit(f"Organization {org_id} does not exist. Pass --org-name to create it.")
            org_ref.set(
                {
                    "org_id": org_id,
                    "name": args.org_name.strip(),
                    "host_uid": uid,
                    "host_email": email,
                    "status": "ACTIVE",
                    "settings": {},
                    "created_at": datetime.now(tz=UTC).isoformat(),
                },
                merge=True,
            )
            role = "HOST"

        membership_id = f"{org_id}-{stable_id('member', email)}"
        client.collection("org_memberships").document(membership_id).set(
            {
                "membership_id": membership_id,
                "org_id": org_id,
                "uid": uid if matched_auth_user else None,
                "email": email,
                "role": role,
                "status": "ACTIVE",
                "invited_by": "provision_script",
                "joined_at": datetime.now(tz=UTC).isoformat() if matched_auth_user else None,
                "disabled_at": None,
            },
            merge=True,
        )
        if not matched_auth_user:
            invite_id = f"{org_id}-{stable_id('invite', email)}"
            client.collection("org_invites").document(invite_id).set(
                {
                    "invite_id": invite_id,
                    "org_id": org_id,
                    "email": email,
                    "role": role,
                    "invited_by": "provision_script",
                    "status": "INVITED",
                    "created_at": datetime.now(tz=UTC).isoformat(),
                    "accepted_at": None,
                },
                merge=True,
            )
        client.collection("users").document(uid).set(
            {
                "role": role,
                "default_org_id": org_id,
                "org_ids": [org_id],
                "role_by_org": {org_id: role},
            },
            merge=True,
        )

    source = "Firebase Auth uid" if matched_auth_user else "email invite placeholder"
    print(f"Provisioned {email} as {role} using {source}: {uid}")
    if org_id:
        print(f"Organization access: {org_id}")
    if not matched_auth_user:
        print("After this email signs in with Google, the backend will bind the invite to the real Firebase uid.")


if __name__ == "__main__":
    main()
