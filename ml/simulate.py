"""Simulator for the raw operational tables (students, applications, transactions).

ALL OUTPUT IS SIMULATED. No real KLE Tech data is used. The generating assumptions live in
config.py and are described in docs/DATA_DICTIONARY.md.

The world follows the real application flow (Phase 3):
    submit -> OCR -> rule-based eligibility -> payment -> admin queue -> decision
* Demand: seasonal Poisson arrivals per document type (with day-level noise and yearly growth).
* Eligibility: exactly the placeholder rules of backend/app/services/eligibility.py.
* Payment: mostly one successful attempt at the placeholder fee; some retries; some abandoned.
* Admin queue: FIFO with finite daily capacity -> turnaround time (TAT) EMERGES from load
  (seasonal peaks, weekends/holidays, staff-leave windows) instead of being drawn from a formula.
* Manual review: a latent logistic model over the features an admin could see; reviewed
  applications take longer and are rejected more often.
* Anomalies: duplicates, frequency bursts, rapid payment retries and amount mismatches are injected
  at KNOWN rates, plus benign look-alikes (legit bundles, re-applications, single payment retries)
  so the problem is not trivially separable.

The returned `application_labels` / `transaction_labels` tables are the ANSWER KEY. They are
written to data/labels/ and must never be used as model features.
"""
from __future__ import annotations

from collections import deque
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from . import config as C
from .features import HistoryTracker, is_working_day, to_epoch_seconds

_FEE_MONTH0 = (2022, 9)  # first month of the fee-history matrix (12 months before the default start)


# --------------------------------------------------------------------------- students
def _make_students(cfg: C.SimConfig, rng: np.random.Generator) -> dict:
    n = cfg.n_students
    adm = rng.choice(np.arange(2018, 2026), size=n)
    codes = list(C.DEPARTMENTS)
    shares = np.array([C.DEPARTMENTS[c][1] for c in codes])
    dept = rng.choice(len(codes), size=n, p=shares / shares.sum())
    ability = np.clip(rng.normal(7.6, 0.85, n), 5.0, 9.7)
    fee_prop = rng.beta(1.2, 12.0, n)
    cgpa_noise = rng.normal(0.0, 0.15, (n, 9))
    lam = np.maximum(0.02, (7.4 - ability) * 0.9)
    sem_grid = np.maximum(np.arange(9), 1)
    backlog_sem = rng.poisson(lam[:, None] * sem_grid[None, :] / 8.0)
    backlog_alumni = rng.binomial(backlog_sem[:, 8], 0.35)
    n_months = (cfg.end.year - _FEE_MONTH0[0]) * 12 + cfg.end.month - _FEE_MONTH0[1] + 4
    p_due = 0.03 + 0.55 * fee_prop
    fee_due = rng.random((n, n_months)) < p_due[:, None]
    fee_cum = np.concatenate([np.zeros((n, 1), dtype=int), np.cumsum(fee_due, axis=1)], axis=1)

    frame = pd.DataFrame({"adm": adm, "dept": [codes[i] for i in dept]})
    frame["idx"] = frame.groupby(["adm", "dept"]).cumcount() + 1
    usn = [f"SYN{a % 100:02d}{d}{i:04d}" for a, d, i in zip(frame.adm, frame.dept, frame.idx)]
    return {
        "n": n, "adm": adm, "dept": frame["dept"].to_numpy(), "usn": usn, "ability": ability,
        "cgpa_noise": cgpa_noise, "backlog_sem": backlog_sem, "backlog_alumni": backlog_alumni,
        "fee_due": fee_due, "fee_cum": fee_cum,
    }


