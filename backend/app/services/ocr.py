"""OCR extraction for uploaded supporting documents (Phase 3).

Library choice (checked against what's actually installable/available in this sandbox before
committing): `pytesseract` (a thin wrapper around the Tesseract OCR engine, which is already
present as a system binary here) for the actual character recognition, plus `pdf2image` (a
wrapper around the `pdftoppm` binary, also already present via poppler-utils) to turn each PDF
page into an image first, since Tesseract itself only reads images. Both were verified installable
with plain `pip install` and both underlying system binaries (`tesseract`, `pdftoppm`) were already
on PATH in this environment, so no extra system packages were needed beyond what's used already.

This is a supporting document-processing step, not one of the three core ML components
(SDP_BUILD_GUIDE.md section 1.5) - kept deliberately simple: extract raw text, then a handful of
regex-based fields that are genuinely findable in an arbitrary scanned academic document (a USN,
a CGPA-shaped number, and any dates) without inventing document-specific templates.
"""
import re
from dataclasses import dataclass
from pathlib import Path

import pytesseract
from pdf2image import convert_from_path
from pdf2image.exceptions import PDFPageCountError, PDFSyntaxError
from PIL import Image, UnidentifiedImageError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.statuses import ApplicationStatus
from app.models import Application, OcrResult

# Matches USNs shaped like app.db.seed_students' simulated records (e.g. "SIM23CSE001"):
# 2-4 letters, 2 digits, 2-4 letters, 3 digits.
_USN_RE = re.compile(r"\b[A-Z]{2,4}[0-9]{2}[A-Z]{2,4}[0-9]{3}\b")
# A bare decimal in the 0.00-10.00 range, as a candidate CGPA-shaped figure.
_CGPA_RE = re.compile(r"\b(10\.00|10|[0-9]\.[0-9]{1,2})\b")
# Common date shapes: 12/05/2024, 12-05-2024, 2024-05-12.
_DATE_RE = re.compile(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})\b")


@dataclass
class OcrOutcome:
    status: str  # "SUCCESS" or "FAILED"
    raw_text: str | None = None
    extracted_fields: dict | None = None
    error_message: str | None = None


def _extract_fields(raw_text: str) -> dict:
    return {
        "word_count": len(raw_text.split()),
        "detected_usns": sorted(set(_USN_RE.findall(raw_text)))[:5],
        "detected_cgpa_like_numbers": sorted(set(_CGPA_RE.findall(raw_text)))[:5],
        "detected_dates": sorted(set(_DATE_RE.findall(raw_text)))[:5],
    }


def _ocr_image(path: Path) -> str:
    with Image.open(path) as img:
        return pytesseract.image_to_string(img)


def _ocr_pdf(path: Path) -> str:
    # 200 DPI is enough for Tesseract on a typical scanned/printed document and keeps this fast.
    pages = convert_from_path(str(path), dpi=200)
    return "\n".join(pytesseract.image_to_string(page) for page in pages)


def run_ocr_on_file(absolute_path: Path, content_type: str) -> OcrOutcome:
    """Run OCR on one stored file. Never raises: unreadable/corrupt input becomes a FAILED outcome."""
    try:
        if content_type == "application/pdf":
            raw_text = _ocr_pdf(absolute_path)
        else:
            raw_text = _ocr_image(absolute_path)
    except (
        PDFPageCountError, PDFSyntaxError, UnidentifiedImageError, OSError,
        pytesseract.TesseractError, Image.DecompressionBombError,
    ) as exc:
        return OcrOutcome(status="FAILED", error_message=f"{type(exc).__name__}: {exc}")

    raw_text = raw_text.strip()
    return OcrOutcome(status="SUCCESS", raw_text=raw_text, extracted_fields=_extract_fields(raw_text))


def run_ocr_for_application(db: Session, application: Application, changed_by: int | None = None) -> Application:
    """Run OCR on every file attached to an application and move it to OCR_COMPLETED.

    A per-file OCR failure (corrupt/unreadable upload) is recorded on that file's OcrResult row
    rather than raised: one bad supporting document shouldn't block the whole application, and a
    failed result is still visible to the student/admin. Re-running is safe: an existing result for
    a file is replaced rather than duplicated (uploaded_document_id is unique).
    """
    failed = 0
    for document in application.documents:
        existing = db.get(OcrResult, document.ocr_result.id) if document.ocr_result else None
        outcome = run_ocr_on_file(settings.upload_path / document.stored_path, document.content_type)
        failed += outcome.status == "FAILED"
        if existing is not None:
            existing.status = outcome.status
            existing.raw_text = outcome.raw_text
            existing.extracted_fields = outcome.extracted_fields
            existing.error_message = outcome.error_message
        else:
            db.add(
                OcrResult(
                    uploaded_document_id=document.id,
                    status=outcome.status,
                    raw_text=outcome.raw_text,
                    extracted_fields=outcome.extracted_fields,
                    error_message=outcome.error_message,
                )
            )

    from app.services.applications import set_status  # local import: avoids a circular import

    set_status(
        db, application, ApplicationStatus.OCR_COMPLETED, changed_by=changed_by,
        note=f"OCR run on {len(application.documents)} file(s)" + (f"; {failed} could not be read" if failed else ""),
    )
    db.commit()
    db.refresh(application)
    return application
