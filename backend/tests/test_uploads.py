import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.models import Application
from app.services import uploads
from tests.conftest import PDF_BYTES, PNG_BYTES
from tests.test_applications import submit


def app_count(db_session, student):
    return db_session.scalar(select(func.count()).select_from(Application).where(Application.student_id == student.id))


def files_on_disk(upload_dir):
    return [p for p in upload_dir.rglob("*") if p.is_file()]


@pytest.mark.parametrize(
    "name,data,ctype",
    [
        ("notes.txt", b"hello", "text/plain"),                       # extension not allowed
        ("script.exe", b"MZ\x90\x00", "application/octet-stream"),   # extension not allowed
        ("fake.pdf", b"this is not a pdf", "application/pdf"),       # right extension, wrong content
        ("really_png.pdf", PNG_BYTES, "application/pdf"),            # PNG bytes named .pdf
        ("really_pdf.png", PDF_BYTES, "image/png"),                  # PDF bytes named .png
        ("empty.pdf", b"", "application/pdf"),
    ],
)
def test_bad_files_rejected_and_nothing_saved(api, student_auth, doc_type, db_session, upload_dir, name, data, ctype):
    student, headers = student_auth
    r = submit(api, headers, doc_type.id, [(name, data, ctype)])
    assert r.status_code == 400
    assert app_count(db_session, student) == 0
    assert files_on_disk(upload_dir) == []


def test_oversized_file_rejected(api, student_auth, doc_type, db_session, upload_dir, monkeypatch):
    student, headers = student_auth
    monkeypatch.setattr(settings, "max_upload_mb", 1)
    limit = 1024 * 1024
    ok = submit(api, headers, doc_type.id, [("ok.pdf", b"%PDF-" + b"a" * (limit - 5), "application/pdf")])
    assert ok.status_code == 201  # exactly at the limit is allowed
    too_big = submit(api, headers, doc_type.id, [("big.pdf", b"%PDF-" + b"a" * (limit - 4), "application/pdf")])
    assert too_big.status_code == 413
    assert app_count(db_session, student) == 1


def _distinct_pdfs(n):
    """n valid PDFs with distinct content (so duplicate detection does not interfere)."""
    return [(f"f{i}.pdf", b"%PDF-1.4\ndocument number " + bytes([i]) + b"\n%%EOF\n", "application/pdf")
            for i in range(n)]


def test_too_many_files_rejected(api, student_auth, doc_type, db_session):
    student, headers = student_auth
    limit = uploads.MAX_FILES_PER_APPLICATION  # dynamic: always the current centralized setting
    files = _distinct_pdfs(limit + 1)
    assert submit(api, headers, doc_type.id, files).status_code == 400
    assert app_count(db_session, student) == 0
    assert submit(api, headers, doc_type.id, files[:limit]).status_code == 201


def test_one_bad_file_means_nothing_saved(api, student_auth, doc_type, db_session, upload_dir):
    student, headers = student_auth
    r = submit(api, headers, doc_type.id, [("good.pdf", PDF_BYTES, "application/pdf"), ("bad.txt", b"x", "text/plain")])
    assert r.status_code == 400
    assert app_count(db_session, student) == 0
    assert files_on_disk(upload_dir) == []


def test_path_traversal_filename_is_neutralised(api, student_auth, doc_type, upload_dir):
    _, headers = student_auth
    r = submit(api, headers, doc_type.id, [("../../evil.pdf", PDF_BYTES, "application/pdf")])
    assert r.status_code == 201
    assert r.json()["documents"][0]["original_filename"] == "evil.pdf"
    stored = files_on_disk(upload_dir)
    assert len(stored) == 1
    assert upload_dir.resolve() in stored[0].resolve().parents
    assert stored[0].name != "evil.pdf"


def test_failure_while_saving_rolls_back_and_removes_files(api, student_auth, doc_type, db_session, upload_dir, monkeypatch):
    student, headers = student_auth
    real_store = uploads.store_file
    calls = {"n": 0}

    def flaky(application_id, item):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("disk full")
        return real_store(application_id, item)

    monkeypatch.setattr(uploads, "store_file", flaky)
    # Two files with DIFFERENT content (same-name files would be de-duplicated before storage,
    # so they would never reach store_file twice).
    with pytest.raises(OSError):
        submit(api, headers, doc_type.id, [
            ("a.pdf", b"%PDF-1.4\nfirst document body\n%%EOF\n", "application/pdf"),
            ("b.pdf", b"%PDF-1.4\nsecond document body\n%%EOF\n", "application/pdf"),
        ])
    assert app_count(db_session, student) == 0
    assert files_on_disk(upload_dir) == []


