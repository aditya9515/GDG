from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)
HEADERS = {"X-Demo-User": "demo-coordinator", "X-Org-Id": "org-demo-relief"}
MEDICAL_HEADERS = {"X-Demo-User": "demo-medical", "X-Org-Id": "org-demo-relief"}


def test_host_can_invite_update_and_remove_member():
    created = client.post("/organizations", headers=HEADERS, json={"name": "Test Host NGO"})
    assert created.status_code == 200
    org_id = created.json()["organization"]["org_id"]

    invite = client.post(
        f"/organizations/{org_id}/invites",
        headers={**HEADERS, "X-Org-Id": org_id},
        json={"email": "new.member@example.com", "role": "VIEWER"},
    )
    assert invite.status_code == 200

    members = client.get(f"/organizations/{org_id}/members", headers={**HEADERS, "X-Org-Id": org_id})
    assert members.status_code == 200
    invited = next(item for item in members.json()["members"] if item["email"] == "new.member@example.com")

    updated = client.patch(
        f"/organizations/{org_id}/members/{invited['membership_id']}",
        headers={**HEADERS, "X-Org-Id": org_id},
        json={"role": "LOGISTICS_LEAD"},
    )
    assert updated.status_code == 200
    assert updated.json()["member"]["role"] == "LOGISTICS_LEAD"

    removed = client.delete(
        f"/organizations/{org_id}/members/{invited['membership_id']}",
        headers={**HEADERS, "X-Org-Id": org_id},
    )
    assert removed.status_code == 200
    assert removed.json()["status"] == "REMOVED"


def test_non_host_cannot_manage_members():
    response = client.post(
        "/organizations/org-demo-relief/invites",
        headers=MEDICAL_HEADERS,
        json={"email": "blocked@example.com", "role": "VIEWER"},
    )
    assert response.status_code == 403


def test_graph1_preview_edit_confirm_creates_records_and_vectors():
    run = client.post(
        "/agent/graph1/run",
        headers=HEADERS,
        json={
            "source_kind": "MANUAL_TEXT",
            "target": "incidents",
            "text": "Flood water rising near Shantinagar bridge. 4 people trapped on rooftop. Need rescue boat.",
        },
    )
    assert run.status_code == 200
    payload = run.json()["run"]
    assert payload["status"] == "WAITING_FOR_CONFIRMATION"
    assert payload["drafts"]

    edited = client.post(
        f"/agent/graph1/run/{payload['run_id']}/edit",
        headers=HEADERS,
        json={"draft_id": payload["drafts"][0]["draft_id"], "prompt": "Add urgent medical support note."},
    )
    assert edited.status_code == 200
    assert "operator prompt" in edited.json()["run"]["drafts"][0]["warnings"][-1].lower()

    confirmed = client.post(f"/agent/graph1/run/{payload['run_id']}/confirm", headers=HEADERS)
    assert confirmed.status_code == 200
    confirmed_payload = confirmed.json()["run"]
    assert confirmed_payload["status"] == "COMMITTED"
    assert confirmed_payload["committed_record_ids"]
