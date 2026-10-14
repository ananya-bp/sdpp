"""Document-based eligibility checklist — one checklist per application type.

Every certificate request (Transcript, Migration Certificate, Duplicate Grade Card, PDC) has
its own list of required documents. A student must upload EVERY mandatory document, and each
upload must pass validation (format/size via the existing upload pipeline, readability via
OCR, content checks below) before payment can proceed. A file is never considered valid just
because it exists.

STATUS VOCABULARY (persisted in `uploaded_documents.validation_status`; deliberately reuses
the existing ApplicationStatus values so no new enum/schema vocabulary is introduced):

    SUBMITTED        -> "Uploaded"      (stored, awaiting automated verification)
    OCR_COMPLETED    -> "Under Review"  (readable; needs a reviewer decision / uncertain match)
    VERIFIED         -> "Verified"      (passed all applicable checks or approved by a reviewer)
    REJECTED         -> "Rejected"      (failed validation; reason stored, replaceable)

Legacy rows created before this feature are treated as Uploaded ("SUBMITTED") and require the
normal process/eligibility run to advance them — see _effective_status().

POLICY NOTE: KLE Tech's official per-document requirements could not be verified for this
project from an official source. Every checklist item is therefore marked verified=False
(UNVERIFIED) unless confirmed elsewhere. Conditional items ("if required by the university")
are controlled by settings flags (transcript_requires_gov_id, transcript_requires_no_dues,
pdc_requires_no_dues) which default to OFF — conditional documents are NEVER silently treated
as universally mandatory. The payment gate enforces only items that are mandatory under the
current configuration; when a policy item is later confirmed (verified=True) the same code
path becomes strict without touching the gate logic.
"""
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.statuses import ApplicationStatus
from app.models import Application, Student, UploadedDocument

# ---------------------------------------------------------------------------
# Checklist item definitions
# ---------------------------------------------------------------------------

MULTI_CATEGORY = {
    "SEMESTER_GRADE_CARDS",   # Transcript: multiple semester marks cards under one item
    "ACADEMIC_RECORDS",       # Migration: multiple available academic records
}


@dataclass(frozen=True)
class ChecklistItem:
    category: str
    label: str
    description: str
    required: bool = True                 # mandatory under current configuration
    conditional: bool = False             # toggled by a configurable university policy
    multi: bool = False                   # several uploads may satisfy this one item
    verified: bool = False                # UNVERIFIED institutional policy placeholder
    requires_review: bool = False         # auto-verification is impossible -> reviewer decides

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "label": self.label,
            "description": self.description,
            "required": self.required,
            "conditional": self.conditional,
            "multi": self.multi,
            "verified": self.verified,
            "requires_review": self.requires_review,
        }


def _item(category, label, description, **kw):
    return ChecklistItem(category=category, label=label, description=description, **kw)


