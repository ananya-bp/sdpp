"""Phase 2 backend tests: config endpoints, request-spec validation, eligibility policy
configuration, and collision-safe synthetic USN allocation.

Uses the existing conftest fixtures (rolled-back db_session, temporary upload dir, api client).
"""
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings, settings
from app.core.usn import (
    SequenceExhaustedError,
    UsNValidationError,
    allocate_synthetic_usn,
    usn_to_email,
    validate_college_email,
)
from app.db.session import SessionLocal
from app.models import DocumentType, Student
from tests.conftest import PDF_BYTES, PNG_BYTES


def _dt_id(db_session, code):
    return db_session.scalar(select(DocumentType.id).where(DocumentType.code == code))


def _auth_for(api, make_student, register):
    student = make_student()
    token = register(student.usn).json()["access_token"]
    return student, {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# GET /api/config/limits — live centralized settings
# ---------------------------------------------------------------------------

def test_config_limits_endpoint(client):
    r = client.get("/api/config/limits")
    assert r.status_code == 200
    body = r.json()
    assert body["max_upload_mb"] == settings.max_upload_mb
    assert body["max_upload_bytes"] == settings.max_upload_mb * 1024 * 1024
    assert body["max_files_per_application"] == settings.max_files_per_application
    assert set(body["allowed_extensions"]) == {"pdf", "jpg", "jpeg", "png"}
    # must not leak secrets or unrelated configuration
    for secret_key in ("secret_key", "database_url"):
        assert secret_key not in body


def test_config_limits_reflect_runtime_change(client, monkeypatch):
    """Endpoint reads live settings, never an import-time snapshot."""
    monkeypatch.setattr(settings, "max_upload_mb", 2)
    monkeypatch.setattr(settings, "max_files_per_application", 3)
    body = client.get("/api/config/limits").json()
    assert body["max_upload_mb"] == 2
    assert body["max_upload_bytes"] == 2 * 1024 * 1024
    assert body["max_files_per_application"] == 3


def test_config_limits_require_no_login(client):
    # public student-facing config: no auth header needed
    assert client.get("/api/config/limits").status_code == 200


# ---------------------------------------------------------------------------
# GET /api/config/forms — four request types with their own specs
# ---------------------------------------------------------------------------

EXPECTED_TYPES = {
    "TRANSCRIPT": "purpose",
    "MIGRATION_CERTIFICATE": "destination_university",
    "DUPLICATE_GRADE_CARD": "semester",
    "PROVISIONAL_DEGREE_CERTIFICATE": "enrollment_year",
}


def test_config_forms_covers_all_four_request_types(client):
    r = client.get("/api/config/forms")
    assert r.status_code == 200
    body = r.json()
    codes = {f["code"] for f in body["forms"]}
    assert codes == set(EXPECTED_TYPES)
    for form in body["forms"]:
        field_keys = {f["key"] for f in form["fields"]}
        # each request type has its OWN distinctive required intake field
        assert EXPECTED_TYPES[form["code"]] in field_keys
        assert len(form["documents"]) >= 1
        # every requirement is honestly labelled unverified (no invented official policy)
        assert form["policy_verified"] is False
        for f in form["fields"]:
            assert f["verified"] is False
        for d in form["documents"]:
            assert d["verified"] is False


def test_config_forms_specs_are_distinct(client):
    forms = client.get("/api/config/forms").json()["forms"]
    fieldsets = {tuple(sorted(f["key"] for f in form["fields"])) for form in forms}
    docsets = {tuple(sorted(d["label"] for d in form["documents"])) for form in forms}
    assert len(fieldsets) == 4  # not one generic form duplicated
    assert len(docsets) == 4


# ---------------------------------------------------------------------------
# Application submission: request-specific validation wired into POST route
# ---------------------------------------------------------------------------

def test_submission_rejects_invalid_select_value(api, make_student, register, db_session):
    _student, headers = _auth_for(api, make_student, register)
    dtid = _dt_id(db_session, "DUPLICATE_GRADE_CARD")
    r = api.post(
        "/api/applications", headers=headers,
        data={"document_type_id": str(dtid), "details": json.dumps({"semester": "99"})},
        files=[("files", ("card.pdf", PDF_BYTES, "application/pdf"))],
    )
    assert r.status_code == 422
    errors = r.json()["detail"]["errors"]
    assert any("Semester" in e for e in errors)


def test_submission_rejects_overlong_field(api, make_student, register, db_session):
    _student, headers = _auth_for(api, make_student, register)
    dtid = _dt_id(db_session, "MIGRATION_CERTIFICATE")
    details = json.dumps({"destination_university": "X" * 500, "reason": "moving"})
    r = api.post(
        "/api/applications", headers=headers,
        data={"document_type_id": str(dtid), "details": details},
        files=[("files", ("proof.pdf", PDF_BYTES, "application/pdf"))],
    )
    assert r.status_code == 422
    assert any("at most" in e for e in r.json()["detail"]["errors"])


def test_submission_missing_unverified_required_field_is_not_blocked(
    api, make_student, register, db_session
):
    """Unverified requirements must NOT invent hard restrictions: submission still succeeds."""
    _student, headers = _auth_for(api, make_student, register)
    dtid = _dt_id(db_session, "TRANSCRIPT")
    r = api.post(
        "/api/applications", headers=headers,
        data={"document_type_id": str(dtid)},  # no 'purpose' at all
        files=[("files", ("proof.png", PNG_BYTES, "image/png"))],
    )
    assert r.status_code == 201, r.text


def test_submission_malformed_details_json_rejected(api, make_student, register, db_session):
    _student, headers = _auth_for(api, make_student, register)
    dtid = _dt_id(db_session, "TRANSCRIPT")
    r = api.post(
        "/api/applications", headers=headers,
        data={"document_type_id": str(dtid), "details": "not-json"},
        files=[("files", ("proof.png", PNG_BYTES, "image/png"))],
    )
    assert r.status_code == 422


def test_submission_requires_login(api, db_session):
    dtid = _dt_id(db_session, "TRANSCRIPT")
    r = api.post("/api/applications", data={"document_type_id": str(dtid)})
    assert r.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Eligibility policy configuration (externalised verified flags)
# ---------------------------------------------------------------------------

def _build_app(db_session, make_student, fee="CLEAR", backlogs=0):
    """Directly build an application + documents with healthy OCR evidence."""
    from app.models import Application, UploadedDocument

    student = make_student(fee_status=fee, backlog_count=backlogs)
    dt = db_session.get(DocumentType, _dt_id(db_session, "PROVISIONAL_DEGREE_CERTIFICATE"))
    app_ = Application(student_id=student.id, document_type_id=dt.id)
    db_session.add(app_)
    db_session.flush()
    doc = UploadedDocument(
        application_id=app_.id, original_filename="a.pdf", stored_path="x",
        content_type="application/pdf", size_bytes=len(PDF_BYTES),
    )
    db_session.add(doc)
    db_session.flush()
    return app_, student


def _with_good_ocr(db_session, app_):
    from app.models import OcrResult

    doc = app_.documents[0]
    r = OcrResult(
        uploaded_document_id=doc.id, status="SUCCESS", extracted_fields={"word_count": 80}
    )
    db_session.add(r)
    db_session.flush()


def test_policy_unverified_fee_rule_routes_to_manual_review(db_session, make_student, monkeypatch):
    from app.services import eligibility

    monkeypatch.setattr(
        settings, "eligibility_policy_json",
        '{"fee_status_clear": {"verified": false}}',
    )
    app_, student = _build_app(db_session, make_student, fee="DUE")
    _with_good_ocr(db_session, app_)
    outcome = eligibility.evaluate(app_, student)
    assert outcome.decision == eligibility.EligibilityDecision.MANUAL_REVIEW
    assert any("Fee" in r for r in outcome.reasons)


def test_policy_verified_fee_rule_gives_not_eligible(db_session, make_student, monkeypatch):
    from app.services import eligibility

    monkeypatch.setattr(
        settings, "eligibility_policy_json",
        '{"fee_status_clear": {"verified": true}}',
    )
    app_, student = _build_app(db_session, make_student, fee="DUE")
    _with_good_ocr(db_session, app_)
    outcome = eligibility.evaluate(app_, student)
    assert outcome.decision == eligibility.EligibilityDecision.NOT_ELIGIBLE


def test_policy_backlog_failure_never_auto_rejects_when_unverified(
    db_session, make_student, monkeypatch
):
    from app.services import eligibility

    monkeypatch.setattr(
        settings, "eligibility_policy_json",
        '{"no_outstanding_backlogs": {"verified": false}}',
    )
    app_, student = _build_app(db_session, make_student, fee="CLEAR", backlogs=3)
    _with_good_ocr(db_session, app_)
    outcome = eligibility.evaluate(app_, student)
    assert outcome.decision == eligibility.EligibilityDecision.MANUAL_REVIEW


def test_uncertain_ocr_never_produces_eligible(db_session, make_student):
    from app.services import eligibility

    app_, student = _build_app(db_session, make_student)
    # no OCR result attached -> uncertain evidence
    outcome = eligibility.evaluate(app_, student)
    assert outcome.decision == eligibility.EligibilityDecision.MANUAL_REVIEW


def test_settings_rejects_malformed_policy_json():
    base = dict(database_url="postgresql://x/y", secret_key="a" * 40)
    with pytest.raises(Exception):
        Settings(**base, eligibility_policy_json='{"fee_status_clear": {"verified": "yes"}}')
    s = Settings(**base, eligibility_policy_json='{"some_rule": {"verified": false}}')
    assert s.eligibility_policy["some_rule"]["verified"] is False


# ---------------------------------------------------------------------------
# USN/email validation + collision-safe synthetic allocation
# ---------------------------------------------------------------------------

def test_email_exact_lowercase_and_domain():
    assert validate_college_email("01fe23bcs054@kletech.ac.in", "01FE23BCS054")
    assert not validate_college_email("01FE23BCS054@kletech.ac.in", "01FE23BCS054")
    assert not validate_college_email("01fe23bcs054@gmail.com", "01FE23BCS054")
    assert not validate_college_email("01fe23bcs054@fakekletech.ac.in", "01FE23BCS054")
    assert not validate_college_email("01fe23bcs054@kletech.ac.in.example.com", "01FE23BCS054")
    assert usn_to_email("01FE23BCS054") == "01fe23bcs054@kletech.ac.in"


@pytest.fixture(scope="module")
def alloc_engine():
    """Separate engine+session factory for allocation tests that really commit, then clean up."""
    from sqlalchemy import create_engine

    eng = create_engine(settings.database_url, pool_pre_ping=True)
    factory = lambda: Session(bind=eng, expire_on_commit=False)  # noqa: E731
    yield factory
    with factory() as s:
        for st in s.scalars(select(Student).where(Student.usn.like("01FE24B%"))).all():
            s.delete(st)
        s.commit()
    eng.dispose()


def test_allocate_synthetic_usn_basic(alloc_engine):
    st = allocate_synthetic_usn(
        alloc_engine, full_name="Alloc Test", department="Computer Science and Engineering",
        admission_year=2024,
    )
    try:
        assert st.usn.startswith("01FE24BCS")
        assert len(st.usn) == 12
        assert validate_college_email(usn_to_email(st.usn), st.usn)
        # sequence within range
        seq = int(st.usn[-3:])
        assert 1 <= seq <= 500
    finally:
        with alloc_engine() as s:
            s.delete(s.get(Student, st.id))
            s.commit()


def test_allocate_rejects_unknown_department(alloc_engine):
    with pytest.raises(UsNValidationError):
        allocate_synthetic_usn(
            alloc_engine, full_name="X", department="Underwater Basket Weaving",
            admission_year=2024,
        )


def test_allocate_rejects_invalid_year(alloc_engine):
    with pytest.raises(UsNValidationError):
        allocate_synthetic_usn(
            alloc_engine, full_name="X", department="Civil Engineering", admission_year=1900,
        )


def test_allocate_retries_past_taken_sequence(alloc_engine):
    """A hand-inserted USN occupying the natural next slot forces a bounded retry."""
    with alloc_engine() as s:
        clash = Student(
            usn="01FE24BME001", full_name="Clash", department="Mechanical Engineering",
            semester=1, cgpa="7.00",
        )
        s.add(clash)
        s.commit()
        clash_id = clash.id
    try:
        st = allocate_synthetic_usn(
            alloc_engine, full_name="Retry Test", department="Mechanical Engineering",
            admission_year=2024, max_retries=10,
        )
        assert st.usn != "01FE24BME001"
        assert st.usn.startswith("01FE24BME")
        with alloc_engine() as s:
            s.delete(s.get(Student, st.id))
            s.commit()
    finally:
        with alloc_engine() as s:
            s.delete(s.get(Student, clash_id))
            s.commit()


def test_allocate_concurrent_no_duplicates(alloc_engine):
    """Eight parallel allocations must produce eight distinct USNs (unique constraint is the
    arbiter; collisions are retried, never leaked as duplicates or errors)."""
    results = []
    errors = []

    def worker(i):
        try:
            return allocate_synthetic_usn(
                alloc_engine, full_name=f"Conc {i}",
                department="Electronics and Communication Engineering",
                admission_year=2024, max_retries=25,
            ).usn
        except Exception as exc:  # pragma: no cover - surfaced via errors below
            errors.append(exc)
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(worker, range(8)))

    assert not errors, errors
    usns = [r for r in results if r]
    assert len(usns) == 8
    assert len(set(usns)) == 8, f"duplicate USNs allocated concurrently: {usns}"
    # all persisted rows are unique too
    with alloc_engine() as s:
        rows = s.scalars(
            select(Student.usn).where(Student.usn.in_(usns))
        ).all()
        assert len(rows) == len(set(rows)) == 8
        for st in s.scalars(select(Student).where(Student.usn.in_(usns))).all():
            s.delete(st)
        s.commit()


def test_existing_real_identifiers_untouched(db_session):
    """Allocation logic never rewrites seeded students."""
    before = db_session.scalars(select(Student.usn).order_by(Student.usn)).all()
    assert "SIM23CSE001" in before and "01FE23BCS001" in before
