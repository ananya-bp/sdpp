"""Turn the raw simulated tables into model-ready datasets (one per ML component).

Design rules (see docs/DATA_DICTIONARY.md):
* Features use only information available at the time the prediction would be made.
* Answer-key columns are prefixed `label_` and never mixed into feature columns.
* Missing values are handled explicitly and documented per column.
* Every dataset carries a chronological `split` (train / valid / test); never shuffle across time.
"""
from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd

from . import config as C
from .features import add_calendar_columns, history_features, split_for, to_epoch_seconds

DAY = 86400.0


# --------------------------------------------------------------------------- shared helpers
def first_payment_times(txns: pd.DataFrame) -> pd.Series:
    """application_id -> time of its first SUCCESS payment (the moment it enters the admin queue)."""
    ok = txns[txns["payment_status"] == "SUCCESS"]
    return ok.groupby("application_id")["transacted_at"].min()


def _count_before(sorted_times: np.ndarray, t: np.ndarray) -> np.ndarray:
    """How many entries of sorted_times are strictly earlier than each t."""
    return np.searchsorted(sorted_times, t, side="left")


def open_queue_size(apps: pd.DataFrame, txns: pd.DataFrame, at: pd.Series) -> np.ndarray:
    """Applications paid but not yet decided at each timestamp in `at` (strictly before it)."""
    paid = np.sort(to_epoch_seconds(first_payment_times(txns)))
    decided = apps["decided_at"].dropna()
    dec = np.sort(to_epoch_seconds(decided))
    t = to_epoch_seconds(at)
    return _count_before(paid, t) - _count_before(dec, t)


# --------------------------------------------------------------------------- forecasting (daily demand)
def build_forecast_daily(apps: pd.DataFrame, txns: pd.DataFrame, cfg: C.SimConfig) -> pd.DataFrame:
    days = pd.date_range(cfg.start, cfg.end, freq="D")
    grid = pd.MultiIndex.from_product([days, C.DOCUMENT_TYPES], names=["date", "document_type"]).to_frame(index=False)

    a = apps.copy()
    a["date"] = a["submitted_at"].dt.normalize()
    counts = a.groupby(["date", "document_type"]).size().rename("applications_submitted")
    grid = grid.merge(counts, on=["date", "document_type"], how="left")
    grid["applications_submitted"] = grid["applications_submitted"].fillna(0).astype(int)

    a["tat_hours"] = (a["decided_at"] - a["submitted_at"]).dt.total_seconds() / 3600.0
    verified = a[a["status"] == "VERIFIED"]
    g = verified.groupby(["date", "document_type"])["tat_hours"]
    tat = pd.DataFrame({"mean_tat_hours": g.mean(), "n_tat_observed": g.size()}).reset_index()
    still_open = (a[a["status"] == "UNDER_REVIEW"].groupby(["date", "document_type"]).size()
                  .rename("n_still_open").reset_index())
    grid = grid.merge(tat, on=["date", "document_type"], how="left").merge(still_open, on=["date", "document_type"], how="left")
    grid["n_tat_observed"] = grid["n_tat_observed"].fillna(0).astype(int)
    grid["n_still_open"] = grid["n_still_open"].fillna(0).astype(int)
    # Missing-value policy for the TAT target: NaN when nothing finished, or when some of that day's
    # applications are still open at the snapshot (a mean over only the fast ones would be biased).
    grid["tat_censored"] = (grid["n_still_open"] > 0).astype(int)
    grid.loc[grid["tat_censored"] == 1, "mean_tat_hours"] = np.nan
    grid = grid.drop(columns=["n_still_open"])

    grid = add_calendar_columns(grid, "date")
    grid["week_of_year"] = grid["date"].dt.isocalendar().week.astype(int)
    grid["days_since_start"] = (grid["date"] - pd.Timestamp(cfg.start)).dt.days
    grid["queue_open_at_day_start"] = open_queue_size(apps, txns, grid["date"])

    grid = grid.sort_values(["document_type", "date"]).reset_index(drop=True)
    by_type = grid.groupby("document_type")["applications_submitted"]
    for lag in (1, 7, 14, 364):
        grid[f"lag_{lag}"] = by_type.shift(lag)
    for win in (7, 28):
        grid[f"roll_mean_{win}"] = by_type.transform(lambda s, w=win: s.shift(1).rolling(w).mean())
    # First 28 days have no complete rolling window: dropped. lag_364 stays NaN for the first year
    # (tree models tolerate NaN; drop the column for linear / SARIMA-style models).
    grid = grid[grid["date"] >= pd.Timestamp(cfg.start) + pd.Timedelta(days=28)]
    grid["split"] = split_for(grid["date"], cfg.train_end, cfg.valid_end)
    return grid.sort_values(["date", "document_type"]).reset_index(drop=True)


