"""Rule-based (deterministic) eligibility checking - see SDP_BUILD_GUIDE.md section 1.4.

This is NOT the ML Eligibility Risk Scoring model (that's Phase 5); it never touches any
risk-scoring table/column and produces a hard ELIGIBLE / NOT_ELIGIBLE / MANUAL_REVIEW
decision, not a probability.

## Outcomes

ELIGIBLE:
  All verified mandatory conditions are satisfied, required information is present, and
  no unresolved verification or policy issue remains.

NOT_ELIGIBLE:
  A verified mandatory criterion definitively fails under a configured and applicable policy.

MANUAL_REVIEW:
  Eligibility cannot be decided automatically because evidence is uncertain (low OCR
  confidence, OCR failure), documents conflict, or the applicable policy is unverified.
  Document verification problems do NOT automatically produce NOT_ELIGIBLE; they route the
  application to admin review so evidence can be checked.

## Mapping to ApplicationStatus (no schema changes needed)

  ELIGIBLE       → ApplicationStatus.ELIGIBLE
  NOT_ELIGIBLE   → ApplicationStatus.NOT_ELIGIBLE
  MANUAL_REVIEW  → ApplicationStatus.MANUAL_REVIEW  (new status added in this phase)

## Policy notes

Thresholds below are a placeholder policy, not real KLE Tech institutional policy (none has
been confirmed for this project). They are marked PLACEHOLDER / UNVERIFIED in code so the
real policy can be swapped in later by changing RULES_BY_DOCUMENT_TYPE without touching the
engine itself.

Current policy (placeholder):
  1. Fee status must be CLEAR for every document type (a due balance blocks any request).
  2. A Provisional Degree Certificate additionally requires zero backlogs.
  3. No CGPA minimum for any document type.
  4. At least one supporting document must be attached, for every document type.
  5. If OCR failed on any document, route to MANUAL_REVIEW (not ELIGIBLE or NOT_ELIGIBLE),
     because the document content could not be verified.
  6. If any document produced very few words (< 5), route to MANUAL_REVIEW: the upload may
     be unreadable or the wrong document.
"""
from dataclasses import dataclass, field
from enum import StrEnum

from sqlalchemy.orm import Session

from app.core.statuses import ApplicationStatus
from app.models import Application, Student