# Per-application-type checklists (institutional requirements UNVERIFIED — see module docstring).
_CHECKLISTS: dict[str, list[ChecklistItem]] = {
    "TRANSCRIPT": [
        _item("STUDENT_DETAILS", "Student Registration Number (SRN/USN) & student details",
              "Your USN and personal details must be consistent with the college records and any ID proof."),
        _item("SEMESTER_GRADE_CARDS", "All available semester grade cards / marks cards",
              "Upload every semester's grade card you have; the checklist shows which are on file.",
              multi=True),
        _item("GOV_ID_PROOF", "Government ID proof (e.g. Aadhaar)",
              "Required only if mandated by university policy — currently configured as NOT required.",
              required=bool(getattr(settings, "transcript_requires_gov_id", False)), conditional=True),
        _item("NO_DUES_CERTIFICATE", "No Dues / clearance certificate",
              "Required only if mandated by university policy — currently configured as NOT required.",
              required=bool(getattr(settings, "transcript_requires_no_dues", False)), conditional=True),
    ],
    "MIGRATION_CERTIFICATE": [
        _item("STUDENT_DETAILS", "Student Registration Number (SRN/USN) & student details",
              "Your USN and personal details must match college records."),
        _item("MIGRATION_APPLICATION", "Written request / completed migration application form",
              "A signed application or written request addressed to the university.",
              requires_review=True),
        _item("ACADEMIC_RECORDS", "Available academic records (semester grade cards)",
              "Upload all grade cards/marks sheets currently available.", multi=True),
        _item("NO_DUES_CERTIFICATE", "No Dues / clearance certificate",
              "Library, lab, hostel and fee clearance as prescribed by the university."),
    ],
    "DUPLICATE_GRADE_CARD": [
        _item("POLICE_FIR", "Original police FIR copy",
              "FIR (or acknowledgement) for the lost grade card.", requires_review=True),
        _item("AFFIDAVIT", "Affidavit on ₹50 stamp paper",
              "Must state your name, SRN/USN, semester, examination month & year, and the request "
              "for a duplicate grade card.", requires_review=True),
        _item("DGC_APPLICATION", "Completed duplicate grade card application form",
              "The filled and signed application form.", requires_review=True),
        _item("GRADE_CARD_PARTICULARS", "Grade card particulars",
              "Semester/term, examination month and year, SGPA/CGPA where applicable — provided in "
              "the application details form.", requires_review=False),
        _item("DELIVERY_DETAILS", "Name, mobile number, postal address & PIN code",
              "For delivery of the reissued grade card — provided in the application details form."),
        # The online fee-payment receipt is GENERATED AFTER payment, so it is intentionally NOT a
        # pre-payment requirement here. Proof of a prior payment would be a separate conditional
        # item once such a workflow is confirmed (none is, so none is invented).
    ],
    "PROVISIONAL_DEGREE_CERTIFICATE": [
        _item("STUDENT_DETAILS", "Student Registration Number (SRN/USN) & student details",
              "Your USN and personal details must match college records."),
        _item("SEMESTER_GRADE_CARDS", "All semester grade cards / consolidated marks card",
              "Complete academic record up to the final semester.", multi=True),
        _item("DEGREE_COMPLETION_PROOF", "Proof of degree-completion",
              "Final result printout or equivalent. An uploaded document alone does NOT establish "
              "completion — the backend verifies authoritative academic records first.",
              requires_review=True),
        _item("PDC_APPLICATION", "Completed PDC application / written request",
              "Signed application or written request.", requires_review=True),
        _item("NO_DUES_CERTIFICATE", "No Dues / clearance certificate",
              "Required only if mandated by university policy — currently configured as NOT required.",
              required=bool(getattr(settings, "pdc_requires_no_dues", False)), conditional=True),
    ],
}

# Categories satisfied from the structured application-details form rather than a file upload.
# STUDENT_DETAILS is form/profile-backed for every request type: the student's USN and personal
# details come from the authenticated record (authoritative), not from an uploaded file — an
# uploaded file can never satisfy this item, so it must not be allowed to squat on its slot.
_FORM_ONLY_CATEGORIES = {"STUDENT_DETAILS", "GRADE_CARD_PARTICULARS", "DELIVERY_DETAILS"}

# Which detail keys substantiate the profile-backed STUDENT_DETAILS item for every request type.
_PROFILE_REQUIREMENTS = ["usn", "full_name", "department"]

# Which detail keys substantiate each form-only category, per request type.
_FORM_REQUIREMENTS: dict[str, dict[str, list[str]]] = {
    "DUPLICATE_GRADE_CARD": {
        "GRADE_CARD_PARTICULARS": ["semester"],          # exam month/year live inside the affidavit
        "DELIVERY_DETAILS": ["full_name", "mobile", "address", "pincode"],
    },
}

