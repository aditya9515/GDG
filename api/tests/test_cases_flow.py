from fastapi.testclient import TestClient

from app.main import app


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
