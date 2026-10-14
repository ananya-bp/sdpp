"""Request-specific form fields and supporting-document specifications.

Each of the four document types a student can request has its own set of extra form fields and
its own supporting-document checklist. The frontend renders these specs (GET /api/config/forms)
and the backend re-validates them on submission, so requirements cannot be bypassed by calling
the API directly.

POLICY NOTE: KLE Tech's official per-document requirements could not be verified for this
project from an official source. Every requirement below is therefore marked
``verified=False`` (UNVERIFIED) and labelled as such in the API response and in the UI. Real
institutional policy should replace these entries without changing the validation code.
"""
from dataclasses import asdict, dataclass, field


def _spec_dict(spec: "RequestSpec") -> dict:
    """JSON-serialisable view of a spec, with per-rule `verified` flags exposed."""
    d = asdict(spec)
    d["policy_verified"] = all(f.verified for f in spec.fields) and all(
        doc.verified for doc in spec.documents
    )
    return d


@dataclass
class FieldSpec:
    key: str
    label: str
    required: bool = True
    input_type: str = "text"          # text | select
    max_length: int = 200
    options: list[str] = field(default_factory=list)
    help_text: str = ""
    verified: bool = False            # UNVERIFIED unless confirmed against official policy

    @property
    def enforceable(self) -> bool:
        """A requirement is only hard-enforced once it has been verified against real policy.

        While `verified=False` the spec is still displayed (labelled UNVERIFIED in the UI), but a
        missing value must NOT block submission — inventing restrictions that were never approved
        by the institution would wrongly reject valid student applications. The engine itself is
        unchanged; only this flag decides enforcement.
        """
        return self.verified

    def validate(self, value: str) -> str | None:
        """Return a field-level error message, or None when the value is acceptable."""
        v = (value or "").strip()
        if self.required and self.enforceable and not v:
            return f"{self.label} is required."
        if len(v) > self.max_length:
            return f"{self.label} must be at most {self.max_length} characters."
        if self.input_type == "select" and v and v not in self.options:
            return f"{self.label}: choose one of {', '.join(self.options)}."
        return None


@dataclass
class DocumentSpec:
    code: str                          # required extension (lowercase): pdf/jpg/jpeg/png
    label: str
    required: bool = True
    verified: bool = False             # UNVERIFIED unless confirmed against official policy

    @property
    def enforceable(self) -> bool:
        """Unverified document requirements are displayed but never hard-block a submission.

        Blocking on an invented requirement would wrongly reject valid applications; once the
        real institutional policy is recorded (verified=True) the same checklist becomes
        mandatory without touching the validation code.
        """
        return self.verified


@dataclass
class RequestSpec:
    code: str
    name: str
    subtitle: str
    fields: list[FieldSpec]
    documents: list[DocumentSpec]

    @property
    def required_document_extensions(self) -> set[str]:
        return {d.code for d in self.documents if d.required}

    def field_errors(self, details: dict) -> list[str]:
        errors = []
        for spec in self.fields:
            err = spec.validate(str(details.get(spec.key, "") or ""))
            if err:
                errors.append(err)
        return errors

    def missing_document_labels(self, extensions: set[str]) -> list[str]:
        """Required supporting documents whose file type was not among the uploads.

        Only VERIFIED requirements are reported as blocking errors (see DocumentSpec.enforceable);
        unverified checklist items are shown in the UI but never reject a submission.

        A required document counts as satisfied when ANY upload matches its declared kind:
        jpg/jpeg are interchangeable (same underlying format), and a PDF-typed requirement is
        also satisfied by JPG/PNG uploads (scanned copies) — the reviewer checks content, and
        the OCR pipeline accepts all four formats. This keeps the check lenient so students are
        never falsely blocked; the backend still validates every file's real type/size/count.
        """
        missing = []
        for d in self.documents:
            if not d.required or not d.enforceable:
                continue
            kinds = {d.code}
            if d.code in ("pdf", "jpg", "jpeg"):
                kinds |= {"pdf", "jpg", "jpeg", "png"} if d.code == "pdf" else {"jpg", "jpeg"}
            if not (kinds & extensions):
                missing.append(d.label)
        return missing

    def missing_unverified_documents(self, extensions: set[str]) -> list[str]:
        """Checklist labels that are requested but not attached (advisory only, non-blocking)."""
        out = []
        for d in self.documents:
            if not d.required or d.enforceable:
                continue
            kinds = {d.code}
            if d.code in ("pdf", "jpg", "jpeg"):
                kinds |= {"pdf", "jpg", "jpeg", "png"} if d.code == "pdf" else {"jpg", "jpeg"}
            if not (kinds & extensions):
                out.append(d.label)
        return out