# Keyword hints used ONLY to propose a category for a newly uploaded file (a hint, never a verdict).
# NOTE: form/profile-backed categories (see _FORM_ONLY_CATEGORIES) are deliberately absent here —
# no uploaded file may ever be hinted into the STUDENT_DETAILS / particulars / delivery slots.
_CATEGORY_HINTS: dict[str, tuple[str, ...]] = {
    "POLICE_FIR": ("fir", "police"),
    "AFFIDAVIT": ("affidavit", "stamp"),
    "NO_DUES_CERTIFICATE": ("no due", "no-dues", "nodues", "clearance", "dues"),
    "MIGRATION_APPLICATION": ("migration", "request letter"),
    "PDC_APPLICATION": ("pdc", "provisional"),
    "DGC_APPLICATION": ("duplicate", "grade card application", "application form"),
    "GOV_ID_PROOF": ("aadhaar", "adhaar", "govt id", "government id", "id proof"),
    "DEGREE_COMPLETION_PROOF": ("degree", "final result", "convocation", "completion"),
    "SEMESTER_GRADE_CARDS": ("grade card", "marks card", "mark card", "semester", "sgpa"),
    "ACADEMIC_RECORDS": ("grade card", "marks", "transcript", "semester"),
}


def get_checklist(document_type_code: str) -> list[ChecklistItem]:
    """Current checklist for a request type, reflecting live policy configuration."""
    base = _CHECKLISTS.get(document_type_code, [])
    out = []
    for item in base:
        required = item.required
        if item.category == "GOV_ID_PROOF":
            required = bool(getattr(settings, "transcript_requires_gov_id", False))
        elif item.category == "NO_DUES_CERTIFICATE" and document_type_code == "TRANSCRIPT":
            required = bool(getattr(settings, "transcript_requires_no_dues", False))
        elif item.category == "NO_DUES_CERTIFICATE" and document_type_code == "PROVISIONAL_DEGREE_CERTIFICATE":
            required = bool(getattr(settings, "pdc_requires_no_dues", False))
        out.append(ChecklistItem(**{**item.__dict__, "required": required}))
    return out


def checklist_payload(document_type_code: str) -> dict:
    items = get_checklist(document_type_code)
    return {
        "document_type_code": document_type_code,
        "policy_note": (
            "Checklist items follow the portal's working configuration and are labelled "
            "UNVERIFIED until confirmed against official KLE Tech policy. Conditional items "
            "(marked 'conditional') are enforced only when the corresponding policy flag is on."
        ),
        "items": [i.to_dict() for i in items],
    }


# ---------------------------------------------------------------------------
# Category assignment
# ---------------------------------------------------------------------------

def guess_category(filename: str, text: str | None) -> str | None:
    """Propose a checklist category from filename/text hints. Hints only — a reviewer or the
    automated content checks still decide; wrong guesses route to review, never auto-reject."""
    hay = f"{filename} {text or ''}".lower()
    for cat, hints in _CATEGORY_HINTS.items():
        if any(h in hay for h in hints):
            return cat
    return None


def assign_categories(db=None, application: Application | None = None,
                      student: Student | None = None) -> None:
    """Positional call ``assign_categories(application)`` (legacy) and keyword call
    ``assign_categories(db=..., application=...)`` are both supported."""
    if application is None and isinstance(db, Application):  # legacy positional usage
        db, application = None, db
    return _assign_categories(application)


