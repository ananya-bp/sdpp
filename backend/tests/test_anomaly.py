"""Anomaly endpoint. Auth is overridden with fake users, so no database rows are needed."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.api.routes import anomaly


class _U:
    def __init__(self, role): self.role = role


def _client(role):
    app = FastAPI()
    app.include_router(anomaly.router, prefix="/api")
    if role:
        app.dependency_overrides[get_current_user] = lambda: _U(role)
    return TestClient(app)


OK = dict(document_type="TRANSCRIPT", amount=200, payment_status="SUCCESS")
BURST = dict(document_type="TRANSCRIPT", amount=200, payment_status="FAILED", attempt_index=4, failed_attempts_before=3,
             seconds_since_prev_attempt=20, student_txns_prior_24h=3)


def test_requires_login():
    assert _client(None).post("/api/anomaly/score", json=OK).status_code == 401


def test_student_forbidden():
    assert _client("student").post("/api/anomaly/score", json=OK).status_code == 403


def test_normal_payment():
    r = _client("admin").post("/api/anomaly/score", json=OK)
    assert r.status_code == 200
    b = r.json()
    assert b["label"] == "NORMAL" and b["is_anomaly"] is False and isinstance(b["anomaly_score"], float)
    assert "anomaly_type" not in b


def test_rapid_retry_burst_flagged_by_model():
    b = _client("admin").post("/api/anomaly/score", json=BURST).json()
    assert b["label"] == "ANOMALOUS" and b["model_flagged"] is True and b["anomaly_score"] >= b["threshold"]


def test_amount_mismatch_flagged_by_rule():
    b = _client("admin").post("/api/anomaly/score", json={**OK, "amount": 500}).json()
    assert b["label"] == "ANOMALOUS" and b["rule_flags"] == ["AMOUNT_MISMATCH"]


def test_validation_errors():
    c = _client("admin")
    assert c.post("/api/anomaly/score", json={**OK, "amount": -5}).status_code == 422
    assert c.post("/api/anomaly/score", json={**OK, "payment_status": "MAYBE"}).status_code == 422
    assert c.post("/api/anomaly/score", json={"amount": 100}).status_code == 422
