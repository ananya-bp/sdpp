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


def test_too_many_files_rejected(api, student_auth, doc_type, db_session):
    student, headers = student_auth
    files = [(f"f{i}.pdf", PDF_BYTES, "application/pdf") for i in range(uploads.MAX_FILES_PER_APPLICATION + 1)]
    assert submit(api, headers, doc_type.id, files).status_code == 400
    assert app_count(db_session, student) == 0
    five = files[:-1]
    assert submit(api, headers, doc_type.id, five).status_code == 201


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
    with pytest.raises(OSError):
        submit(api, headers, doc_type.id, [("a.pdf", PDF_BYTES, "application/pdf"), ("b.pdf", PDF_BYTES, "application/pdf")])
    assert app_count(db_session, student) == 0
    assert files_on_disk(upload_dir) == []


def test_file_count_limit_is_configurable_and_enforced(api, student_auth, doc_type, db_session, monkeypatch):
    """Reducing MAX_FILES_PER_APPLICATION via settings is enforced at the API level.

    This confirms the limit is controlled by settings (not a hard-coded constant),
    so it can be changed in one place and takes effect everywhere.
    """
    student, headers = student_auth
    monkeypatch.setattr(settings, "max_files_per_application", 2)

    # 2 files → accepted under the new limit.
    ok = submit(api, headers, doc_type.id, [
        ("a.pdf", PDF_BYTES, "application/pdf"),
        ("b.pdf", PDF_BYTES, "application/pdf"),
    ])
    assert ok.status_code == 201, ok.text

    # 3 files → rejected under the new limit.
    bad = submit(api, headers, doc_type.id, [
        ("c.pdf", PDF_BYTES, "application/pdf"),
        ("d.pdf", PDF_BYTES, "application/pdf"),
        ("e.pdf", PDF_BYTES, "application/pdf"),
    ])
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

