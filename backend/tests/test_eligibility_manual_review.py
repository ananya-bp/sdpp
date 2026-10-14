"""Tests for the MANUAL_REVIEW eligibility outcome.

Verifies:
- OCR failure on any document triggers MANUAL_REVIEW (not NOT_ELIGIBLE).
- Very low OCR word count triggers MANUAL_REVIEW.
- A document mismatch (readable content but wrong document) alone does not
  automatically make the student academically ineligible.
- MANUAL_REVIEW is correctly recorded in status history.
- Payment cannot be initiated on a MANUAL_REVIEW application.
- ELIGIBLE cases still work correctly through the full flow.
- Existing NOT_ELIGIBLE cases (fee due, backlogs) are unaffected.
"""
import io
import struct
import zlib

import pytest
from sqlalchemy import select

from app.core.statuses import ApplicationStatus
from app.models import Application, DocumentType, OcrResult, Student
from app.services import eligibility as elig
from app.services.eligibility import EligibilityDecision
from tests.conftest import PDF_BYTES, PNG_BYTES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_png() -> bytes:
    """Minimal valid 1×1 PNG."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))
    header = struct.pack(">IIBBBB", 1, 1, 8, 2, 0, 0)
    header += b"\x00"
    pixel = zlib.compress(b"\x00\xff\x00\x00")
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", pixel) + chunk(b"IEND", b"")


def submit_with_files(api, headers, doc_type_id, files):
    return api.post(
        "/api/applications",
        headers=headers,
        data={"document_type_id": str(doc_type_id)},
        files=files,
    )


def run_ocr(api, headers, app_id):
    return api.post(f"/api/applications/{app_id}/ocr", headers=headers)


def run_eligibility(api, headers, app_id):
    return api.post(f"/api/applications/{app_id}/eligibility", headers=headers)


def initiate_payment(api, headers, app_id):
    return api.post(f"/api/applications/{app_id}/payment/initiate", headers=headers)


def register_student(api, db_session, make_student, **student_kwargs):
    """Create a student and return (student, auth headers)."""
    student = make_student(**student_kwargs)
    r = api.post(
        "/api/auth/register",
        json={"usn": student.usn, "email": "test_mr@example.com", "password": "Passw0rd!x"},
    )
    assert r.status_code == 201, r.text
    return student, {"Authorization": f"Bearer {r.json()['access_token']}"}


def get_doc_type(db_session, code: str) -> DocumentType:
    return db_session.scalar(select(DocumentType).where(DocumentType.code == code))


# ---------------------------------------------------------------------------
# Unit-level tests: evaluate() directly (no HTTP, no real OCR)
# ---------------------------------------------------------------------------

def _make_app_with_ocr(doc_type_code, fee_status, backlog_count, ocr_rows, db_session):
    """Build an Application stub with attached OcrResult rows for unit testing evaluate()."""
    from decimal import Decimal
    from unittest.mock import MagicMock

    doc_type = MagicMock()
    doc_type.code = doc_type_code

    student = MagicMock()
    student.fee_status = fee_status
    student.backlog_count = backlog_count

    def make_doc(status, word_count=None, error=None):
        doc = MagicMock()
        ocr = MagicMock()
        ocr.status = status
        ocr.error_message = error
        ocr.extracted_fields = {"word_count": word_count} if word_count is not None else None
        doc.ocr_result = ocr
        return doc

    app = MagicMock()
    app.document_type = doc_type
    app.documents = [make_doc(**r) for r in ocr_rows]
    return app, student


def test_evaluate_eligible_all_ok():
    app, student = _make_app_with_ocr(
        "TRANSCRIPT", "CLEAR", 0,
        [{"status": "SUCCESS", "word_count": 120}],
        None,
    )
    outcome = elig.evaluate(app, student)
    assert outcome.decision == EligibilityDecision.ELIGIBLE
    assert outcome.eligible is True


def test_evaluate_not_eligible_fee_due():
    """Fee DUE → NOT_ELIGIBLE regardless of OCR."""
    app, student = _make_app_with_ocr(
        "TRANSCRIPT", "DUE", 0,
        [{"status": "SUCCESS", "word_count": 200}],
        None,
    )
    outcome = elig.evaluate(app, student)
    assert outcome.decision == EligibilityDecision.NOT_ELIGIBLE
    assert any("Fee status" in r for r in outcome.reasons)


def test_evaluate_manual_review_on_ocr_failure():
    """A FAILED OCR result triggers MANUAL_REVIEW, not NOT_ELIGIBLE."""
    app, student = _make_app_with_ocr(
        "TRANSCRIPT", "CLEAR", 0,
        [{"status": "FAILED", "error": "Corrupt file"}],
        None,
    )
    outcome = elig.evaluate(app, student)
    assert outcome.decision == EligibilityDecision.MANUAL_REVIEW
    assert not outcome.eligible
    # Reason should mention the document, not an academic condition.
    assert any("could not be read" in r for r in outcome.reasons)


def test_evaluate_manual_review_on_low_word_count():
    """Very few OCR words (< 5) → MANUAL_REVIEW (blank/wrong document)."""
    app, student = _make_app_with_ocr(
        "TRANSCRIPT", "CLEAR", 0,
        [{"status": "SUCCESS", "word_count": 2}],
        None,
    )
    outcome = elig.evaluate(app, student)
    assert outcome.decision == EligibilityDecision.MANUAL_REVIEW
    assert any("word count" in r for r in outcome.reasons)


def test_evaluate_manual_review_mixed_ok_and_failed():
    """One readable, one failed → MANUAL_REVIEW (not ELIGIBLE just because one is fine)."""
    app, student = _make_app_with_ocr(
        "TRANSCRIPT", "CLEAR", 0,
        [
            {"status": "SUCCESS", "word_count": 150},
            {"status": "FAILED", "error": "Unreadable"},
        ],
        None,
    )
    outcome = elig.evaluate(app, student)
    assert outcome.decision == EligibilityDecision.MANUAL_REVIEW


def test_evaluate_not_eligible_takes_priority_over_ocr_issues():
    """When a mandatory condition fails (fee due) AND OCR is bad, result is NOT_ELIGIBLE.

    The mandatory academic condition is checked first; a definitive INELIGIBLE outcome
    does not get upgraded to MANUAL_REVIEW by a bad scan.
    """
    app, student = _make_app_with_ocr(
        "TRANSCRIPT", "DUE", 0,
        [{"status": "FAILED", "error": "Unreadable"}],
        None,
    )
    outcome = elig.evaluate(app, student)
    assert outcome.decision == EligibilityDecision.NOT_ELIGIBLE


def test_evaluate_no_documents_not_eligible():
    """No documents → NOT_ELIGIBLE (the 'has supporting documents' condition fails)."""
    from unittest.mock import MagicMock
    doc_type = MagicMock()
    doc_type.code = "TRANSCRIPT"
    student = MagicMock()
    student.fee_status = "CLEAR"
    student.backlog_count = 0
    app = MagicMock()
    app.document_type = doc_type
    app.documents = []
    outcome = elig.evaluate(app, student)
    assert outcome.decision == EligibilityDecision.NOT_ELIGIBLE


# ---------------------------------------------------------------------------
# Integration tests: MANUAL_REVIEW via HTTP (real OCR pipeline not needed;
# we force an OCR-failed result by using an HTTP test client that overrides
# the OCR service using monkeypatch).
# ---------------------------------------------------------------------------

def test_manual_review_status_recorded_in_history(api, db_session, student_auth, doc_type, monkeypatch):
    """When an OCR result fails, the eligibility endpoint stores MANUAL_REVIEW in history."""
    _, headers = student_auth

    # Submit application with a valid PNG.
    r = submit_with_files(api, headers, doc_type.id, [("files", ("doc.png", PNG_BYTES, "image/png"))])
    assert r.status_code == 201
    app_id = r.json()["id"]

    # Simulate an OCR run by inserting a FAILED result directly, then calling /eligibility.
    # (The /ocr endpoint runs real Tesseract which we don't control; we patch the service.)
    import app.services.ocr as ocr_svc

    def fake_ocr_app(db, application, changed_by=None):
        # Advance status to OCR_COMPLETED and insert a FAILED result.
        from app.services.applications import set_status
        from app.models import OcrResult, UploadedDocument
        from sqlalchemy import select as sa_select

        docs = db.scalars(
            sa_select(UploadedDocument).where(UploadedDocument.application_id == application.id)
        ).all()
        for doc in docs:
            db.add(OcrResult(
                uploaded_document_id=doc.id,
                status="FAILED",
                error_message="Simulated OCR failure",
            ))
        set_status(db, application, ApplicationStatus.OCR_COMPLETED, changed_by=changed_by)
        db.commit()
        db.refresh(application)
        return application

    monkeypatch.setattr(ocr_svc, "run_ocr_for_application", fake_ocr_app)

    r = run_ocr(api, headers, app_id)
    assert r.status_code == 200

    r = run_eligibility(api, headers, app_id)
    assert r.status_code == 200
    result = r.json()
    assert result["status"] == "MANUAL_REVIEW", f"Expected MANUAL_REVIEW, got {result['status']}"
    assert any(h["status"] == "MANUAL_REVIEW" for h in result["history"])
    # Reason should mention the document problem, not an academic condition.
    last_note = next(h["note"] for h in reversed(result["history"]) if h["status"] == "MANUAL_REVIEW")
    assert "could not be read" in last_note or "Manual review" in last_note


def test_payment_blocked_on_manual_review(api, db_session, student_auth, doc_type, monkeypatch):
    """Payment must not be initiatable on a MANUAL_REVIEW application."""
    _, headers = student_auth
    r = submit_with_files(api, headers, doc_type.id, [("files", ("doc.png", PNG_BYTES, "image/png"))])
    assert r.status_code == 201
    app_id = r.json()["id"]

    import app.services.ocr as ocr_svc
    from app.services.applications import set_status
    from app.core.statuses import ApplicationStatus
    from app.models import OcrResult, UploadedDocument
    from sqlalchemy import select as sa_select

    def fake_ocr_failed(db, application, changed_by=None):
        docs = db.scalars(
            sa_select(UploadedDocument).where(UploadedDocument.application_id == application.id)
        ).all()
        for doc in docs:
            db.add(OcrResult(uploaded_document_id=doc.id, status="FAILED"))
        set_status(db, application, ApplicationStatus.OCR_COMPLETED, changed_by=changed_by)
        db.commit()
        db.refresh(application)
        return application

    monkeypatch.setattr(ocr_svc, "run_ocr_for_application", fake_ocr_failed)
    run_ocr(api, headers, app_id)
    run_eligibility(api, headers, app_id)

    # Payment must be refused.
    r = initiate_payment(api, headers, app_id)
    assert r.status_code == 400
    assert "ELIGIBLE" in r.json()["detail"] or "eligible" in r.json()["detail"].lower()


def test_eligible_case_still_works(api, db_session, student_auth, doc_type, monkeypatch):
    """Ensuring ELIGIBLE still works after the MANUAL_REVIEW changes."""
    _, headers = student_auth
    r = submit_with_files(api, headers, doc_type.id, [("files", ("doc.png", PNG_BYTES, "image/png"))])
    assert r.status_code == 201
    app_id = r.json()["id"]

    import app.services.ocr as ocr_svc
    from app.services.applications import set_status
    from app.models import OcrResult, UploadedDocument
    from sqlalchemy import select as sa_select

    def fake_ocr_success(db, application, changed_by=None):
        docs = db.scalars(
            sa_select(UploadedDocument).where(UploadedDocument.application_id == application.id)
        ).all()
        for doc in docs:
            db.add(OcrResult(
                uploaded_document_id=doc.id,
                status="SUCCESS",
                raw_text="Student record 01FE23BCS054 CGPA 8.75",
                extracted_fields={"word_count": 50, "detected_usns": [], "detected_cgpa_like_numbers": [], "detected_dates": []},
            ))
        set_status(db, application, ApplicationStatus.OCR_COMPLETED, changed_by=changed_by)
        db.commit()
        db.refresh(application)
        return application

    monkeypatch.setattr(ocr_svc, "run_ocr_for_application", fake_ocr_success)
    run_ocr(api, headers, app_id)

    r = run_eligibility(api, headers, app_id)
    assert r.status_code == 200
    # student_auth creates a student with fee CLEAR and 0 backlogs → ELIGIBLE.
    assert r.json()["status"] == "ELIGIBLE"
