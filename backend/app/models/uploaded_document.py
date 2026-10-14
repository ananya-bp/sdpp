from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.ocr_result import OcrResult  # noqa: F401  (relationship target)


class UploadedDocument(Base):
    """A supporting file a student uploaded with an application (PDF, JPG or PNG).

    The file itself lives on disk under UPLOAD_DIR; stored_path is relative to that folder.
    """

    __tablename__ = "uploaded_documents"
    __table_args__ = (CheckConstraint("size_bytes > 0", name="size_positive"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    original_filename: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(String(500))
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int]
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Phase 3: OCR output for this file, if OCR has been run.
    ocr_result: Mapped["OcrResult | None"] = relationship(
        cascade="all, delete-orphan", passive_deletes=True, uselist=False
    )
