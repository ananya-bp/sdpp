from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import DocumentType
from app.schemas.document_type import DocumentTypeOut

router = APIRouter(prefix="/document-types", tags=["document-types"])


@router.get("", response_model=list[DocumentTypeOut])
def list_document_types(db: Session = Depends(get_db)):
    """Active document types a student can apply for."""
    stmt = select(DocumentType).where(DocumentType.is_active.is_(True)).order_by(DocumentType.id)
    return db.scalars(stmt).all()
