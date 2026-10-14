"""Backend tests run against the real PostgreSQL database configured in backend/.env.

Prerequisites: `alembic upgrade head` and `python -m app.db.seed` have been run.
Every test that writes data uses a transaction that is rolled back, so tests leave no rows behind;
uploaded files go to a temporary folder.
"""
import struct
import zlib
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import engine, get_db
from app.main import app
from app.models import DocumentType, Student

PASSWORD = "Passw0rd!x"


def make_png() -> bytes:
    """A tiny valid 1x1 PNG."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    pixel = zlib.compress(b"\x00\xff\x00\x00")
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", pixel) + chunk(b"IEND", b"")


PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"
PNG_BYTES = make_png()


@pytest.fixture(scope="session")
def client() -> TestClient:
    """Plain client for endpoints that need no data isolation (health checks, CORS)."""
    return TestClient(app)


@pytest.fixture
def db_session():
    connection = engine.connect()
    outer = connection.begin()
    # expire_on_commit=False and autoflush=False mirror the production SessionLocal
    # (app/db/session.py). With SQLAlchemy's defaults, commits expire loaded objects, which hid a
    # real stale-collection bug in payment/initiate's response from the whole test suite.
    session = Session(
        bind=connection,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
        autoflush=False,
    )
    try:
        yield session
    finally:
        session.close()
        outer.rollback()
        connection.close()


@pytest.fixture
def upload_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))
    return tmp_path


@pytest.fixture
def api(db_session, upload_dir):
    """Client whose requests use the rolled-back test session and a temporary upload folder."""
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def make_student(db_session):
    counter = {"n": 0}

    def _make(usn: str | None = None, **overrides) -> Student:
        counter["n"] += 1
        student = Student(
            usn=usn or f"TEST{counter['n']:04d}",
            full_name=overrides.pop("full_name", "Test Student"),
            department="Computer Science and Engineering",
            semester=7,
            cgpa=Decimal("8.50"),
            **overrides,
        )
        db_session.add(student)
        db_session.flush()
        return student

    return _make


@pytest.fixture
def register(api):
    def _register(usn: str, email: str = "student@example.com", password: str = PASSWORD):
        return api.post("/api/auth/register", json={"usn": usn, "email": email, "password": password})

    return _register


@pytest.fixture
def student_auth(make_student, register):
    """A registered student: returns (student, auth headers)."""
    student = make_student()
    token = register(student.usn).json()["access_token"]
    return student, {"Authorization": f"Bearer {token}"}


@pytest.fixture
def doc_type(db_session) -> DocumentType:
    return db_session.scalars(select(DocumentType).where(DocumentType.is_active).order_by(DocumentType.id)).first()
