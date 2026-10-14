"""Constants for the SIMULATED data pipeline (Phase 4).

EVERYTHING this pipeline produces is simulated. No real KLE Tech student, application or payment
record exists in this project or was used to build these datasets. Distributions below are
ASSUMPTIONS chosen to make a plausible university workflow, not measurements of one.

The eligibility rules and fee schedule are copies of the placeholder policy in
backend/app/services/eligibility.py and payments.py; backend/tests/test_ml_config_sync.py fails
if the two ever drift apart.
"""
from dataclasses import dataclass
from datetime import date

SEED = 20260928

DOCUMENT_TYPES = [
    "TRANSCRIPT",
    "MIGRATION_CERTIFICATE",
    "DUPLICATE_GRADE_CARD",
    "PROVISIONAL_DEGREE_CERTIFICATE",
]

# Copy of backend FEE_BY_DOCUMENT_TYPE (placeholder fees, not a real fee circular).
FEE_BY_DOCUMENT_TYPE = {
    "TRANSCRIPT": 200.00,
    "MIGRATION_CERTIFICATE": 500.00,
    "DUPLICATE_GRADE_CARD": 150.00,
    "PROVISIONAL_DEGREE_CERTIFICATE": 300.00,
}

# Copy of the backend's placeholder eligibility rules.
COMMON_ELIGIBILITY_CONDITIONS = {"fee_status_clear", "has_supporting_documents"}
ZERO_BACKLOG_REQUIRED_FOR = {"PROVISIONAL_DEGREE_CERTIFICATE"}

DEPARTMENTS = {  # department code -> (name, share of students)
    "CSE": ("Computer Science and Engineering", 0.30),
    "ECE": ("Electronics and Communication Engineering", 0.22),
    "EEE": ("Electrical and Electronics Engineering", 0.16),
    "MEC": ("Mechanical Engineering", 0.18),
    "CIV": ("Civil Engineering", 0.14),
}

# ---- Simulated calendar (assumptions, not the real KLE Tech academic calendar) ----
HOLIDAYS_MD = [(1, 1), (1, 26), (5, 1), (8, 15), (10, 2), (11, 10), (11, 11), (12, 25)]
ACADEMIC_PHASE_BY_MONTH = {  # month -> phase
    1: "results", 2: "teaching", 3: "teaching", 4: "teaching", 5: "exam", 6: "results",
    7: "vacation", 8: "teaching", 9: "teaching", 10: "teaching", 11: "teaching", 12: "exam",
}

# ---- Demand model: expected applications per calendar day = BASE * SEASON[month] * DOW * trend ----
BASE_DAILY_RATE = {
    "TRANSCRIPT": 4.2, "MIGRATION_CERTIFICATE": 1.8,
    "DUPLICATE_GRADE_CARD": 3.2, "PROVISIONAL_DEGREE_CERTIFICATE": 2.2,
}
SEASON = {  # index 0 = January
    "TRANSCRIPT":                     [0.9, 0.9, 1.5, 1.4, 0.9, 0.8, 1.0, 1.7, 1.9, 1.8, 1.5, 1.0],
    "MIGRATION_CERTIFICATE":          [0.5, 0.5, 0.6, 0.8, 1.2, 2.2, 2.6, 2.0, 1.0, 0.6, 0.5, 0.5],
    "DUPLICATE_GRADE_CARD":           [1.4, 1.5, 0.8, 0.7, 0.9, 1.3, 1.5, 0.8, 0.7, 0.7, 0.8, 0.9],
    "PROVISIONAL_DEGREE_CERTIFICATE": [0.4, 0.4, 0.5, 0.6, 1.0, 2.4, 2.8, 2.2, 1.6, 0.8, 0.5, 0.4],
}
DAY_OF_WEEK_FACTOR = [1.25, 1.15, 1.10, 1.05, 1.00, 0.55, 0.35]  # Monday..Sunday
ANNUAL_GROWTH = 0.08
DAILY_SHOCK_SIGMA = 0.20  # day-level lognormal noise (overdispersion vs plain Poisson)
HOUR_WEIGHTS = [1, 1, 1, 1, 1, 1, 2, 4, 8, 11, 12, 11, 8, 8, 10, 11, 10, 8, 7, 8, 9, 7, 4, 2]

# ---- Admin processing (drives turnaround time) ----
WORK_UNITS = {  # capacity units one application consumes
    "TRANSCRIPT": 1.0, "MIGRATION_CERTIFICATE": 0.8,
    "DUPLICATE_GRADE_CARD": 0.5, "PROVISIONAL_DEGREE_CERTIFICATE": 1.2,
}
REVIEW_WORK_MULTIPLIER = 2.2
REVIEW_HOLD_HOURS = (12.0, 72.0)
CAPACITY_MEAN, CAPACITY_SD = 30.0, 3.5   # units per working day
LEAVE_WINDOWS_PER_YEAR, LEAVE_LENGTH_DAYS, LEAVE_CAPACITY_FACTOR = 2, 14, 0.6
REJECT_PROB, REJECT_PROB_IF_REVIEW = 0.02, 0.12
WORKDAY_START_HOUR, WORKDAY_HOURS = 9.5, 8.0

# ---- Application / payment behaviour ----
P_HAS_DOCUMENTS = 0.93
P_OCR_FAILED = 0.08
P_OCR_NO_CGPA_FOUND = 0.04
P_OCR_MISMATCH = 0.06
P_REAPPLY_AFTER_INELIGIBLE = 0.25
P_ALUMNI_BUNDLE = 0.05
P_ABANDON_PAYMENT = 0.04
P_PAY_RETRY_ONCE, P_PAY_RETRY_TWICE = 0.06, 0.01

# ---- Injected anomalies (known rates, so detection can be evaluated later) ----
P_DUPLICATE_APPLICATION = 0.003     # of eligible applications
P_RAPID_RETRY_BURST = 0.002         # of eligible, paying applications
P_AMOUNT_MISMATCH = 0.007           # of normally-paid applications
BURSTS_PER_YEAR = 4.0               # frequency-burst episodes (one student, 6-12 applications in 36h)

# ---- Risk-label generating model (latent; see simulate.py) ----
RISK_INTERCEPT = -4.1

@dataclass(frozen=True)
class SimConfig:
    n_students: int = 3000
    start: date = date(2023, 9, 1)
    end: date = date(2026, 8, 31)          # snapshot date: nothing after this is observed
    train_end: date = date(2025, 8, 31)
    valid_end: date = date(2026, 2, 28)    # test = everything after valid_end
    seed: int = SEED


def small_config(seed: int = SEED) -> SimConfig:
    """Fast configuration used by the tests (about 6 months, 400 students)."""
    return SimConfig(
        n_students=400, start=date(2024, 6, 1), end=date(2024, 11, 30),
        train_end=date(2024, 9, 30), valid_end=date(2024, 10, 31), seed=seed,
    )
