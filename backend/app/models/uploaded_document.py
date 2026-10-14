from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.ext.hybrid import hybrid_property
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

    @hybrid_property
    def extension(self) -> str | None:  # type: ignore[no-redef]
        """Normalised extension (pdf/jpg/jpeg/png) — not a DB column, no migration needed.

        For in-flight upload objects (before INSERT) this returns the validated extension of
        the file content that was attached at construction time; for rows loaded from the
        database it is derived from stored_path (which ends in the validated extension).
        Used to check request-specific required-document types.
        """
        attached = self.__dict__.get("_upload_extension")
        if attached is not None:
            return attached
        path = self.stored_path or ""
        _, _, ext = path.rpartition(".")
        return ext.lower() or None

    @extension.setter
    def extension(self, value: str | None) -> None:
        # Store in the instance __dict__ under a private key so SQLAlchemy's attribute events
        # never see an unmapped write on a persistent object.
        self.__dict__["_upload_extension"] = value

    @extension.inplace.expression
    @classmethod
    def _extension_expression(cls):
        """SQL-side equivalent, so filter/order_by on the class also work."""
        return func.lower(func.substring_index(cls.__table__.c.stored_path, ".", -1))
