from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.statuses import ApplicationStatus
from app.models import (
    Application,
    ApplicationStatusHistory,
    DocumentType,
    Student,
    UploadedDocument,
)
from app.services import uploads


def set_status(
    db: Session,
    application: Application,
    status: ApplicationStatus,
    changed_by: int | None = None,
    note: str | None = None,
) -> None:
    """Change an application's status AND record it in the history (used by every phase)."""
    application.status = status.value
    db.add(
        ApplicationStatusHistory(
            application_id=application.id, status=status.value, changed_by=changed_by, note=note
        )
    )


def load_application(db: Session, application_id: int, student_id: int) -> Application | None:
    """One application with its relations, only if it belongs to the given student.

    populate_existing=True forces the relations to be re-read from the database even when the
    session already holds this Application. Routes call this twice (load -> change -> reload
    for the response); the session uses expire_on_commit=False, so without it the reload can
    return the stale, pre-change collections (e.g. payment/initiate answering with an empty
    `transactions` list although a PENDING row had just been committed).
    """
    stmt = (
        select(Application)
        .where(Application.id == application_id, Application.student_id == student_id)
        .options(
            selectinload(Application.document_type),
            selectinload(Application.documents).selectinload(UploadedDocument.ocr_result),
            selectinload(Application.history),
            selectinload(Application.transactions),
        )
        .execution_options(populate_existing=True)
    )
    return db.scalars(stmt).one_or_none()


def list_applications(db: Session, student_id: int) -> list[Application]:
    stmt = (
        select(Application)
        .where(Application.student_id == student_id)
        .options(selectinload(Application.document_type))
        .order_by(Application.submitted_at.desc(), Application.id.desc())
    )
    return list(db.scalars(stmt).all())


def create_application(
    db: Session,
    student: Student,
    document_type: DocumentType,
    items: list[uploads.ValidatedUpload],
) -> Application:
    """Create the application, its first history row and its files in one unit.

    If anything fails, the database work is rolled back and any files already written are removed.
    """
    application = Application(student_id=student.id, document_type_id=document_type.id)
    db.add(application)
    db.flush()  # assigns application.id
    set_status(
        db, application, ApplicationStatus.SUBMITTED, changed_by=student.user_id,
        note="Application submitted",
    )

    written: list[str] = []
    try:
        for item in items:
            relative = uploads.store_file(application.id, item)
            written.append(relative)
            db.add(
                UploadedDocument(
                    application_id=application.id,
                    original_filename=item.original_filename,
                    stored_path=relative,
                    content_type=item.content_type,
                    size_bytes=len(item.data),
                    # non-persisted hybrid attribute: validated extension of the file content
                    extension=item.extension,
                )
            )
        db.commit()
    except Exception:
        db.rollback()
        uploads.remove_stored_files(written)
        raise
    return application
