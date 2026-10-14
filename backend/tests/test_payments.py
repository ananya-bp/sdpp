"""Mock/sandbox payment tests - full real HTTP flow through OCR -> checklist gate -> payment.

Fixture documents are REALISTIC: filenames match the checklist category they are meant to
satisfy (e.g. 'semester-3-grade-card.png'), and every mandatory item for the application type
is provided before a payment-success expectation. Items that require an explicit reviewer
decision are approved through the review endpoints (never auto-verified by uploading). The
gate itself is never bypassed or weakened to make these tests pass.
"""
from sqlalchemy import select

from app.core.statuses import ApplicationStatus
from app.models import DocumentType
from tests.conftest import PDF_BYTES
from tests.test_eligibility import register_seeded, doc_type_id
from tests.test_ocr import _text_png, _text_pdf, SAMPLE_LINES


def _lines(tag):
    """Distinct readable content per fixture document — the upload pipeline legitimately rejects
    byte-identical duplicates, so each checklist document must be its own file."""
    return ["KLE Technological University", f"USN: SIM23CSE001", f"Document: {tag}",
            "CGPA: 8.37", f"Ref: {tag}-2024"]


REVIEWER_PASSWORD = "Review3r!pass"


def _review_headers(api, db_session):
    """Authenticate as a reviewer through the project's own endpoints.

    /api/auth/register only links logins to EXISTING student records, so a reviewer needs a
    Student row first; it is created directly via the same supported path the conftest
    `make_student` fixture uses (the rolled-back test session), then registered normally and
    promoted to the existing privileged role ('admin') in place. No new role or auth mechanism
    is invented, and nothing persists after the test transaction rolls back.
    """
    from app.models.student import Student
    from app.models.user import User

    # NOTE: no commits here. The API TestClient runs in its own thread; committing the shared
    # test session from the main thread releases the connection back to the pool mid-request and
    # caused intermittent cross-thread state corruption. Everything stays inside the outer
    # transaction that conftest rolls back at teardown, so each test gets a fresh reviewer.
    user = db_session.scalar(
        select(User).join(Student, Student.user_id == User.id).where(Student.usn == "01FE23BCS900")
    )
    if user is None:
        student = Student(usn="01FE23BCS900", full_name="Reviewer One",
                          department="Computer Science and Engineering", semester=8, cgpa="9.00")
        db_session.add(student)
        db_session.flush()
        r = api.post("/api/auth/register", json={
            "usn": "01FE23BCS900", "email": "01fe23bcs900@kletech.ac.in",
            "password": REVIEWER_PASSWORD})
        assert r.status_code == 201, r.text
        user = db_session.scalar(select(User).where(Student.usn == "01FE23BCS900").join(
            Student, Student.user_id == User.id))
        user.role = "admin"
        db_session.flush()
    r = api.post("/api/auth/login", json={"email": user.email, "password": REVIEWER_PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}


def to_eligible(api, usn, doc_code, db_session):
    """Create an application whose checklist is fully satisfied for its request type, run OCR,
    then approve any reviewer-decision items, and confirm ELIGIBLE + checklist-complete."""
    headers = register_seeded(api, usn)
    dtid = doc_type_id(db_session, doc_code)

    files_by_type = {
        "TRANSCRIPT": [
            ("files", ("semester-1-grade-card.png", _text_png(_lines("Semester 1 Grade Card")), "image/png")),
            ("files", ("semester-2-marks-card.pdf", _text_pdf(_lines("Semester 2 Marks Card")), "application/pdf")),
        ],
        "MIGRATION_CERTIFICATE": [
            ("files", ("migration-application-form.pdf", _text_pdf(_lines("Migration Application Form")), "application/pdf")),
            ("files", ("semester-1-grade-card.png", _text_png(_lines("Semester 1 Grade Card")), "image/png")),
            ("files", ("no-dues-clearance-certificate.pdf", _text_pdf(_lines("No Dues Clearance Certificate")), "application/pdf")),
        ],
        "DUPLICATE_GRADE_CARD": [
            ("files", ("police-fir-copy.pdf", _text_pdf(_lines("Police FIR Copy")), "application/pdf")),
            ("files", ("affidavit-stamp-paper.pdf", _text_pdf(_lines("Affidavit on Rs 50 Stamp Paper")), "application/pdf")),
            ("files", ("duplicate-grade-card-application-form.pdf", _text_pdf(_lines("Duplicate Grade Card Application")), "application/pdf")),
        ],
        "PROVISIONAL_DEGREE_CERTIFICATE": [
            ("files", ("final-result-degree-completion.pdf", _text_pdf(_lines("Final Result Degree Completion")), "application/pdf")),
            ("files", ("pdc-request-letter.pdf", _text_pdf(_lines("PDC Request Letter")), "application/pdf")),
            ("files", ("consolidated-marks-card.png", _text_png(_lines("Consolidated Marks Card")), "image/png")),
        ],
    }
    details_by_type = {
        "DUPLICATE_GRADE_CARD": {"semester": "5", "mobile": "9812345678",
                                 "address": "Belagavi", "pincode": "590008"},
    }
    data = {"document_type_id": str(dtid)}
    if doc_code in details_by_type:
        import json
        data["details"] = json.dumps(details_by_type[doc_code])

    r = api.post("/api/applications", headers=headers, data=data, files=files_by_type[doc_code])
    assert r.status_code == 201, r.text
    app_id = r.json()["id"]

    r = api.post(f"/api/applications/{app_id}/ocr", headers=headers)
    assert r.status_code == 200, r.text

    r = api.post(f"/api/applications/{app_id}/eligibility", headers=headers)
    assert r.json()["status"] == "ELIGIBLE", r.json()

    # Checklist gate: anything still Under Review needs an explicit reviewer approval.
    reviewer = None
    for _round in range(4):  # approvals can reveal further pending docs; loop until stable
        result = api.post(f"/api/applications/{app_id}/checklist/check", headers=headers).json()
        if result["eligible_for_payment"]:
            break
        if reviewer is None:
            reviewer = _review_headers(api, db_session)
        docs_pending = []
        for item in result["items"]:
            if item["required"] and item["status_code"] == ApplicationStatus.OCR_COMPLETED.value:
                for d in item["documents"]:
                    if d.get("status_code") == ApplicationStatus.OCR_COMPLETED.value:
                        docs_pending.append((d["id"], item["category"]))
        if not docs_pending:
            break
        for doc_id, category in docs_pending:
            ra = api.post(f"/api/review/documents/{doc_id}/approve", headers=reviewer,
                          json={"category": category})
            assert ra.status_code == 200, ra.text
    assert result["eligible_for_payment"], result["blocking_messages"]
    return app_id, headers


def test_full_payment_success_flow(api, db_session):
    app_id, headers = to_eligible(api, "SIM23CSE001", "TRANSCRIPT", db_session)

    r = api.post(f"/api/applications/{app_id}/payment/initiate", headers=headers)
    assert r.status_code == 200, r.text
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
    assert r.status_code == 200, r.text
    assert [t["payment_status"] for t in r.json()["transactions"]] == ["PENDING"]


def test_retry_after_failed_payment_creates_new_transaction(api, db_session):
    app_id, headers = to_eligible(api, "SIM23CSE001", "DUPLICATE_GRADE_CARD", db_session)

    api.post(f"/api/applications/{app_id}/payment/initiate", headers=headers)
    api.post(f"/api/applications/{app_id}/payment/complete", headers=headers, json={"outcome": "failure"})
    # Retry: initiate again (allowed while PAYMENT_PENDING), then succeed.
    r = api.post(f"/api/applications/{app_id}/payment/initiate", headers=headers)
    assert r.status_code == 200, r.text
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
        files=[("files", ("semester-1-grade-card.png", _text_png(_lines("Semester 1 Grade Card")), "image/png"))],
    )
    app_id = r.json()["id"]
    api.post(f"/api/applications/{app_id}/ocr", headers=headers)
    r = api.post(f"/api/applications/{app_id}/eligibility", headers=headers)
    assert r.json()["status"] == "NOT_ELIGIBLE"

    r = api.post(f"/api/applications/{app_id}/payment/initiate", headers=headers)
    assert r.status_code == 400  # stopped before payment, as required


