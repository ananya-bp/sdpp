"""Tests for the USN generation, validation, and college-email module.

Covers:
- All 9 approved branch codes are supported.
- Sequences 001 and 500 are accepted; 000 and 501 are rejected.
- Format validation (12 chars, uppercase, correct prefix/pattern).
- Email derivation: lowercase USN + @kletech.ac.in.
- Invalid domain emails are rejected.
- Department-to-branch mapping is enforced.
- Full admission year matches encoded YY digits.
- generate_usn and parse_usn round-trip.
"""
import pytest

from app.core.usn import (
    BRANCH_CODES,
    SEQ_MAX,
    SEQ_MIN,
    UsNValidationError,
    branch_from_department,
    generate_usn,
    parse_usn,
    usn_to_email,
    validate_college_email,
    validate_email_domain,
    validate_usn,
)


# ---------------------------------------------------------------------------
# Canonical format validation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("usn", [
    "01FE23BCS054",  # valid BCS
    "01FE23BCI001",  # valid BCI
    "01FE23BEC002",  # valid BEC
    "01FE23BEE003",  # valid BEE
    "01FE23BCV004",  # valid BCV
    "01FE23BME005",  # valid BME
    "01FE23BAR006",  # valid BAR
    "01FE23BBT007",  # valid BBT
    "01FE23BEV008",  # valid BEV
    "01FE23BCS001",  # boundary: seq 001
    "01FE23BCS500",  # boundary: seq 500
])
def test_valid_usns_pass(usn):
    assert validate_usn(usn), f"Expected {usn!r} to be valid"


@pytest.mark.parametrize("usn", [
    "01FE23BCS000",  # seq 000 below range
    "01FE23BCS501",  # seq 501 above range
    "01FE23XXX001",  # unsupported branch code
    "01FE23BCS054X", # too long
    "01FE23BC054",   # branch only 2 chars
    "01FE3BCS054",   # YY only 1 digit
    "01fe23bcs054",  # lowercase — canonical form is uppercase
    "02FE23BCS054",  # wrong prefix (02 not 01)
    "01FX23BCS054",  # wrong prefix (FX not FE)
    "SIM23CSE001",   # legacy/simulated format — not canonical 01FE
    "",
    "TOOSHORT",
    "01FE23BCS0540", # 13 chars
])
def test_invalid_usns_rejected(usn):
    assert not validate_usn(usn), f"Expected {usn!r} to be invalid"


def test_all_nine_branch_codes_are_supported():
    expected = {"BCS", "BCI", "BEC", "BEE", "BCV", "BME", "BAR", "BBT", "BEV"}
    assert set(BRANCH_CODES.keys()) == expected


# ---------------------------------------------------------------------------
# Sequence boundary tests
# ---------------------------------------------------------------------------

def test_sequence_001_accepted():
    assert validate_usn("01FE23BCS001")


def test_sequence_500_accepted():
    assert validate_usn("01FE23BCS500")


def test_sequence_000_rejected():
    assert not validate_usn("01FE23BCS000")


def test_sequence_501_rejected():
    assert not validate_usn("01FE23BCS501")


# ---------------------------------------------------------------------------
# generate_usn and parse_usn
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("year,branch,seq,expected", [
    (2023, "BCS", 54,  "01FE23BCS054"),
    (2023, "BCS", 1,   "01FE23BCS001"),
    (2023, "BCS", 500, "01FE23BCS500"),
    (2000, "BEC", 100, "01FE00BEC100"),
    (1947, "BEE", 1,   "01FE47BEE001"),   # earliest supported year
    (2026, "BME", 250, "01FE26BME250"),
])
def test_generate_usn_produces_correct_format(year, branch, seq, expected):
    assert generate_usn(year, branch, seq) == expected


def test_generate_usn_rejects_unsupported_branch():
    with pytest.raises(UsNValidationError, match="Unsupported branch"):
        generate_usn(2023, "XYZ", 1)


def test_generate_usn_rejects_sequence_zero():
    with pytest.raises(UsNValidationError, match="out of range"):
        generate_usn(2023, "BCS", 0)


def test_generate_usn_rejects_sequence_501():
    with pytest.raises(UsNValidationError, match="out of range"):
        generate_usn(2023, "BCS", 501)


def test_generate_usn_rejects_invalid_year():
    with pytest.raises(UsNValidationError, match="out of range"):
        generate_usn(1946, "BCS", 1)


