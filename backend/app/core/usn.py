"""USN (University Seat Number) generation, validation, and college-email derivation.

KLE Technological University USN format: 01FE{YY}{BRANCH}{NNN}

  01FE   : fixed institutional prefix
  YY     : final two digits of the full admission year  (e.g. 23 for 2023)
  BRANCH : approved 3-character branch code (see BRANCH_CODES)
  NNN    : student sequence 001 – 500

Canonical USNs are exactly 12 uppercase alphanumeric characters.

College email rule:
  Lowercase the complete USN → append @kletech.ac.in
  01FE23BCS054  →  01fe23bcs054@kletech.ac.in

Department mapping:
  Verified mappings are marked VERIFIED.  Unverified mappings are marked UNVERIFIED and should
  be confirmed against official KLE Tech records before use in production.

Supported admission years: 1947 – 2099 (the two-digit YY is stored alongside the full year;
the full year is the source of truth because YY alone cannot distinguish centuries).
"""
import re
from typing import NamedTuple

# ---------------------------------------------------------------------------
# Branch codes and department mapping
# ---------------------------------------------------------------------------

COLLEGE_EMAIL_DOMAIN = "@kletech.ac.in"

# Canonical pattern: 01FE + 2 digit year + 3-letter branch + 3 digit sequence.
_USN_PATTERN = re.compile(r"^01FE(\d{2})([A-Z]{3})(\d{3})$")

# Approved branch codes with their full department names.
# Sources:
#   VERIFIED   – matched against existing seed_students.py department names and standard KLE Tech
#                department structure as described in the project brief.
#   UNVERIFIED – inferred from common Indian university conventions; must be confirmed against
#                official KLE Tech records before use.


class BranchInfo(NamedTuple):
    department: str        # full department name stored in the students table
    verified: bool         # True if confirmed against official KLE Tech sources


BRANCH_CODES: dict[str, BranchInfo] = {
    # --- VERIFIED against seed_students.py department names ---
    "BCS": BranchInfo("Computer Science and Engineering", True),
    "BEC": BranchInfo("Electronics and Communication Engineering", True),
    "BEE": BranchInfo("Electrical and Electronics Engineering", True),
    "BME": BranchInfo("Mechanical Engineering", True),
    "BCV": BranchInfo("Civil Engineering", True),
    # --- UNVERIFIED: inferred from common Indian university conventions ---
    "BCI": BranchInfo("Computer Science and Information Science", False),   # UNVERIFIED
    "BAR": BranchInfo("Architecture", False),                               # UNVERIFIED
    "BBT": BranchInfo("Biotechnology", False),                              # UNVERIFIED
    "BEV": BranchInfo("Environmental Engineering", False),                  # UNVERIFIED
}

# Reverse mapping: department name (lower) → branch code(s).
# Used for validation when creating students from department-labelled records.
_DEPT_TO_BRANCH: dict[str, str] = {
    info.department.lower(): code for code, info in BRANCH_CODES.items()
}

# Valid sequence range.
SEQ_MIN = 1
SEQ_MAX = 500

# Hard floor for full admission years (historical records begin in 1947). The supported
# *upper* bound is an application policy: it is read live from the centralised settings
# (USN_YEAR_MAX) so future years are allowed only within the explicitly configured range.
YEAR_MIN = 1947


def _supported_year_range() -> tuple[int, int]:
    """Configured supported full-admission-year range, re-read on every call."""
    try:
        from app.core.config import settings

        return settings.usn_supported_years
    except Exception:
        # Fallback for standalone use (no .env / settings unavailable): documented default.
        return YEAR_MIN, 2026


def _check_year(year: int) -> None:
    lo, hi = _supported_year_range()
    if not isinstance(year, int) or isinstance(year, bool):
        raise UsNValidationError(f"Admission year {year!r} must be an integer.")
    if not (lo <= year <= hi):
        raise UsNValidationError(
            f"Admission year {year} is outside the configured supported range ({lo}–{hi})."
        )


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

class UsNValidationError(ValueError):
    """Raised when a USN or email fails format validation."""


def validate_usn(usn: str) -> bool:
    """Return True when *usn* matches the canonical 01FE format, False otherwise.

    Does NOT check whether the USN exists in the database.
    """
    m = _USN_PATTERN.match(usn)
    if not m:
        return False
    seq = int(m.group(3))
    branch = m.group(2)
    return SEQ_MIN <= seq <= SEQ_MAX and branch in BRANCH_CODES


def parse_usn(usn: str) -> tuple[int, str, int]:
    """Parse a canonical USN and return (two_digit_year, branch, sequence).

    Raises UsNValidationError on invalid format.
    """
    m = _USN_PATTERN.match(usn)
    if not m:
        raise UsNValidationError(
            f"'{usn}' is not a valid KLE Tech USN. "
            f"Expected format: 01FE{{YY}}{{BRANCH}}{{NNN}} (e.g. 01FE23BCS054)."
        )
    yy, branch, seq_str = int(m.group(1)), m.group(2), int(m.group(3))
    if branch not in BRANCH_CODES:
        raise UsNValidationError(
            f"Unsupported branch code '{branch}'. "
            f"Supported codes: {', '.join(sorted(BRANCH_CODES))}."
        )
    if not (SEQ_MIN <= seq_str <= SEQ_MAX):
        raise UsNValidationError(
            f"Sequence {seq_str:03d} is out of range. "
            f"Valid range: {SEQ_MIN:03d}–{SEQ_MAX:03d}."
        )
    return yy, branch, seq_str


