"""Sandbox/mock payment for an eligible application - see SDP_BUILD_GUIDE.md section 1.3
("sandbox/mock payment, no real gateway") and section 1.5 (transactions.amount had no source of
truth yet as of Phase 2).

FEE_BY_DOCUMENT_TYPE below is a PLACEHOLDER fee schedule, not a real KLE Tech fee structure (none
was given for this build - same "don't invent institutional policy" situation as the eligibility
thresholds in app/services/eligibility.py). Round, clearly-fake numbers on purpose so nobody
mistakes them for a real fee circular.

There's no real gateway to call back from, so this mock takes the outcome as an explicit input
(`outcome="success"` or `"failure"`) representing what a real gateway's callback would report -
this is the sandbox simplification: a real integration would replace `complete_payment`'s caller
with an actual webhook handler, not this test controlling the result directly.
"""
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.statuses import ApplicationStatus
from app.models import Application, Transaction

FEE_BY_DOCUMENT_TYPE: dict[str, Decimal] = {
    "TRANSCRIPT": Decimal("200.00"),
    "MIGRATION_CERTIFICATE": Decimal("500.00"),
    "DUPLICATE_GRADE_CARD": Decimal("150.00"),
    "PROVISIONAL_DEGREE_CERTIFICATE": Decimal("300.00"),
}


def initiate_payment(db: Session, application: Application, changed_by: int | None = None) -> Transaction:
    """Start a payment attempt: a new PENDING transaction, and the application moves to
    PAYMENT_PENDING. Safe to call again after a FAILED attempt (a fresh transaction is created
    for the retry, and the old FAILED row is kept - both feed the Phase 5C anomaly-detection
    "rapid retries" signal later)."""
    amount = FEE_BY_DOCUMENT_TYPE.get(application.document_type.code, Decimal("0.00"))
    transaction = Transaction(application_id=application.id, amount=amount, payment_status="PENDING")
    db.add(transaction)

    from app.services.applications import set_status  # local import: avoids a circular import

    set_status(
        db, application, ApplicationStatus.PAYMENT_PENDING, changed_by=changed_by,
        note=f"Payment initiated: {amount}",
    )
    db.commit()
    db.refresh(transaction)
    return transaction


def complete_payment(
    db: Session, application: Application, transaction: Transaction, outcome: str, changed_by: int | None = None
) -> Transaction:
    """Record the mock gateway's result. Only a real 'success' advances the application; a
    'failure' updates the transaction row and leaves the application at PAYMENT_PENDING so the
    student can retry - it must never be silently marked completed."""
    if outcome == "success":
        transaction.payment_status = "SUCCESS"

        from app.services.applications import set_status  # local import: avoids a circular import

        set_status(
            db, application, ApplicationStatus.PAYMENT_COMPLETED, changed_by=changed_by,
            note=f"Payment completed: {transaction.amount}",
        )
    else:
        transaction.payment_status = "FAILED"
    db.commit()
    db.refresh(transaction)
    return transaction
