import json
from app.models import DocumentType, UploadedDocument, Application
from sqlalchemy import select
from tests.test_ocr import _text_pdf, _text_png

def _lines(tag):
    return ["KLE Technological University", "USN: SIM23CSE001", f"Document: {tag}", "CGPA: 8.37", f"Ref: {tag}-2024"]

def test_debug(api, db_session):
    from tests.test_eligibility import register_seeded, doc_type_id
    headers = register_seeded(api, "SIM23CSE001")
    dtid = doc_type_id(db_session, "MIGRATION_CERTIFICATE")
    r = api.post("/api/applications", headers=headers, data={"document_type_id": str(dtid)}, files=[
        ("files", ("migration-application-form.pdf", _text_pdf(_lines("Migration Application Form")), "application/pdf")),
        ("files", ("semester-1-grade-card.png", _text_png(_lines("Semester 1 Grade Card")), "image/png")),
        ("files", ("no-dues-clearance-certificate.pdf", _text_pdf(_lines("No Dues Clearance Certificate")), "application/pdf")),
    ])
    assert r.status_code == 201, r.text
    app_id = r.json()["id"]
    for d in db_session.scalars(select(UploadedDocument).filter_by(application_id=app_id)):
        print("ROW:", d.id, repr(d.original_filename), repr(d.stored_path), repr(d.document_category), repr(d.validation_status))
    r = api.post(f"/api/applications/{app_id}/ocr", headers=headers)
    print("OCR:", r.status_code, json.dumps(r.json())[:300])
    for d in db_session.scalars(select(UploadedDocument).filter_by(application_id=app_id)):
        db_session.refresh(d)
        print("POST-OCR ROW:", d.id, repr(d.original_filename), repr(d.document_category), repr(d.validation_status))
    res = api.post(f"/api/applications/{app_id}/checklist/check", headers=headers).json()
    print(json.dumps(res["items"], indent=1)[:2000])
    assert False