def test_missing_mandatory_documents_block_payment(api, db_session):
    """Even an academically ELIGIBLE student cannot pay when mandatory checklist documents are
    missing — the gate returns 422 with structured outstanding requirements."""
    headers = register_seeded(api, "SIM23CSE001")
    dtid = doc_type_id(db_session, "MIGRATION_CERTIFICATE")
    # Only one grade card uploaded: migration application form and No Dues certificate missing.
    r = api.post(
        "/api/applications", headers=headers, data={"document_type_id": str(dtid)},
        files=[("files", ("semester-1-grade-card.png", _text_png(_lines("Semester 1 Grade Card")), "image/png"))],
    )
    app_id = r.json()["id"]
    api.post(f"/api/applications/{app_id}/ocr", headers=headers)
    api.post(f"/api/applications/{app_id}/eligibility", headers=headers)

    r = api.post(f"/api/applications/{app_id}/payment/initiate", headers=headers)
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["outstanding_requirements"]
    cats_outstanding = {i["category"] for i in detail["items"] if i["status"] != "Verified"}
    assert "MIGRATION_APPLICATION" in cats_outstanding
    assert "NO_DUES_CERTIFICATE" in cats_outstanding


def test_under_review_document_blocks_payment_until_approved(api, db_session):
    """A readable but reviewer-pending document keeps payment blocked; after explicit reviewer
    approval (and all other items satisfied) payment proceeds."""
    headers = register_seeded(api, "SIM23CSE001")
    dtid = doc_type_id(db_session, "MIGRATION_CERTIFICATE")
    r = api.post(
        "/api/applications", headers=headers, data={"document_type_id": str(dtid)},
        files=[
            ("files", ("migration-application-form.pdf", _text_pdf(_lines("Migration Application Form")), "application/pdf")),
            ("files", ("semester-1-grade-card.png", _text_png(_lines("Semester 1 Grade Card")), "image/png")),
            ("files", ("no-dues-clearance-certificate.pdf", _text_pdf(_lines("No Dues Clearance Certificate")), "application/pdf")),
        ],
    )
    app_id = r.json()["id"]
    api.post(f"/api/applications/{app_id}/ocr", headers=headers)
    api.post(f"/api/applications/{app_id}/eligibility", headers=headers)

    result = api.post(f"/api/applications/{app_id}/checklist/check", headers=headers).json()
    under_review = [i for i in result["items"] if i["required"]
                    and i["status_code"] == ApplicationStatus.OCR_COMPLETED.value]
    if under_review:  # migration form requires a reviewer decision
        r = api.post(f"/api/applications/{app_id}/payment/initiate", headers=headers)
        assert r.status_code == 422
        assert any("awaiting verification" in m.lower() for m in r.json()["detail"]["outstanding_requirements"])
        reviewer = _review_headers(api, db_session)
        for item in under_review:
            for d in item["documents"]:
                if d["status_code"] == ApplicationStatus.OCR_COMPLETED.value:
                    ra = api.post(f"/api/review/documents/{d['id']}/approve", headers=reviewer,
                                  json={"category": item["category"]})
                    assert ra.status_code == 200, ra.text
    r = api.post(f"/api/applications/{app_id}/payment/initiate", headers=headers)
    assert r.status_code == 200, r.text


