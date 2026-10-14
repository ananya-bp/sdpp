from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.ocr_result import OcrResult  # noqa: F401  (relationship target)

if TYPE_CHECKING:  # circular-import guard: Application already imports this module
    from app.models.application import Application


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

    application: Mapped["Application"] = relationship(back_populates="documents")

    # --- Checklist / verification tracking -------------------------------------------
    # Checklist category is PERSISTED (see the `document_category` DB column added by revision
    # 20261014_562d5a8aebea). Persistence is what lets a reviewer's decision survive across
    # requests: without it, hint-based reassignment in a later request would silently move an
    # already-verified document to a different checklist slot and break payment gating.
    document_category: Mapped[str | None] = mapped_column(String(50), nullable=True)
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
    def extension(self) -> str | None:  # type: ignore[no-redef]
        """Normalised extension (pdf/jpg/jpeg/png) — not a DB column, no migration needed.

        Precedence: an explicitly assigned value (`_extension_override`, written by the
        setter during in-flight upload handling before `stored_path` exists) wins; otherwise
        the extension is derived from `stored_path` (which ends in the validated extension),
        so rows loaded from the database in any new session behave identically.
        Used to check request-specific required-document types.
        """
        override = self.__dict__.get("_extension_override")
        if override is not None:
            return override
        path = self.stored_path or ""
        _, slash, ext = path.rpartition(".")
        # A dot must actually follow a directory/file name; "uploads/noextension" has no
        # extension and must not be misread as one.
        if not slash or not ext:
            return None
        return ext.lower()

    @extension.setter
    def extension(self, value: str | None) -> None:
        # Store in the instance __dict__ under a private key so SQLAlchemy's attribute
        # events never see an unmapped write on a persistent object. This is what makes
        # `doc.extension = "pdf"` safe before `stored_path` has been populated.
        self.__dict__["_extension_override"] = value

    @extension.inplace.expression
    @classmethod
    def _extension_expression(cls):
        """SQL-side equivalent, so filter/order_by on the class also work."""
        return func.lower(func.substring_index(cls.__table__.c.stored_path, ".", -1))
