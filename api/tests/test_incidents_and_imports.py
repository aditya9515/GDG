from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)
HEADERS = {"X-Demo-User": "demo-coordinator"}


def test_incident_routes_support_maps_first_dispatch():
    created = client.post(
        "/incidents",
        headers=HEADERS,
        json={"raw_input": "Accident near highway, 3 injured, bleeding. Need first responder and ambulance."},
    )
    assert created.status_code == 200
    case_id = created.json()["case_id"]

    extracted = client.post(f"/incidents/{case_id}/extract", headers=HEADERS)
    assert extracted.status_code == 200

    scored = client.post(f"/incidents/{case_id}/score", headers=HEADERS)
    assert scored.status_code == 200

    options = client.post(f"/incidents/{case_id}/dispatch-options", headers=HEADERS)
    assert options.status_code == 200
    recommendation = options.json()["recommendations"][0]

    dispatched = client.post(
        f"/incidents/{case_id}/dispatch",
        headers=HEADERS,
        json={
            "team_id": recommendation["team_id"],
            "volunteer_ids": recommendation["volunteer_ids"],
            "resource_ids": recommendation["resource_ids"],
            "resource_allocations": recommendation["resource_allocations"],
        },
    )
    assert dispatched.status_code == 200

    detail = client.get(f"/incidents/{case_id}", headers=HEADERS)
    assert detail.status_code == 200
    assert detail.json()["case"]["status"] == "ASSIGNED"


def test_csv_import_creates_new_resource():
    csv_bytes = b"resource_id,resource_type,quantity_available,location_label,owning_team_id\nRES-999,MEDICAL_KIT,4,Field Depot,TEAM-001\n"
    imported = client.post(
        "/ingestion-jobs",
        headers=HEADERS,
        data={"kind": "CSV", "target": "resources"},
        files={"file": ("resources.csv", csv_bytes, "text/csv")},
    )
    assert imported.status_code == 200
    assert imported.json()["status"] == "COMPLETED"

    resources = client.get("/resources", headers=HEADERS)
    assert resources.status_code == 200
    assert any(item["resource_id"] == "RES-999" for item in resources.json()["items"])
