"""Mock/sandbox payment tests - full real HTTP flow through OCR -> eligibility -> payment."""
from sqlalchemy import select

from app.models import DocumentType
from tests.conftest import PDF_BYTES
from tests.test_eligibility import register_seeded, doc_type_id
from tests.test_ocr import _text_png, SAMPLE_LINES


def to_eligible(api, usn, doc_code, db_session):
    headers = register_seeded(api, usn)
    dtid = doc_type_id(db_session, doc_code)
    r = api.post(
        "/api/applications", headers=headers, data={"document_type_id": str(dtid)},
        files=[("files", ("proof.png", _text_png(SAMPLE_LINES), "image/png"))],
    )
    app_id = r.json()["id"]
    api.post(f"/api/applications/{app_id}/ocr", headers=headers)
    r = api.post(f"/api/applications/{app_id}/eligibility", headers=headers)
    assert r.json()["status"] == "ELIGIBLE", r.json()
    return app_id, headers


def test_full_payment_success_flow(api, db_session):
    app_id, headers = to_eligible(api, "SIM23CSE001", "TRANSCRIPT", db_session)

    r = api.post(f"/api/applications/{app_id}/payment/initiate", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "PAYMENT_PENDING"
    assert len(body["transactions"]) == 1
    assert body["transactions"][0]["payment_status"] == "PENDING"
    assert body["transactions"][0]["amount"] == "200.00"  # TRANSCRIPT placeholder fee

    r = api.post(f"/api/applications/{app_id}/payment/complete", headers=headers, json={"outcome": "success"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "PAYMENT_COMPLETED"
    assert body["transactions"][0]["payment_status"] == "SUCCESS"
    assert body["history"][-1]["status"] == "PAYMENT_COMPLETED"


def test_failed_payment_does_not_complete_application(api, db_session):
    app_id, headers = to_eligible(api, "SIM23CSE001", "MIGRATION_CERTIFICATE", db_session)

    api.post(f"/api/applications/{app_id}/payment/initiate", headers=headers)
    r = api.post(f"/api/applications/{app_id}/payment/complete", headers=headers, json={"outcome": "failure"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "PAYMENT_PENDING"  # NOT silently completed
    assert body["transactions"][0]["payment_status"] == "FAILED"
    assert "PAYMENT_COMPLETED" not in [h["status"] for h in body["history"]]


def test_initiate_response_includes_the_new_pending_transaction(api, db_session):
    """The frontend picks 'Simulate payment' vs 'Start/Retry payment' from this very response, so
    it must already contain the PENDING row that was just created (regression: it used to come
    back with an empty list because the reload returned the session's stale collection)."""
    app_id, headers = to_eligible(api, "SIM23CSE001", "DUPLICATE_GRADE_CARD", db_session)
    r = api.post(f"/api/applications/{app_id}/payment/initiate", headers=headers)
    assert r.status_code == 200
    assert [t["payment_status"] for t in r.json()["transactions"]] == ["PENDING"]


def test_retry_after_failed_payment_creates_new_transaction(api, db_session):
    app_id, headers = to_eligible(api, "SIM23CSE001", "DUPLICATE_GRADE_CARD", db_session)

    api.post(f"/api/applications/{app_id}/payment/initiate", headers=headers)
    api.post(f"/api/applications/{app_id}/payment/complete", headers=headers, json={"outcome": "failure"})
    # Retry: initiate again (allowed while PAYMENT_PENDING), then succeed.
    r = api.post(f"/api/applications/{app_id}/payment/initiate", headers=headers)
    assert r.status_code == 200
    assert len(r.json()["transactions"]) == 2
    r = api.post(f"/api/applications/{app_id}/payment/complete", headers=headers, json={"outcome": "success"})
    assert r.json()["status"] == "PAYMENT_COMPLETED"
    statuses = [t["payment_status"] for t in r.json()["transactions"]]
    assert statuses == ["FAILED", "SUCCESS"]  # first attempt kept for the audit trail


def test_not_eligible_application_cannot_pay(api, db_session):
    headers = register_seeded(api, "SIM23CSE004")  # fee DUE -> NOT_ELIGIBLE
    dtid = doc_type_id(db_session, "TRANSCRIPT")
    r = api.post(
        "/api/applications", headers=headers, data={"document_type_id": str(dtid)},
        files=[("files", ("proof.png", _text_png(SAMPLE_LINES), "image/png"))],
    )
    app_id = r.json()["id"]
    api.post(f"/api/applications/{app_id}/ocr", headers=headers)
    r = api.post(f"/api/applications/{app_id}/eligibility", headers=headers)
    assert r.json()["status"] == "NOT_ELIGIBLE"

    r = api.post(f"/api/applications/{app_id}/payment/initiate", headers=headers)
    assert r.status_code == 400  # stopped before payment, as required


def test_cannot_complete_payment_with_none_pending(api, db_session):
    app_id, headers = to_eligible(api, "SIM23CSE001", "TRANSCRIPT", db_session)
    r = api.post(f"/api/applications/{app_id}/payment/complete", headers=headers, json={"outcome": "success"})
    assert r.status_code == 400  # never initiated


def test_invalid_outcome_rejected(api, db_session):
    app_id, headers = to_eligible(api, "SIM23CSE001", "TRANSCRIPT", db_session)
    api.post(f"/api/applications/{app_id}/payment/initiate", headers=headers)
    r = api.post(f"/api/applications/{app_id}/payment/complete", headers=headers, json={"outcome": "maybe"})
    assert r.status_code == 400


def test_payment_requires_login(api):
    assert api.post("/api/applications/1/payment/initiate").status_code == 401
    assert api.post("/api/applications/1/payment/complete", json={"outcome": "success"}).status_code == 401


def test_payment_404_for_someone_elses_application(api, db_session):
    app_id, _ = to_eligible(api, "SIM23CSE001", "TRANSCRIPT", db_session)
    other_headers = register_seeded(api, "SIM23CSE002")
    r = api.post(f"/api/applications/{app_id}/payment/initiate", headers=other_headers)
    assert r.status_code == 404
