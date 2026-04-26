from __future__ import annotations

import json
import sys
from pathlib import Path

from google.cloud import firestore

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.core.config import get_settings


ROOT = Path(__file__).resolve().parents[2]
SEED_DIR = ROOT / "seed"
SEED_PATHS = {
    "users": SEED_DIR / "users.json",
    "organizations": SEED_DIR / "organizations.json",
    "org_memberships": SEED_DIR / "org_memberships.json",
    "org_invites": SEED_DIR / "org_invites.json",
}


def main() -> None:
    settings = get_settings()
    if not settings.firebase_project_id:
        raise SystemExit("Set FIREBASE_PROJECT_ID before bootstrapping Firestore users.")

    client = firestore.Client(project=settings.firebase_project_id, database=settings.firestore_database)

    for collection, path in SEED_PATHS.items():
        if not path.exists():
            continue
        rows = json.loads(path.read_text(encoding="utf-8"))
        for row in rows:
            doc_id = row.get("uid") or row.get("org_id") or row.get("membership_id") or row.get("invite_id")
            if not doc_id:
                continue
            if collection == "users" and row.get("email"):
                row["email_normalized"] = row["email"].strip().lower()
            client.collection(collection).document(doc_id).set(row, merge=True)
            print(f"Upserted {collection}/{doc_id}")


if __name__ == "__main__":
    main()
