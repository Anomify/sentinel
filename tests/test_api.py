from fastapi.testclient import TestClient


def client():
    from cimonitor.api import app
    return TestClient(app)


def test_every_read_endpoint_works_on_an_empty_workspace():
    c = client()
    comp = c.get("/api/meta").json()["entities"][1]["id"]
    for url in ["/api/meta", "/api/overview", "/api/events", "/api/stack", "/api/hiring", "/api/radar", "/api/positioning",
                "/api/visibility", "/api/coverage", "/api/guard", "/api/runs", "/api/digests", "/api/digests/preview",
                f"/api/competitors/{comp}", f"/api/facts?competitor={comp}", f"/api/deepdive/{comp}", f"/api/deepdive/{comp}/markdown",
                f"/api/scan/{comp}"]:
        r = c.get(url)
        assert r.status_code == 200, (url, r.text[:200])


def test_add_target_validates_and_registers(monkeypatch):
    from cimonitor import jobs
    monkeypatch.setattr(jobs, "run_async", lambda *a, **k: None)
    c = client()
    assert c.post("/api/targets", json={"domain": "not a domain"}).status_code == 400
    r = c.post("/api/targets", json={"domain": "https://www.newco.ai/pricing"}).json()
    assert r["status"] == "scanning"
    ent = next(e for e in c.get("/api/meta").json()["entities"] if e["id"] == r["id"])
    assert ent["domains"] == ["newco.ai"] and ent["source"] == "ui"


def test_workspace_requires_its_token():
    from cimonitor import tenancy
    tok = tenancy.create("acme", "Acme")
    c = client()
    assert c.get("/api/meta", headers={"X-Workspace": "acme"}).status_code == 401
    r = c.get("/api/meta", headers={"X-Workspace": "acme", "Authorization": f"Bearer {tok}"})
    assert r.status_code == 200 and r.json()["workspace"] == "acme"
    assert c.get("/api/meta", headers={"X-Workspace": "nope"}).status_code == 404