def generate_usn(year: int, branch: str, seq: int) -> str:
    """Generate a canonical USN for the given admission *year*, *branch* code, and *seq*.

    Raises UsNValidationError for unsupported or out-of-range inputs.
    Does NOT guarantee uniqueness — callers must check for collisions.
    """
    _check_year(year)
    branch = branch.upper()
    if branch not in BRANCH_CODES:
        raise UsNValidationError(
            f"Unsupported branch code '{branch}'. "
            f"Supported codes: {', '.join(sorted(BRANCH_CODES))}."
        )
    if not (SEQ_MIN <= seq <= SEQ_MAX):
        raise UsNValidationError(
            f"Sequence {seq} is out of range ({SEQ_MIN}–{SEQ_MAX})."
        )
    yy = year % 100
    return f"01FE{yy:02d}{branch}{seq:03d}"


def usn_to_email(usn: str) -> str:
    """Derive the canonical college email from a canonical USN.

    Raises UsNValidationError if the USN is not in canonical format.
    """
    if not validate_usn(usn):
        raise UsNValidationError(
            f"'{usn}' is not a valid canonical KLE Tech USN; cannot derive college email."
        )
    return usn.lower() + COLLEGE_EMAIL_DOMAIN


def validate_college_email(email: str, usn: str) -> bool:
    """Return True if *email* is the correct college email for *usn*.

    Rules:
    - email must EQUAL usn.lower() + @kletech.ac.in exactly (case-sensitive comparison —
      an uppercase local part such as '01FE23BCS054@kletech.ac.in' is NOT accepted;
      canonical emails are always lowercase).
    - email domain must be exactly kletech.ac.in.
    - No subdomains, aliases, or similar-looking domains are accepted.
    """
    if not validate_usn(usn):
        return False  # non-canonical USN — cannot apply the derivation rule
    expected = usn_to_email(usn)
    return email == expected


def validate_email_domain(email: str) -> bool:
    """Return True if *email* uses the exact @kletech.ac.in domain.

    Rejects gmail.com, kletech.com, fakekletech.ac.in, kletech.ac.in.example.com, and similar.
    The check splits at the LAST '@' so a look-alike domain embedded in the local part
    ('kletech.ac.in@googlemail.com') is still rejected.
    """
    _, sep, domain = email.rpartition("@")
    return bool(sep) and domain.lower() == COLLEGE_EMAIL_DOMAIN.lstrip("@")


def branch_from_department(department: str) -> str | None:
    """Return the branch code for a department name, or None if not found.

    Case-insensitive. Returns None for unknown departments.
    """
    return _DEPT_TO_BRANCH.get(department.strip().lower())


def normalize_email(email: str) -> str:
    """Normalise an email for validation/storage: strip surrounding whitespace and
    lowercase it (permitted input casing is normalised before validation).

    Raises UsNValidationError for structurally malformed input (empty, spaces inside,
    missing local part or domain, multiple '@').
    """
    if not isinstance(email, str):
        raise UsNValidationError("Email must be a string.")
    cleaned = email.strip()
    if not cleaned or any(ch.isspace() for ch in cleaned):
        raise UsNValidationError(f"Email {email!r} is empty or contains whitespace.")
    if cleaned.count("@") != 1:
        raise UsNValidationError(
            f"Email {email!r} is malformed: exactly one '@' separator is required."
        )
    local, _, domain = cleaned.partition("@")
    if not local or not domain or "." not in domain:
        raise UsNValidationError(f"Email {email!r} has a missing local part or domain.")
    return cleaned.lower()


def validate_full_admission_year(usn: str, admission_year: int) -> bool:
    """Return True when *admission_year* (full calendar year) matches the two-digit code
    embedded in canonical USN *usn*. The full year is always the source of truth; the YY
    code alone cannot distinguish centuries (e.g. 1923 vs 2023 both encode '23').

    Raises UsNValidationError if *usn* is not canonical.
    """
    yy, _branch, _seq = parse_usn(usn)
    if not isinstance(admission_year, int) or isinstance(admission_year, bool):
        raise UsNValidationError(f"Admission year {admission_year!r} must be an integer.")
    # The full admission year is the source of truth; only its plausibility (not the
    # configured *generation* range) is checked here, so historical records can still be
    # validated. Century ambiguity is resolved by the stored full year, never by YY alone.
    if not (1000 <= admission_year <= 9999):
        raise UsNValidationError(f"Admission year {admission_year} is not a plausible calendar year.")
    return admission_year % 100 == yy


