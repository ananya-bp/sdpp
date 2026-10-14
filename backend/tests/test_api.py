def test_health_ok(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_health_db_connected(client):
    r = client.get("/api/health/db")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["database"] == "connected"
    assert body["name"]


def test_document_types_seeded(client):
    r = client.get("/api/document-types")
    assert r.status_code == 200
    codes = {item["code"] for item in r.json()}
    assert {
        "TRANSCRIPT",
        "MIGRATION_CERTIFICATE",
        "DUPLICATE_GRADE_CARD",
        "PROVISIONAL_DEGREE_CERTIFICATE",
    } <= codes


def test_cors_preflight_allows_frontend_origin(client):
    r = client.options(
        "/api/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_cors_blocks_unknown_origin(client):
    r = client.get("/api/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in r.headers