# Per-request-type field sets (kept minimal and genuinely request-specific; no invented academic
# restrictions — these are intake details, not eligibility criteria).
_SPECS: dict[str, RequestSpec] = {
    "TRANSCRIPT": RequestSpec(
        code="TRANSCRIPT",
        name="Official Transcript",
        subtitle="Complete academic record issued by the university.",
        fields=[
            FieldSpec("purpose", "Purpose of request", required=True, input_type="select",
                      options=["Higher studies", "Employment", "Personal record"],
                      help_text="Why the transcript is needed (shown to reviewers only)."),
            FieldSpec("copies", "Number of hard copies", required=False, input_type="select",
                      options=["1", "2", "3"],
                      help_text="Optional; defaults to the standard issue count."),
        ],
        documents=[
            DocumentSpec("pdf", "Fee-payment receipt (PDF)", required=True),
            DocumentSpec("pdf", "Previous semester mark card (PDF/JPG/PNG)", required=False),
        ],
    ),
    "MIGRATION_CERTIFICATE": RequestSpec(
        code="MIGRATION_CERTIFICATE",
        name="Migration Certificate",
        subtitle="Required when moving to another university.",
        fields=[
            FieldSpec("destination_university", "Destination university", required=True,
                      help_text="The university you intend to join."),
            FieldSpec("reason", "Reason for migration", required=True,
                      help_text="Brief reason for requesting the certificate."),
        ],
        documents=[
            DocumentSpec("pdf", "Admission proof at the new university (PDF)", required=True),
            DocumentSpec("pdf", "No-objection / transfer letter (PDF)", required=False),
        ],
    ),
    "DUPLICATE_GRADE_CARD": RequestSpec(
        code="DUPLICATE_GRADE_CARD",
        name="Duplicate Grade Card",
        subtitle="Reissue of a grade card lost or damaged after collection.",
        fields=[
            FieldSpec("semester", "Semester of the grade card", required=True, input_type="select",
                      options=[str(i) for i in range(1, 9)]),
            FieldSpec("reason", "Reason for reissue", required=True, input_type="select",
                      options=["Lost", "Damaged"]),
        ],
        documents=[
            DocumentSpec("pdf", "Police/FIR copy or affidavit (PDF)", required=True,
                         ),
            DocumentSpec("jpg", "Copy of the original grade card (JPG/PNG photo)", required=False),
        ],
    ),
    "PROVISIONAL_DEGREE_CERTIFICATE": RequestSpec(
        code="PROVISIONAL_DEGREE_CERTIFICATE",
        name="Provisional Degree Certificate",
        subtitle="Issued after final results, pending the convocation degree.",
        fields=[
            FieldSpec("enrollment_year", "Enrolment year", required=True,
                      help_text="Full four-digit year of admission, e.g. 2023."),
            FieldSpec("program", "Programme", required=True, input_type="select",
                      options=["B.E.", "B.Tech", "M.E.", "M.Tech"]),
        ],
        documents=[
            DocumentSpec("pdf", "Final semester result printout (PDF)", required=True),
            DocumentSpec("pdf", "On-campus employment/self-declaration (PDF)", required=False),
        ],
    ),
}


def get_spec(code: str) -> RequestSpec | None:
    return _SPECS.get(code)


def all_specs() -> list[RequestSpec]:
    return list(_SPECS.values())


def validate_submission(code: str, details: dict, uploaded_extensions: set[str]) -> list[str]:
    """Return all field-level + missing-document errors for one submission (empty list = OK)."""
    spec = get_spec(code)
    if spec is None:
        return []  # unknown code: handled elsewhere (document-type lookup already rejects it)
    errors = spec.field_errors(details or {})
    for label in spec.missing_document_labels(uploaded_extensions):
        errors.append(f"Missing required supporting document: {label}.")
    return errors


def forms_payload() -> dict:
    """Serialisable form specifications for GET /api/config/forms."""
    from app.services import uploads as _uploads

    return {
        "allowed_extensions": sorted(_uploads.ALLOWED_EXTENSIONS),
        "policy_note": (
            "Per-request field/document requirements are UNVERIFIED placeholders: they could "
            "not be confirmed against official KLE Tech policy. Each spec carries verified=false."
        ),
        "forms": [_spec_dict(s) for s in all_specs()],
    }
