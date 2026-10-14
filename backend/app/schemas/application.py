from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, computed_field

from app.core.statuses import status_label
from app.services.payments import FEE_BY_DOCUMENT_TYPE
from app.schemas.document_type import DocumentTypeOut


class _Orm(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class OcrResultOut(_Orm):
    status: str
    raw_text: str | None = None
    extracted_fields: dict | None = None
    error_message: str | None = None
    processed_at: datetime


class DocumentOut(_Orm):
    id: int
    original_filename: str
    content_type: str
    size_bytes: int
    uploaded_at: datetime
    ocr_result: OcrResultOut | None = None


class StatusHistoryOut(_Orm):
    status: str
    changed_at: datetime
    note: str | None = None

    @computed_field
    @property
    def status_label(self) -> str:
        return status_label(self.status)


class ApplicationSummary(_Orm):
    id: int
    document_type: DocumentTypeOut
    status: str
    submitted_at: datetime

    @computed_field
    @property
    def status_label(self) -> str:
        return status_label(self.status)


class TransactionOut(_Orm):
    id: int
    amount: Decimal
    payment_status: str
    transacted_at: datetime


class PaymentCompleteIn(BaseModel):
    # Mock gateway result (see app/services/payments.py) - a real integration would replace this
    # with a webhook payload instead of taking the outcome directly from the caller.
    outcome: str  # "success" or "failure"


class ApplicationDetail(ApplicationSummary):
    documents: list[DocumentOut]
    history: list[StatusHistoryOut]
    transactions: list[TransactionOut]

    @computed_field
    @property
    def fee_amount(self) -> Decimal | None:
        """The fee for this document type (sandbox placeholder schedule in services/payments.py).

        Exposed so the UI shows the backend's number rather than keeping its own copy.
        """
        return FEE_BY_DOCUMENT_TYPE.get(self.document_type.code)
