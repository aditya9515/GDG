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


def test_graph1_file_csv_preview_is_staged_until_confirm():
    csv_bytes = (
        b"raw_input,category,location_text,lat,lng,required_resources,priority_feature,map_feature\n"
        b'"Flood water rising near Shantinagar bridge. 4 people trapped on rooftop. Need rescue boat.",RESCUE,"Shantinagar bridge, Patna",25.5941,85.1376,RESCUE_BOAT,ROOFTOP_RESCUE,river bridge\n'
    )
    preview = client.post(
        "/agent/graph1/run-file",
        headers=HEADERS,
        data={"source_kind": "CSV", "target": "incidents"},
        files={"file": ("incidents.csv", csv_bytes, "text/csv")},
    )

    assert preview.status_code == 200
    run = preview.json()["run"]
    assert run["status"] == "WAITING_FOR_CONFIRMATION"
    assert run["drafts"][0]["payload"]["provider_used"]
    assert run["drafts"][0]["payload"]["location_confidence"] == "EXACT"
    assert run["drafts"][0]["payload"]["geo"] == {"lat": 25.5941, "lng": 85.1376}

    before = client.get("/incidents", headers=HEADERS)
    before_ids = {item["case_id"] for item in before.json()["items"]}
    assert set(run["committed_record_ids"]) == set()

    confirmed = client.post(f"/agent/graph1/run/{run['run_id']}/confirm", headers=HEADERS)
    assert confirmed.status_code == 200
    committed = confirmed.json()["run"]["committed_record_ids"]
    assert committed

    after = client.get("/incidents", headers=HEADERS)
    after_ids = {item["case_id"] for item in after.json()["items"]}
    assert set(committed).issubset(after_ids - before_ids)
    detail = client.get(f"/incidents/{committed[0]}", headers=HEADERS)
    assert detail.status_code == 200
    assert detail.json()["case"]["location_confidence"] == "EXACT"
    assert detail.json()["case"]["geo"] == {"lat": 25.5941, "lng": 85.1376}


def test_graph1_file_csv_can_stage_and_commit_resources():
    csv_bytes = b"resource_id,resource_type,quantity_available,location_label,owning_team_id\nRES-GRAPH1,MEDICAL_KIT,5,Field Depot,TEAM-001\n"
    preview = client.post(
        "/agent/graph1/run-file",
        headers=HEADERS,
        data={"source_kind": "CSV", "target": "resources"},
        files={"file": ("resources.csv", csv_bytes, "text/csv")},
    )

    assert preview.status_code == 200
    run = preview.json()["run"]
    assert run["drafts"][0]["draft_type"] == "RESOURCE"

    resources_before = client.get("/resources", headers=HEADERS).json()["items"]
    assert all(item["resource_id"] != "RES-GRAPH1" for item in resources_before)

    confirmed = client.post(f"/agent/graph1/run/{run['run_id']}/confirm", headers=HEADERS)
    assert confirmed.status_code == 200

    resources_after = client.get("/resources", headers=HEADERS).json()["items"]
    assert any(item["resource_id"] == "RES-GRAPH1" for item in resources_after)


def test_graph2_missing_location_pauses_then_resume_replans():
    created = client.post(
        "/incidents",
        headers=HEADERS,
        json={"raw_input": "Need blankets tonight for elderly people in temporary shelter."},
    )
    assert created.status_code == 200
    case_id = created.json()["case_id"]
    assert client.post(f"/incidents/{case_id}/extract", headers=HEADERS).status_code == 200
    assert client.post(f"/incidents/{case_id}/score", headers=HEADERS).status_code == 200

    run = client.post(
        "/agent/graph2/run",
        headers=HEADERS,
        json={"linked_case_id": case_id, "text": "Plan assignment"},
    )
    assert run.status_code == 200
    payload = run.json()["run"]
    assert payload["status"] == "WAITING_FOR_USER"
    assert payload["needs_user_input"] is True

    resumed = client.post(
        f"/agent/graph2/run/{payload['run_id']}/resume",
        headers=HEADERS,
        json={"answers": {"confirm_location": "Government school relief camp, Cuttack"}},
    )
    assert resumed.status_code == 200
    resumed_payload = resumed.json()["run"]
    assert resumed_payload["run_id"] == payload["run_id"]
    assert resumed_payload["status"] == "WAITING_FOR_CONFIRMATION"
    assert resumed_payload["drafts"][0]["payload"]["recommendations"]