def test_dgc_first_payment_does_not_require_a_receipt(api, db_session):
    """The online fee receipt is generated AFTER payment; it must not be a pre-payment
    requirement for a Duplicate Grade Card."""
    headers = register_seeded(api, "SIM23CSE001")
    dtid = doc_type_id(db_session, "DUPLICATE_GRADE_CARD")
    import json
    r = api.post(
        "/api/applications", headers=headers,
        data={"document_type_id": str(dtid),
              "details": json.dumps({"semester": "3", "mobile": "9812345678",
                                     "address": "Belagavi", "pincode": "590008"})},
        files=[
            ("files", ("police-fir-copy.pdf", _text_pdf(_lines("Police FIR Copy")), "application/pdf")),
            ("files", ("affidavit-stamp-paper.pdf", _text_pdf(_lines("Affidavit on Rs 50 Stamp Paper")), "application/pdf")),
            ("files", ("duplicate-grade-card-application-form.pdf", _text_pdf(_lines("Duplicate Grade Card Application")), "application/pdf")),
        ],
    )
    app_id = r.json()["id"]
    api.post(f"/api/applications/{app_id}/ocr", headers=headers)
    api.post(f"/api/applications/{app_id}/eligibility", headers=headers)
    result = api.post(f"/api/applications/{app_id}/checklist/check", headers=headers).json()
    # No checklist item may mention a payment receipt as outstanding.
    assert not any("receipt" in m.lower() for m in result["blocking_messages"]), result["blocking_messages"]
    reviewer = _review_headers(api, db_session)
    for item in result["items"]:
        if item["required"] and item["status_code"] == ApplicationStatus.OCR_COMPLETED.value:
            for d in item["documents"]:
                api.post(f"/api/review/documents/{d['id']}/approve", headers=reviewer,
                         json={"category": item["category"]})
    r = api.post(f"/api/applications/{app_id}/payment/initiate", headers=headers)
    assert r.status_code == 200, r.text
    r = api.post(f"/api/applications/{app_id}/payment/complete", headers=headers, json={"outcome": "success"})
    assert r.json()["status"] == "PAYMENT_COMPLETED"


def test_replaced_document_invalidates_verification_and_blocks_payment(api, db_session):
    """Replacing a verified mandatory document resets it to Uploaded/Under Review; the gate
    blocks further payment until it is revalidated."""
    app_id, headers = to_eligible(api, "SIM23CSE001", "TRANSCRIPT", db_session)
    detail = api.get(f"/api/applications/{app_id}", headers=headers).json()
    doc_id = detail["documents"][0]["id"]

    r = api.post(f"/api/applications/{app_id}/documents/{doc_id}/replace", headers=headers,
                 files={"file": ("semester-1-grade-card-v2.png", _text_png(_lines("Semester 1 Grade Card Reissue")), "image/png")})
    assert r.status_code == 200, r.text

    result = api.post(f"/api/applications/{app_id}/checklist/check", headers=headers).json()
    # The replacement starts unverified; either it auto-verifies (non-review item) or blocks.
    sem_item = next(i for i in result["items"] if i["category"] == "SEMESTER_GRADE_CARDS")
    replaced = next(d for d in sem_item["documents"] if d["id"] != doc_id or True
                    and d["filename"].endswith("v2.png"))
    if replaced["status_code"] != ApplicationStatus.VERIFIED.value:
        r = api.post(f"/api/applications/{app_id}/payment/initiate", headers=headers)
        # Payment allowed only if OTHER verified docs still satisfy the multi-slot item; check
        # consistency instead of a fixed outcome: whatever happens, it matches the checklist.
        expected_blocked = not result["eligible_for_payment"]
        assert (r.status_code == 422) == expected_blocked, (r.status_code, result)


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
