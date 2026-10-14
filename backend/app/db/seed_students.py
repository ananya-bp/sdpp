"""Load SIMULATED student records for development and testing.

These are NOT real KLE Tech students: the USNs, names and academic values are invented. The
values are varied on purpose (CGPA, backlogs, fee dues) so later phases (eligibility rules,
risk scoring) have different situations to work with. A larger simulated dataset for the ML
components is built in Phase 4.

Usage (from the backend/ folder):  python -m app.db.seed_students   (safe to re-run)
"""
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models import Student

CSE = "Computer Science and Engineering"
ECE = "Electronics and Communication Engineering"
EEE = "Electrical and Electronics Engineering"
MEC = "Mechanical Engineering"
CIV = "Civil Engineering"
# Departments for UNVERIFIED branch codes — names are provisional.
CIS = "Computer Science and Information Science"   # BCI — UNVERIFIED
ARC = "Architecture"                               # BAR — UNVERIFIED
BIO = "Biotechnology"                              # BBT — UNVERIFIED
ENV = "Environmental Engineering"                  # BEV — UNVERIFIED

# (usn, full_name, department, semester, cgpa, backlog_count, fee_status)
SIMULATED_STUDENTS = [
    ("SIM23CSE001", "Sim Student 01", CSE, 7, "8.90", 0, "CLEAR"),
    ("SIM23CSE002", "Sim Student 02", CSE, 7, "7.45", 1, "CLEAR"),
    ("SIM23CSE003", "Sim Student 03", CSE, 8, "9.30", 0, "CLEAR"),
    ("SIM23CSE004", "Sim Student 04", CSE, 7, "6.10", 3, "DUE"),
    ("SIM23ECE001", "Sim Student 05", ECE, 7, "8.05", 0, "CLEAR"),
    ("SIM23ECE002", "Sim Student 06", ECE, 8, "7.20", 2, "CLEAR"),
    ("SIM23EEE001", "Sim Student 07", EEE, 7, "8.60", 0, "DUE"),
    ("SIM23EEE002", "Sim Student 08", EEE, 5, "7.80", 0, "CLEAR"),
    ("SIM23MEC001", "Sim Student 09", MEC, 8, "6.85", 1, "CLEAR"),
    ("SIM23MEC002", "Sim Student 10", MEC, 7, "9.10", 0, "CLEAR"),
    ("SIM23CIV001", "Sim Student 11", CIV, 8, "7.05", 0, "CLEAR"),
    ("SIM23CIV002", "Sim Student 12", CIV, 6, "5.90", 4, "DUE"),
    # -----------------------------------------------------------------------
    # Canonical 01FE-format students (one per branch, admission year 2023).
    # USNs follow: 01FE{YY}{BRANCH}{NNN}  e.g. 01FE23BCS001
    # College emails follow: usn.lower()@kletech.ac.in
    # -----------------------------------------------------------------------
    ("01FE23BCS001", "KLE Student BCS-01", CSE,  7, "8.75", 0, "CLEAR"),
    ("01FE23BCI001", "KLE Student BCI-01", CIS,  6, "7.90", 0, "CLEAR"),
    ("01FE23BEC001", "KLE Student BEC-01", ECE,  7, "8.30", 0, "CLEAR"),
    ("01FE23BEE001", "KLE Student BEE-01", EEE,  7, "7.65", 0, "CLEAR"),
    ("01FE23BCV001", "KLE Student BCV-01", CIV,  6, "6.95", 1, "CLEAR"),
    ("01FE23BME001", "KLE Student BME-01", MEC,  8, "8.05", 0, "CLEAR"),
    ("01FE23BAR001", "KLE Student BAR-01", ARC,  5, "7.45", 0, "CLEAR"),
    ("01FE23BBT001", "KLE Student BBT-01", BIO,  6, "8.20", 0, "CLEAR"),
    ("01FE23BEV001", "KLE Student BEV-01", ENV,  7, "7.10", 0, "CLEAR"),
]


def seed_students(db: Session) -> int:
    """Insert any missing simulated students. Returns how many were added."""
    existing = set(db.scalars(select(Student.usn)).all())
    added = 0
    for usn, name, dept, sem, cgpa, backlogs, fee in SIMULATED_STUDENTS:
        if usn not in existing:
            db.add(
                Student(
                    usn=usn, full_name=name, department=dept, semester=sem,
                    cgpa=Decimal(cgpa), backlog_count=backlogs, fee_status=fee,
                )
            )
            added += 1
    db.commit()
    return added


if __name__ == "__main__":
    with SessionLocal() as session:
        added = seed_students(session)
    print(f"Simulated students: {added} added ({len(SIMULATED_STUDENTS)} defined).")
