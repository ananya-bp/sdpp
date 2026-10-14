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

# Valid full admission year range (full calendar year, not two-digit shorthand).
YEAR_MIN = 1947
YEAR_MAX = 2099


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
    if not (YEAR_MIN <= year <= YEAR_MAX):
        raise UsNValidationError(
            f"Admission year {year} is out of range ({YEAR_MIN}–{YEAR_MAX})."
        )
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
    - email local part must equal usn.lower()
    - email domain must be exactly kletech.ac.in
    - No subdomains, aliases, or similar-looking domains are accepted.
    """
    if not validate_usn(usn):
        return False  # non-canonical USN — cannot apply the derivation rule
    expected = usn_to_email(usn)
    return email.lower() == expected


def validate_email_domain(email: str) -> bool:
    """Return True if *email* uses the exact @kletech.ac.in domain.

    Rejects gmail.com, kletech.com, kletech.ac.in.example.com, and similar.
    """
    return email.lower().endswith(COLLEGE_EMAIL_DOMAIN)


def branch_from_department(department: str) -> str | None:
    """Return the branch code for a department name, or None if not found.

    Case-insensitive. Returns None for unknown departments.
    """
    return _DEPT_TO_BRANCH.get(department.strip().lower())
