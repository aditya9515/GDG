from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)
HEADERS = {"X-Demo-User": "demo-coordinator", "X-Org-Id": "org-demo-relief"}
MEDICAL_HEADERS = {"X-Demo-User": "demo-medical", "X-Org-Id": "org-demo-relief"}


def test_members_response_omits_invites_and_invite_endpoint_is_removed():
    created = client.post("/organizations", headers=HEADERS, json={"name": "Test Host NGO"})
    assert created.status_code == 200
    org_id = created.json()["organization"]["org_id"]

    invite = client.post(
        f"/organizations/{org_id}/invites",
        headers={**HEADERS, "X-Org-Id": org_id},
        json={"email": "new.member@example.com", "role": "VIEWER"},
    )
    assert invite.status_code == 404

    members = client.get(f"/organizations/{org_id}/members", headers={**HEADERS, "X-Org-Id": org_id})
    assert members.status_code == 200
    assert "invites" not in members.json()
    assert len(members.json()["members"]) == 1


def test_non_host_cannot_manage_members():
    response = client.patch(
        "/organizations/org-demo-relief/members/org-demo-relief-demo-logistics",
        headers=MEDICAL_HEADERS,
        json={"role": "VIEWER"},
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


def test_graph1_mixed_document_extracts_incidents_teams_and_resources():
    document = b"""
    Need urgent flood rescue near Shantinagar bridge. Four people trapped on rooftop.

    Team River Rescue skill water rescue certified available base Shantinagar bridge.

    Resource stock rescue boat quantity 2 available at Shantinagar bridge depot.
    """
    preview = client.post(
        "/agent/graph1/run-file",
        headers=HEADERS,
        data={"source_kind": "PDF", "target": "mixed"},
        files={"file": ("mixed_report.pdf", document, "application/pdf")},
    )

    assert preview.status_code == 200
    run = preview.json()["run"]
    draft_types = {draft["draft_type"] for draft in run["drafts"]}
    assert {"INCIDENT", "TEAM", "RESOURCE"}.issubset(draft_types)
    assert run["meta"]["draft_counts"]["INCIDENT"] >= 1


def test_graph1_unrelated_csv_returns_no_empty_drafts():
    csv_bytes = b"name,color,unrelated\napple,red,fruit\nbanana,yellow,fruit\n"
    preview = client.post(
        "/agent/graph1/run-file",
        headers=HEADERS,
        data={"source_kind": "CSV", "target": "incidents"},
        files={"file": ("unrelated.csv", csv_bytes, "text/csv")},
    )

    assert preview.status_code == 200
    run = preview.json()["run"]
    assert run["drafts"] == []
    assert any("No matching data found" in warning or "No usable rows" in warning for warning in run["source_artifacts"][0]["parse_warnings"])


def test_graph1_gdacs_style_csv_detects_incidents():
    csv_bytes = (
        b"id,iso3,country,title,summary,event_type,severity_unit,severity_value,source,from_date,to_date,link,geo_lat,geo_long,gdacs_bbox\n"
        b'WF1028455,AUS,Australia,Green forest fire notification in Australia,"On 17/04/2026, a forest fire started in Australia, until 17/04/2026.",Wildfire,ha,5545,Joint Research Center,"Fri, 17 Apr 2026 00:00:00 GMT","Fri, 17 Apr 2026 00:00:00 GMT",https://www.gdacs.org/report.aspx?eventtype=WF&eventid=1028455,-15.5674,125.9064,"121.9 129.9 -19.5 -11.5"\n'
        b'EQ1535489,CRI,Costa Rica,"Green earthquake (Magnitude 5.7M, Depth:20km) in Costa Rica","On 4/15/2026, an earthquake occurred in Costa Rica potentially affecting 170 thousand in MMI IV.",Earthquake,M,5.7,Joint Research Center,"Wed, 15 Apr 2026 06:56:02 GMT","Wed, 15 Apr 2026 06:56:02 GMT",https://www.gdacs.org/report.aspx?eventtype=EQ&eventid=1535489,9.9151,-86.3803,"-90.3 -82.3 5.9 13.9"\n'
    )
    preview = client.post(
        "/agent/graph1/run-file",
        headers=HEADERS,
        data={"source_kind": "CSV", "target": "incidents"},
        files={"file": ("gdacs_rss_information.csv", csv_bytes, "text/csv")},
    )

    assert preview.status_code == 200
    run = preview.json()["run"]
    assert len(run["drafts"]) == 2
    first = run["drafts"][0]
    assert first["draft_type"] == "INCIDENT"
    assert first["payload"]["provider_used"] in {"Gemini", "Ollama", "Heuristic"}
    assert first["payload"]["extraction_mode"] in {"heuristic", "model_row"}
    assert first["payload"]["location_confidence"] == "EXACT"
    assert first["payload"]["geo"] == {"lat": -15.5674, "lng": 125.9064}
    assert first["payload"]["extracted"]["category"] == "PROTECTION"
    assert {item["resource_type"] for item in first["payload"]["extracted"]["required_resources"]} == {"FIRE_EXTINGUISHER", "N95_MASKS"}
    second = run["drafts"][1]
    assert second["payload"]["provider_used"] in {"Gemini", "Ollama", "Heuristic"}
    assert second["payload"]["extraction_mode"] in {"heuristic", "model_row"}
    assert second["payload"]["extracted"]["people_affected"] == 170000
    assert second["payload"]["extracted"]["category"] == "RESCUE"
    assert first["confidence"] != second["confidence"]


def test_graph1_large_gdacs_preview_stays_below_firestore_document_limit():
    rows = [
        "id,iso3,country,title,summary,event_type,severity_unit,severity_value,source,from_date,to_date,link,geo_lat,geo_long,gdacs_bbox"
    ]
    for index in range(246):
        severity = 1200 + index * 37
        rows.append(
            f'WF{index:07d},AUS,Australia,Green forest fire notification in Australia,'
            f'"On 17/04/2026, a forest fire started in Australia affecting sector {index}.",'
            f'Wildfire,ha,{severity},Joint Research Center,'
            f'"Fri, 17 Apr 2026 00:00:00 GMT","Fri, 17 Apr 2026 00:00:00 GMT",'
            f'https://www.gdacs.org/report.aspx?eventtype=WF&eventid={index},'
            f'{-15.5 + index / 10000:.6f},{125.9 + index / 10000:.6f},'
            f'"121.9 129.9 -19.5 -11.5"'
        )
    csv_bytes = ("\n".join(rows) + "\n").encode("utf-8")
    preview = client.post(
        "/agent/graph1/run-file",
        headers=HEADERS,
        data={"source_kind": "CSV", "target": "incidents"},
        files={"file": ("large-gdacs.csv", csv_bytes, "text/csv")},
    )

    assert preview.status_code == 200
    run = preview.json()["run"]
    assert len(run["drafts"]) == 246
    assert all(draft["payload"]["provider_used"] in {"Gemini", "Ollama", "Heuristic"} for draft in run["drafts"])
    assert all(draft["payload"]["extraction_mode"] in {"heuristic", "model_row"} for draft in run["drafts"])
    assert run["meta"]["estimated_graph_run_bytes"] < 950_000


def test_graph1_unknown_csv_headers_use_row_batch_extraction_for_team_and_resource():
    from app.core.dependencies import get_agent_graph_service

    service = get_agent_graph_service()
    previous_provider = service.extractor.settings.ai_provider
    service.extractor.settings.ai_provider = "heuristic"
    try:
        csv_bytes = (
            b"unit,abilities,station,asset,count,site\n"
            b"River Response Crew,water rescue certified available,Shantinagar bridge,,,\n"
            b",,,rescue boat,2,Shantinagar bridge depot\n"
        )
        preview = client.post(
            "/agent/graph1/run-file",
            headers=HEADERS,
            data={"source_kind": "CSV", "target": "mixed"},
            files={"file": ("unknown-operational.csv", csv_bytes, "text/csv")},
        )
    finally:
        service.extractor.settings.ai_provider = previous_provider

    assert preview.status_code == 200
    run = preview.json()["run"]
    draft_types = {draft["draft_type"] for draft in run["drafts"]}
    assert {"TEAM", "RESOURCE"}.issubset(draft_types)
    assert all(draft["extraction_mode"] != "csv_fallback_parser" for draft in run["drafts"])
    assert all(draft["source_headers"] for draft in run["drafts"])
    assert all(draft["source_fragment"] for draft in run["drafts"])


def test_graph1_team_resource_field_updates_change_structured_payload():
    team_csv = b"team_id,display_name,capability_tags,base_label\nTEAM-EDIT,Original Team,RESCUE,Old Base\n"
    preview = client.post(
        "/agent/graph1/run-file",
        headers=HEADERS,
        data={"source_kind": "CSV", "target": "teams"},
        files={"file": ("teams.csv", team_csv, "text/csv")},
    )
    assert preview.status_code == 200
    run = preview.json()["run"]
    draft = run["drafts"][0]

    edited = client.post(
        f"/agent/graph1/run/{run['run_id']}/edit",
        headers=HEADERS,
        json={
            "draft_id": draft["draft_id"],
            "field_updates": {
                "team.display_name": "Updated Medical Team",
                "team.capability_tags": "MEDICAL,AMBULANCE",
                "team.base_geo.lat": "25.61",
                "team.base_geo.lng": "85.14",
            },
        },
    )
    assert edited.status_code == 200
    payload = edited.json()["run"]["drafts"][0]["payload"]
    assert payload["team"]["display_name"] == "Updated Medical Team"
    assert payload["team"]["capability_tags"] == ["MEDICAL", "AMBULANCE"]
    assert payload["team"]["base_geo"] == {"lat": 25.61, "lng": 85.14}

    resource_csv = b"resource_id,resource_type,quantity_available,location_label\nRES-EDIT,WATER_TANKER,1,Old Depot\n"
    resource_preview = client.post(
        "/agent/graph1/run-file",
        headers=HEADERS,
        data={"source_kind": "CSV", "target": "resources"},
        files={"file": ("resources.csv", resource_csv, "text/csv")},
    )
    assert resource_preview.status_code == 200
    resource_run = resource_preview.json()["run"]
    resource_draft = resource_run["drafts"][0]

    resource_edited = client.post(
        f"/agent/graph1/run/{resource_run['run_id']}/edit",
        headers=HEADERS,
        json={
            "draft_id": resource_draft["draft_id"],
            "field_updates": {
                "resource.resource_type": "MEDICAL_KIT",
                "resource.quantity_available": "7",
                "resource.location.lat": "25.62",
                "resource.location.lng": "85.15",
            },
        },
    )
    assert resource_edited.status_code == 200
    resource_payload = resource_edited.json()["run"]["drafts"][0]["payload"]
    assert resource_payload["resource"]["resource_type"] == "MEDICAL_KIT"
    assert resource_payload["resource"]["quantity_available"] == 7.0
    assert resource_payload["resource"]["location"] == {"lat": 25.62, "lng": 85.15}


def test_graph1_team_resource_prompt_reevaluation_can_change_full_structured_payload():
    from app.core.dependencies import get_agent_graph_service

    service = get_agent_graph_service()
    previous_provider = service.extractor.settings.ai_provider
    service.extractor.settings.ai_provider = "heuristic"
    try:
        team_preview = client.post(
            "/agent/graph1/run-file",
            headers=HEADERS,
            data={"source_kind": "CSV", "target": "teams"},
            files={
                "file": (
                    "teams.csv",
                    b"team_id,display_name,capability_tags,base_label\nTEAM-OLD,Original Team,RESCUE,Old Base\n",
                    "text/csv",
                )
            },
        )
        assert team_preview.status_code == 200
        team_run = team_preview.json()["run"]
        team_draft = team_run["drafts"][0]

        team_edited = client.post(
            f"/agent/graph1/run/{team_run['run_id']}/edit",
            headers=HEADERS,
            json={
                "draft_id": team_draft["draft_id"],
                "prompt": (
                    "team id to TEAM-PROMPT. display name to Mobile Medical Alpha. "
                    "capabilities to medical, ambulance. members to VOL-1,VOL-2. "
                    "base label to Patna Medical Base. current label to Patna Field Post. "
                    "service radius to 45. availability status to offline. active dispatches to 2. "
                    "reliability score to 0.64. base lat to 25.61. base lng to 85.14. "
                    "current lat to 25.62. current lng to 85.15."
                ),
            },
        )
        assert team_edited.status_code == 200
        team_payload = team_edited.json()["run"]["drafts"][0]["payload"]["team"]
        assert team_payload["team_id"] == "TEAM-PROMPT"
        assert team_payload["display_name"] == "Mobile Medical Alpha"
        assert team_payload["capability_tags"] == ["MEDICAL", "AMBULANCE"]
        assert team_payload["member_ids"] == ["VOL-1", "VOL-2"]
        assert team_payload["base_label"] == "Patna Medical Base"
        assert team_payload["current_label"] == "Patna Field Post"
        assert team_payload["service_radius_km"] == 45.0
        assert team_payload["availability_status"] == "OFFLINE"
        assert team_payload["active_dispatches"] == 2
        assert team_payload["reliability_score"] == 0.64
        assert team_payload["base_geo"] == {"lat": 25.61, "lng": 85.14}
        assert team_payload["current_geo"] == {"lat": 25.62, "lng": 85.15}

        resource_preview = client.post(
            "/agent/graph1/run-file",
            headers=HEADERS,
            data={"source_kind": "CSV", "target": "resources"},
            files={
                "file": (
                    "resources.csv",
                    b"resource_id,resource_type,quantity_available,location_label\nRES-OLD,WATER_TANKER,1,Old Depot\n",
                    "text/csv",
                )
            },
        )
        assert resource_preview.status_code == 200
        resource_run = resource_preview.json()["run"]
        resource_draft = resource_run["drafts"][0]

        resource_edited = client.post(
            f"/agent/graph1/run/{resource_run['run_id']}/edit",
            headers=HEADERS,
            json={
                "draft_id": resource_draft["draft_id"],
                "prompt": (
                    "resource id to RES-PROMPT. resource type to medical kit. quantity to 9. "
                    "owning team id to TEAM-PROMPT. location to Patna Depot. current label to Patna Clinic. "
                    "constraints to cold chain, priority. location lat to 25.63. location lng to 85.16. "
                    "current lat to 25.64. current lng to 85.17. image url to https://example.test/kit.jpg."
                ),
            },
        )
        assert resource_edited.status_code == 200
        resource_payload = resource_edited.json()["run"]["drafts"][0]["payload"]["resource"]
        assert resource_payload["resource_id"] == "RES-PROMPT"
        assert resource_payload["resource_type"] == "MEDICAL_KIT"
        assert resource_payload["quantity_available"] == 9.0
        assert resource_payload["owning_team_id"] == "TEAM-PROMPT"
        assert resource_payload["location_label"] == "Patna Depot"
        assert resource_payload["current_label"] == "Patna Clinic"
        assert resource_payload["constraints"] == ["COLD_CHAIN", "PRIORITY"]
        assert resource_payload["location"] == {"lat": 25.63, "lng": 85.16}
        assert resource_payload["current_geo"] == {"lat": 25.64, "lng": 85.17}
        assert resource_payload["image_url"] == "https://example.test/kit.jpg"
    finally:
        service.extractor.settings.ai_provider = previous_provider


def test_graph1_prompt_edit_preserves_source_raw_input():
    run = client.post(
        "/agent/graph1/run",
        headers=HEADERS,
        json={
            "source_kind": "MANUAL_TEXT",
            "target": "incidents",
            "text": "Need ambulance near district hospital for pregnant woman in labour.",
        },
    ).json()["run"]
    draft = run["drafts"][0]
    original_source = draft["payload"]["source_raw_input"]

    edited = client.post(
        f"/agent/graph1/run/{run['run_id']}/edit",
        headers=HEADERS,
        json={"draft_id": draft["draft_id"], "prompt": "Correction: mark as critical medical transport."},
    )

    assert edited.status_code == 200
    payload = edited.json()["run"]["drafts"][0]["payload"]
    assert payload["source_raw_input"] == original_source
    assert "Correction: mark as critical medical transport." in payload["working_input"]


def test_graph1_full_context_prompt_can_patch_location_coordinates_and_any_payload_field():
    from app.core.dependencies import get_agent_graph_service
    from app.models.domain import ReevaluationPatch
    from app.services.extractor import ReevaluationPatchResult

    run = client.post(
        "/agent/graph1/run-file",
        headers=HEADERS,
        data={"source_kind": "CSV", "target": "incidents"},
        files={
            "file": (
                "incident.csv",
                b"raw_input,category,location_text,lat,lng,required_resources\n"
                b'"Need rescue at old bridge",RESCUE,"Old Bridge",25.5,85.1,RESCUE_BOAT\n',
                "text/csv",
            )
        },
    ).json()["run"]
    draft = run["drafts"][0]

    service = get_agent_graph_service()
    original = service.extractor.reevaluate_payload_patch_with_metadata

    def fake_patch(envelope):
        assert envelope["draft"]["payload"]["geo"] == {"lat": 25.5, "lng": 85.1}
        assert envelope["draft"]["payload"]["extracted"]["location_text"] == "Old Bridge"
        return ReevaluationPatchResult(
            patch=ReevaluationPatch(
                payload_patch={
                    "extracted": {
                        "location_text": "Corrected Bridge Point",
                        "urgency": "CRITICAL",
                        "people_affected": 12,
                        "confidence": 0.91,
                    },
                    "geo": {"lat": 26.1234, "lng": 86.5678},
                    "location_confidence": "EXACT",
                },
                changed_fields=["extracted.location_text", "extracted.urgency", "geo.lat", "geo.lng"],
                reasoning_summary="Updated location, urgency, and affected count from full context.",
            ),
            provider_used="Gemini",
        )

    service.extractor.reevaluate_payload_patch_with_metadata = fake_patch
    try:
        edited = client.post(
            f"/agent/graph1/run/{run['run_id']}/edit",
            headers=HEADERS,
            json={"draft_id": draft["draft_id"], "prompt": "Correct the coordinates and mark as critical."},
        )
    finally:
        service.extractor.reevaluate_payload_patch_with_metadata = original

    assert edited.status_code == 200
    payload = edited.json()["run"]["drafts"][0]["payload"]
    assert payload["extracted"]["location_text"] == "Corrected Bridge Point"
    assert payload["extracted"]["urgency"] == "CRITICAL"
    assert payload["extracted"]["people_affected"] == 12
    assert payload["geo"] == {"lat": 26.1234, "lng": 86.5678}
    assert "geo.lat" in edited.json()["run"]["drafts"][0]["changed_fields"]


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
    assert "ranked_recommendations" in resumed_payload["drafts"][0]["payload"]
    assert "reserve_teams" in resumed_payload["drafts"][0]["payload"]
    assert "conflicts" in resumed_payload["drafts"][0]["payload"]

    top_team = resumed_payload["drafts"][0]["payload"]["ranked_recommendations"][0]["team_id"]
    edited = client.post(
        f"/agent/graph2/run/{payload['run_id']}/edit",
        headers=HEADERS,
        json={
            "draft_id": resumed_payload["drafts"][0]["draft_id"],
            "prompt": f"Exclude {top_team} and keep a reserve team if possible.",
        },
    )
    assert edited.status_code == 200
    edited_payload = edited.json()["run"]["drafts"][0]["payload"]
    assert all(item["team_id"] != top_team for item in edited_payload["ranked_recommendations"])
    assert any("excluded" in warning.lower() for warning in edited.json()["run"]["drafts"][0]["warnings"])


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


def _create_isolated_org(name: str) -> tuple[str, dict[str, str]]:
    created = client.post("/organizations", headers=HEADERS, json={"name": name})
    assert created.status_code == 200
    org_id = created.json()["organization"]["org_id"]
    return org_id, {**HEADERS, "X-Org-Id": org_id}


def _seed_batch_assets(headers: dict[str, str], quantity: int = 1) -> tuple[str, str, str]:
    team = client.post(
        "/teams",
        headers=headers,
        json={
            "display_name": "Batch Rescue Unit",
            "capability_tags": ["RESCUE", "EVACUATION", "WATER_RESCUE", "RESCUE_BOAT", "FLOOD"],
            "base_label": "Batch Base, Patna",
            "base_geo": {"lat": 25.594, "lng": 85.138},
            "current_geo": {"lat": 25.594, "lng": 85.138},
            "service_radius_km": 80,
            "reliability_score": 0.95,
        },
    )
    assert team.status_code == 200
    team_id = team.json()["team_id"]

    volunteer = client.post(
        "/volunteers",
        headers=headers,
        json={
            "display_name": "Batch Responder",
            "team_id": team_id,
            "role_tags": ["RESPONDER"],
            "skills": ["RESCUE", "EVACUATION", "WATER_RESCUE", "RESCUE_BOAT", "FLOOD"],
            "home_base_label": "Batch Base, Patna",
            "home_base": {"lat": 25.594, "lng": 85.138},
            "current_geo": {"lat": 25.594, "lng": 85.138},
            "reliability_score": 0.9,
        },
    )
    assert volunteer.status_code == 200

    resource = client.post(
        "/resources",
        headers=headers,
        json={
            "resource_type": "RESCUE_BOAT",
            "quantity_available": quantity,
            "location_label": "Batch Boat Depot",
            "location": {"lat": 25.596, "lng": 85.139},
            "current_geo": {"lat": 25.596, "lng": 85.139},
        },
    )
    assert resource.status_code == 200
    return team_id, volunteer.json()["volunteer_id"], resource.json()["resource_id"]


def _commit_incident_csv(headers: dict[str, str], rows: list[str]) -> list[str]:
    csv_text = (
        "raw_input,category,location_text,lat,lng,required_resources,people_affected,priority_feature\n"
        + "\n".join(rows)
        + "\n"
    )
    preview = client.post(
        "/agent/graph1/run-file",
        headers=headers,
        data={"source_kind": "CSV", "target": "incidents"},
        files={"file": ("batch-incidents.csv", csv_text.encode("utf-8"), "text/csv")},
    )
    assert preview.status_code == 200
    run = preview.json()["run"]
    assert run["drafts"]
    confirmed = client.post(f"/agent/graph1/run/{run['run_id']}/confirm", headers=headers)
    assert confirmed.status_code == 200
    return confirmed.json()["run"]["committed_record_ids"]


def test_batch_graph2_plans_all_open_cases_and_confirm_case():
    _, headers = _create_isolated_org("Batch Planning Happy Path")
    _seed_batch_assets(headers, quantity=1)
    case_ids = _commit_incident_csv(
        headers,
        [
            '"Critical rooftop flood rescue at Batch Bridge. 12 people trapped. Need rescue boat.",RESCUE,"Batch Bridge, Patna",25.5941,85.1376,RESCUE_BOAT,12,ROOFTOP_RESCUE',
        ],
    )

    response = client.post(
        "/agent/graph2/batch-run",
        headers=headers,
        json={
            "case_ids": [],
            "planning_mode": "global",
            "include_reserve": True,
            "operator_prompt": "Prioritize flood rescue first.",
        },
    )
    assert response.status_code == 200
    run = response.json()["run"]
    assert run["graph_name"] == "batch_dispatch_planning_graph"
    assert run["status"] == "WAITING_FOR_CONFIRMATION"

    plan = run["drafts"][0]["payload"]["batch_plan"]
    assert plan["stats"]["total_cases"] == 1
    planned = plan["planned_cases"][0]
    assert planned["case_id"] == case_ids[0]
    assert planned["assignment_status"] in {"ASSIGNED", "PARTIAL"}
    assert planned["selected_recommendation"]["team_id"]
    assert planned["selected_recommendation"]["route_summary"]["status"] in {"fallback", "exact"}

    confirmed = client.post(
        f"/agent/graph2/run/{run['run_id']}/confirm-case",
        headers=headers,
        json={"case_id": planned["case_id"]},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["run"]["committed_record_ids"]

    dispatches = client.get("/dispatches", headers=headers)
    assert dispatches.status_code == 200
    assert any(item["case_id"] == planned["case_id"] for item in dispatches.json()["items"])


def test_graph2_single_and_batch_reevaluation_receive_full_context_and_patch_coordinates():
    from app.core.dependencies import get_agent_graph_service
    from app.models.domain import ReevaluationPatch
    from app.services.extractor import ReevaluationPatchResult

    _, headers = _create_isolated_org("Graph 2 Full Context Patch")
    _seed_batch_assets(headers, quantity=2)
    case_ids = _commit_incident_csv(
        headers,
        [
            '"Critical rescue at Full Context Bridge. Need rescue boat.",RESCUE,"Full Context Bridge, Patna",25.5941,85.1376,RESCUE_BOAT,8,ROOFTOP_RESCUE',
        ],
    )

    service = get_agent_graph_service()
    original = service.extractor.reevaluate_payload_patch_with_metadata

    single_run = client.post(
        "/agent/graph2/run",
        headers=headers,
        json={"linked_case_id": case_ids[0], "text": "Plan dispatch"},
    ).json()["run"]
    single_draft = single_run["drafts"][0]

    def fake_single_patch(envelope):
        assert envelope["draft"]["payload"]["case_id"] == case_ids[0]
        assert envelope["repository_context"]["teams"]
        return ReevaluationPatchResult(
            patch=ReevaluationPatch(
                payload_patch={
                    "location_override": {
                        "location_text": "Corrected dispatch point",
                        "geo": {"lat": 25.7, "lng": 85.2},
                    },
                    "conflicts": ["Operator corrected case coordinates."],
                    "reasoning_summary": "Coordinates corrected; route facts must be recomputed by backend.",
                },
                changed_fields=["location_override.geo.lat", "location_override.geo.lng", "conflicts"],
            ),
            provider_used="Gemini",
        )

    service.extractor.reevaluate_payload_patch_with_metadata = fake_single_patch
    try:
        edited_single = client.post(
            f"/agent/graph2/run/{single_run['run_id']}/edit",
            headers=headers,
            json={"draft_id": single_draft["draft_id"], "prompt": "Change destination to 25.7, 85.2."},
        )
    finally:
        service.extractor.reevaluate_payload_patch_with_metadata = original

    assert edited_single.status_code == 200
    single_payload = edited_single.json()["run"]["drafts"][0]["payload"]
    assert single_payload["location_override"]["geo"] == {"lat": 25.7, "lng": 85.2}
    assert single_payload["selected_plan"]["route_summary"]["status"] in {"fallback", "exact"}

    batch_run = client.post(
        "/agent/graph2/batch-run",
        headers=headers,
        json={"case_ids": case_ids, "planning_mode": "global", "include_reserve": False},
    ).json()["run"]

    def fake_batch_patch(envelope):
        assert envelope["reevaluation_scope"] == "batch_case_plan"
        assert envelope["selected_planned_case"]["case_id"] == case_ids[0]
        assert envelope["batch_plan_summary"]["planned_case_count"] == 1
        return ReevaluationPatchResult(
            patch=ReevaluationPatch(
                payload_patch={
                    "selected_case": {"operator_note": "Use the corrected field coordinates."},
                    "case_location_override": {
                        "location_text": "Batch corrected dispatch point",
                        "geo": {"lat": 25.71, "lng": 85.21},
                    },
                },
                changed_fields=["selected_case.operator_note", "case_location_override.geo.lat", "case_location_override.geo.lng"],
                reasoning_summary="Batch case location corrected from full context.",
            ),
            provider_used="Gemini",
        )

    service.extractor.reevaluate_payload_patch_with_metadata = fake_batch_patch
    try:
        edited_batch = client.post(
            f"/agent/graph2/run/{batch_run['run_id']}/edit-case",
            headers=headers,
            json={"case_id": case_ids[0], "prompt": "Move this case to 25.71, 85.21 and add a note."},
        )
    finally:
        service.extractor.reevaluate_payload_patch_with_metadata = original

    assert edited_batch.status_code == 200
    batch_draft = edited_batch.json()["run"]["drafts"][0]
    assert batch_draft["payload"]["case_overrides"][case_ids[0]]["geo"] == {"lat": 25.71, "lng": 85.21}
    planned = batch_draft["payload"]["batch_plan"]["planned_cases"][0]
    assert planned["operator_note"] == "Move this case to 25.71, 85.21 and add a note."
    assert planned["selected_recommendation"]["route_summary"]["status"] in {"fallback", "exact"}


def test_batch_graph2_consumes_capacity_once_and_explains_waiting_case():
    _, headers = _create_isolated_org("Batch Planning Scarcity")
    _seed_batch_assets(headers, quantity=1)
    case_ids = _commit_incident_csv(
        headers,
        [
            '"Critical rooftop flood rescue at Scarcity Bridge. 20 people trapped. Need rescue boat.",RESCUE,"Scarcity Bridge, Patna",25.5941,85.1376,RESCUE_BOAT,20,ROOFTOP_RESCUE',
            '"Second flood rescue at Scarcity School. 5 people stranded. Need rescue boat.",RESCUE,"Scarcity School, Patna",25.6041,85.1476,RESCUE_BOAT,5,ROOFTOP_RESCUE',
        ],
    )

    response = client.post(
        "/agent/graph2/batch-run",
        headers=headers,
        json={
            "case_ids": case_ids,
            "planning_mode": "global",
            "include_reserve": False,
        },
    )
    assert response.status_code == 200
    plan = response.json()["run"]["drafts"][0]["payload"]["batch_plan"]
    statuses = {item["case_id"]: item["assignment_status"] for item in plan["planned_cases"]}

    assert set(statuses) == set(case_ids)
    assert sum(1 for status in statuses.values() if status in {"ASSIGNED", "PARTIAL"}) == 1
    leftovers = [item for item in plan["planned_cases"] if item["assignment_status"] in {"WAITING", "UNASSIGNED", "BLOCKED"}]
    assert leftovers
    assert any(item["reasons"] for item in leftovers)


def test_batch_graph2_marks_missing_location_case_blocked():
    _, headers = _create_isolated_org("Batch Planning Missing Location")
    _seed_batch_assets(headers, quantity=1)
    created = client.post(
        "/incidents",
        headers=headers,
        json={"raw_input": "Need rescue help for a family, exact location not available yet."},
    )
    assert created.status_code == 200
    case_id = created.json()["case_id"]
    assert client.post(f"/incidents/{case_id}/extract", headers=headers).status_code == 200
    assert client.post(f"/incidents/{case_id}/score", headers=headers).status_code == 200

    response = client.post(
        "/agent/graph2/batch-run",
        headers=headers,
        json={"case_ids": [case_id], "planning_mode": "global", "include_reserve": False},
    )
    assert response.status_code == 200
    plan = response.json()["run"]["drafts"][0]["payload"]["batch_plan"]
    assert plan["planned_cases"][0]["assignment_status"] == "BLOCKED"
    assert any("location" in reason.lower() for reason in plan["planned_cases"][0]["reasons"])