def test_file_count_limit_is_configurable_and_enforced(api, student_auth, doc_type, db_session, monkeypatch):
    """Reducing MAX_FILES_PER_APPLICATION via settings is enforced at the API level.

    This confirms the limit is controlled by settings (not a hard-coded constant),
    so it can be changed in one place and takes effect everywhere.
    """
    student, headers = student_auth
    monkeypatch.setattr(settings, "max_files_per_application", 2)

    # 2 distinct files → accepted under the new limit.
    ok = submit(api, headers, doc_type.id, _distinct_pdfs(2))
    assert ok.status_code == 201, ok.text

    # 3 distinct files → rejected under the new limit.
    bad = submit(api, headers, doc_type.id, _distinct_pdfs(3))
    assert bad.status_code == 400
    assert app_count(db_session, student) == 1  # only the first one was saved


def test_sixth_file_rejected_at_default_limit(api, student_auth, doc_type, db_session):
    """The sixth file in one application is rejected when the default limit is 5."""
    student, headers = student_auth
    # Five identical-named but differently-numbered valid PDFs (unique content).
    six_files = [(f"f{i}.pdf", b"%PDF-" + bytes([i]) + b"content", "application/pdf") for i in range(6)]
    r = submit(api, headers, doc_type.id, six_files)
    assert r.status_code == 400
    assert app_count(db_session, student) == 0


def test_duplicate_file_rejected(api, student_auth, doc_type, db_session):
    """Uploading the exact same file twice (same bytes) in one request is rejected."""
    _, headers = student_auth
    r = submit(api, headers, doc_type.id, [
        ("original.pdf", PDF_BYTES, "application/pdf"),
        ("copy.pdf",     PDF_BYTES, "application/pdf"),   # identical content
    ])
    assert r.status_code == 400
    assert "duplicate" in r.json()["detail"].lower()



def test_same_file_sent_twice_under_same_name_is_stored_once(api, student_auth, doc_type, db_session):
    """Accidental repeats of the identical file under its real name must not fail the request."""
    _, headers = student_auth
    r = submit(api, headers, doc_type.id, [
        ("same.pdf", PDF_BYTES, "application/pdf"),
        ("same.pdf", PDF_BYTES, "application/pdf"),
    ])
    assert r.status_code == 201, r.text
    assert len(r.json()["documents"]) == 1


# ---------------------------------------------------------------------------
# UploadedDocument.extension hybrid-property lifecycle (regression coverage)
# ---------------------------------------------------------------------------


def _make_doc(stored_path="uploads/abc.pdf", **kw):
    from app.models.uploaded_document import UploadedDocument

    defaults = dict(
        application_id=1,
        original_filename="abc.pdf",
        stored_path=stored_path,
        content_type="application/pdf",
        size_bytes=1024,
    )
    defaults.update(kw)
    return UploadedDocument(**defaults)


def test_extension_assignable_before_stored_path_exists():
    """Upload routes assign `extension` before INSERT/stored_path is populated."""
    doc = _make_doc(stored_path="")
    doc.extension = "PDF"  # must not raise AttributeError
    assert doc.extension == "PDF"


def test_extension_reads_explicit_override():
    doc = _make_doc()
    doc.extension = "jpeg"
    assert doc.extension == "jpeg"


def test_extension_derived_from_stored_path_without_override():
    doc = _make_doc(stored_path="uploads/photo.JPG")
    assert doc.extension == "jpg"


def test_extension_persists_and_reloads_from_new_session(db_session):
    """A row written and re-loaded in a fresh session derives extension from stored_path."""
    from sqlalchemy.orm import Session

    from app.models.application import Application, ApplicationStatusHistory  # noqa: F401
    from app.models.document_type import DocumentType
    from app.models.student import Student
    from app.models.uploaded_document import UploadedDocument

    student = db_session.query(Student).first()
    assert student is not None, "test DB must contain a seeded student"

    doc_type = db_session.query(DocumentType).first()
    assert doc_type is not None, "test DB must contain a seeded document type"

    application = Application(student_id=student.id, document_type_id=doc_type.id)
    db_session.add(application)
    db_session.flush()

    doc = UploadedDocument(
        application_id=application.id,
        original_filename="scan.pdf",
        stored_path="uploads/scan-1234.pdf",
        content_type="application/pdf",
        size_bytes=2048,
    )
    doc.extension = "pdf"  # in-flight assignment must not break INSERT
    db_session.add(doc)
    db_session.commit()
    doc_id = doc.id

    # Load the row in a brand-new session bound to the same connection/transaction,
    # emulating a separate request. The override lives only on the old instance, so
    # the reloaded row must derive its extension from stored_path.
    other = Session(bind=db_session.get_bind())
    try:
        reloaded = other.get(UploadedDocument, doc_id)
        assert reloaded is not None
        assert "_extension_override" not in reloaded.__dict__
        assert reloaded.extension == "pdf"
    finally:
        other.close()
        # Clean up (rows live inside the rolled-back test transaction anyway; this keeps
        # repeated runs within the same transaction idempotent).
        db_session.delete(db_session.get(UploadedDocument, doc_id))
        db_session.delete(db_session.get(Application, application.id))
        db_session.commit()


def test_extension_handles_missing_path_or_extension_safely():
    doc = _make_doc(stored_path="uploads/noextension")
    assert doc.extension is None
    doc2 = _make_doc(stored_path="")
    assert doc2.extension is None
