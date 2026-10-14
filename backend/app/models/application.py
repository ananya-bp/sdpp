from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.document_type import DocumentType  # noqa: F401  (relationship target)
from app.models.transaction import Transaction  # noqa: F401  (relationship target)


class Application(Base):
    """One request for one document by one student.

    Turnaround time (TAT) is NOT stored: it is derived later as (end timestamp - submitted_at),
    so it can never go out of sync. The exact end point is settled in Phase 4.
    """

    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="RESTRICT"), index=True)
    document_type_id: Mapped[int] = mapped_column(
        ForeignKey("document_types.id", ondelete="RESTRICT"), index=True
    )
    # Status vocabulary is finalised in Phase 2; the initial value is always 'SUBMITTED'.
    status: Mapped[str] = mapped_column(String(30), default="SUBMITTED", server_default="SUBMITTED", index=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    document_type: Mapped["DocumentType"] = relationship()
    documents: Mapped[list["UploadedDocument"]] = relationship(
        order_by="UploadedDocument.id", cascade="all, delete-orphan", passive_deletes=True
    )
    history: Mapped[list["ApplicationStatusHistory"]] = relationship(
        order_by="ApplicationStatusHistory.id", cascade="all, delete-orphan", passive_deletes=True
    )
    transactions: Mapped[list["Transaction"]] = relationship(order_by="Transaction.id")


class ApplicationStatusHistory(Base):
    """Append-only log of status changes: powers live tracking and the audit trail."""

    __tablename__ = "application_status_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(30))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    changed_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