def _assign_categories(application: Application) -> None:
    """Give every uploaded row a checklist category for this application (per-request assignment).

    Deterministic priority, using ONLY data that actually exists:
      1. an explicit reviewer category persisted in the document's validation_reason marker,
      2. a filename hint (guess_category over the original filename),
      3. an OCR-text hint when an OCR result exists,
      4. otherwise UNASSIGNED — which routes the document to manual review instead of silently
         classifying it.
    Category assignment NEVER verifies a document; verification is a separate step
    (verify_document / an explicit reviewer action). A reviewer decision always wins over hints,
    so a corrected classification survives later OCR text changes.
    """
    code = application.document_type.code
    valid = {item.category for item in get_checklist(code)}
    reviewer_assigned: set[str] = set()
    # Pass 1: reviewer decisions always win over hints. The persisted marker is authoritative;
    # additionally, a row the pipeline already marked VERIFIED keeps its current category —
    # re-guessing from filename/OCR text could silently move a verified document to a different
    # checklist slot on every evaluation. A multi-slot item (e.g. semester grade cards) may be
    # satisfied by several documents, so it does not block other docs from the same category.
    # Pass 1: reviewer decisions and persisted categories always win over hints.
    # document_category is a PERSISTED column (revision 20261014_562d5a8aebea), so the value
    # loaded from the database is authoritative across requests/sessions — no private-attribute
    # lookups. A reviewer marker overrides a stale stored category; otherwise any existing
    # stored category is KEPT (re-guessing could silently move a verified or already-classified
    # document to another checklist slot on every evaluation). Only rows with no category at all
    # fall through to the deterministic hint chain below.
    for doc in application.documents:
        stored = getattr(doc, "document_category", None) or "UNASSIGNED"
        reviewer_cat = read_review_category(doc)
        if reviewer_cat:
            doc.document_category = reviewer_cat if reviewer_cat in valid else "UNASSIGNED"
            if reviewer_cat in valid:
                reviewer_assigned.add(reviewer_cat)
            continue
        if stored != "UNASSIGNED" and stored in valid:
            doc.document_category = stored
            reviewer_assigned.add(stored)
            continue
        if stored != "UNASSIGNED" and stored not in valid:
            doc.document_category = "UNASSIGNED"  # stale category for this type -> needs review
            continue
        # Pass 2 (per unclassified doc): deterministic hint chain — filename first, OCR text
        # second. A hint that collides with an already-claimed single-slot item is dropped
        # rather than stealing its slot; multi-slot items (grade cards) tolerate several
        # documents. `assigned` is the running set of claimed slots so two hinted docs cannot
        # both take one single-slot item.
        assigned = set(reviewer_assigned)
        for d in application.documents:
            c = getattr(d, "document_category", None)
            if c and c != "UNASSIGNED" and d is not doc:
                assigned.add(c)
        cat = guess_category(doc.original_filename or "", "")
        if cat in assigned:
            item = _find_item(code, cat)
            if item is not None and not getattr(item, "multi", False):
                cat = None
        if cat is None and doc.ocr_result is not None:
            cat = guess_category("", doc.ocr_result.raw_text)
            if cat in assigned:
                item = _find_item(code, cat)
                if item is not None and not getattr(item, "multi", False):
                    cat = None
        doc.document_category = cat if (cat and cat in valid) else "UNASSIGNED"


# Reviewer decisions are persisted as status + reason on the document row itself; the category
# override travels through `validation_reason` metadata written by the review endpoint:
#   "review-category:<CATEGORY>" appended to the reason string. This avoids any schema change.
_REVIEW_CAT_PREFIX = "review-category:"


def record_review_category(db: Session, doc: UploadedDocument, category: str | None) -> None:
    """Persist a reviewer's category correction inside the existing validation_reason column."""
    reason = (doc.validation_reason or "").split(f" {_REVIEW_CAT_PREFIX}")[0].strip()
    if category:
        reason = f"{reason} {_REVIEW_CAT_PREFIX}{category}".strip()
    doc.validation_reason = reason or None


def apply_category(db: Session, doc: UploadedDocument, category: str | None) -> None:
    """Persist an explicitly confirmed checklist category on a document row."""
    doc.document_category = category or "UNASSIGNED"
    db.commit()


def read_review_category(doc: UploadedDocument) -> str | None:
    reason = getattr(doc, "validation_reason", None) or ""
    idx = reason.find(_REVIEW_CAT_PREFIX)
    if idx == -1:
        return None
    tail = reason[idx + len(_REVIEW_CAT_PREFIX):]
    return tail.split()[0] if tail.split() else None


def strip_review_marker(reason: str | None) -> str | None:
    if not reason:
        return reason
    idx = reason.find(_REVIEW_CAT_PREFIX)
    return (reason[:idx].strip() if idx != -1 else reason) or None


