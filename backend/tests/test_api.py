from fastapi.testclient import TestClient

from radar.api.main import app, db
from radar.store import FindingIn, upsert_finding


def test_api_lists_and_details(session):
    f = upsert_finding(session, FindingIn(url="https://azmostbet90.com", status="confirmed", text="Promo kod: AZ90")).finding
    session.commit()
    app.dependency_overrides[db] = lambda: session
    try:
        c = TestClient(app)
        r = c.get("/api/findings", params={"source": "organic_domain", "q": "mostbet"})
        assert r.status_code == 200 and r.json()["total"] == 1
        d = c.get(f"/api/findings/{f.public_id}").json()
        assert d["host"] == "azmostbet90.com" and d["events"][0]["kind"] == "detected"
        r = c.post(f"/api/findings/{f.public_id}/status", json={"status": "blocked", "actor": "test"})
        assert r.json()["status"] == "blocked"
        assert f.blocked_at is not None
        assert c.post(f"/api/findings/{f.public_id}/status", json={"status": "bogus"}).status_code == 422
        ov = c.get("/api/overview").json()
        assert ov["total"] == 1
        assert c.post("/api/settings/whitelist", json={"kind": "domain", "value": "TFC.az", "owner": "TFC"}).status_code == 200
        assert any(w["value"] == "tfc.az" for w in c.get("/api/settings/whitelist").json())
    finally:
        app.dependency_overrides.clear()
