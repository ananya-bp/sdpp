"""Rule-based eligibility tests, run against the real seeded simulated students
(app.db.seed_students - varied CGPA/backlogs/fee status on purpose) so different students are
shown getting correct, different outcomes, not just one synthetic case.
"""
import pytest
from sqlalchemy import select

from app.core.statuses import ApplicationStatus
from app.models import DocumentType, Student
from tests.conftest import PDF_BYTES
from tests.test_ocr import _text_png, SAMPLE_LINES


def register_seeded(api, usn):
    r = api.post("/api/auth/register", json={"usn": usn, "email": f"{usn.lower()}@example.com", "password": "Passw0rd!x"})
    assert r.status_code == 201, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}


def full_flow(api, headers, doc_type_id, attach_file=True):
    files = [("files", ("proof.png", _text_png(SAMPLE_LINES), "image/png"))] if attach_file else None
    r = api.post("/api/applications", headers=headers, data={"document_type_id": str(doc_type_id)}, files=files)
    assert r.status_code == 201, r.text
    app_id = r.json()["id"]
    r = api.post(f"/api/applications/{app_id}/ocr", headers=headers)
    assert r.status_code == 200, r.text
    r = api.post(f"/api/applications/{app_id}/eligibility", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def doc_type_id(db_session, code):
    return db_session.scalar(select(DocumentType.id).where(DocumentType.code == code))


def student_by_usn(db_session, usn):
    return db_session.scalar(select(Student).where(Student.usn == usn))


@pytest.mark.parametrize(
    "usn,doc_code,expected",
    [
        ("SIM23CSE001", "TRANSCRIPT", "ELIGIBLE"),  # CGPA 8.90, 0 backlogs, fee CLEAR
        ("SIM23CSE002", "TRANSCRIPT", "ELIGIBLE"),  # 1 backlog but transcript has no backlog rule
        ("SIM23CSE004", "TRANSCRIPT", "NOT_ELIGIBLE"),  # fee DUE -> blocks every type
        ("SIM23EEE001", "TRANSCRIPT", "NOT_ELIGIBLE"),  # fee DUE, 0 backlogs -> still blocked on fee
        ("SIM23CSE001", "PROVISIONAL_DEGREE_CERTIFICATE", "ELIGIBLE"),  # 0 backlogs, fee CLEAR
        ("SIM23CSE002", "PROVISIONAL_DEGREE_CERTIFICATE", "NOT_ELIGIBLE"),  # 1 backlog blocks provisional
        ("SIM23MEC002", "PROVISIONAL_DEGREE_CERTIFICATE", "ELIGIBLE"),  # 0 backlogs, fee CLEAR
        ("SIM23CIV002", "PROVISIONAL_DEGREE_CERTIFICATE", "NOT_ELIGIBLE"),  # 4 backlogs + fee DUE
    ],
)
def test_eligibility_outcomes_per_seeded_student(api, db_session, usn, doc_code, expected):
    headers = register_seeded(api, usn)
    result = full_flow(api, headers, doc_type_id(db_session, doc_code))
    assert result["status"] == expected
    assert result["history"][-1]["status"] == expected


def test_not_eligible_without_fee_due_but_no_documents(api, db_session):
    """SIM23CSE001 has clean fee/backlogs, but the common 'required documents' rule still applies."""
    headers = register_seeded(api, "SIM23CSE001")
    result = full_flow(api, headers, doc_type_id(db_session, "TRANSCRIPT"), attach_file=False)
    assert result["status"] == "NOT_ELIGIBLE"
    assert "documents" in result["history"][-1]["note"].lower()


def test_eligibility_reasons_are_recorded_in_history_note(api, db_session):
    headers = register_seeded(api, "SIM23CIV002")  # fee DUE, 4 backlogs
    result = full_flow(api, headers, doc_type_id(db_session, "PROVISIONAL_DEGREE_CERTIFICATE"))
    note = result["history"][-1]["note"]
    assert "fee status" in note.lower()
    assert "backlog" in note.lower()


def test_eligibility_requires_ocr_first(api, student_auth, doc_type):
    _, headers = student_auth
    r = api.post("/api/applications", headers=headers, data={"document_type_id": str(doc_type.id)})
    app_id = r.json()["id"]
    # Skip OCR - go straight to eligibility
    r = api.post(f"/api/applications/{app_id}/eligibility", headers=headers)
    assert r.status_code == 400


def test_eligibility_requires_login(api):
    assert api.post("/api/applications/1/eligibility").status_code == 401


def test_eligibility_404_for_someone_elses_application(api, db_session):
    headers_a = register_seeded(api, "SIM23CSE001")
    app_id = full_flow(api, headers_a, doc_type_id(db_session, "TRANSCRIPT"))["id"]

    headers_b = register_seeded(api, "SIM23CSE002")
    r = api.post(f"/api/applications/{app_id}/eligibility", headers=headers_b)
    assert r.status_code == 404


def test_eligibility_does_not_touch_risk_scoring(api, db_session):
    """Phase 5's ML risk scoring is a separate concern (section 1.4) - confirm this step is
    purely status/history and doesn't write to the transactions table or any risk-related field."""
    from app.models import Transaction

    headers = register_seeded(api, "SIM23CSE001")
    full_flow(api, headers, doc_type_id(db_session, "TRANSCRIPT"))
    assert db_session.query(Transaction).count() == 0
