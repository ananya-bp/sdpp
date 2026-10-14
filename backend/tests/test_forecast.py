"""Forecast endpoints. Auth is overridden with fake users, so no database rows are needed."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.api.routes import forecast


class _U:
    def __init__(self, role): self.role = role


def _client(role):
    app = FastAPI()
    app.include_router(forecast.router, prefix="/api")
    if role:
        app.dependency_overrides[get_current_user] = lambda: _U(role)
    return TestClient(app)


TAT = dict(document_type="TRANSCRIPT", num_documents=1, is_alumni=False, submitted_at="2026-09-02T10:00:00",
           queue_open_at_submission=12, apps_prev_24h=5, apps_prev_7d=30, doc_apps_prev_7d=15)


def test_requires_login():
    assert _client(None).get("/api/forecast/demand", params={"document_type": "TRANSCRIPT", "date": "2026-09-01"}).status_code == 401


def test_students_forbidden():
    assert _client("student").post("/api/forecast/tat", json=TAT).status_code == 403


def test_demand_ok():
    r = _client("admin").get("/api/forecast/demand", params={"document_type": "TRANSCRIPT", "date": "2026-09-01"})
    assert r.status_code == 200 and 0 <= r.json()["expected_applications"] < 40


def test_demand_date_too_far_ahead():
    r = _client("admin").get("/api/forecast/demand", params={"document_type": "TRANSCRIPT", "date": "2026-12-01"})
    assert r.status_code == 422


def test_tat_ok_and_unknown_type():
    c = _client("admin")
    r = c.post("/api/forecast/tat", json=TAT)
    assert r.status_code == 200 and 0 < r.json()["expected_tat_hours"] < 300
    assert c.post("/api/forecast/tat", json={**TAT, "document_type": "NOPE"}).status_code == 422
