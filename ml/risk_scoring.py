"""Phase 5.2 - Eligibility RISK scoring (Logistic Regression).

NOT an eligibility decision. Rule-based eligibility (backend/app/services/eligibility.py) still alone decides
ELIGIBLE / NOT_ELIGIBLE. This model outputs a probability in [0, 1] that an (already eligible) application
will need MANUAL REVIEW. The administrator always makes the final call (SDP_BUILD_GUIDE.md section 1.4).

Data is SIMULATED (docs/DATA_DICTIONARY.md).
Train:    python -m ml.risk_scoring          (from project root)
Predict:  from ml.risk_scoring import predict_risk
"""
from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (accuracy_score, brier_score_loss, f1_score, precision_score,
                             recall_score, roc_auc_score)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder, StandardScaler

from . import config as C

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "processed" / "risk_scoring.csv"
SUMMARY = ROOT / "data" / "dataset_summary.json"
MODEL_DIR = ROOT / "models"
MODEL_PATH = MODEL_DIR / "risk_scoring_logistic.joblib"
METRICS_PATH = MODEL_DIR / "risk_scoring_metrics.json"

TARGET = "label_needs_manual_review"
CAT = ["document_type", "department"]
COUNT = ["backlog_count", "past_fee_delays_12m", "prior_apps_count", "prior_review_count_lagged"]  # log1p'd
PLAIN = ["semester", "is_alumni", "cgpa", "num_documents", "ocr_failed", "ocr_cgpa_found", "ocr_cgpa_mismatch"]
FEATURES = CAT + COUNT + PLAIN

# Columns in risk_scoring.csv that must NEVER be model inputs, and why.
EXCLUDED = {
    TARGET: "the label itself",
    "application_id": "identifier", "student_id": "identifier (would memorise students)",
    "submitted_at": "raw timestamp / used only for the chronological split",
    "split": "split label",
}
DOC_TYPES = sorted(C.FEE_BY_DOCUMENT_TYPE)
DEPT_CODES = sorted(C.DEPARTMENTS)
_DEPT_BY_NAME = {name: code for code, (name, _) in C.DEPARTMENTS.items()}


def _build(C_reg: float, log_counts: bool) -> Pipeline:
    if log_counts:
        num = [("cnt", Pipeline([("log", FunctionTransformer(np.log1p, feature_names_out="one-to-one")),
                                 ("sc", StandardScaler())]), COUNT),
               ("plain", StandardScaler(), PLAIN)]
    else:
        num = [("num", StandardScaler(), COUNT + PLAIN)]
    ct = ColumnTransformer(num + [("cat", OneHotEncoder(handle_unknown="ignore", drop="first"), CAT)])
    return Pipeline([("prep", ct), ("lr", LogisticRegression(C=C_reg, max_iter=2000))])


def _scores(y, p, thr):
    yhat = (p >= thr).astype(int)
    return {"n": int(len(y)), "positive_rate": round(float(np.mean(y)), 4),
            "mean_predicted_prob": round(float(np.mean(p)), 4),
            "accuracy": round(accuracy_score(y, yhat), 4), "precision": round(precision_score(y, yhat, zero_division=0), 4),
            "recall": round(recall_score(y, yhat), 4), "f1": round(f1_score(y, yhat), 4),
            "roc_auc": round(roc_auc_score(y, p), 4), "brier": round(brier_score_loss(y, p), 4),
            "pred_min": round(float(p.min()), 4), "pred_max": round(float(p.max()), 4)}


def coefficient_table(pipe: Pipeline) -> list[dict]:
    names = pipe.named_steps["prep"].get_feature_names_out()
    coefs = pipe.named_steps["lr"].coef_[0]
    rows = [{"feature": n.split("__", 1)[1], "coefficient": round(float(c), 4),
             "odds_ratio": round(float(np.exp(c)), 3),
             "direction": "raises review probability" if c > 0 else "lowers review probability"}
            for n, c in zip(names, coefs)]
    return sorted(rows, key=lambda r: -abs(r["coefficient"]))


