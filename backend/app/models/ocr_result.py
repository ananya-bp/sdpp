from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class OcrResult(Base):
    """OCR output for one uploaded supporting document (Phase 3).

    One row per UploadedDocument (unique constraint). OCR is a supporting document-processing
    step, not one of the three core ML components (see SDP_BUILD_GUIDE.md section 1.5).
    """

    __tablename__ = "ocr_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    uploaded_document_id: Mapped[int] = mapped_column(
        ForeignKey("uploaded_documents.id", ondelete="CASCADE"), unique=True, index=True
    )
    status: Mapped[str] = mapped_column(String(20))  # SUCCESS / FAILED
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_fields: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Back-reference so deleting an UploadedDocument cascades cleanly through the ORM too
    # (the DB-level ON DELETE CASCADE already protects the table itself).
    uploaded_document: Mapped["UploadedDocument"] = relationship(back_populates="ocr_result")  # noqa: F821
