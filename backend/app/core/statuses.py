"""Application status vocabulary, one value per stage of the workflow.

Phase 2 only ever sets SUBMITTED. The remaining values are used by later phases
(3: OCR/eligibility/payment, 7: admin review/document generation). Stored as plain strings
in the database, so adding a value later needs no migration.
"""
from enum import StrEnum


class ApplicationStatus(StrEnum):
    SUBMITTED = "SUBMITTED"
    OCR_COMPLETED = "OCR_COMPLETED"
    ELIGIBLE = "ELIGIBLE"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    MANUAL_REVIEW = "MANUAL_REVIEW"  # eligibility uncertain; routed to admin review
    PAYMENT_PENDING = "PAYMENT_PENDING"
    PAYMENT_COMPLETED = "PAYMENT_COMPLETED"
    UNDER_REVIEW = "UNDER_REVIEW"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    DOCUMENT_GENERATED = "DOCUMENT_GENERATED"


STATUS_LABELS = {
    ApplicationStatus.SUBMITTED: "Submitted",
    ApplicationStatus.OCR_COMPLETED: "Documents processed",
    ApplicationStatus.ELIGIBLE: "Eligible",
    ApplicationStatus.NOT_ELIGIBLE: "Not eligible",
    ApplicationStatus.MANUAL_REVIEW: "Pending manual review",
    ApplicationStatus.PAYMENT_PENDING: "Payment pending",
    ApplicationStatus.PAYMENT_COMPLETED: "Payment completed",
    ApplicationStatus.UNDER_REVIEW: "Under admin review",
    ApplicationStatus.VERIFIED: "Verified",
    ApplicationStatus.REJECTED: "Rejected",
    ApplicationStatus.DOCUMENT_GENERATED: "Document ready",
}


def status_label(value: str) -> str:
    """Human-friendly label for a stored status string (falls back to the raw value)."""
    try:
        return STATUS_LABELS[ApplicationStatus(value)]
    except ValueError:
        return value
