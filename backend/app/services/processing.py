"""Automatic post-submission processing: OCR, then rule-based eligibility.

The existing endpoints POST /{id}/ocr and POST /{id}/eligibility are synchronous (they do the work
inside the request) and each one is a manual step. The student portal should not make the student
click through them, so `process_application` chains the *existing* service functions in order:

    SUBMITTED --run_ocr_for_application--> OCR_COMPLETED --run_eligibility_for_application--> ELIGIBLE / NOT_ELIGIBLE

Properties this function guarantees:
* Every status change goes through the existing services, i.e. `set_status()`, so
  `application_status_history` stays complete. Nothing here decides eligibility itself.
* Idempotent / no duplicate work: a PostgreSQL advisory lock (per application id) serialises
  concurrent calls (two browser tabs, a page refresh mid-OCR, a double click). The application is
  re-read *after* the lock is acquired, so the second caller sees the finished state and does
  nothing instead of running OCR or eligibility a second time.
* Eligibility only runs when OCR actually succeeded for every file. A file that could not be read
  stops the chain at OCR_COMPLETED (the status vocabulary has no "OCR failed" state) so the student
  sees the error; `retry_failed_ocr=True` re-runs OCR, which replaces (never duplicates) results.
* Once an application has an eligibility result or has moved on to payment or later, calling this
  again is a no-op. Payments are never started here.
"""
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.statuses import ApplicationStatus
from app.models import Application, Student
from app.services import applications as applications_service
from app.services import eligibility as eligibility_service
from app.services import ocr as ocr_service

_LOCK_NAMESPACE = 5001  # arbitrary constant: keeps our advisory locks apart from any other use


def ocr_succeeded_for_all(application: Application) -> bool:
    """True when every attached file has a SUCCESS OCR result (vacuously true with no files)."""
    return all(d.ocr_result is not None and d.ocr_result.status == "SUCCESS" for d in application.documents)


@contextmanager
def _application_lock(db: Session, application_id: int) -> Iterator[None]:
    """Hold a session-level advisory lock on its own connection.

    A dedicated connection is used because the request's session releases/changes its connection
    on every commit, which would strand a session-level lock taken on it.
    """
    with db.get_bind().engine.connect() as conn:
        params = {"ns": _LOCK_NAMESPACE, "id": application_id}
        conn.execute(text("SELECT pg_advisory_lock(:ns, :id)"), params)
        try:
            yield
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(:ns, :id)"), params)
            conn.commit()


def process_application(
    db: Session, application_id: int, student: Student, retry_failed_ocr: bool = False
) -> Application | None:
    """Advance an application as far as automatic processing allows; return it (None if not found)."""
    with _application_lock(db, application_id):
        application = applications_service.load_application(db, application_id, student.id)
        if application is None:
            return None

        needs_ocr = application.status == ApplicationStatus.SUBMITTED.value or (
            application.status == ApplicationStatus.OCR_COMPLETED.value
            and retry_failed_ocr
            and not ocr_succeeded_for_all(application)
        )
        if needs_ocr:
            ocr_service.run_ocr_for_application(db, application, changed_by=student.user_id)
            application = applications_service.load_application(db, application_id, student.id)

        if application.status == ApplicationStatus.OCR_COMPLETED.value and ocr_succeeded_for_all(application):
            eligibility_service.run_eligibility_for_application(
                db, application, student, changed_by=student.user_id
            )
            application = applications_service.load_application(db, application_id, student.id)

        return application