def test_parse_usn_round_trip():
    usn = "01FE23BCS054"
    yy, branch, seq = parse_usn(usn)
    assert yy == 23
    assert branch == "BCS"
    assert seq == 54
    # YY encodes the last two digits of the full admission year 2023.
    assert (2023 % 100) == yy


def test_parse_usn_raises_on_invalid():
    with pytest.raises(UsNValidationError):
        parse_usn("NOTAUSN")


# ---------------------------------------------------------------------------
# Email derivation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("usn,expected_email", [
    ("01FE23BCS054", "01fe23bcs054@kletech.ac.in"),
    ("01FE23BEC001", "01fe23bec001@kletech.ac.in"),
    ("01FE23BEV500", "01fe23bev500@kletech.ac.in"),
])
def test_usn_to_email(usn, expected_email):
    assert usn_to_email(usn) == expected_email


def test_usn_to_email_rejects_invalid_usn():
    with pytest.raises(UsNValidationError):
        usn_to_email("SIM23CSE001")  # non-canonical


@pytest.mark.parametrize("email,usn,expect", [
    ("01fe23bcs054@kletech.ac.in", "01FE23BCS054", True),
    ("01FE23BCS054@kletech.ac.in", "01FE23BCS054", False),  # uppercase local part
    ("01fe23bcs054@gmail.com",     "01FE23BCS054", False),
    ("01fe23bcs054@kletech.com",   "01FE23BCS054", False),
    ("01fe23bcs054@fakekletech.ac.in", "01FE23BCS054", False),
    ("01fe23bcs054@kletech.ac.in.example.com", "01FE23BCS054", False),
    ("other@kletech.ac.in",        "01FE23BCS054", False),
])
def test_validate_college_email(email, usn, expect):
    assert validate_college_email(email, usn) == expect


# ---------------------------------------------------------------------------
# Domain validation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("email,valid", [
    ("01fe23bcs054@kletech.ac.in",          True),
    ("student@kletech.ac.in",               True),
    ("student@gmail.com",                   False),
    ("student@kletech.com",                 False),
    ("student@fakekletech.ac.in",           False),
    ("student@kletech.ac.in.example.com",   False),
])
def test_email_domain_validation(email, valid):
    assert validate_email_domain(email) == valid


# ---------------------------------------------------------------------------
# Department → branch mapping
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("dept,expected_branch", [
    ("Computer Science and Engineering",             "BCS"),
    ("computer science and engineering",             "BCS"),  # case-insensitive
    ("Electronics and Communication Engineering",   "BEC"),
    ("Electrical and Electronics Engineering",      "BEE"),
    ("Mechanical Engineering",                      "BME"),
    ("Civil Engineering",                           "BCV"),
])
def test_branch_from_department_verified(dept, expected_branch):
    assert branch_from_department(dept) == expected_branch


def test_branch_from_department_unknown_returns_none():
    assert branch_from_department("Unknown Department XYZ") is None


# ---------------------------------------------------------------------------
# 12-character length check
# ---------------------------------------------------------------------------

def test_canonical_usn_is_12_characters():
    usn = generate_usn(2023, "BCS", 54)
    assert len(usn) == 12, f"Expected 12 chars, got {len(usn)}: {usn!r}"


def test_generated_usn_is_uppercase_alphanumeric():
    usn = generate_usn(2023, "BEC", 100)
    assert usn.isalnum() and usn == usn.upper()


# ---------------------------------------------------------------------------
# Registration validation: canonical USN requires matching @kletech.ac.in email
# ---------------------------------------------------------------------------

def test_register_schema_canonical_usn_requires_kletech_email():
    """RegisterRequest must reject a canonical USN paired with a non-kletech email."""
    from app.schemas.auth import RegisterRequest
    import pydantic

    # Valid pair: canonical USN + matching email
    req = RegisterRequest(usn="01FE23BCS054", email="01fe23bcs054@kletech.ac.in", password="Passw0rd!")
    assert req.usn == "01FE23BCS054"

    # Invalid: canonical USN + gmail
    with pytest.raises(pydantic.ValidationError, match="college email must be"):
        RegisterRequest(usn="01FE23BCS054", email="student@gmail.com", password="Passw0rd!")


def test_register_schema_sim_usn_accepts_any_email():
    """RegisterRequest must continue to accept SIM-format USNs with any valid email."""
    from app.schemas.auth import RegisterRequest

    req = RegisterRequest(usn="SIM23CSE001", email="student@example.com", password="Passw0rd!")
    assert req.usn == "SIM23CSE001"
