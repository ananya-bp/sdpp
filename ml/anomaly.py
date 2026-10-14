"""Phase 5.3 - Payment-transaction anomaly detection (Isolation Forest, unsupervised).

Decision support only: it flags a payment attempt as NORMAL or ANOMALOUS for administrator review. It never blocks
or rejects anything and it does NOT know *which kind* of anomaly it saw (no type is returned).
The `label_*` columns are used ONLY for evaluation / threshold choice, never as model inputs.
Data is SIMULATED (docs/DATA_DICTIONARY.md).

Train:    python -m ml.anomaly            (from project root)
Predict:  from ml.anomaly import predict_anomaly
"""
from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.metrics import (average_precision_score, confusion_matrix, f1_score, precision_score,
                             recall_score, roc_auc_score)

from . import config as C

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "processed" / "anomaly_transactions.csv"
MODEL_DIR = ROOT / "models"
MODEL_PATH = MODEL_DIR / "anomaly_isolation_forest.joblib"
METRICS_PATH = MODEL_DIR / "anomaly_metrics.json"

LABEL, LABEL_TYPE = "label_is_anomaly", "label_anomaly_type"
RAW_NUMERIC = ["amount_ratio", "attempt_index", "failed_attempts_before", "seconds_since_prev_attempt",
           "student_txns_prior_24h", "student_other_apps_24h", "student_other_apps_7d",
           "same_doc_other_apps_7d", "same_doc_other_paid_apps_7d"]
STATUSES = ["FAILED", "PENDING", "SUCCESS"]
# amount_ratio is model-input as amount_deviation = |amount_ratio - 1| (chosen on validation: AUC 0.9385 -> 0.9470).
FEATURES = ["amount_deviation"] + RAW_NUMERIC[1:] + [f"ps_{s}" for s in STATUSES]  # + payment_status one-hot (own outcome: legitimate)
AMOUNT_RULE_TOL = 0.005  # rule layer: |amount/expected_fee - 1| > tol  => AMOUNT_MISMATCH (deterministic, not ML)

EXCLUDED = {
    LABEL: "evaluation label - never a feature", LABEL_TYPE: "evaluation label - never a feature",
    "split": "split label", "transaction_id": "identifier", "application_id": "identifier", "student_id": "identifier",
    "transacted_at": "raw timestamp (used only for the chronological split)",
    "document_type": "only sets the fee; the anomaly signal is captured by amount_ratio",
    "amount": "redundant with amount_ratio (and depends on document type)", "expected_amount": "redundant with amount_ratio",
    "amount_ratio": "not used raw: fed to the model as amount_deviation = |amount_ratio - 1|",
    "minutes_since_submission": "no gain on validation (feature-set comparison)",
    "hour": "no gain on validation (feature-set comparison)", "dow": "no gain on validation (feature-set comparison)",
    "payment_status": "replaced by its one-hot columns ps_*",
}
PARAMS = dict(n_estimators=200, max_samples=1024, contamination="auto", random_state=42, n_jobs=1)
THRESHOLD_GRID_PCT = [1, 1.5, 2, 2.5, 3, 3.5, 4, 5, 6, 8, 10]  # candidate "flag top q% of TRAIN scores" cut-offs


def make_matrix(df: pd.DataFrame) -> pd.DataFrame:
    X = df[RAW_NUMERIC].astype(float).copy()
    X["amount_deviation"] = (X.pop("amount_ratio") - 1.0).abs()
    for s in STATUSES:
        X[f"ps_{s}"] = (df["payment_status"] == s).astype(float)
    return X[FEATURES]


def amount_rule(amount_ratio) -> np.ndarray:
    """Deterministic rule layer (NOT part of the Isolation Forest): payment amount differs from the fee schedule."""
    return (np.abs(np.asarray(amount_ratio, dtype=float) - 1.0) > AMOUNT_RULE_TOL)


def _score(model, X) -> np.ndarray:
    """Higher = more anomalous (= -sklearn score_samples; roughly 0.3 normal ... 0.8+ very unusual)."""
    return -model.score_samples(X)


