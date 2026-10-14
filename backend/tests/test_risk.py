"""Risk endpoint. Auth is overridden with fake users, so no database rows are needed."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.api.routes import risk


class _U:
    def __init__(self, role): self.role = role


def _client(role):
    app = FastAPI()
    app.include_router(risk.router, prefix="/api")
    if role:
        app.dependency_overrides[get_current_user] = lambda: _U(role)
    return TestClient(app)


OK = dict(document_type="TRANSCRIPT", department="CSE", semester=7, cgpa=7.5, backlog_count=1)


def test_requires_login():
    assert _client(None).post("/api/risk/score", json=OK).status_code == 401


def test_student_forbidden():
    assert _client("student").post("/api/risk/score", json=OK).status_code == 403


def test_valid_request_returns_probability_only():
    r = _client("admin").post("/api/risk/score", json=OK)
    assert r.status_code == 200
    body = r.json()
    assert 0.0 <= body["manual_review_probability"] <= 1.0
    assert isinstance(body["flagged_for_review"], bool)
    assert "ELIGIBLE" not in body and "eligible" not in body  # never an eligibility decision
    assert "not an eligibility decision" in body["note"].lower()


def test_riskier_profile_scores_higher():
    c = _client("admin")
    low = c.post("/api/risk/score", json={**OK, "cgpa": 9.3, "backlog_count": 0}).json()["manual_review_probability"]
    high = c.post("/api/risk/score", json={**OK, "cgpa": 5.9, "backlog_count": 4, "past_fee_delays_12m": 3,
                                           "prior_review_count_lagged": 2, "prior_apps_count": 4}).json()["manual_review_probability"]
    assert high > low


def test_validation_errors():
    c = _client("admin")
    assert c.post("/api/risk/score", json={**OK, "cgpa": 11}).status_code == 422
    assert c.post("/api/risk/score", json={**OK, "document_type": "NOPE"}).status_code == 422
    assert c.post("/api/risk/score", json={**OK, "department": "XYZ"}).status_code == 422  # rejected by model wrapper
    assert c.post("/api/risk/score", json={"document_type": "TRANSCRIPT"}).status_code == 422
