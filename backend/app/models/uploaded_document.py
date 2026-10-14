from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.ocr_result import OcrResult  # noqa: F401  (relationship target)


class UploadedDocument(Base):
    """A supporting file a student uploaded with an application (PDF, JPG or PNG).

    The file itself lives on disk under UPLOAD_DIR; stored_path is relative to that folder.

    Document-based eligibility (checklist feature): each upload is tracked against the
    checklist category of its application's request type and carries its own validation
    status/reason plus reviewer audit fields. Statuses reuse the existing ApplicationStatus
    vocabulary (SUBMITTED=Uploaded, OCR_COMPLETED=Under Review, VERIFIED, REJECTED) so no new
    enum values were introduced. `replaces_document_id` gives replacement history without a
    separate table.
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

    # --- Checklist / verification tracking -------------------------------------------
    # document_category is a NON-persisted attribute (hybrid, like `extension` below): the
    # checklist feature assigns categories at evaluation time from filename/OCR hints and
    # reviewer decisions, so no database column/migration was needed for it.
    validation_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    validation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    replaces_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("uploaded_documents.id", ondelete="SET NULL"), nullable=True
    )

    # Phase 3: OCR output for this file, if OCR has been run.
    ocr_result: Mapped["OcrResult | None"] = relationship(
        cascade="all, delete-orphan", passive_deletes=True, uselist=False
    )

    @hybrid_property
    def document_category(self) -> str | None:  # type: ignore[no-redef]
        """Checklist category for this upload — NON-persisted (no DB column, no migration).

        Held on the instance only: hint-based assignment runs at checklist-evaluation time and
        reviewer decisions re-assign it within the same request; nothing is cached across
        requests. This keeps the feature fully additive to the existing schema.
        """
        return self.__dict__.get("_document_category")

    @document_category.setter
    def document_category(self, value: str | None) -> None:
        self.__dict__["_document_category"] = value

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
