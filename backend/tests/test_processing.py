"""Tests for POST /applications/{id}/process - the automatic OCR -> eligibility chain.

Runs the real Tesseract pipeline and the real eligibility rules; nothing is mocked.
"""
from sqlalchemy import select

from app.models import DocumentType
from tests.conftest import PASSWORD
from tests.test_ocr import SAMPLE_LINES, _text_png, submit


def _png_file():
    return [("proof.png", _text_png(SAMPLE_LINES), "image/png")]


def _statuses(body):
    return [h["status"] for h in body["history"]]


def _doc_type_id(db_session, code):
    return db_session.scalar(select(DocumentType.id).where(DocumentType.code == code))


def test_process_runs_ocr_then_eligibility(api, student_auth, doc_type):
    _, headers = student_auth
    app_id = submit(api, headers, doc_type.id, _png_file()).json()["id"]

    r = api.post(f"/api/applications/{app_id}/process", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ELIGIBLE"
    assert _statuses(body) == ["SUBMITTED", "OCR_COMPLETED", "ELIGIBLE"]  # history preserved via set_status
    assert body["documents"][0]["ocr_result"]["status"] == "SUCCESS"
    assert body["transactions"] == []  # processing never starts a payment
    assert body["fee_amount"] is not None


def test_process_is_idempotent(api, student_auth, doc_type):
    _, headers = student_auth
    app_id = submit(api, headers, doc_type.id, _png_file()).json()["id"]
    first = api.post(f"/api/applications/{app_id}/process", headers=headers).json()
    second = api.post(f"/api/applications/{app_id}/process", headers=headers).json()
    assert second["status"] == "ELIGIBLE"
    assert _statuses(second) == _statuses(first)  # no second OCR / eligibility run
    assert second["documents"][0]["ocr_result"]["processed_at"] == first["documents"][0]["ocr_result"]["processed_at"]


def test_process_ineligible_student_stops_at_not_eligible(api, make_student, register, db_session):
    student = make_student(fee_status="DUE")
    headers = {"Authorization": "Bearer " + register(student.usn).json()["access_token"]}
    app_id = submit(api, headers, _doc_type_id(db_session, "TRANSCRIPT"), _png_file()).json()["id"]

    body = api.post(f"/api/applications/{app_id}/process", headers=headers).json()
    assert body["status"] == "NOT_ELIGIBLE"
    assert "Fee status" in body["history"][-1]["note"]
    # ...and the existing payment endpoint still refuses it
    r = api.post(f"/api/applications/{app_id}/payment/initiate", headers=headers)
    assert r.status_code == 400
    # processing again does not change a decided application
    again = api.post(f"/api/applications/{app_id}/process", headers=headers).json()
    assert _statuses(again) == _statuses(body)


def test_process_failed_ocr_does_not_run_eligibility_and_can_retry(api, student_auth, doc_type):
    _, headers = student_auth
    corrupt = b"%PDF-1.4\n" + (b"\x00\x01\x02garbage" * 30)
    app_id = submit(api, headers, doc_type.id, [("bad.pdf", corrupt, "application/pdf")]).json()["id"]

    body = api.post(f"/api/applications/{app_id}/process", headers=headers).json()
    assert body["status"] == "OCR_COMPLETED"  # stopped: eligibility must not run on unreadable input
    assert body["documents"][0]["ocr_result"]["status"] == "FAILED"
    assert "could not be read" in body["history"][-1]["note"]

    # A plain repeat does nothing (no automatic retry loop) ...
    again = api.post(f"/api/applications/{app_id}/process", headers=headers).json()
    assert _statuses(again) == ["SUBMITTED", "OCR_COMPLETED"]
    # ... an explicit retry re-runs OCR (replacing, not duplicating, the result), still failing here.
    retried = api.post(f"/api/applications/{app_id}/process?retry_ocr=true", headers=headers).json()
    assert _statuses(retried) == ["SUBMITTED", "OCR_COMPLETED", "OCR_COMPLETED"]
    assert len(retried["documents"]) == 1 and retried["documents"][0]["ocr_result"]["status"] == "FAILED"


def test_retry_ocr_is_a_noop_when_ocr_already_succeeded(api, student_auth, doc_type):
    _, headers = student_auth
    app_id = submit(api, headers, doc_type.id, _png_file()).json()["id"]
    first = api.post(f"/api/applications/{app_id}/process", headers=headers).json()
    again = api.post(f"/api/applications/{app_id}/process?retry_ocr=true", headers=headers).json()
    assert _statuses(again) == _statuses(first)


def test_process_leaves_payment_states_alone(api, student_auth, doc_type):
    _, headers = student_auth
    app_id = submit(api, headers, doc_type.id, _png_file()).json()["id"]
    api.post(f"/api/applications/{app_id}/process", headers=headers)
    api.post(f"/api/applications/{app_id}/payment/initiate", headers=headers)
    body = api.post(f"/api/applications/{app_id}/process?retry_ocr=true", headers=headers).json()
    assert body["status"] == "PAYMENT_PENDING"
    assert len(body["transactions"]) == 1


def test_process_requires_login(api):
    assert api.post("/api/applications/1/process").status_code == 401


def test_process_404_for_someone_elses_application(api, student_auth, make_student, register, doc_type):
    _, headers = student_auth
    app_id = submit(api, headers, doc_type.id, _png_file()).json()["id"]
    other = make_student()
    other_headers = {"Authorization": "Bearer " + register(other.usn, "other@example.com").json()["access_token"]}
    assert api.post(f"/api/applications/{app_id}/process", headers=other_headers).status_code == 404
    # and the owner's application was not touched by the attempt
    assert api.get(f"/api/applications/{app_id}", headers=headers).json()["status"] == "SUBMITTED"


def test_detail_exposes_fee_from_backend_schedule(api, student_auth, db_session):
    _, headers = student_auth
    for code, fee in [("TRANSCRIPT", "200.00"), ("MIGRATION_CERTIFICATE", "500.00")]:
        app_id = submit(api, headers, _doc_type_id(db_session, code), _png_file()).json()["id"]
        assert api.get(f"/api/applications/{app_id}", headers=headers).json()["fee_amount"] == fee