# ---------------------------------------------------------------------------
# Automated per-document verification
# ---------------------------------------------------------------------------

def _reason(doc: UploadedDocument, note: str) -> str:
    return f"{note} ({doc.original_filename})"


def verify_document(application: Application, doc: UploadedDocument, student: Student) -> tuple[str, str]:
    """Automated verification for one document. Returns (status, reason_or_empty).

    Rules (never claims authenticity from OCR text alone):
      - No OCR yet                     -> SUBMITTED (Uploaded; unreadable files were already
                                          rejected at upload time by the size/signature checks)
      - OCR FAILED / produced nothing  -> REJECTED (unreadable/corrupted file; replace it)
      - Low OCR confidence             -> OCR_COMPLETED (Under Review — evidence uncertain)
      - USN stated in a document conflicts with the student's official USN
                                       -> OCR_COMPLETED (Under Review — mismatch needs review,
                                          NOT an automatic rejection)
      - Degree-completion proof        -> checked against authoritative records by the caller
      - Everything else readable       -> OCR_COMPLETED (Under Review) when the item needs a
                                          reviewer decision, else VERIFIED.
    """
    ocr = doc.ocr_result
    if ocr is None:
        return ApplicationStatus.SUBMITTED.value, ""
    if ocr.status != "SUCCESS":
        return ApplicationStatus.REJECTED.value, _reason(
            doc, "The file could not be read (corrupted, empty or password-protected). Please replace it."
        )
    text = (ocr.raw_text or "").strip()
    if len(text.split()) < 3:
        return ApplicationStatus.REJECTED.value, _reason(
            doc, "The file appears unreadable or blank after processing. Please upload a clearer scan."
        )
    issues: list[str] = []
    fields = ocr.extracted_fields or {}
    conf = fields.get("confidence")
    if isinstance(conf, (int, float)) and conf < 60:
        issues.append("Low OCR confidence — the text could not be read reliably.")
    usn_found = fields.get("usn") or _find_usn_in_text(text)
    if usn_found and usn_found.upper() != student.usn.upper():
        issues.append(
            f"The registration number found in this document ({usn_found}) does not match your "
            f"official USN ({student.usn}). A manual check is required."
        )
    if issues:
        return ApplicationStatus.OCR_COMPLETED.value, " ".join(issues) + " This is a verification concern, not an academic rejection."

    category = getattr(doc, "document_category", None)
    item = _find_item(application.document_type.code, category)
    if item is None or item.requires_review or category in (None, "UNASSIGNED"):
        return ApplicationStatus.OCR_COMPLETED.value, (
            "The document was read successfully and is awaiting verification by an authorized reviewer."
        )
    return ApplicationStatus.VERIFIED.value, "Automated checks passed: readable, correct format, consistent with your records."


def _find_item(code: str, category: str | None):
    if not category:
        return None
    for item in get_checklist(code):
        if item.category == category:
            return item
    return None


_USN_RE = None


def _find_usn_in_text(text: str) -> str | None:
    global _USN_RE
    if _USN_RE is None:
        import re

        _USN_RE = re.compile(r"\b01FE\d{2}(?:BCS|BCI|BEC|BEE|BCV|BME|BAR|BBT|BEV)\d{3}\b", re.IGNORECASE)
    m = _USN_RE.search(text)
    return m.group(0) if m else None


# ---------------------------------------------------------------------------
# Checklist evaluation & eligibility
# ---------------------------------------------------------------------------

_STATUS_LABELS = {
    None: "Missing",
    ApplicationStatus.SUBMITTED.value: "Uploaded",
    ApplicationStatus.OCR_COMPLETED.value: "Under Review",
    ApplicationStatus.VERIFIED.value: "Verified",
    ApplicationStatus.REJECTED.value: "Rejected",
}


