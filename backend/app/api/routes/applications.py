import json
import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_student
from app.core.statuses import ApplicationStatus
from app.db.session import get_db
from app.models import DocumentType, Student, UploadedDocument
from app.schemas.application import ApplicationDetail, ApplicationSummary, PaymentCompleteIn
from app.services import applications as service
from app.services import document_checklist
from app.services import eligibility as eligibility_service
from app.services import ocr as ocr_service
from app.services import payments as payment_service
from app.services import processing as processing_service
from app.services import request_specs, uploads

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/applications", tags=["applications"])


@router.post("", response_model=ApplicationDetail, status_code=201)
def submit_application(
    document_type_id: int = Form(...),
    details: str = Form(default="{}"),
    files: list[UploadFile] = File(default=[]),
    student: Student = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    """Submit an application for one document type, with optional supporting files (multipart form).

    `details` is a JSON object of request-specific form fields (see GET /api/config/forms); the
    backend re-validates them per request type so requirements cannot be bypassed by calling the
    API directly. Field/document problems return 422 with actionable field-level errors.
    """
    document_type = db.get(DocumentType, document_type_id)
    if document_type is None or not document_type.is_active:
        raise HTTPException(400, "Unknown document type.")

    try:
        parsed_details = json.loads(details) if details else {}
    except (ValueError, TypeError):
        raise HTTPException(422, {"errors": ["'details' must be a JSON object."]})
    if not isinstance(parsed_details, dict):
        raise HTTPException(422, {"errors": ["'details' must be a JSON object."]})

    items = uploads.validate_uploads(files)  # raises 400/413 before anything is saved

    spec_errors = request_specs.validate_submission(
        document_type.code, parsed_details, {i.extension for i in items}
    )
    if spec_errors:
        raise HTTPException(422, {"errors": spec_errors})

    application = service.create_application(db, student, document_type, items, details_json=json.dumps(parsed_details))
    # Assign checklist categories from filename hints while the uploads are still in memory and
    # persist them (create_application's commit precedes this), so every later request/session —
    # including the read-only GET checklist — sees the same deterministic classification.
    document_checklist.assign_categories(application)
    db.commit()
    return service.load_application(db, application.id, student.id)


@router.post("/{application_id}/documents/{document_id}/replace", response_model=ApplicationDetail)
def replace_document(
    application_id: int,
    document_id: int,
    file: UploadFile = File(...),
    student: Student = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    """Replace one uploaded document (e.g. after rejection).

    The old row is deleted with its OCR result and file; the replacement keeps the checklist
    category but starts verification again from scratch, so any previous VERIFIED status for it
    is invalidated and payment stays blocked until it validates. Ownership is enforced by
    loading the application through the student's own record only.
    """
    application = service.load_application(db, application_id, student.id)
    if application is None:
        raise HTTPException(404, "Application not found.")
    old = next((d for d in application.documents if d.id == document_id), None)
    if old is None:
        raise HTTPException(404, "Document not found on this application.")

    items = uploads.validate_uploads([file])  # raises 400/413 before anything is saved
    item = items[0]

    relative = uploads.store_file(application.id, item)
    try:
        new_doc = UploadedDocument(
            application_id=application.id,
            original_filename=item.original_filename,
            stored_path=relative,
            content_type=item.content_type,
            size_bytes=len(item.data),
            extension=item.extension,
            document_category=old.document_category,   # keep its place on the checklist
            validation_status=None,                    # -> treated as Uploaded; revalidated
            version=(old.version or 1) + 1,
            replaces_document_id=old.id,
        )
        db.add(new_doc)
        db.delete(old)
        db.commit()
    except Exception:
        uploads.remove_stored_files([relative])
        db.rollback()
        raise
    return service.load_application(db, application_id, student.id)


@router.get("", response_model=list[ApplicationSummary])
def my_applications(student: Student = Depends(get_current_student), db: Session = Depends(get_db)):
    """The signed-in student's applications, newest first."""
    return service.list_applications(db, student.id)


@router.get("/{application_id}", response_model=ApplicationDetail)
def my_application(
    application_id: int,
    student: Student = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    """One of the signed-in student's applications, with files and status history."""
    application = service.load_application(db, application_id, student.id)
    if application is None:  # not found, or belongs to someone else: same answer on purpose
        raise HTTPException(404, "Application not found.")
    return application


@router.post("/{application_id}/ocr", response_model=ApplicationDetail)
def run_ocr(
    application_id: int,
    student: Student = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    """Run OCR on this application's supporting documents and advance it to OCR_COMPLETED.

    Safe to call again (e.g. after fixing an upload): each file's OCR result is replaced, not
    duplicated, and a new OCR_COMPLETED history entry is appended either way.
    """
    application = service.load_application(db, application_id, student.id)
    if application is None:
        raise HTTPException(404, "Application not found.")
    if application.status == ApplicationStatus.SUBMITTED.value or application.status == ApplicationStatus.OCR_COMPLETED.value:
        ocr_service.run_ocr_for_application(db, application, changed_by=student.user_id)
        return service.load_application(db, application_id, student.id)
    raise HTTPException(400, f"Cannot run OCR on an application with status '{application.status}'.")


@router.post("/{application_id}/process", response_model=ApplicationDetail)
def process_application(
    application_id: int,
    retry_ocr: bool = False,
    student: Student = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    """Run the automatic post-submission steps: OCR, then (only if OCR succeeded) eligibility.

    Used by the student portal right after submission. Idempotent and safe to call repeatedly or
    concurrently - see app/services/processing.py. `retry_ocr=true` re-runs OCR when a file failed.
    Never starts a payment.
    """
    try:
        application = processing_service.process_application(
            db, application_id, student, retry_failed_ocr=retry_ocr
        )
    except Exception:
        db.rollback()
        logger.exception("Automatic processing failed for application %s", application_id)
        raise HTTPException(
            500,
            "Processing could not be completed. Your application and documents were saved; "
            "please try again.",
        )
    if application is None:
        raise HTTPException(404, "Application not found.")
    return application


_ELIGIBILITY_ALLOWED_FROM = {
    ApplicationStatus.OCR_COMPLETED.value,
    ApplicationStatus.ELIGIBLE.value,
    ApplicationStatus.NOT_ELIGIBLE.value,
    ApplicationStatus.MANUAL_REVIEW.value,   # re-run allowed after student uploads new docs
}


@router.post("/{application_id}/eligibility", response_model=ApplicationDetail)
def run_eligibility(
    application_id: int,
    student: Student = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    """Evaluate rule-based eligibility (deterministic - see SDP_BUILD_GUIDE.md section 1.4).

    Requires OCR to have run first (OCR_COMPLETED), matching the workflow order in section 1.2.
    Re-running is allowed (e.g. after the student adds a missing document and resubmits OCR).
    """
    application = service.load_application(db, application_id, student.id)
    if application is None:
        raise HTTPException(404, "Application not found.")
    if application.status not in _ELIGIBILITY_ALLOWED_FROM:
        raise HTTPException(
            400,
            f"Cannot evaluate eligibility on an application with status '{application.status}'. "
            "Run OCR first.",
        )
    eligibility_service.run_eligibility_for_application(db, application, student, changed_by=student.user_id)
    return service.load_application(db, application_id, student.id)


@router.get("/{application_id}/checklist")
def get_checklist(
    application_id: int,
    student: Student = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    """The document checklist for this application's request type, with current upload status.

    Read-only view (no persistence side effects) so opening it never changes validation state.
    """
    application = service.load_application(db, application_id, student.id)
    if application is None:
        raise HTTPException(404, "Application not found.")
    result = document_checklist.evaluate_checklist(db, application, student, persist=False)
    return {
        **document_checklist.checklist_payload(application.document_type.code),
        "evaluation": result,
    }


@router.post("/{application_id}/checklist/check")
def check_eligibility(
    application_id: int,
    student: Student = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    """"Check Eligibility": run automated document verification and evaluate the checklist.

    Persists newly derived statuses. Missing documents, rejected files and items awaiting
    review are reported explicitly; payment remains blocked until every mandatory item is
    Verified.
    """
    application = service.load_application(db, application_id, student.id)
    if application is None:
        raise HTTPException(404, "Application not found.")
    result = document_checklist.evaluate_checklist(db, application, student)
    return result


@router.post("/{application_id}/payment/initiate", response_model=ApplicationDetail)
def initiate_payment(
    application_id: int,
    student: Student = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    """Start a mock/sandbox payment - see app/services/payments.py. Only an ELIGIBLE application
    can start paying (an ineligible one must stop here); a PAYMENT_PENDING application can call
    this again to retry after a failed attempt.

    DOCUMENT CHECKLIST GATE (authoritative, server-side): before any transaction row is created
    the checklist is re-evaluated from database records — every mandatory document uploaded,
    validated and Verified (or reviewer-approved). Frontend eligibility flags are never trusted.
    A retry on an existing PAYMENT_PENDING application re-checks too, so eligibility that
    changed after the order was created blocks further payment attempts.
    """
    application = service.load_application(db, application_id, student.id)
    if application is None:
        raise HTTPException(404, "Application not found.")
    if application.status not in (ApplicationStatus.ELIGIBLE.value, ApplicationStatus.PAYMENT_PENDING.value):
        raise HTTPException(
            400,
            f"Cannot start payment on an application with status '{application.status}'. "
            "The application must be ELIGIBLE first.",
        )
    checklist_result = document_checklist.evaluate_checklist(db, application, student)
    if not checklist_result["eligible_for_payment"]:
        raise HTTPException(
            422,
            {
                "message": "Payment is blocked until every required document has been uploaded and verified.",
                "outstanding_requirements": checklist_result["blocking_messages"],
                "progress": checklist_result["progress"],
                "items": [
                    {"category": i["category"], "label": i["label"], "required": i["required"],
                     "status": i["status"], "reason": i["note"]}
                    for i in checklist_result["items"] if i["required"]
                ],
            },
        )
    payment_service.initiate_payment(db, application, changed_by=student.user_id)
    return service.load_application(db, application_id, student.id)


@router.post("/{application_id}/payment/complete", response_model=ApplicationDetail)
def complete_payment(
    application_id: int,
    body: PaymentCompleteIn,
    student: Student = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    """Record the mock gateway's result for the most recent PENDING transaction.

    A 'failure' outcome updates that transaction and leaves the application at PAYMENT_PENDING
    (never silently marked completed); only 'success' advances it to PAYMENT_COMPLETED.
    """
    if body.outcome not in ("success", "failure"):
        raise HTTPException(400, "outcome must be 'success' or 'failure'.")
    application = service.load_application(db, application_id, student.id)
    if application is None:
        raise HTTPException(404, "Application not found.")
    if application.status != ApplicationStatus.PAYMENT_PENDING.value:
        raise HTTPException(400, f"No payment is pending on this application (status '{application.status}').")
    pending = [t for t in application.transactions if t.payment_status == "PENDING"]
    if not pending:
        raise HTTPException(400, "No pending transaction to complete.")
    payment_service.complete_payment(db, application, pending[-1], body.outcome, changed_by=student.user_id)
    return service.load_application(db, application_id, student.id)