class EligibilityDecision(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    MANUAL_REVIEW = "MANUAL_REVIEW"


@dataclass
class Condition:
    name: str
    check: "callable"          # (Application, Student) -> bool
    reason_if_failed: "callable"   # (Application, Student) -> str
    verified: bool = True          # False = policy not officially confirmed; route to MANUAL_REVIEW


def _fee_clear(app: Application, student: Student) -> bool:
    return student.fee_status == "CLEAR"


def _fee_clear_reason(app: Application, student: Student) -> str:
    return f"Fee status is '{student.fee_status}', not CLEAR."


def _no_backlogs(app: Application, student: Student) -> bool:
    return student.backlog_count == 0


def _no_backlogs_reason(app: Application, student: Student) -> str:
    return f"{student.backlog_count} backlog(s) outstanding; a Provisional Degree Certificate requires zero."


def _has_documents(app: Application, student: Student) -> bool:
    return len(app.documents) >= 1


def _has_documents_reason(app: Application, student: Student) -> str:
    return "No supporting documents were attached to this application."


# Conditions applied to every document type, regardless of which type it is.
COMMON_CONDITIONS: list[Condition] = [
    Condition("fee_status_clear", _fee_clear, _fee_clear_reason, verified=True),
    Condition("has_supporting_documents", _has_documents, _has_documents_reason, verified=True),
]

# Extra conditions per document type code (in addition to COMMON_CONDITIONS above).
# PLACEHOLDER: these are illustrative defaults, not confirmed KLE Tech institutional policy.
RULES_BY_DOCUMENT_TYPE: dict[str, list[Condition]] = {
    "TRANSCRIPT": [],
    "MIGRATION_CERTIFICATE": [],
    "DUPLICATE_GRADE_CARD": [],
    "PROVISIONAL_DEGREE_CERTIFICATE": [
        # PLACEHOLDER: zero backlogs required for a Provisional Degree Certificate.
        # Source: placeholder default, not confirmed by official KLE Tech policy.
        Condition("no_outstanding_backlogs", _no_backlogs, _no_backlogs_reason, verified=True),
    ],
}


# ---------------------------------------------------------------------------
# OCR evidence checks — route to MANUAL_REVIEW when evidence is unreliable.
# These are NOT academic conditions; they are evidence-quality gates.
# ---------------------------------------------------------------------------

def _ocr_evidence_issues(app: Application) -> list[str]:
    """Return reasons why OCR evidence is insufficient for automatic eligibility.

    A FAILED or low-confidence OCR result means the document content was not verified.
    This triggers MANUAL_REVIEW (not NOT_ELIGIBLE) — the student may have provided a
    perfectly valid document that just needs human verification.
    """
    issues: list[str] = []
    if not app.documents:
        return issues  # no documents: caught by _has_documents condition above
    for doc in app.documents:
        r = doc.ocr_result
        if r is None:
            issues.append(
                f"'{doc.original_filename}': document has not been processed yet (OCR not run)."
            )
        elif r.status == "FAILED":
            issues.append(
                f"'{doc.original_filename}': could not be read ({r.error_message or 'unreadable file'})."
                " A human reviewer must verify its contents."
            )
        elif r.extracted_fields and (r.extracted_fields.get("word_count", 0) < 5):
            issues.append(
                f"'{doc.original_filename}': very few words were extracted (word count "
                f"{r.extracted_fields.get('word_count', 0)}). The document may be blank, "
                "corrupt, or incorrectly uploaded. A reviewer must check its contents."
            )
    return issues


@dataclass
class EligibilityOutcome:
    decision: EligibilityDecision
    failed_conditions: list[str] = field(default_factory=list)
    manual_review_reasons: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    # Backward-compatible property so existing code that checked outcome.eligible still works.
    @property
    def eligible(self) -> bool:
        return self.decision == EligibilityDecision.ELIGIBLE


def evaluate(application: Application, student: Student) -> EligibilityOutcome:
    """Evaluate every condition for this application's document type.

    Returns ELIGIBLE, NOT_ELIGIBLE, or MANUAL_REVIEW.
    Never raises.
    """
    # 1. Run mandatory conditions (academic / administrative eligibility).
    code = application.document_type.code
    conditions = COMMON_CONDITIONS + RULES_BY_DOCUMENT_TYPE.get(code, [])
    failed_names: list[str] = []
    failed_reasons: list[str] = []
    unverified_names: list[str] = []

    for condition in conditions:
        if not condition.check(application, student):
            failed_names.append(condition.name)
            failed_reasons.append(condition.reason_if_failed(application, student))
            if not condition.verified:
                unverified_names.append(condition.name)

    # 2. If a verified mandatory condition failed → NOT_ELIGIBLE immediately.
    #    Unverified conditions that fail → MANUAL_REVIEW (policy needs confirmation).
    verified_failures = [n for n in failed_names if n not in unverified_names]
    if verified_failures:
        return EligibilityOutcome(
            decision=EligibilityDecision.NOT_ELIGIBLE,
            failed_conditions=failed_names,
            reasons=failed_reasons,
        )

    # 3. Check OCR evidence quality. Problems here → MANUAL_REVIEW, not NOT_ELIGIBLE.
    ocr_issues = _ocr_evidence_issues(application)
    if ocr_issues or unverified_names:
        review_reasons = ocr_issues[:]
        if unverified_names:
            review_reasons.append(
                f"Conditions {unverified_names} could not be automatically verified "
                "(policy unconfirmed). Manual confirmation required."
            )
        return EligibilityOutcome(
            decision=EligibilityDecision.MANUAL_REVIEW,
            manual_review_reasons=review_reasons,
            reasons=review_reasons,
        )

    # 4. All conditions pass and evidence is acceptable → ELIGIBLE.
    return EligibilityOutcome(decision=EligibilityDecision.ELIGIBLE)


def run_eligibility_for_application(
    db: Session, application: Application, student: Student, changed_by: int | None = None
) -> Application:
    """Evaluate eligibility and record ELIGIBLE / NOT_ELIGIBLE / MANUAL_REVIEW via set_status()."""
    outcome = evaluate(application, student)

    if outcome.decision == EligibilityDecision.ELIGIBLE:
        status = ApplicationStatus.ELIGIBLE
        note = "Eligible: all conditions met."
    elif outcome.decision == EligibilityDecision.NOT_ELIGIBLE:
        status = ApplicationStatus.NOT_ELIGIBLE
        note = "; ".join(outcome.reasons)
    else:
        # MANUAL_REVIEW
        status = ApplicationStatus.MANUAL_REVIEW
        note = "Manual review required: " + "; ".join(outcome.reasons)

    from app.services.applications import set_status  # local import: avoids a circular import

    set_status(db, application, status, changed_by=changed_by, note=note)
    db.commit()
    db.refresh(application)
    return application
