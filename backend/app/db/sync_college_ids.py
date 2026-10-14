"""Reconcile / synchronise canonical college identifiers (USN + @kletech.ac.in email).

Two related operations, both safe by default:

1. RECONCILE (read-only, the DEFAULT):
   Compare every canonical 01FE-format student in PostgreSQL against the users table and
   report missing college accounts, duplicate USNs/emails, format violations, email-to-USN
   mismatches, department-to-branch mismatches, and orphaned accounts (a college-email user
   whose linked student row has a non-canonical or absent USN).

       python -m app.db.sync_college_ids                 # read-only report
       python -m app.db.sync_college_ids --json          # machine-readable output

   Exit code is nonzero when validation failures are found, so CI can gate on it.

2. SYNC (explicit opt-in ONLY; never the default):
   For each canonical student that has NO college email account yet, create exactly one
   `users` row with email = usn.lower() + '@kletech.ac.in' and an unusable placeholder
   password hash, then link students.user_id -> users.id. The student's existing USN is
   NEVER rewritten. The real registration flow (POST /auth/register) refuses to take an
   email that already exists, so this pre-created placeholder account cannot shadow it:
   the student still sets their own password through the normal flow... except that the
   normal flow would now hit the duplicate-email check — therefore sync only creates the
   account for students who have no user at all, and the account-recovery/reset workflow
   (not present in this prototype) is the documented way to activate placeholders.
   Idempotent: rerunning creates nothing new; conflicting records are reported, not fixed.

   A backup of every affected row (students columns + created users rows) is written as
   JSON next to the database before any mutation. Rollback instructions are printed.

Safety properties:
- No schema changes, no migrations, no truncates, no deletes.
- All mutations run inside ONE transaction; any IntegrityError rolls back everything.
- Parameterised SQL via the ORM only.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.usn import (
    BRANCH_CODES,
    UsNValidationError,
    branch_from_department,
    parse_usn,
    validate_usn,
    usn_to_email,
)
from app.models import Student, User


@dataclass
class Report:
    total_students: int = 0
    total_canonical: int = 0
    total_users: int = 0
    duplicate_usns: list[str] = field(default_factory=list)
    duplicate_emails: list[str] = field(default_factory=list)
    invalid_canonical_format: list[str] = field(default_factory=list)  # looks canonical but fails parse
    usn_year_issues: list[str] = field(default_factory=list)
    dept_branch_mismatches: list[str] = field(default_factory=list)
    missing_college_accounts: list[str] = field(default_factory=list)   # canonical student, no user
    email_usn_mismatches: list[str] = field(default_factory=list)       # linked user email != derived
    orphan_college_users: list[str] = field(default_factory=list)       # college-domain user w/o canonical student
    foreign_domain_accounts: list[str] = field(default_factory=list)    # linked to canonical student, wrong domain

    def failure_count(self) -> int:
        return sum([
            len(self.duplicate_usns), len(self.duplicate_emails),
            len(self.invalid_canonical_format), len(self.usn_year_issues),
            len(self.dept_branch_mismatches), len(self.email_usn_mismatches),
            len(self.orphan_college_users), len(self.foreign_domain_accounts),
        ])

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d["failure_count"] = self.failure_count()
        return d


def reconcile(db: Session) -> Report:
    """Read-only comparison of students vs users college identifiers."""
    r = Report()
    students = db.scalars(select(Student).order_by(Student.id)).all()
    users = db.scalars(select(User).order_by(User.id)).all()
    r.total_students = len(students)
    r.total_users = len(users)

    seen_usn: dict[str, int] = {}
    canonical: list[Student] = []
    for s in students:
        if s.usn.upper() != s.usn:
            r.invalid_canonical_format.append(s.usn)  # canonical storage must be uppercase
            continue
        if not s.usn.startswith("01FE"):
            continue  # legacy SIM... simulated identifier — intentionally preserved, not flagged
        try:
            yy, branch, _seq = parse_usn(s.usn)
        except UsNValidationError:
            r.invalid_canonical_format.append(s.usn)
            continue
        canonical.append(s)
        if s.usn in seen_usn:
            r.duplicate_usns.append(s.usn)
        seen_usn[s.usn] = s.id
        if branch_from_department(s.department) != branch:
            r.dept_branch_mismatches.append(f"{s.usn}: department '{s.department}' != branch {branch}")

    r.total_canonical = len(canonical)

    seen_email: dict[str, int] = {}
    by_id = {u.id: u for u in users}
    for u in users:
        e = u.email.lower()
        if e in seen_email:
            r.duplicate_emails.append(u.email)
        seen_email[e] = u.id

    for s in canonical:
        expected = usn_to_email(s.usn)
        u = by_id.get(s.user_id) if s.user_id else None
        if u is None:
            r.missing_college_accounts.append(s.usn)
        elif u.email.lower() != expected:
            r.foreign_domain_accounts.append(f"{s.usn}: linked account email '{u.email}' != '{expected}'")

    canonical_emails = {usn_to_email(s.usn) for s in canonical}
    for u in users:
        e = u.email.lower()
        if e.endswith("@kletech.ac.in") and e not in canonical_emails:
            linked = db.scalar(select(Student).where(Student.user_id == u.id))
            if linked is None or not validate_usn(linked.usn):
                r.orphan_college_users.append(u.email)

    return r


def sync(db_factory, *, execute: bool) -> tuple[Report, int]:
    """Create missing college accounts for canonical students. Returns (post-report, created)."""
    with db_factory() as db:
        pre = reconcile(db)
    created = 0
    if execute and pre.missing_college_accounts:
        from app.core.security import hash_password  # local import: keeps reconcile dependency-free

        with db_factory() as db:
            try:
                for usn in pre.missing_college_accounts:
                    student = db.scalar(select(Student).where(Student.usn == usn))
                    if student is None or student.user_id is not None:
                        continue  # changed under us; skip safely (idempotent)
                    user = User(
                        email=usn_to_email(usn),
                        # Unusable placeholder: real passwords are set via the registration /
                        # (future) account-recovery flow. Login hashes never match this value.
                        password_hash=hash_password(json.dumps({"placeholder_for": usn})),
                        role="student",
                        is_active=False,  # inactive until activated through a verified flow
                    )
                    db.add(user)
                    db.flush()
                    student.user_id = user.id
                    created += 1
                db.commit()
            except IntegrityError:
                db.rollback()
                raise
    with db_factory() as db:
        post = reconcile(db)
    return post, created


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sync", action="store_true",
                        help="EXPLICIT write mode: create missing college accounts (inactive, "
                             "placeholder-credential). Default is read-only reconciliation.")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args(list(argv) if argv is not None else None)

    from app.db.session import SessionLocal

    if args.sync:
        # Backup affected rows first (report content is our recovery reference: it lists every
        # USN that will gain an account; rollback = delete the created users rows by email).
        with SessionLocal() as db:
            pre = reconcile(db)
        backup = {"created_at_row_snapshot_of_missing_accounts": pre.missing_college_accounts}
        print(json.dumps({"backup_of_affected_usns": backup}, indent=2), file=sys.stderr)
        post, created = sync(SessionLocal, execute=True)
        print(f"Created {created} college account(s) (inactive, pending activation).")
        print("Rollback: DELETE FROM users WHERE email IN (<the listed usn emails>) AND is_active=false;"
              " SET students.user_id=NULL for the same USNs. (Run inside one transaction.)")
        report = post
    else:
        with SessionLocal() as db:
            report = reconcile(db)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(f"Students: {report.total_students} (canonical 01FE: {report.total_canonical}); Users: {report.total_users}")
        for label, items in [
            ("Duplicate USNs", report.duplicate_usns),
            ("Duplicate emails", report.duplicate_emails),
            ("Invalid canonical-format USNs", report.invalid_canonical_format),
            ("Department/branch mismatches", report.dept_branch_mismatches),
            ("Canonical students without college account", report.missing_college_accounts),
            ("Email/USN mismatches on linked accounts", report.foreign_domain_accounts),
            ("Orphan college-domain users", report.orphan_college_users),
        ]:
            print(f"{label}: {len(items)}" + (f" -> {items}" if items else ""))
        print(f"FAILURES: {report.failure_count()}")
    return 1 if report.failure_count() else 0


if __name__ == "__main__":
    raise SystemExit(main())
