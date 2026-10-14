"""Generate every Phase 4 dataset with one command (run from the project root):

    python -m ml.make_datasets

Steps: simulate raw tables -> write CSVs -> READ THEM BACK -> build model-ready datasets -> validate
-> write dataset_summary.json (with SHA-256 checksums). Same seed => identical files.
All data is SIMULATED; see docs/DATA_DICTIONARY.md.

College identifiers (USN + email): students.csv additionally carries `college_email`, derived
from each student's USN by the SHARED backend utility (app/core/usn.py) — never generated
independently. Canonical 01FE-format USNs get their exact lowercase @kletech.ac.in address;
legacy SYN-format simulated USNs have no college mailbox and stay empty (documented, not
invented). CSVs are written atomically (temp file + os.replace) so an interrupted run cannot
corrupt the previous dataset.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import pandas as pd

# Shared USN/email utility from the backend package: single source of truth for identifier
# rules across the app, data-generation scripts, the CSV pipeline and tests.
_BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))
from app.core.usn import validate_usn, usn_to_email  # noqa: E402

from . import config as C
from .prepare import (build_anomaly_transactions, build_forecast_daily, build_risk_scoring,
                      build_tat_applications)
from .simulate import simulate
from .validate_datasets import validate

DATA_DIR = Path(__file__).resolve().parent / "data"
RAW_DATES = {"students": [], "applications": ["submitted_at", "decided_at"], "transactions": ["transacted_at"]}
PROCESSED_DATES = {"forecast_daily": ["date"], "tat_applications": ["submitted_at"],
                   "risk_scoring": ["submitted_at"], "anomaly_transactions": ["transacted_at"]}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_csv_atomic(df: pd.DataFrame, path: Path) -> None:
    """Write a CSV so an interrupted operation can never leave a corrupted/partial target file."""
    tmp = path.with_name(path.name + ".tmp")
    df.to_csv(tmp, index=False)
    os.replace(tmp, path)  # atomic on POSIX and Windows


def add_college_emails(students: pd.DataFrame) -> pd.DataFrame:
    """Derive `college_email` from `usn` with the shared utility (idempotent; preserves columns)."""
    out = students.copy()
    emails = []
    for usn in out["usn"]:
        if isinstance(usn, str) and validate_usn(usn.strip().upper()):
            emails.append(usn_to_email(usn.strip().upper()))
        else:
            emails.append("")  # legacy/simulated USN: no college mailbox exists for it
    out["college_email"] = emails
    return out


def _read_raw(out: Path) -> tuple[dict, dict]:
    raw = {name: pd.read_csv(out / "raw" / f"{name}.csv", parse_dates=dates) for name, dates in RAW_DATES.items()}
    labels = {
        "application_labels": pd.read_csv(out / "labels" / "application_labels.csv", dtype={"needs_manual_review": "Int64"}),
        "transaction_labels": pd.read_csv(out / "labels" / "transaction_labels.csv"),
    }
    return raw, labels


def run(cfg: C.SimConfig, out: Path = DATA_DIR, verbose: bool = True) -> tuple[dict, list[str]]:
    for sub in ("raw", "labels", "processed"):
        (out / sub).mkdir(parents=True, exist_ok=True)
    sim = simulate(cfg)
    sim["students"] = add_college_emails(sim["students"])  # derived via the shared utility
    for name in RAW_DATES:
        _write_csv_atomic(sim[name], out / "raw" / f"{name}.csv")
    for name in ("application_labels", "transaction_labels"):
        _write_csv_atomic(sim[name], out / "labels" / f"{name}.csv")

    raw, labels = _read_raw(out)  # everything downstream uses the files on disk
    processed = {
        "forecast_daily": build_forecast_daily(raw["applications"], raw["transactions"], cfg),
        "tat_applications": build_tat_applications(raw["applications"], raw["transactions"], cfg),
        "risk_scoring": build_risk_scoring(raw["applications"], labels["application_labels"], raw["students"], cfg),
        "anomaly_transactions": build_anomaly_transactions(raw["applications"], raw["transactions"],
                                                           labels["transaction_labels"], cfg),
    }
    for name, df in processed.items():
        _write_csv_atomic(df, out / "processed" / f"{name}.csv")
    processed = {  # validate what was actually written
        name: pd.read_csv(out / "processed" / f"{name}.csv", parse_dates=PROCESSED_DATES[name])
        for name in processed
    }
    summary, failures = validate(raw, labels, processed, cfg)
    summary["generation"] = {
        "seed": cfg.seed, "n_students": cfg.n_students, "start": str(cfg.start), "snapshot_end": str(cfg.end),
        "train_end": str(cfg.train_end), "valid_end": str(cfg.valid_end),
        "data_origin": "SIMULATED - no real KLE Tech data. No public benchmark dataset is included.",
    }
    files = sorted(p for p in out.rglob("*.csv"))
    summary["files"] = {str(p.relative_to(out)): {"rows": int(sum(1 for _ in open(p, "rb")) - 1), "sha256": _sha256(p)}
                        for p in files}
    (out / "dataset_summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    if verbose:
        print(f"wrote {len(files)} CSV files to {out}")
        print(f"hard checks failed: {len(failures)}")
        for f in failures:
            print("  FAIL:", f)
    return summary, failures


if __name__ == "__main__":
    _, problems = run(C.SimConfig())
    sys.exit(1 if problems else 0)