def _effective_status(
    doc: UploadedDocument,
    student: Student | None = None,
    override: str | None = None,
) -> str:
    """Validation status of one stored document, honouring legacy rows.

    `override` is the freshly computed automated status for this evaluation pass. An explicit
    reviewer VERIFIED decision (reviewed_by set) is authoritative and never downgraded by a
    later hint-based reclassification; automated statuses, by contrast, may replace the stored
    value (e.g. after replacement resets a document, or when OCR newly fails).
    """
    st = getattr(doc, "validation_status", None) or ApplicationStatus.SUBMITTED.value
    if override is not None:
        reviewer_verified = (
            st == ApplicationStatus.VERIFIED.value
            and getattr(doc, "reviewed_by", None) is not None
        )
        if not reviewer_verified:
            st = override
    category = getattr(doc, "document_category", None)
    if st == ApplicationStatus.VERIFIED.value and category == "DEGREE_COMPLETION_PROOF":
        # Authoritative completion check: an uploaded document alone must not establish it.
        if not degree_completion_confirmed(student):
            return ApplicationStatus.OCR_COMPLETED.value
    return st


def degree_completion_confirmed(student: Student | None) -> bool:
    """Authoritative academic completion signal (simulated university data in this project):
    past the final semester and zero outstanding backlogs. If either is unknown → not confirmed."""
    if student is None:
        return False
    try:
        sem = int(student.semester)
        backlogs = int(student.backlog_count)
    except (TypeError, ValueError):
        return False
    return sem >= 8 and backlogs == 0


def evaluate_checklist(db: Session, application: Application, student: Student, *, persist: bool = True) -> dict:
    """Run automated verification over the application's documents and evaluate the checklist.

    `persist=True` writes newly derived validation statuses/category assignments back to the DB.
    Re-running is cheap and idempotent; replaced documents re-enter verification automatically
    because replacement resets their status to SUBMITTED.
    """
    before = {id(doc): getattr(doc, "document_category", None) for doc in application.documents}
    assign_categories(application)
    # Persist the per-application category assignments so they survive across requests/sessions
    # (the hybrid `extension` attribute is intentionally never written to this column).
    if db is not None and any(
        id(doc) in before and getattr(doc, "document_category", None) != before[id(doc)]
        for doc in application.documents
    ):
        db.commit()
    changed = False
    computed: dict[int, str] = {}
    for doc in application.documents:
        new_status, reason = verify_document(application, doc, student)
        computed[doc.id] = new_status
        if getattr(doc, "validation_status", None) != new_status:
            doc.validation_status = new_status
            changed = True
        if reason != (getattr(doc, "validation_reason", None) or ""):
            doc.validation_reason = reason or None
            changed = True
        if new_status == ApplicationStatus.VERIFIED.value and getattr(doc, "verified_at", None) is None:
            from datetime import datetime, timezone

            doc.verified_at = datetime.now(timezone.utc)
            changed = True
        if new_status != ApplicationStatus.VERIFIED.value and getattr(doc, "verified_at", None) is not None:
            doc.verified_at = None  # stale verification invalidated (replacement/rejection)
            changed = True
    if persist and changed:
        db.commit()

    docs = list(application.documents)
    items_out = []
    blocking: list[str] = []
    verified_required = 0
    total_required = 0
    for item in get_checklist(application.document_type.code):
        matching = [d for d in docs if getattr(d, "document_category", None) == item.category]
        statuses = [_effective_status(d, student, computed.get(d.id)) for d in matching]
        if item.category in _FORM_ONLY_CATEGORIES:
            if item.category == "STUDENT_DETAILS":
                # Profile-backed for every request type: USN/name/department come from the
                # authoritative authenticated student record, never from an uploaded file.
                reqs = _PROFILE_REQUIREMENTS
            else:
                reqs = _FORM_REQUIREMENTS.get(application.document_type.code, {}).get(item.category, [])
            ok = all(_detail_present(application, key, student) for key in reqs)
            if ok:
                status = ApplicationStatus.VERIFIED.value
                note = "Provided in the application form and cross-checked against your profile."
            elif matching:
                status = ApplicationStatus.OCR_COMPLETED.value
                note = "Some delivery/particulars details are missing from the form."
            else:
                status = ApplicationStatus.SUBMITTED.value if not item.required else None
                status = status or None
                note = "Fill these details in the application form." if item.required else "Optional."
            items_out.append({**item.to_dict(), "status": _STATUS_LABELS[status], "status_code": status,
                              "documents": [], "note": note})
            if item.required:
                total_required += 1
                if status == ApplicationStatus.VERIFIED.value:
                    verified_required += 1
                else:
                    blocking.append(_blocking_message(item, status))
            continue

        if not matching:
            status = None
            note = "Not uploaded yet." if item.required else "Optional — not uploaded."
        elif ApplicationStatus.REJECTED.value in statuses:
            status = ApplicationStatus.REJECTED.value
            note = next((d.validation_reason for d in matching if _effective_status(d, student, computed.get(d.id)) == ApplicationStatus.REJECTED.value), "File rejected.")
        elif ApplicationStatus.OCR_COMPLETED.value in statuses:
            status = ApplicationStatus.OCR_COMPLETED.value
            note = next((d.validation_reason for d in matching if _effective_status(d, student, computed.get(d.id)) == ApplicationStatus.OCR_COMPLETED.value), "Awaiting verification.")
        elif ApplicationStatus.SUBMITTED.value in statuses:
            status = ApplicationStatus.SUBMITTED.value
            note = "Uploaded. Run document processing to validate it."
        else:
            status = ApplicationStatus.VERIFIED.value
            note = "Verified."
        items_out.append({
            **item.to_dict(),
            "status": _STATUS_LABELS[status],
            "status_code": status,
            "documents": [
                {
                    "id": d.id,
                    "filename": d.original_filename,
                    "uploaded_at": d.uploaded_at.isoformat() if d.uploaded_at else None,
                    "status": _STATUS_LABELS[_effective_status(d, student, computed.get(d.id))],
                    "status_code": _effective_status(d, student, computed.get(d.id)),
                    "reason": d.validation_reason,
                    "reviewed_by": d.reviewed_by,
                    "reviewed_at": d.reviewed_at.isoformat() if getattr(d, "reviewed_at", None) else None,
                }
                for d in matching
            ],
            "note": note,
        })
        if item.required:
            total_required += 1
            if status == ApplicationStatus.VERIFIED.value:
                verified_required += 1
            else:
                blocking.append(_blocking_message(item, status))

    eligible = not blocking
    return {
        "eligible_for_payment": eligible,
        "progress": {"verified_required": verified_required, "total_required": total_required},
        "items": items_out,
        "blocking_messages": blocking,
    }