def _cls(y, s, yhat) -> dict:
    yhat = np.asarray(yhat).astype(int)
    tn, fp, fn, tp = confusion_matrix(y, yhat, labels=[0, 1]).ravel()
    return {"n": int(len(y)), "anomalies": int(y.sum()), "flagged": int(yhat.sum()),
            "tp": int(tp), "fp": int(fp), "fn": int(fn), "tn": int(tn),
            "precision": round(precision_score(y, yhat, zero_division=0), 4), "recall": round(recall_score(y, yhat), 4),
            "f1": round(f1_score(y, yhat), 4), "roc_auc": round(roc_auc_score(y, s), 4),
            "avg_precision": round(average_precision_score(y, s), 4), "flag_rate": round(float(yhat.mean()), 4)}


def _by_type(df, flag) -> dict:
    d = df.assign(flag=np.asarray(flag).astype(int))
    out = {}
    for t, g in d.groupby(LABEL_TYPE):
        if t == "NONE":
            continue
        out[t] = {"injected": int(len(g)), "detected": int(g.flag.sum()), "missed": int(len(g) - g.flag.sum()),
                  "recall": round(float(g.flag.mean()), 4)}
    rr = d[d[LABEL_TYPE] == "RAPID_RETRIES"]
    for name, g in (("first_attempt (attempt_index=1)", rr[rr.attempt_index == 1]), ("later_attempts (>1)", rr[rr.attempt_index > 1])):
        out.setdefault("RAPID_RETRIES_breakdown", {})[name] = {"injected": int(len(g)), "detected": int(g.flag.sum()),
                                                                "recall": round(float(g.flag.mean()), 4) if len(g) else None}
    flagged = d[d.flag == 1]
    out["flagged_rows_by_true_type"] = {k: int(v) for k, v in flagged[LABEL_TYPE].value_counts().items()}
    nm = d[d[LABEL_TYPE] == "NONE"]
    out["false_positive_rate_normal_rows"] = {
        "all_normal": round(float(nm.flag.mean()), 4),
        "normal_first_attempts": round(float(nm[nm.attempt_index == 1].flag.mean()), 4),
        "normal_retries (benign look-alikes, attempt_index>1)": round(float(nm[nm.attempt_index > 1].flag.mean()), 4)}
    return out


def train() -> dict:
    df = pd.read_csv(DATA)
    assert not set(FEATURES) & set(EXCLUDED), "feature list overlaps excluded/label columns"
    assert not [f for f in FEATURES if f.startswith("label_")]
    known = set(RAW_NUMERIC) | set(EXCLUDED)
    assert set(df.columns) <= known, f"unclassified columns: {set(df.columns) - known}"
    s = {k: df[df.split == k].reset_index(drop=True) for k in ("train", "valid", "test")}
    ref = json.loads((ROOT / "data" / "dataset_summary.json").read_text())["anomaly_transactions"]

    # 1) Unsupervised fit on TRAIN features only (labels never passed to fit).
    model = IsolationForest(**PARAMS).fit(make_matrix(s["train"]))
    tr_s = _score(model, make_matrix(s["train"]))
    va_s = _score(model, make_matrix(s["valid"]))

    # 2) Threshold: candidates are "flag the top q% of TRAIN scores"; pick the q with best F1 on VALID of the deployed
    #    flag (IF flag OR amount rule). This is the only place labels influence a decision; test is not used here.
    rule = {k: amount_rule(s[k]["amount_ratio"]) for k in s}
    cands = {q: float(np.percentile(tr_s, 100 - q)) for q in THRESHOLD_GRID_PCT}
    f1s = {q: f1_score(s["valid"][LABEL], ((va_s >= t) | rule["valid"]).astype(int)) for q, t in cands.items()}
    q_best = max(f1s, key=f1s.get)
    thr = cands[q_best]

    out = {"params": PARAMS, "features": FEATURES, "excluded": EXCLUDED,
           "threshold": {"score_threshold": round(thr, 6), "rule": f"flag top {q_best}% of train scores (chosen by best valid F1 of IF+rule)",
                         "valid_f1_by_q_pct": {str(q): round(v, 4) for q, v in f1s.items()}},
           "amount_rule_tolerance": AMOUNT_RULE_TOL,
           "phase4_reference": {"overall_rate": ref["anomaly_rate"], "best_single_feature_auc": {
               k: v["auc"] for k, v in ref["separability_best_single_feature"].items()}}}
    te_s = _score(model, make_matrix(s["test"]))  # TEST scored once, after every decision above
    scores = {"train": tr_s, "valid": va_s, "test": te_s}
    for name in ("train", "valid", "test"):
        if_flag = scores[name] >= thr
        both = if_flag | rule[name]
        out[name] = {"isolation_forest_only": {"overall": _cls(s[name][LABEL], scores[name], if_flag), "by_type": _by_type(s[name], if_flag)},
                     "if_plus_amount_rule": {"overall": _cls(s[name][LABEL], scores[name], both), "by_type": _by_type(s[name], both)}}

    MODEL_DIR.mkdir(exist_ok=True)
    joblib.dump({"model": model, "features": FEATURES, "threshold": thr, "fees": dict(C.FEE_BY_DOCUMENT_TYPE)}, MODEL_PATH, compress=3)
    METRICS_PATH.write_text(json.dumps(out, indent=2))
    return out


