from decimal import Decimal

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from app.db.session import engine
from app.models import (
    Application,
    ApplicationStatusHistory,
    DocumentType,
    Student,
    Transaction,
    UploadedDocument,
    User,
)

EXPECTED_TABLES = {
    "users",
    "students",
    "document_types",
    "applications",
    "application_status_history",
    "transactions",
    "uploaded_documents",
}


def test_all_tables_exist():
    assert EXPECTED_TABLES <= set(inspect(engine).get_table_names())


def _make_student(db, usn="TEST-USN-0001", cgpa="8.50"):
    student = Student(
        usn=usn, full_name="Test Student", department="CSE", semester=7, cgpa=Decimal(cgpa)
    )
    db.add(student)
    db.flush()
    return student


def test_application_flow_rows_link_correctly(db_session):
    """student -> application -> status history + transaction, with server defaults applied."""
    user = User(email="test.student@example.com", password_hash="not-a-real-hash")
    db_session.add(user)
    db_session.flush()
    assert user.role == "student"

    student = _make_student(db_session)
    student.user_id = user.id
    doc_type = db_session.scalars(select(DocumentType).limit(1)).one()

    app_row = Application(student_id=student.id, document_type_id=doc_type.id)
    db_session.add(app_row)
    db_session.flush()
    db_session.refresh(app_row)
    assert app_row.status == "SUBMITTED"
    assert app_row.submitted_at is not None
    assert app_row.approved_at is None

    db_session.add(ApplicationStatusHistory(application_id=app_row.id, status="SUBMITTED"))
    db_session.add(Transaction(application_id=app_row.id, amount=Decimal("250.00")))
    db_session.flush()

    txn = db_session.scalars(select(Transaction).where(Transaction.application_id == app_row.id)).one()
    assert txn.payment_status == "PENDING"
    assert txn.transacted_at is not None


@pytest.mark.parametrize("cgpa", ["10.50", "-0.10"])
def test_cgpa_out_of_range_rejected(db_session, cgpa):
    with pytest.raises(IntegrityError):
        _make_student(db_session, cgpa=cgpa)


def test_duplicate_usn_rejected(db_session):
    _make_student(db_session, usn="TEST-USN-DUP")
    with pytest.raises(IntegrityError):
        _make_student(db_session, usn="TEST-USN-DUP")


def test_invalid_user_role_rejected(db_session):
    db_session.add(User(email="x@example.com", password_hash="h", role="superuser"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_negative_transaction_amount_rejected(db_session):
    student = _make_student(db_session, usn="TEST-USN-TXN")
    doc_type = db_session.scalars(select(DocumentType).limit(1)).one()
    app_row = Application(student_id=student.id, document_type_id=doc_type.id)
    db_session.add(app_row)
    db_session.flush()
    db_session.add(Transaction(application_id=app_row.id, amount=Decimal("-1.00")))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_uploaded_document_rules_and_cascade(db_session):
    student = _make_student(db_session, usn="TEST-USN-DOC")
    doc_type = db_session.scalars(select(DocumentType).limit(1)).one()
    app_row = Application(student_id=student.id, document_type_id=doc_type.id)
    db_session.add(app_row)
    db_session.flush()

    db_session.add(UploadedDocument(
        application_id=app_row.id, original_filename="a.pdf", stored_path="1/a.pdf",
        content_type="application/pdf", size_bytes=10,
    ))
    db_session.add(ApplicationStatusHistory(application_id=app_row.id, status="SUBMITTED"))
    db_session.flush()

    # deleting the application removes its files' rows and history (database-level cascade)
    db_session.execute(Application.__table__.delete().where(Application.id == app_row.id))
    remaining = db_session.scalars(select(UploadedDocument).where(UploadedDocument.application_id == app_row.id)).all()
    assert remaining == []


def test_uploaded_document_size_must_be_positive(db_session):
    student = _make_student(db_session, usn="TEST-USN-SZ")
    doc_type = db_session.scalars(select(DocumentType).limit(1)).one()
    app_row = Application(student_id=student.id, document_type_id=doc_type.id)
    db_session.add(app_row)
    db_session.flush()
    db_session.add(UploadedDocument(
        application_id=app_row.id, original_filename="a.pdf", stored_path="1/a.pdf",
        content_type="application/pdf", size_bytes=0,
    ))
    with pytest.raises(IntegrityError):
        db_session.flush()