def _blocking_message(item: ChecklistItem, status_code: str | None) -> str:
    label = item.label
    if status_code == ApplicationStatus.REJECTED.value:
        return f"Your {label.lower()} was rejected — replace it with a valid file."
    if status_code == ApplicationStatus.OCR_COMPLETED.value:
        return f"Your {label.lower()} is awaiting verification by an authorized reviewer."
    if status_code == ApplicationStatus.SUBMITTED.value:
        return f"Your {label.lower()} is uploaded but not validated yet — run document processing."
    if item.category in _FORM_ONLY_CATEGORIES:
        return f"Complete the required details for: {label}."
    return f"Upload the missing document: {label}."


def _detail_present(application: Application, key: str, student: Student) -> bool:
    """Form-detail presence check. Delivery details fall back to the student's official profile
    (name/mobile/address/PIN columns where they exist) so the check works even for applications
    created before the details form existed."""
    import json

    raw = getattr(application, "details_json", None) or "{}"
    try:
        details = json.loads(raw)
    except (ValueError, TypeError):
        details = {}
    value = str(details.get(key, "") or "").strip()
    if not value and key == "full_name":
        value = (student.full_name or "").strip()
    if not value:
        # Fall back to an official profile column of the same name, if the model has one.
        profile_value = getattr(student, key, None)
        if profile_value is not None and not callable(profile_value):
            value = str(profile_value).strip()
    return bool(value)
