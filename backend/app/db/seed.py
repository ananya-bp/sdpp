"""Seed reference data. Safe to run repeatedly (idempotent).

Usage (from the backend/ folder):  python -m app.db.seed
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models import DocumentType

# Document types named in the SDP project brief. Fees are intentionally NOT seeded here.
DOCUMENT_TYPES = [
    ("TRANSCRIPT", "Transcript"),
    ("MIGRATION_CERTIFICATE", "Migration Certificate"),
    ("DUPLICATE_GRADE_CARD", "Duplicate Grade Card"),
    ("PROVISIONAL_DEGREE_CERTIFICATE", "Provisional Degree Certificate"),
]


def seed_document_types(db: Session) -> int:
    """Insert any missing document types. Returns how many were added."""
    existing = set(db.scalars(select(DocumentType.code)).all())
    added = 0
    for code, name in DOCUMENT_TYPES:
        if code not in existing:
            db.add(DocumentType(code=code, name=name))
            added += 1
    db.commit()
    return added


if __name__ == "__main__":
    with SessionLocal() as session:
        added = seed_document_types(session)
    print(f"Seed complete: {added} document type(s) added.")
