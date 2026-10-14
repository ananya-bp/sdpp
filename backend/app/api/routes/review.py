"""Authorized-reviewer workflow for document verification (checklist feature).

Reviewers are existing `role='admin'` users — no new role is invented and no auth mechanism is
changed. Students can never reach these endpoints; students can never set their own documents'
verification status through the ordinary upload/replace routes (those only ever store automated
statuses derived server-side).

Statuses reuse the existing ApplicationStatus vocabulary (see document_checklist):
    OCR_COMPLETED -> "Under Review", VERIFIED -> approved, REJECTED -> rejected with reason.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_user
from app.core.statuses import ApplicationStatus
from app.db.session import get_db
from app.models import Application, UploadedDocument, User
from app.services import document_checklist

router = APIRouter(prefix="/review", tags=["review"])


def get_reviewer(user: User = Depends(get_current_user)) -> User:
    """Reviewer authorization: only the project's existing privileged role ('admin')."""
    if user.role != "admin":
        raise HTTPException(403, "Reviewer (admin) account required.")
    return user


class ReviewDecisionIn(BaseModel):
    category: str | None = Field(
        None, description="Checklist category this document satisfies (reviewer decision)."
    )
    reason: str | None = Field(None, description="Reviewer note stored with the decision.")


class RejectIn(BaseModel):
    reason: str = Field(min_length=5, max_length=2000)
    category: str | None = None


def _load_doc(db: Session, document_id: int) -> UploadedDocument:
    doc = db.scalar(
        select(UploadedDocument)
        .where(UploadedDocument.id == document_id)
        .options(joinedload(UploadedDocument.application).joinedload(Application.document_type))
    )
    if doc is None:
        raise HTTPException(404, "Document not found.")
    return doc


@router.get("/pending")
def list_pending(reviewer: User = Depends(get_reviewer), db: Session = Depends(get_db)):
    """Documents awaiting a reviewer decision across all applications."""
    docs = db.scalars(
        select(UploadedDocument)
        .where(UploadedDocument.validation_status == ApplicationStatus.OCR_COMPLETED.value)
        .order_by(UploadedDocument.uploaded_at)
        .options(joinedload(UploadedDocument.application).joinedload(Application.document_type))
    ).all()
    out = []
    for d in docs:
        checklist = document_checklist.get_checklist(d.application.document_type.code)
        cats = [c.category for c in checklist]
        current = getattr(d, "document_category", None)
        # In-request hint assignment to show reviewers a proposed category (never a verdict).
        proposed = document_checklist.guess_category(
            d.original_filename, d.ocr_result.raw_text if d.ocr_result else None
        )
        out.append(
            {
                "document_id": d.id,
                "application_id": d.application_id,
                "student_usn": d.application.student.usn if d.application.student else None,
                "document_type": d.application.document_type.code,
                "filename": d.original_filename,
                "uploaded_at": d.uploaded_at.isoformat() if d.uploaded_at else None,
                "current_category": current if current in cats else None,
                "proposed_category": proposed if proposed in cats else None,
                "categories": cats,
                "reason": document_checklist.strip_review_marker(d.validation_reason),
            }
        )
    return {"count": len(out), "documents": out}


@router.post("/documents/{document_id}/approve")
def approve_document(
    document_id: int,
    body: ReviewDecisionIn,
    reviewer: User = Depends(get_reviewer),
    db: Session = Depends(get_db),
):
    """Explicit reviewer approval. Verification comes from THIS action, never from a successful
    upload or OCR extraction alone."""
    doc = _load_doc(db, document_id)
    application = doc.application
    code = application.document_type.code
    cats = [c.category for c in document_checklist.get_checklist(code)]
    category = body.category or getattr(doc, "document_category", None)
    if category in (None, "UNASSIGNED"):
        raise HTTPException(
            422,
            {"message": "A checklist category is required before approving.", "categories": cats},
        )
    if category not in cats:
        raise HTTPException(
            422,
            {"message": f"'{category}' is not a valid checklist category for {code}.", "categories": cats},
        )
    now = datetime.now(timezone.utc)
    doc.document_category = category
    doc.validation_status = ApplicationStatus.VERIFIED.value
    note = body.reason.strip() if body.reason else "Approved by reviewer."
    document_checklist.record_review_category(db, doc, category)
    # record_review_category rewrites validation_reason; compose final reason with reviewer note.
    doc.validation_reason = f"{note} [{category}]"
    doc.reviewed_by = reviewer.id
    doc.reviewed_at = now
    doc.verified_at = now
    db.commit()
    result = document_checklist.evaluate_checklist(db, application, application.student)
    return {
        "document_id": doc.id,
        "status": doc.validation_status,
        "category": category,
        "eligibility": result,
    }


@router.post("/documents/{document_id}/reject")
def reject_document(
    document_id: int,
    body: RejectIn,
    reviewer: User = Depends(get_reviewer),
    db: Session = Depends(get_db),
):
    """Reviewer rejection. A reason is mandatory; the document stays blocking payment until the
    student replaces it."""
    doc = _load_doc(db, document_id)
    application = doc.application
    code = application.document_type.code
    category = body.category or getattr(doc, "document_category", None)
    cats = [c.category for c in document_checklist.get_checklist(code)]
    if category and category not in cats:
        raise HTTPException(
            422, {"message": f"'{category}' is not a valid checklist category for {code}.", "categories": cats}
        )
    now = datetime.now(timezone.utc)
    if category:
        doc.document_category = category
        document_checklist.record_review_category(db, doc, category)
    doc.validation_status = ApplicationStatus.REJECTED.value
    doc.validation_reason = body.reason.strip()
    if category:
        doc.validation_reason = f"{body.reason.strip()} [{category}]"
    doc.reviewed_by = reviewer.id
    doc.reviewed_at = now
    doc.verified_at = None  # any previous verification is invalidated
    db.commit()
    result = document_checklist.evaluate_checklist(db, application, application.student)
    return {"document_id": doc.id, "status": doc.validation_status, "eligibility": result}