# ---------------------------------------------------------------------------
# Collision-safe synthetic USN allocation (uses existing unique constraints; no schema changes)
# ---------------------------------------------------------------------------

class SequenceExhaustedError(RuntimeError):
    """Raised when every sequence in SEQ_MIN..SEQ_MAX is already taken for year+branch."""


def allocate_synthetic_usn(
    session_factory,
    *,
    full_name: str,
    department: str,
    admission_year: int,
    semester: int = 1,
    cgpa: str = "7.00",
    backlog_count: int = 0,
    fee_status: str = "CLEAR",
    max_retries: int = 25,
):
    """Create a Student row with a fresh, collision-free canonical USN and matching college email.

    SYNTHETIC records only — never rewrites or regenerates identifiers of existing students.

    Concurrency safety strategy (no pre-check-then-insert race):
      1. Compute a starting sequence from MAX(seq) of existing canonical USNs for this
         year+branch (purely an optimisation that skips the common case of sequential churn).
      2. Attempt inserts at candidate sequences in a bounded randomised order.
      3. The students.usn UNIQUE constraint is the real arbiter: on any collision
         (IntegrityError from a concurrent insert, or a legacy/hand-assigned USN occupying the
         slot) the failed transaction is rolled back and the next candidate is tried. Checking
         existence first would be racy; we rely on the database constraint instead.
      4. Each attempt runs in its own short transaction via the supplied session factory, so
         concurrent callers serialise cleanly on the unique index.

    Raises UsNValidationError for unsupported branches/years/departments, SequenceExhaustedError
    when all 500 slots are taken, and RuntimeError if collisions exceed max_retries.
    Returns the persisted Student instance.
    """
    import random
    from decimal import Decimal as _Decimal

    from sqlalchemy import func as _func, select as _select

    from app.models import Student

    # --- validate inputs through the existing format machinery (raises UsNValidationError) ---
    _check_year(admission_year)
    branch = branch_from_department(department)
    if branch is None:
        raise UsNValidationError(
            f"Department '{department}' has no verified branch-code mapping. "
            "Refusing to guess; add an official mapping before allocating USNs for it."
        )
    info = BRANCH_CODES[branch]
    if info.department.lower() != department.strip().lower():
        raise UsNValidationError(
            f"Department '{department}' does not match branch '{branch}' "
            f"(expected '{info.department}')."
        )

    yy = admission_year % 100

    def _existing_seqs(session) -> set[int]:
        usns = session.scalars(
            _select(Student.usn).where(Student.usn.like(f"01FE{yy:02d}{branch}%"))
        ).all()
        seqs: set[int] = set()
        for u in usns:
            try:
                seqs.add(parse_usn(u)[2])
            except UsNValidationError:
                pass  # malformed legacy value sharing the prefix: ignore for start calc
        return seqs

    candidates: list[int] | None = None
    attempts = 0
    while True:
        if candidates is None:
            # First pass: learn which sequences are taken, then build a randomised probe order
            # starting near max+1 (cheap for the common sequential-allocation case).
            with session_factory() as s:
                taken = _existing_seqs(s)
            free = [n for n in range(SEQ_MIN, SEQ_MAX + 1) if n not in taken]
            if not free:
                raise SequenceExhaustedError(
                    f"All {SEQ_MAX - SEQ_MIN + 1} sequences for year {admission_year} "
                    f"branch {branch} are allocated."
                )
            head_start = (max(taken) if taken else SEQ_MIN - 1) + 1
            head = [n for n in free if n >= head_start]
            tail = [n for n in free if n < head_start]
            random.shuffle(head)
            random.shuffle(tail)
            candidates = head[: max_retries // 2] + tail + head[max_retries // 2:]
            # keep only plausible probes within the retry budget from the front
            candidates = candidates[: max_retries]

        seq = candidates.pop(0)
        usn = generate_usn(admission_year, branch, seq)  # validated canonical format
        email = usn_to_email(usn)                        # exact lowercase rule
        attempts += 1
        try:
            with session_factory() as s:
                student = Student(
                    usn=usn,
                    full_name=full_name,
                    department=BRANCH_CODES[branch].department,
                    semester=semester,
                    cgpa=_Decimal(str(cgpa)),
                    backlog_count=backlog_count,
                    fee_status=fee_status,
                )
                s.add(student)
                s.commit()
                return student
        except Exception as exc:
            # Only unique-constraint collisions are retried; anything else propagates unchanged.
            from sqlalchemy.exc import IntegrityError

            if not isinstance(exc, IntegrityError):
                raise
            # Explicit rollback so the failed attempt's transaction is cleanly terminated
            # before the next candidate is tried (Session.close() alone discards the session
            # but does not guarantee an ROLLBACK was emitted on every backend).
            try:
                s.rollback()
            except Exception:
                pass  # session may already be closed/unusable; connection release suffices
            if attempts < max_retries:
                continue
            raise RuntimeError(
                f"USN allocation exceeded {max_retries} collision retries "
                f"(year {admission_year}, branch {branch})."
            ) from exc