def train() -> dict:
    df = pd.read_csv(DATA)
    assert not set(FEATURES) & set(EXCLUDED), "feature list overlaps excluded/leakage columns"
    assert set(FEATURES) | set(EXCLUDED) == set(df.columns), "unexpected/missing columns in risk_scoring.csv"
    ref = json.loads(SUMMARY.read_text())["risk_scoring"]
    s = {k: df[df.split == k] for k in ("train", "valid", "test")}  # existing chronological split - no reshuffling
    Xtr, ytr = s["train"][FEATURES], s["train"][TARGET]
    Xva, yva = s["valid"][FEATURES], s["valid"][TARGET]

    # Decisions on VALID only: log1p on count features (yes/no) x regularisation strength. 8 fits, no CV.
    grid = [(lc, c) for lc in (False, True) for c in (0.01, 0.1, 1.0, 10.0)]
    res = [(roc_auc_score(yva, _build(c, lc).fit(Xtr, ytr).predict_proba(Xva)[:, 1]), lc, c) for lc, c in grid]
    best_auc, log_counts, c_reg = max(res, key=lambda t: (round(t[0], 4), -t[2]))  # ties -> stronger regularisation
    pipe = _build(c_reg, log_counts).fit(Xtr, ytr)

    # Review-flag threshold: F1-optimal on VALID (0.5 is not meaningful: prevalence drifts 18% -> 27% -> 29%).
    pv = pipe.predict_proba(Xva)[:, 1]
    thr = float(max(np.arange(0.10, 0.60, 0.01), key=lambda t: f1_score(yva, (pv >= t).astype(int))))
    thr = round(thr, 2)

    out = {"chosen": {"log1p_counts": log_counts, "C": c_reg, "valid_grid_auc": {f"log={a},C={b}": round(v, 4) for v, a, b in res},
                      "flag_threshold_from_valid_f1": thr},
           "features": FEATURES, "excluded": EXCLUDED, "oracle_auc": {k: v["oracle_auc"] for k, v in ref["per_split"].items()},
           "phase4_throwaway_logreg_test_auc": ref["sanity_baseline_logreg_test_auc"]}
    for name in ("train", "valid"):
        p = pipe.predict_proba(s[name][FEATURES])[:, 1]
        out[name] = {"at_0.5": _scores(s[name][TARGET], p, 0.5), f"at_{thr}": _scores(s[name][TARGET], p, thr)}
    pt = pipe.predict_proba(s["test"][FEATURES])[:, 1]  # TEST touched once, after all decisions above
    yt = s["test"][TARGET]
    out["test"] = {"at_0.5": _scores(yt, pt, 0.5), f"at_{thr}": _scores(yt, pt, thr),
                   "majority_class_accuracy": round(1 - float(yt.mean()), 4)}
    out["test_auc_below_oracle"] = bool(out["test"]["at_0.5"]["roc_auc"] < out["oracle_auc"]["test"])
    out["coefficients"] = coefficient_table(pipe)

    MODEL_DIR.mkdir(exist_ok=True)
    joblib.dump({"pipeline": pipe, "features": FEATURES, "threshold": thr,
                 "doc_types": DOC_TYPES, "departments": DEPT_CODES}, MODEL_PATH, compress=3)
    METRICS_PATH.write_text(json.dumps(out, indent=2))
    return out


# ------------------------------- prediction -------------------------------
_ART = None


def _load():
    global _ART
    if _ART is None:
        if not MODEL_PATH.exists():
            raise FileNotFoundError(f"{MODEL_PATH} not found - run `python -m ml.risk_scoring` first")
        _ART = joblib.load(MODEL_PATH)
    return _ART


def _row(*, document_type, department, semester, is_alumni, cgpa, backlog_count, past_fee_delays_12m,
         prior_apps_count, prior_review_count_lagged, num_documents, ocr_failed, ocr_detected_cgpa) -> dict:
    dept = _DEPT_BY_NAME.get(department, department)  # accept 'CSE' or 'Computer Science and Engineering'
    if document_type not in DOC_TYPES:
        raise ValueError(f"unknown document_type {document_type!r}")
    if dept not in DEPT_CODES:
        raise ValueError(f"unknown department {department!r}")
    if not 0 <= float(cgpa) <= 10:
        raise ValueError("cgpa must be between 0 and 10")
    for k, v in dict(backlog_count=backlog_count, past_fee_delays_12m=past_fee_delays_12m, prior_apps_count=prior_apps_count,
                     prior_review_count_lagged=prior_review_count_lagged, num_documents=num_documents).items():
        if v < 0:
            raise ValueError(f"{k} must be >= 0")
    # Same definitions as ml/prepare.py: no detected CGPA -> found=0, mismatch=0 (explicit flag, not "matched").
    found = ocr_detected_cgpa is not None and not ocr_failed
    mismatch = round(abs(float(ocr_detected_cgpa) - float(cgpa)), 2) if found else 0.0
    return {"document_type": document_type, "department": dept, "semester": int(semester), "is_alumni": int(bool(is_alumni)),
            "cgpa": float(cgpa), "backlog_count": int(backlog_count), "past_fee_delays_12m": int(past_fee_delays_12m),
            "prior_apps_count": int(prior_apps_count), "prior_review_count_lagged": int(prior_review_count_lagged),
            "num_documents": int(num_documents), "ocr_failed": int(bool(ocr_failed)), "ocr_cgpa_found": int(found),
            "ocr_cgpa_mismatch": mismatch}


def predict_risk(*, document_type: str, department: str, semester: int, cgpa: float, backlog_count: int,
                 is_alumni: bool = False, past_fee_delays_12m: int = 0, prior_apps_count: int = 0,
                 prior_review_count_lagged: int = 0, num_documents: int = 1, ocr_failed: bool = False,
                 ocr_detected_cgpa: float | None = None) -> float:
    """Probability (0.0-1.0) that this application will need MANUAL REVIEW, per the trained model.

    This is decision support for the administrator. It is NOT an eligibility decision and never returns
    ELIGIBLE/NOT_ELIGIBLE. Inputs are what is known at submission time; history counts default to 0 (= no
    recorded history). `ocr_detected_cgpa=None` means OCR found no CGPA.
    """
    art = _load()
    row = _row(document_type=document_type, department=department, semester=semester, is_alumni=is_alumni, cgpa=cgpa,
               backlog_count=backlog_count, past_fee_delays_12m=past_fee_delays_12m, prior_apps_count=prior_apps_count,
               prior_review_count_lagged=prior_review_count_lagged, num_documents=num_documents, ocr_failed=ocr_failed,
               ocr_detected_cgpa=ocr_detected_cgpa)
    p = float(art["pipeline"].predict_proba(pd.DataFrame([row])[art["features"]])[0, 1])
    return min(max(p, 0.0), 1.0)


def review_flag_threshold() -> float:
    """Probability above which the admin UI may highlight an application (chosen on the validation split)."""
    return float(_load()["threshold"])


if __name__ == "__main__":
    print(json.dumps(train(), indent=2))
