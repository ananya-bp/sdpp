# Import every model so Base.metadata knows about all tables (needed by Alembic).
from app.models.application import Application, ApplicationStatusHistory
from app.models.document_type import DocumentType
from app.models.ocr_result import OcrResult
from app.models.student import Student
from app.models.transaction import Transaction
from app.models.uploaded_document import UploadedDocument
from app.models.user import User

__all__ = [
    "Application",
    "ApplicationStatusHistory",
    "DocumentType",
    "OcrResult",
    "Student",
    "Transaction",
    "UploadedDocument",
    "User",
]