# ------------------------------- prediction -------------------------------
_ART = None


def _load():
    global _ART
    if _ART is None:
        if not MODEL_PATH.exists():
            raise FileNotFoundError(f"{MODEL_PATH} not found - run `python -m ml.anomaly` first")
        _ART = joblib.load(MODEL_PATH)
    return _ART


def predict_anomaly(*, document_type: str, amount: float, payment_status: str, attempt_index: int = 1,
                    failed_attempts_before: int = 0, seconds_since_prev_attempt: float = 86400.0,
                    student_txns_prior_24h: int = 0, student_other_apps_24h: int = 0, student_other_apps_7d: int = 0,
                    same_doc_other_apps_7d: int = 0, same_doc_other_paid_apps_7d: int = 0) -> dict:
    """Score ONE payment attempt from what is known at that moment.

    Returns {"anomaly_score": float (higher = more unusual), "threshold": float, "model_flagged": bool (Isolation Forest),
             "rule_flags": ["AMOUNT_MISMATCH"] if the amount differs from the fee schedule (deterministic rule, not ML),
             "is_anomaly": model_flagged OR rule_flags, "label": "NORMAL" | "ANOMALOUS"}. Decision support for the
    administrator; the Isolation Forest itself says nothing about which kind of anomaly it is. Conventions from the dataset: first attempt => seconds_since_prev_attempt = 86400.
    """
    art = _load()
    if document_type not in art["fees"]:
        raise ValueError(f"unknown document_type {document_type!r}")
    if payment_status not in STATUSES:
        raise ValueError(f"payment_status must be one of {STATUSES}")
    if amount < 0 or attempt_index < 1 or seconds_since_prev_attempt < 0:
        raise ValueError("amount >= 0, attempt_index >= 1 and seconds_since_prev_attempt >= 0 are required")
    for k, v in dict(failed_attempts_before=failed_attempts_before, student_txns_prior_24h=student_txns_prior_24h,
                     student_other_apps_24h=student_other_apps_24h, student_other_apps_7d=student_other_apps_7d,
                     same_doc_other_apps_7d=same_doc_other_apps_7d, same_doc_other_paid_apps_7d=same_doc_other_paid_apps_7d).items():
        if v < 0:
            raise ValueError(f"{k} must be >= 0")
    row = pd.DataFrame([{"amount_ratio": round(amount / art["fees"][document_type], 4), "attempt_index": attempt_index,
                         "failed_attempts_before": failed_attempts_before, "seconds_since_prev_attempt": seconds_since_prev_attempt,
                         "student_txns_prior_24h": student_txns_prior_24h, "student_other_apps_24h": student_other_apps_24h,
                         "student_other_apps_7d": student_other_apps_7d, "same_doc_other_apps_7d": same_doc_other_apps_7d,
                         "same_doc_other_paid_apps_7d": same_doc_other_paid_apps_7d, "payment_status": payment_status}])
    score = float(_score(art["model"], make_matrix(row))[0])
    if_flag = bool(score >= art["threshold"])
    rule_flags = ["AMOUNT_MISMATCH"] if bool(amount_rule(row["amount_ratio"])[0]) else []  # deterministic rule layer
    flag = if_flag or bool(rule_flags)
    return {"anomaly_score": round(score, 6), "threshold": round(float(art["threshold"]), 6),
            "model_flagged": if_flag, "rule_flags": rule_flags,
            "is_anomaly": flag, "label": "ANOMALOUS" if flag else "NORMAL"}


if __name__ == "__main__":
    print(json.dumps(train(), indent=2))