# --------------------------------------------------------------------------- TAT (per application)
def build_tat_applications(apps: pd.DataFrame, txns: pd.DataFrame, cfg: C.SimConfig) -> pd.DataFrame:
    """One row per VERIFIED application. Features known at submission; target = decided_at - submitted_at."""
    a = apps.sort_values("submitted_at").reset_index(drop=True)
    sub = to_epoch_seconds(a["submitted_at"])
    a["queue_open_at_submission"] = open_queue_size(a, txns, a["submitted_at"])
    a["apps_prev_24h"] = _count_before(sub, sub) - _count_before(sub, sub - DAY)
    a["apps_prev_7d"] = _count_before(sub, sub) - _count_before(sub, sub - 7 * DAY)
    a["doc_apps_prev_7d"] = 0
    for doc in C.DOCUMENT_TYPES:
        m = (a["document_type"] == doc).to_numpy()
        s = np.sort(sub[m])
        a.loc[m, "doc_apps_prev_7d"] = _count_before(s, sub[m]) - _count_before(s, sub[m] - 7 * DAY)
    a["submit_hour"] = a["submitted_at"].dt.hour
    a = add_calendar_columns(a, "submitted_at", prefix="submit_")
    a["tat_hours"] = (a["decided_at"] - a["submitted_at"]).dt.total_seconds() / 3600.0
    out = a[a["status"] == "VERIFIED"].copy()
    out["split"] = split_for(out["submitted_at"], cfg.train_end, cfg.valid_end)
    cols = ["application_id", "submitted_at", "document_type", "num_documents", "is_alumni", "submit_hour",
            "submit_dow", "submit_month", "submit_is_working_day", "submit_is_holiday", "submit_academic_phase",
            "queue_open_at_submission", "apps_prev_24h", "apps_prev_7d", "doc_apps_prev_7d", "tat_hours", "split"]
    return out[cols].reset_index(drop=True)


# --------------------------------------------------------------------------- risk scoring
def build_risk_scoring(apps: pd.DataFrame, labels: pd.DataFrame, students: pd.DataFrame,
                       cfg: C.SimConfig) -> pd.DataFrame:
    """Applications that passed the rule-based check, were paid for, and were DECIDED by the snapshot.

    Why only decided ones: the label (did it need manual attention?) is only observable once an
    application has been handled; still-open applications are right-censored and excluded, exactly as
    they would be when training on the real portal's history.
    """
    a = apps.sort_values(["submitted_at", "application_id"]).reset_index(drop=True)
    lab = labels.set_index("application_id")
    reviewed = np.nan_to_num(lab.loc[a["application_id"], "needs_manual_review"].astype(float).to_numpy())
    prior_apps, prior_rev = history_features(a["student_id"].to_numpy(), a["submitted_at"], reviewed)
    a["prior_apps_count"] = prior_apps
    a["prior_review_count_lagged"] = prior_rev
    a["label_needs_manual_review"] = lab.loc[a["application_id"], "needs_manual_review"].to_numpy()

    d = a[(a["eligibility_result"] == "ELIGIBLE") & a["status"].isin(["VERIFIED", "REJECTED"])].copy()
    d = d.merge(students[["student_id", "department"]], on="student_id", how="left")
    d["cgpa"] = d["cgpa_at_submission"]
    d["backlog_count"] = d["backlog_count_at_submission"]
    d["semester"] = d["semester_at_submission"]
    # OCR features. Missing-value policy: no detected CGPA -> mismatch = 0, with explicit flags so
    # "nothing to compare" is never confused with "matched".
    d["ocr_failed"] = (d["ocr_status"] == "FAILED").astype(int)
    d["ocr_cgpa_found"] = d["ocr_detected_cgpa"].notna().astype(int)
    d["ocr_cgpa_mismatch"] = (d["ocr_detected_cgpa"] - d["cgpa"]).abs().fillna(0.0).round(2)
    d["label_needs_manual_review"] = d["label_needs_manual_review"].astype(int)
    d["split"] = split_for(d["submitted_at"], cfg.train_end, cfg.valid_end)
    # NOT included: fee_status (always CLEAR once eligible, i.e. constant) and everything that is only
    # known after the application is handled (status, decided_at, TAT, payment retries).
    cols = ["application_id", "student_id", "submitted_at", "document_type", "department", "semester",
            "is_alumni", "cgpa", "backlog_count", "past_fee_delays_12m", "prior_apps_count",
            "prior_review_count_lagged", "num_documents", "ocr_failed", "ocr_cgpa_found", "ocr_cgpa_mismatch",
            "label_needs_manual_review", "split"]
    return d[cols].reset_index(drop=True)