def test_host_can_reset_active_org_operational_data_without_removing_membership():
    created = client.post("/organizations", headers=HEADERS, json={"name": "Reset Test NGO"})
    assert created.status_code == 200
    org_id = created.json()["organization"]["org_id"]
    org_headers = {**HEADERS, "X-Org-Id": org_id}

    incident = client.post(
        "/incidents",
        headers=org_headers,
        json={"raw_input": "Flood rescue needed near test bridge.", "source_channel": "MANUAL"},
    )
    assert incident.status_code == 200
    case_id = incident.json()["case_id"]
    location = client.post(
        f"/incidents/{case_id}/location",
        headers=org_headers,
        json={
            "location_text": "Test Bridge",
            "lat": 25.5,
            "lng": 85.1,
            "location_confidence": "EXACT",
        },
    )
    assert location.status_code == 200

    team_csv = b"team_id,display_name,capability_tags,base_label,base_lat,base_lng\nTEAM-RESET,Reset Rescue,WATER_RESCUE,Reset Base,25.51,85.11\n"
    team_preview = client.post(
        "/agent/graph1/run-file",
        headers=org_headers,
        data={"source_kind": "CSV", "target": "teams"},
        files={"file": ("teams.csv", team_csv, "text/csv")},
    )
    assert team_preview.status_code == 200
    assert client.post(f"/agent/graph1/run/{team_preview.json()['run']['run_id']}/confirm", headers=org_headers).status_code == 200

    resource_csv = b"resource_id,resource_type,quantity_available,location_label,lat,lng\nRES-RESET,RESCUE_BOAT,1,Reset Depot,25.52,85.12\n"
    resource_preview = client.post(
        "/agent/graph1/run-file",
        headers=org_headers,
        data={"source_kind": "CSV", "target": "resources"},
        files={"file": ("resources.csv", resource_csv, "text/csv")},
    )
    assert resource_preview.status_code == 200
    assert client.post(f"/agent/graph1/run/{resource_preview.json()['run']['run_id']}/confirm", headers=org_headers).status_code == 200

    response = client.post(
        f"/organizations/{org_id}/reset-data",
        headers=org_headers,
        json={"confirmation": "RESET_ORG_DATA"},
    )
    assert response.status_code == 200
    counts = response.json()["deleted_counts"]
    assert counts["incidents"] >= 1
    assert counts["teams"] >= 1
    assert counts["resources"] >= 1
    assert counts["agent_runs"] >= 2

    assert client.get("/incidents", headers=org_headers).json()["items"] == []
    assert client.get("/teams", headers=org_headers).json()["items"] == []
    assert client.get("/resources", headers=org_headers).json()["items"] == []
    members = client.get(f"/organizations/{org_id}/members", headers=org_headers)
    assert members.status_code == 200
    assert any(item["role"] == "HOST" for item in members.json()["members"])


def test_non_host_cannot_reset_org_data_and_invalid_coordinates_are_rejected():
    blocked = client.post(
        "/organizations/org-demo-relief/reset-data",
        headers=MEDICAL_HEADERS,
        json={"confirmation": "RESET_ORG_DATA"},
    )
    assert blocked.status_code == 403

    created = client.post(
        "/incidents",
        headers=HEADERS,
        json={"raw_input": "Need verification near impossible coordinate."},
    )
    assert created.status_code == 200
    invalid_location = client.post(
        f"/incidents/{created.json()['case_id']}/location",
        headers=HEADERS,
        json={"location_text": "Invalid point", "lat": 111, "lng": 85.1, "location_confidence": "EXACT"},
    )
    assert invalid_location.status_code == 422


def test_reset_does_not_delete_other_organization_records():
    first = client.post("/organizations", headers=HEADERS, json={"name": "Reset Isolation One"})
    second = client.post("/organizations", headers=HEADERS, json={"name": "Reset Isolation Two"})
    assert first.status_code == 200
    assert second.status_code == 200
    org_one = first.json()["organization"]["org_id"]
    org_two = second.json()["organization"]["org_id"]

    one_headers = {**HEADERS, "X-Org-Id": org_one}
    two_headers = {**HEADERS, "X-Org-Id": org_two}
    assert client.post("/incidents", headers=one_headers, json={"raw_input": "Org one case"}).status_code == 200
    org_two_case = client.post("/incidents", headers=two_headers, json={"raw_input": "Org two case"})
    assert org_two_case.status_code == 200

    reset = client.post(
        f"/organizations/{org_one}/reset-data",
        headers=one_headers,
        json={"confirmation": "RESET_ORG_DATA"},
    )
    assert reset.status_code == 200

    remaining = client.get("/incidents", headers=two_headers)
    assert remaining.status_code == 200
    assert any(item["case_id"] == org_two_case.json()["case_id"] for item in remaining.json()["items"])
