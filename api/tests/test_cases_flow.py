from fastapi.testclient import TestClient

from app.main import app
from app.core.dependencies import get_repository
from app.models.domain import UserProfile


client = TestClient(app)
HEADERS = {"X-Demo-User": "demo-coordinator"}


def test_case_pipeline_happy_path():
    created = client.post(
        "/cases",
        headers=HEADERS,
        json={"raw_input": "Flood water rising fast near Shantinagar bridge. 4 people on rooftop incl 1 child. Need rescue boat ASAP."},
    )
    assert created.status_code == 200
    case_id = created.json()["case_id"]

    extracted = client.post(f"/cases/{case_id}/extract", headers=HEADERS)
    assert extracted.status_code == 200
    assert extracted.json()["extracted"]["category"] == "RESCUE"

    scored = client.post(f"/cases/{case_id}/score", headers=HEADERS)
    assert scored.status_code == 200
    assert scored.json()["urgency"] in {"CRITICAL", "HIGH"}

    recommendations = client.post(f"/cases/{case_id}/recommendations", headers=HEADERS)
    assert recommendations.status_code == 200
    assert recommendations.json()["recommendations"]

    top = recommendations.json()["recommendations"][0]
    assigned = client.post(
        f"/cases/{case_id}/assign",
        headers=HEADERS,
        json={"volunteer_ids": top["volunteer_ids"], "resource_allocations": top["resource_allocations"]},
    )
    assert assigned.status_code == 200

    detail = client.get(f"/cases/{case_id}", headers=HEADERS)
    assert detail.status_code == 200
    assert detail.json()["case"]["status"] == "ASSIGNED"


def test_me_returns_seeded_demo_profile():
    response = client.get("/me", headers=HEADERS)

    assert response.status_code == 200
    payload = response.json()
    assert payload["uid"] == "demo-coordinator"
    assert payload["role"] == "HOST"
    assert payload["enabled"] is True
    assert payload["is_host"] is True
    assert payload["organizations"][0]["org_id"] == "org-demo-relief"


def test_repository_can_resolve_email_invite_before_firebase_uid_binding():
    repository = get_repository()
    invited = UserProfile(
        uid="invite-real-operator",
        email="real.operator@example.com",
        role="INCIDENT_COORDINATOR",
        enabled=True,
    )

    repository.save_user_profile(invited)
    found = repository.get_user_profile_by_email("REAL.OPERATOR@example.com")

    assert found is not None
    assert found.uid == "invite-real-operator"

    bound = repository.save_user_profile(
        UserProfile(
            uid="firebase-real-uid",
            email="real.operator@example.com",
            role=found.role,
            enabled=found.enabled,
            team_scope=found.team_scope,
        )
    )

    assert bound.uid == "firebase-real-uid"
    assert repository.get_user_profile("firebase-real-uid") is not None