# --------------------------------------------------------------------------- anomaly detection
def build_anomaly_transactions(apps: pd.DataFrame, txns: pd.DataFrame, tlabels: pd.DataFrame,
                               cfg: C.SimConfig) -> pd.DataFrame:
    """One row per payment attempt with behavioural features known at that moment."""
    t = txns.merge(apps[["application_id", "student_id", "document_type", "submitted_at"]], on="application_id")
    t = t.sort_values(["transacted_at", "transaction_id"]).reset_index(drop=True)
    t["expected_amount"] = t["document_type"].map(C.FEE_BY_DOCUMENT_TYPE)
    t["amount_ratio"] = (t["amount"] / t["expected_amount"]).round(4)
    is_failed = (t["payment_status"] == "FAILED").astype(int)
    t["attempt_index"] = t.groupby("application_id").cumcount() + 1
    t["failed_attempts_before"] = is_failed.groupby(t["application_id"]).cumsum() - is_failed
    prev = t.groupby("application_id")["transacted_at"].shift(1)
    # Missing-value policy: a first attempt has no previous attempt -> sentinel of one day.
    t["seconds_since_prev_attempt"] = (t["transacted_at"] - prev).dt.total_seconds().fillna(DAY)
    t["minutes_since_submission"] = ((t["transacted_at"] - t["submitted_at"]).dt.total_seconds() / 60.0).round(2)
    t["hour"] = t["transacted_at"].dt.hour
    t["dow"] = t["transacted_at"].dt.dayofweek

    tt = to_epoch_seconds(t["transacted_at"])
    paid_at = first_payment_times(txns)
    app_paid = to_epoch_seconds(pd.Series(t["application_id"]).map(paid_at))  # NaT -> NaN
    app_sub = to_epoch_seconds(t["submitted_at"])
    apps_s = apps.assign(sub=to_epoch_seconds(apps["submitted_at"]),
                         paid=to_epoch_seconds(apps["application_id"].map(paid_at)))

    n = len(t)
    f_txn24 = np.zeros(n)
    f_apps24 = np.zeros(n)
    f_apps7 = np.zeros(n)
    f_doc7 = np.zeros(n)
    f_docpaid7 = np.zeros(n)
    student_groups = t.groupby("student_id").indices
    app_groups = {k: (g["sub"].to_numpy(), g["paid"].to_numpy(), g["application_id"].to_numpy(),
                      g["document_type"].to_numpy())
                  for k, g in apps_s.groupby("student_id")}
    for sid, rows in student_groups.items():
        times = np.sort(tt[rows])
        s_sub, s_paid, s_app, s_doc = app_groups[sid]
        order = np.argsort(s_sub)
        s_sub, s_paid, s_app, s_doc = s_sub[order], s_paid[order], s_app[order], s_doc[order]
        for r in rows:
            now = tt[r]
            f_txn24[r] = (np.searchsorted(times, now, "left") - np.searchsorted(times, now - DAY, "left"))
            own = t.at[r, "application_id"]
            in24 = (s_sub >= now - DAY) & (s_sub <= now) & (s_app != own)
            in7 = (s_sub >= now - 7 * DAY) & (s_sub <= now) & (s_app != own)
            same = in7 & (s_doc == t.at[r, "document_type"])
            f_apps24[r], f_apps7[r], f_doc7[r] = in24.sum(), in7.sum(), same.sum()
            f_docpaid7[r] = (same & (s_paid < now)).sum()  # NaN paid -> comparison False
    t["student_txns_prior_24h"] = f_txn24.astype(int)
    t["student_other_apps_24h"] = f_apps24.astype(int)
    t["student_other_apps_7d"] = f_apps7.astype(int)
    t["same_doc_other_apps_7d"] = f_doc7.astype(int)
    t["same_doc_other_paid_apps_7d"] = f_docpaid7.astype(int)

    lab = tlabels.set_index("transaction_id")
    t["label_is_anomaly"] = lab.loc[t["transaction_id"], "is_anomaly"].to_numpy()
    t["label_anomaly_type"] = lab.loc[t["transaction_id"], "anomaly_type"].to_numpy()
    t["split"] = split_for(t["transacted_at"], cfg.train_end, cfg.valid_end)
    cols = ["transaction_id", "application_id", "student_id", "transacted_at", "document_type", "payment_status",
            "amount", "expected_amount", "amount_ratio", "attempt_index", "failed_attempts_before",
            "seconds_since_prev_attempt", "minutes_since_submission", "student_txns_prior_24h",
            "student_other_apps_24h", "student_other_apps_7d", "same_doc_other_apps_7d",
            "same_doc_other_paid_apps_7d", "hour", "dow", "label_is_anomaly", "label_anomaly_type", "split"]
    return t[cols].reset_index(drop=True)