def _state(st: dict, sid: np.ndarray, year: np.ndarray, month: np.ndarray) -> dict:
    """Vectorised academic/fee snapshot of students `sid` at (year, month)."""
    m = (year - st["adm"][sid]) * 12 + month - 8
    sem = np.clip(m // 6 + 1, 1, 8)
    graduated = m >= 46
    cgpa = np.clip(st["ability"][sid] + st["cgpa_noise"][sid, sem], 4.5, 9.95).round(2)
    backlogs = np.where(graduated, st["backlog_alumni"][sid], st["backlog_sem"][sid, sem])
    mi = (year - _FEE_MONTH0[0]) * 12 + month - _FEE_MONTH0[1]
    lo = np.maximum(mi - 12, 0)
    past = st["fee_cum"][sid, mi] - st["fee_cum"][sid, lo]
    return {"m": m, "sem": sem, "graduated": graduated, "cgpa": cgpa, "backlogs": backlogs,
            "fee_due": st["fee_due"][sid, mi], "past": past}


# --------------------------------------------------------------------------- arrivals
def _pool_weights(doc: str, enrolled, grad, sem, m) -> np.ndarray:
    if doc == "TRANSCRIPT":
        return (np.where(grad, 1.5, 0) + np.where(enrolled & (sem >= 7), 3.0, 0)
                + np.where(enrolled & (sem == 6), 1.0, 0))
    if doc == "MIGRATION_CERTIFICATE":
        return (np.where(grad, 3.0, 0) + np.where(enrolled & (sem == 8), 1.0, 0)
                + np.where(enrolled & (sem <= 4), 0.15, 0))
    if doc == "DUPLICATE_GRADE_CARD":
        return np.where(enrolled & (sem >= 2), 1.0, 0) + np.where(grad, 1.0, 0)
    return np.where(grad & (m <= 58), 3.0, 0) + np.where(enrolled & (sem == 8), 1.0, 0)


def _base_arrivals(cfg: C.SimConfig, st: dict, rng: np.random.Generator) -> pd.DataFrame:
    n, adm = st["n"], st["adm"]
    hour_p = np.array(C.HOUR_WEIGHTS, dtype=float)
    hour_p /= hour_p.sum()
    sids, docs, stamps = [], [], []
    d = cfg.start
    while d <= cfg.end:
        m = (d.year - adm) * 12 + d.month - 8
        sem = np.clip(m // 6 + 1, 1, 8)
        enrolled, grad = (m >= 0) & (m <= 45), (m >= 46) & (m <= 70)
        years = (d - cfg.start).days / 365.0
        midnight = datetime(d.year, d.month, d.day)
        for doc in C.DOCUMENT_TYPES:
            lam = (C.BASE_DAILY_RATE[doc] * C.SEASON[doc][d.month - 1]
                   * C.DAY_OF_WEEK_FACTOR[d.weekday()] * (1 + C.ANNUAL_GROWTH * years)
                   * np.exp(rng.normal(0.0, C.DAILY_SHOCK_SIGMA)))
            k = rng.poisson(lam)
            w = _pool_weights(doc, enrolled, grad, sem, m)
            if k == 0 or w.sum() <= 0:
                continue
            chosen = rng.choice(n, size=k, p=w / w.sum())
            hours = rng.choice(24, size=k, p=hour_p)
            secs = rng.integers(0, 3600, size=k)
            for sid, h, s in zip(chosen, hours, secs):
                sids.append(int(sid))
                docs.append(doc)
                stamps.append(midnight + timedelta(hours=int(h), seconds=int(s)))
        d += timedelta(days=1)
    return pd.DataFrame({"sid": sids, "document_type": docs, "submitted_at": pd.to_datetime(stamps)})


def _draw_documents(k: int, rng: np.random.Generator, p_has: float) -> np.ndarray:
    has = rng.random(k) < p_has
    return np.where(has, np.minimum(1 + rng.poisson(0.7, k), 5), 0)


def _finalize(df: pd.DataFrame, st: dict, rng: np.random.Generator, kind: str) -> pd.DataFrame:
    """Attach the student snapshot, uploads, OCR outcome and rule-based eligibility to new events."""
    df = df.copy()
    k = len(df)
    if k == 0:
        return df
    ts = pd.DatetimeIndex(df["submitted_at"])
    sid = df["sid"].to_numpy()
    s = _state(st, sid, ts.year.to_numpy(), ts.month.to_numpy())
    df["semester_at_submission"] = np.where(s["graduated"], 8, s["sem"])
    df["is_alumni"] = s["graduated"].astype(int)
    df["cgpa_at_submission"] = s["cgpa"]
    df["backlog_count_at_submission"] = s["backlogs"]
    df["fee_status_at_submission"] = np.where(s["fee_due"], "DUE", "CLEAR")
    df["past_fee_delays_12m"] = s["past"]

    if "num_documents" not in df:
        df["num_documents"] = _draw_documents(k, rng, C.P_HAS_DOCUMENTS)
    nd = df["num_documents"].to_numpy()
    status = np.where(nd == 0, "NONE", np.where(rng.random(k) < C.P_OCR_FAILED, "FAILED", "SUCCESS"))
    no_cgpa = (status == "SUCCESS") & (rng.random(k) < C.P_OCR_NO_CGPA_FOUND)
    mismatch = (status == "SUCCESS") & ~no_cgpa & (rng.random(k) < C.P_OCR_MISMATCH)
    delta = rng.uniform(0.3, 1.5, k) * rng.choice([-1.0, 1.0], k)
    detected = np.where(mismatch, np.clip(s["cgpa"] + delta, 0.0, 10.0), s["cgpa"])
    detected = np.where((status != "SUCCESS") | no_cgpa, np.nan, detected).round(2)
    df["ocr_status"] = status
    df["ocr_detected_cgpa"] = detected

    zero_backlog_doc = df["document_type"].isin(C.ZERO_BACKLOG_REQUIRED_FOR).to_numpy()
    eligible = (~s["fee_due"]) & (nd >= 1) & ~(zero_backlog_doc & (s["backlogs"] > 0))
    df["eligibility_result"] = np.where(eligible, "ELIGIBLE", "NOT_ELIGIBLE")
    df["kind"] = kind
    return df


def _cutoff(cfg: C.SimConfig) -> datetime:
    return datetime(cfg.end.year, cfg.end.month, cfg.end.day, 23, 59, 59)


def _build_applications(cfg: C.SimConfig, st: dict, rng: np.random.Generator) -> pd.DataFrame:
    base = _finalize(_base_arrivals(cfg, st, rng), st, rng, "NORMAL")

    # Benign look-alike 1: alumni sometimes request several document types at once.
    extra = []
    alumni_rows = base.index[base["is_alumni"] == 1]
    for i in alumni_rows[rng.random(len(alumni_rows)) < C.P_ALUMNI_BUNDLE]:
        others = [t for t in C.DOCUMENT_TYPES if t != base.at[i, "document_type"]]
        for doc in rng.choice(others, size=int(rng.integers(1, 3)), replace=False):
            extra.append({"sid": int(base.at[i, "sid"]), "document_type": str(doc),
                          "submitted_at": base.at[i, "submitted_at"] + timedelta(minutes=int(rng.integers(0, 180)))})
    bundles = _finalize(pd.DataFrame(extra, columns=["sid", "document_type", "submitted_at"]), st, rng, "NORMAL")
    first = pd.concat([base, bundles], ignore_index=True)

    # Benign look-alike 2: a student whose request was rejected by the rules often fixes it and re-applies.
    bad = first[first["eligibility_result"] == "NOT_ELIGIBLE"]
    bad = bad[rng.random(len(bad)) < C.P_REAPPLY_AFTER_INELIGIBLE]
    re_df = pd.DataFrame({
        "sid": bad["sid"].to_numpy(), "document_type": bad["document_type"].to_numpy(),
        "submitted_at": bad["submitted_at"] + pd.to_timedelta(rng.uniform(1, 5, len(bad)), unit="D"),
        "num_documents": _draw_documents(len(bad), rng, 0.97),
    })
    reapply = _finalize(re_df, st, rng, "NORMAL")

    pool = pd.concat([first, reapply], ignore_index=True)

    # Injected anomaly 1: duplicate request (same student + same document type, minutes/hours later).
    ok = pool[pool["eligibility_result"] == "ELIGIBLE"]
    src = ok[rng.random(len(ok)) < C.P_DUPLICATE_APPLICATION]
    delay = np.clip(rng.exponential(6 * 3600, len(src)), 300, 48 * 3600)
    dup_df = pd.DataFrame({
        "sid": src["sid"].to_numpy(), "document_type": src["document_type"].to_numpy(),
        "submitted_at": src["submitted_at"] + pd.to_timedelta(delay, unit="s"),
        "num_documents": src["num_documents"].to_numpy(),
    })
    dups = _finalize(dup_df, st, rng, "DUPLICATE_REQUEST")

    # Injected anomaly 2: frequency burst (one student, 6-12 applications within 36 hours).
    n_days = (cfg.end - cfg.start).days + 1
    n_bursts = max(1, int(round(C.BURSTS_PER_YEAR * n_days / 365.0)))
    burst_rows = []
    for _ in range(n_bursts):
        day = cfg.start + timedelta(days=int(rng.integers(0, max(1, n_days - 3))))
        start = datetime(day.year, day.month, day.day) + timedelta(hours=float(rng.uniform(8, 20)))
        m = (day.year - st["adm"]) * 12 + day.month - 8
        candidates = np.where((m >= 0) & (m <= 70))[0]
        sid = int(rng.choice(candidates))
        k = int(rng.integers(6, 13))
        for off, doc, nd in zip(rng.uniform(0, 36 * 3600, k), rng.choice(C.DOCUMENT_TYPES, k),
                                _draw_documents(k, rng, 0.9)):
            burst_rows.append({"sid": sid, "document_type": str(doc), "num_documents": int(nd),
                               "submitted_at": start + timedelta(seconds=float(off))})
    bursts = _finalize(pd.DataFrame(burst_rows, columns=["sid", "document_type", "submitted_at", "num_documents"]),
                       st, rng, "FREQUENCY_BURST")

    apps = pd.concat([pool, dups, bursts], ignore_index=True)
    apps["submitted_at"] = pd.to_datetime(apps["submitted_at"]).dt.floor("s")
    apps = apps[apps["submitted_at"] <= _cutoff(cfg)]
    apps = apps.sort_values(["submitted_at", "sid", "document_type"], kind="stable").reset_index(drop=True)
    apps["application_id"] = np.arange(1, len(apps) + 1)
    return apps


# --------------------------------------------------------------------------- manual-review label
_DOC_RISK = {"TRANSCRIPT": 0.0, "MIGRATION_CERTIFICATE": 0.5,
             "DUPLICATE_GRADE_CARD": 0.3, "PROVISIONAL_DEGREE_CERTIFICATE": 0.4}


def _draw_review_labels(apps: pd.DataFrame, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """Latent model of 'this application needed manual attention' for ELIGIBLE applications.

    It uses only things an admin could see (academics, fee history, OCR outcome, past applications)
    plus unobserved noise, so even a perfect model cannot reach AUC 1.0. Returns (label, true_prob);
    both are NaN for applications that failed the rule-based eligibility check.
    """
    n = len(apps)
    cgpa = apps["cgpa_at_submission"].to_numpy()
    back = apps["backlog_count_at_submission"].to_numpy()
    past = apps["past_fee_delays_12m"].to_numpy()
    det = apps["ocr_detected_cgpa"].to_numpy()
    ocr = apps["ocr_status"].to_numpy()
    mism = (ocr == "SUCCESS") & ~np.isnan(det) & (np.abs(np.nan_to_num(det) - cgpa) > 0.05)
    z = (C.RISK_INTERCEPT + 0.75 * (back >= 1) + 0.30 * np.minimum(back, 5)
         + 0.55 * np.maximum(0.0, 7.0 - cgpa) + 0.45 * np.minimum(past, 4)
         + apps["document_type"].map(_DOC_RISK).to_numpy() + 1.6 * mism + 0.9 * (ocr == "FAILED")
         + 0.5 * apps["is_alumni"].to_numpy() + 0.6 * ((cgpa < 6.5) & (past >= 1))
         + rng.normal(0.0, 0.7, n))
    tracker = HistoryTracker()
    t = to_epoch_seconds(apps["submitted_at"])
    sid = apps["sid"].to_numpy()
    eligible = apps["eligibility_result"].to_numpy() == "ELIGIBLE"
    label = np.full(n, np.nan)
    prob = np.full(n, np.nan)
    for i in range(n):
        y = 0
        if eligible[i]:
            zi = (z[i] + 0.9 * min(tracker.prior_reviews_lagged(sid[i], t[i]), 3)
                  + 0.15 * min(tracker.prior_apps(sid[i], t[i]), 6))
            prob[i] = 1.0 / (1.0 + np.exp(-zi))
            y = int(rng.random() < prob[i])
            label[i] = y
        tracker.add(sid[i], t[i], y)
    return label, prob


# --------------------------------------------------------------------------- payments
def _payments(apps: pd.DataFrame, cfg: C.SimConfig, rng: np.random.Generator) -> pd.DataFrame:
    cutoff = _cutoff(cfg)
    n = len(apps)
    ua, ub, uc, up = rng.random(n), rng.random(n), rng.random(n), rng.random(n)
    fees = C.FEE_BY_DOCUMENT_TYPE
    rows = []
    for i in np.where(apps["eligibility_result"].to_numpy() == "ELIGIBLE")[0]:
        app_id = int(apps.at[i, "application_id"])
        doc = apps.at[i, "document_type"]
        fee = fees[doc]
        t0 = apps.at[i, "submitted_at"].to_pydatetime() + timedelta(seconds=max(60.0, rng.exponential(1200.0)))
        attempts: list[tuple[datetime, str, float, str]] = []  # (time, status, amount, txn_anomaly)
        if ua[i] < C.P_ABANDON_PAYMENT:
            attempts.append((t0, "PENDING" if rng.random() < 0.6 else "FAILED", fee, "NONE"))
        elif ub[i] < C.P_RAPID_RETRY_BURST:
            k = int(rng.integers(5, 10))
            offsets = np.sort(rng.uniform(0, rng.uniform(60, 300), k))
            ok_last = rng.random() < 0.6
            for j, off in enumerate(offsets):
                status = "SUCCESS" if (j == k - 1 and ok_last) else "FAILED"
                attempts.append((t0 + timedelta(seconds=float(off)), status, fee, "RAPID_RETRIES"))
        else:
            r = up[i]
            if r < C.P_PAY_RETRY_TWICE:
                seq = ["FAILED", "FAILED", "SUCCESS"]
            elif r < C.P_PAY_RETRY_TWICE + C.P_PAY_RETRY_ONCE:
                seq = ["FAILED", "SUCCESS"]
            else:
                seq = ["SUCCESS"]
            t = t0
            for status in seq:
                attempts.append((t, status, fee, "NONE"))
                t = t + timedelta(seconds=float(rng.uniform(60, 1200)))
            if uc[i] < C.P_AMOUNT_MISMATCH:
                tt, status, _, _ = attempts[-1]
                kind = rng.integers(0, 3)
                if kind == 0:
                    amount = round(fee * float(rng.uniform(0.2, 0.9)), 2)
                elif kind == 1:
                    amount = round(fee * float(rng.choice([1.5, 2.0, 3.0])), 2)
                else:
                    amount = float(rng.choice([v for v in fees.values() if v != fee]))
                attempts[-1] = (tt, status, amount, "AMOUNT_MISMATCH")
        for tt, status, amount, anomaly in attempts:
            if tt <= cutoff:
                rows.append((app_id, round(float(amount), 2), status, tt, anomaly))
    txn = pd.DataFrame(rows, columns=["application_id", "amount", "payment_status", "transacted_at", "txn_anomaly"])
    txn["transacted_at"] = pd.to_datetime(txn["transacted_at"]).dt.floor("s")
    txn = txn.sort_values(["transacted_at", "application_id"], kind="stable").reset_index(drop=True)
    txn.insert(0, "transaction_id", np.arange(1, len(txn) + 1))
    return txn


# --------------------------------------------------------------------------- admin queue
def _leave_dates(cfg: C.SimConfig, rng: np.random.Generator) -> set:
    horizon = (cfg.end - cfg.start).days + 260
    out = set()
    for year_block in range(int(np.ceil(horizon / 365.0))):
        for _ in range(C.LEAVE_WINDOWS_PER_YEAR):
            s = cfg.start + timedelta(days=year_block * 365 + int(rng.integers(0, 365)))
            for k in range(C.LEAVE_LENGTH_DAYS):
                out.add(s + timedelta(days=k))
    return out


def _simulate_queue(ready: list[datetime], units: np.ndarray, cfg: C.SimConfig,
                    rng: np.random.Generator) -> list[datetime | None]:
    """FIFO queue with finite daily capacity. Returns the decision time of every item."""
    n = len(ready)
    finish: list[datetime | None] = [None] * n
    if n == 0:
        return finish
    order = sorted(range(n), key=lambda j: ready[j])
    leave = _leave_dates(cfg, rng)
    queue: deque[int] = deque()
    ptr = 0
    d = ready[order[0]].date()
    limit = cfg.end + timedelta(days=260)
    while d <= limit and (ptr < n or queue):
        if is_working_day(d):
            noon = datetime(d.year, d.month, d.day, 12)
            while ptr < n and ready[order[ptr]] <= noon:
                queue.append(order[ptr])
                ptr += 1
            cap = max(6.0, float(rng.normal(C.CAPACITY_MEAN, C.CAPACITY_SD)))
            if d in leave:
                cap *= C.LEAVE_CAPACITY_FACTOR
            used = 0.0
            while queue and used < cap:
                j = queue.popleft()
                used += float(units[j])
                frac = min(used / cap, 1.0)
                t = datetime(d.year, d.month, d.day) + timedelta(hours=C.WORKDAY_START_HOUR + frac * C.WORKDAY_HOURS)
                finish[j] = max(t, ready[j] + timedelta(minutes=30))
        d += timedelta(days=1)
    return finish


# --------------------------------------------------------------------------- orchestration
def simulate(cfg: C.SimConfig) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(cfg.seed)
    st = _make_students(cfg, rng)
    apps = _build_applications(cfg, st, rng)
    label, prob = _draw_review_labels(apps, rng)
    apps["needs_manual_review"] = label
    apps["true_review_prob"] = prob
    txn = _payments(apps, cfg, rng)
    cutoff = _cutoff(cfg)

    success = txn[txn["payment_status"] == "SUCCESS"].groupby("application_id")["transacted_at"].min()
    has_txn = set(txn["application_id"])
    aid = apps["application_id"].to_numpy()
    paid_at = pd.Series(aid).map(success)
    in_queue = paid_at.notna().to_numpy()
    review = np.nan_to_num(apps["needs_manual_review"].to_numpy()) == 1
    reject = rng.random(len(apps)) < (C.REJECT_PROB + (C.REJECT_PROB_IF_REVIEW - C.REJECT_PROB) * review)

    idx = np.where(in_queue)[0]
    hold = np.where(review[idx], rng.uniform(*C.REVIEW_HOLD_HOURS, len(idx)), 0.0)
    ready = [paid_at.iloc[i].to_pydatetime() + timedelta(hours=float(h)) for i, h in zip(idx, hold)]
    units = np.array([C.WORK_UNITS[apps.at[i, "document_type"]] * (C.REVIEW_WORK_MULTIPLIER if review[i] else 1.0)
                      for i in idx])
    finish = _simulate_queue(ready, units, cfg, rng)

    decided = pd.Series([pd.NaT] * len(apps), dtype="datetime64[ns]")
    for i, f in zip(idx, finish):
        if f is not None and f <= cutoff:
            decided.iloc[i] = pd.Timestamp(f).floor("s")
    status = np.full(len(apps), "NOT_ELIGIBLE", dtype=object)
    elig = apps["eligibility_result"].to_numpy() == "ELIGIBLE"
    status[elig] = "ELIGIBLE"
    status[elig & np.isin(aid, list(has_txn))] = "PAYMENT_PENDING"
    status[in_queue] = "UNDER_REVIEW"
    done = decided.notna().to_numpy()
    status[done & ~reject] = "VERIFIED"
    status[done & reject] = "REJECTED"

    applications = pd.DataFrame({
        "application_id": aid,
        "student_id": apps["sid"].to_numpy() + 1,
        "document_type": apps["document_type"],
        "submitted_at": apps["submitted_at"],
        "semester_at_submission": apps["semester_at_submission"],
        "is_alumni": apps["is_alumni"],
        "cgpa_at_submission": apps["cgpa_at_submission"],
        "backlog_count_at_submission": apps["backlog_count_at_submission"],
        "fee_status_at_submission": apps["fee_status_at_submission"],
        "past_fee_delays_12m": apps["past_fee_delays_12m"],
        "num_documents": apps["num_documents"],
        "ocr_status": apps["ocr_status"],
        "ocr_detected_cgpa": apps["ocr_detected_cgpa"],
        "eligibility_result": apps["eligibility_result"],
        "status": status,
        "decided_at": decided,
    })
    students = pd.DataFrame({
        "student_id": np.arange(1, st["n"] + 1), "usn": st["usn"], "department": st["dept"],
        "admission_year": st["adm"], "graduation_year": st["adm"] + 4,
    })
    application_labels = pd.DataFrame({
        "application_id": aid,
        "needs_manual_review": pd.array(np.where(np.isnan(label), -1, label).astype(int), dtype="Int64"),
        "sim_true_review_probability": np.round(prob, 6),
        "sim_anomaly_type": apps["kind"].replace({"NORMAL": "NONE"}).to_numpy(),
    })
    application_labels.loc[application_labels["needs_manual_review"] == -1, "needs_manual_review"] = pd.NA

    app_kind = dict(zip(aid, application_labels["sim_anomaly_type"]))
    app_level = txn["application_id"].map(app_kind)
    anomaly_type = np.where(txn["txn_anomaly"] != "NONE", txn["txn_anomaly"], app_level)
    transaction_labels = pd.DataFrame({
        "transaction_id": txn["transaction_id"],
        "is_anomaly": (anomaly_type != "NONE").astype(int),
        "anomaly_type": anomaly_type,
    })
    transactions = txn.drop(columns=["txn_anomaly"])
    return {"students": students, "applications": applications, "transactions": transactions,
            "application_labels": application_labels, "transaction_labels": transaction_labels}
