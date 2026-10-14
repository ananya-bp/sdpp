import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_student
from app.core.statuses import ApplicationStatus
from app.db.session import get_db
from app.models import DocumentType, Student
from app.schemas.application import ApplicationDetail, ApplicationSummary, PaymentCompleteIn
from app.services import applications as service
from app.services import eligibility as eligibility_service
from app.services import ocr as ocr_service
from app.services import payments as payment_service
from app.services import processing as processing_service
from app.services import uploads

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/applications", tags=["applications"])


@router.post("", response_model=ApplicationDetail, status_code=201)
def submit_application(
    document_type_id: int = Form(...),
    files: list[UploadFile] = File(default=[]),
    student: Student = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    """Submit an application for one document type, with optional supporting files (multipart form)."""
    document_type = db.get(DocumentType, document_type_id)
    if document_type is None or not document_type.is_active:
        raise HTTPException(400, "Unknown document type.")

    items = uploads.validate_uploads(files)  # raises 400/413 before anything is saved
    application = service.create_application(db, student, document_type, items)
    return service.load_application(db, application.id, student.id)


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


@router.post("/{application_id}/payment/initiate", response_model=ApplicationDetail)
def initiate_payment(
    application_id: int,
    student: Student = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    """Start a mock/sandbox payment - see app/services/payments.py. Only an ELIGIBLE application
    can start paying (an ineligible one must stop here); a PAYMENT_PENDING application can call
    this again to retry after a failed attempt."""
    application = service.load_application(db, application_id, student.id)
    if application is None:
        raise HTTPException(404, "Application not found.")
    if application.status not in (ApplicationStatus.ELIGIBLE.value, ApplicationStatus.PAYMENT_PENDING.value):
        raise HTTPException(
            400,
            f"Cannot start payment on an application with status '{application.status}'. "
            "The application must be ELIGIBLE first.",
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
