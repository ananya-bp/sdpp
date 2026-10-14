"""Data validation for the simulated datasets.

`validate(raw, labels, processed, cfg)` returns (summary, failures). An empty failures list means
every hard check passed. The "sanity baselines" are NOT the Phase 5 models: they are throwaway
checks that the datasets contain learnable signal (and that the signal is not trivially perfect),
and they give Phase 5 a floor to beat. Nothing here is saved or served.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C
from .features import history_features

FORBIDDEN_FEATURE_SUBSTRINGS = ("sim_", "true_", "oracle", "decided", "tat_hours_target")
# "status" is deliberately not a banned substring: application-level workflow status IS leakage
# (it's only known once the application is handled), but a transaction's own payment_status is a
# legitimate, known-at-the-time feature of that transaction. Ban the workflow column by exact name
# instead of by substring, so payment_status is not caught by accident.
VALID_STATUSES = {"NOT_ELIGIBLE", "ELIGIBLE", "PAYMENT_PENDING", "UNDER_REVIEW", "VERIFIED", "REJECTED"}


def _expected_eligible(apps: pd.DataFrame) -> np.ndarray:
    zero_backlog_doc = apps["document_type"].isin(C.ZERO_BACKLOG_REQUIRED_FOR)
    ok = (apps["fee_status_at_submission"] == "CLEAR") & (apps["num_documents"] >= 1)
    ok &= ~(zero_backlog_doc & (apps["backlog_count_at_submission"] > 0))
    return ok.to_numpy()


def _auc(y: np.ndarray, score: np.ndarray) -> float:
    from sklearn.metrics import roc_auc_score
    return float(roc_auc_score(y, score))


def check_raw(raw: dict, labels: dict, cfg: C.SimConfig, fail: list) -> dict:
    stu, apps, txn = raw["students"], raw["applications"], raw["transactions"]
    al, tl = labels["application_labels"], labels["transaction_labels"]
    cutoff = pd.Timestamp(cfg.end) + pd.Timedelta(hours=23, minutes=59, seconds=59)

    def need(cond: bool, msg: str) -> None:
        if not cond:
            fail.append(msg)

    need(stu["student_id"].is_unique and stu["usn"].is_unique, "student ids / USNs not unique")
    # ---- college identifier integrity (USN/email rules from the shared backend utility) ----
    if "college_email" in stu.columns:
        emails = stu["college_email"].fillna("")
        nonempty = emails[emails != ""]
        need(nonempty.is_unique, "duplicate college emails in students.csv")
        for _usn, _em in zip(stu["usn"], emails):
            if _em == "":
                continue  # legacy SYN-format simulated USN: no college mailbox (documented)
            if not (_em == str(_usn).lower() + "@kletech.ac.in"):
                fail.append(f"college email {_em!r} does not match USN {_usn!r}")
                break
    need(apps["application_id"].is_unique, "application ids not unique")
    need(txn["transaction_id"].is_unique, "transaction ids not unique")
    need(apps["student_id"].isin(stu["student_id"]).all(), "application -> student foreign key broken")
    need(txn["application_id"].isin(apps["application_id"]).all(), "transaction -> application foreign key broken")
    need(al["application_id"].tolist() == apps["application_id"].tolist(), "application_labels not aligned with applications")
    need(tl["transaction_id"].tolist() == txn["transaction_id"].tolist(), "transaction_labels not aligned with transactions")
    need(set(apps["document_type"]) <= set(C.DOCUMENT_TYPES), "unknown document type")
    need(set(apps["status"]) <= VALID_STATUSES, "unknown status value")
    need(apps["submitted_at"].max() <= cutoff and txn["transacted_at"].max() <= cutoff, "timestamp after the snapshot date")
    need(apps["submitted_at"].is_monotonic_increasing, "applications not ordered by submission time")
    need(apps["cgpa_at_submission"].between(0, 10).all(), "CGPA out of range")
    need((apps["backlog_count_at_submission"] >= 0).all(), "negative backlog count")
    need((txn["amount"] > 0).all(), "non-positive payment amount")

    # Consistency with the running app's placeholder rules.
    need((apps["eligibility_result"] == np.where(_expected_eligible(apps), "ELIGIBLE", "NOT_ELIGIBLE")).all(),
         "eligibility_result disagrees with the backend rules")
    ineligible_ids = set(apps.loc[apps["eligibility_result"] == "NOT_ELIGIBLE", "application_id"])
    need(not txn["application_id"].isin(ineligible_ids).any(), "a NOT_ELIGIBLE application has payments")

    # Workflow consistency.
    decided = apps["status"].isin(["VERIFIED", "REJECTED"])
    need(apps.loc[decided, "decided_at"].notna().all() and apps.loc[~decided, "decided_at"].isna().all(),
         "decided_at present exactly for VERIFIED/REJECTED")
    need((apps.loc[decided, "decided_at"] >= apps.loc[decided, "submitted_at"]).all(), "decision before submission")
    paid_ids = set(txn.loc[txn["payment_status"] == "SUCCESS", "application_id"])
    need(set(apps.loc[decided | (apps["status"] == "UNDER_REVIEW"), "application_id"]) <= paid_ids,
         "decided/under-review application without a successful payment")

    # Fees: every attempt not labelled as an amount anomaly must equal the fee schedule.
    merged = txn.merge(apps[["application_id", "document_type"]], on="application_id").merge(tl, on="transaction_id")
    normal_amount = merged["anomaly_type"] != "AMOUNT_MISMATCH"
    need((merged.loc[normal_amount, "amount"] == merged.loc[normal_amount, "document_type"].map(C.FEE_BY_DOCUMENT_TYPE)).all(),
         "non-anomalous payment amount differs from the fee schedule")
    need((merged.loc[~normal_amount, "amount"] != merged.loc[~normal_amount, "document_type"].map(C.FEE_BY_DOCUMENT_TYPE)).all(),
         "AMOUNT_MISMATCH row equals the fee")

    joined = apps.merge(al, on="application_id")
    need(joined.loc[joined["eligibility_result"] == "NOT_ELIGIBLE", "needs_manual_review"].isna().all(),
         "review label present for an ineligible application")
    need(joined.loc[joined["eligibility_result"] == "ELIGIBLE", "needs_manual_review"].notna().all(),
         "review label missing for an eligible application")
    return {
        "students": len(stu), "applications": len(apps), "transactions": len(txn),
        "status_counts": apps["status"].value_counts().to_dict(),
        "applications_by_document_type": apps["document_type"].value_counts().to_dict(),
        "eligible_share": round(float((apps["eligibility_result"] == "ELIGIBLE").mean()), 4),
        "first_submission": str(apps["submitted_at"].min()), "last_submission": str(apps["submitted_at"].max()),
    }


def check_processed(raw: dict, labels: dict, proc: dict, cfg: C.SimConfig, fail: list) -> dict:
    apps = raw["applications"]
    fc, tat, risk, anom = proc["forecast_daily"], proc["tat_applications"], proc["risk_scoring"], proc["anomaly_transactions"]
    summary: dict = {}

    def need(cond: bool, msg: str) -> None:
        if not cond:
            fail.append(msg)

    # ---- splits are chronological in every dataset
    for name, df, col in (("forecast_daily", fc, "date"), ("tat_applications", tat, "submitted_at"),
                          ("risk_scoring", risk, "submitted_at"), ("anomaly_transactions", anom, "transacted_at")):
        order = {"train": 0, "valid": 1, "test": 2}
        s = df.sort_values(col)["split"].map(order)
        need(s.is_monotonic_increasing, f"{name}: splits are not chronological")
        need(set(df["split"]) == {"train", "valid", "test"}, f"{name}: a split is empty")
        summary.setdefault("split_sizes", {})[name] = df["split"].value_counts().reindex(["train", "valid", "test"]).to_dict()

    # ---- no answer-key / post-outcome columns among features
    for name, df in proc.items():
        feats = [c for c in df.columns if not c.startswith("label_") and c != "split"]
        bad = [c for c in feats if c == "status" or any(sub in c for sub in FORBIDDEN_FEATURE_SUBSTRINGS)]
        need(not bad, f"{name}: suspicious feature columns {bad}")

    # ---- forecasting
    kept = apps[apps["submitted_at"].dt.normalize() >= fc["date"].min()]
    need(int(fc["applications_submitted"].sum()) == len(kept), "forecast_daily counts do not add up to the raw applications")
    need(len(fc) == fc["date"].nunique() * len(C.DOCUMENT_TYPES), "forecast_daily is not a full date x document-type grid")
    one_type = fc[fc["document_type"] == "TRANSCRIPT"].sort_values("date").reset_index(drop=True)
    # The first 7 rows of the shipped file were computed from days that were trimmed off (see
    # build_forecast_daily), so only rows from index 7 onward can be checked against the file itself.
    check = one_type.iloc[7:]
    need(bool((one_type["applications_submitted"].shift(7).iloc[7:].to_numpy() == check["lag_7"].to_numpy()).all()),
         "lag_7 does not equal the value 7 days earlier")
    for col in ("applications_submitted", "lag_1", "lag_7", "lag_14", "roll_mean_7", "roll_mean_28", "dow", "month"):
        need(fc[col].notna().all(), f"forecast_daily: unexpected missing values in {col}")
    need(fc.loc[fc["tat_censored"] == 1, "mean_tat_hours"].isna().all(), "censored days must have a missing mean TAT")
    test = fc[fc["split"] == "test"]
    train = fc[fc["split"] == "train"]
    base_mean = train.groupby("document_type")["applications_submitted"].mean()
    mae_mean = float((test["applications_submitted"] - test["document_type"].map(base_mean)).abs().mean())
    mae_lag7 = float((test["applications_submitted"] - test["lag_7"]).abs().mean())
    summary["forecasting_sanity_baselines"] = {
        "note": "test-split MAE of daily applications per document type; floors for Phase 5A to beat",
        "train_mean_mae": round(mae_mean, 3), "seasonal_naive_lag7_mae": round(mae_lag7, 3),
        "mean_daily_applications_per_type": round(float(fc["applications_submitted"].mean()), 3),
    }
    summary["forecast_days_with_censored_tat"] = int(fc["tat_censored"].sum())

    # ---- TAT
    need((tat["tat_hours"] >= 0).all(), "negative turnaround time")
    need(bool(np.isfinite(tat.select_dtypes("number")).all().all()), "tat_applications has non-finite numbers")
    q = tat["tat_hours"].quantile([0.05, 0.25, 0.5, 0.75, 0.95, 0.99]).round(1)
    summary["tat_hours_quantiles"] = {str(k): float(v) for k, v in q.items()}
    tt = tat[tat["split"] == "test"]
    train_median = tat.loc[tat["split"] == "train", "tat_hours"].median()
    summary["tat_sanity_baseline"] = {
        "note": "test-split MAE in hours; floor for Phase 5A to beat",
        "train_median_mae_hours": round(float((tt["tat_hours"] - train_median).abs().mean()), 2),
    }
    q_corr = tat["tat_hours"].corr(tat["queue_open_at_submission"], method="spearman")
    need(q_corr > 0.2, f"queue length should be positively related to turnaround time (spearman={q_corr:.3f})")
    quint = pd.qcut(tat["queue_open_at_submission"], 5, duplicates="drop")
    q_medians = tat.groupby(quint, observed=True)["tat_hours"].median()
    summary["tat_by_queue_quintile_median_hours"] = {str(k): round(float(v), 1) for k, v in q_medians.items()}
    need(q_medians.is_monotonic_increasing,
         "median TAT should rise monotonically across queue-length quintiles")

    # ---- risk scoring
    need(set(risk["label_needs_manual_review"]) <= {0, 1}, "risk label is not binary")
    need(risk.isna().sum().sum() == 0, "risk_scoring contains missing values")
    feature_cols = [c for c in risk.columns if c not in ("application_id", "student_id", "submitted_at", "split")
                    and not c.startswith("label_")]
    constant = [c for c in feature_cols if risk[c].nunique() <= 1]
    need(not constant, f"risk_scoring has constant columns {constant}")
    need(bool((risk["cgpa"] - apps.set_index("application_id").loc[risk["application_id"], "cgpa_at_submission"].to_numpy()).abs().max() == 0),
         "risk cgpa differs from raw")
    a = apps.sort_values(["submitted_at", "application_id"]).reset_index(drop=True)
    lab = labels["application_labels"].set_index("application_id")
    rev = np.nan_to_num(lab.loc[a["application_id"], "needs_manual_review"].astype(float).to_numpy())
    pa, pr = history_features(a["student_id"].to_numpy(), a["submitted_at"], rev)
    hist = pd.DataFrame({"application_id": a["application_id"], "pa": pa, "pr": pr})
    m = risk.merge(hist, on="application_id")
    need((m["prior_apps_count"] == m["pa"]).all() and (m["prior_review_count_lagged"] == m["pr"]).all(),
         "risk history features do not match a fresh recomputation")

    prev = risk.groupby("split")["label_needs_manual_review"].mean().round(4).to_dict()
    oracle = labels["application_labels"].set_index("application_id")["sim_true_review_probability"]
    per_split = {}
    for sp in ("train", "valid", "test"):
        d = risk[risk["split"] == sp]
        per_split[sp] = {"rows": len(d), "positive_rate": prev[sp],
                         "oracle_auc": round(_auc(d["label_needs_manual_review"].to_numpy(), oracle.loc[d["application_id"]].to_numpy()), 4)}
    need(all(0.10 <= v["positive_rate"] <= 0.40 for v in per_split.values()), "review prevalence outside 10-40%")
    summary["risk_scoring"] = {
        "rows": len(risk), "per_split": per_split,
        "oracle_auc_note": "AUC of the TRUE generating probability: the ceiling any model can reach on this simulated label",
        "single_feature_auc_train": {c: round(_auc(risk.loc[risk["split"] == "train", "label_needs_manual_review"].to_numpy(),
                                                   risk.loc[risk["split"] == "train", c].to_numpy()), 3)
                                     for c in ("backlog_count", "cgpa", "past_fee_delays_12m", "prior_review_count_lagged",
                                               "ocr_cgpa_mismatch", "ocr_failed", "prior_apps_count")},
    }
    try:
        from sklearn.compose import ColumnTransformer
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import OneHotEncoder, StandardScaler
        cat = ["document_type", "department"]
        num = [c for c in feature_cols if c not in cat]
        pipe = make_pipeline(ColumnTransformer([("c", OneHotEncoder(handle_unknown="ignore"), cat),
                                                ("n", StandardScaler(), num)]), LogisticRegression(max_iter=1000))
        tr, te = risk[risk["split"] == "train"], risk[risk["split"] == "test"]
        pipe.fit(tr[feature_cols], tr["label_needs_manual_review"])
        auc = _auc(te["label_needs_manual_review"].to_numpy(), pipe.predict_proba(te[feature_cols])[:, 1])
        summary["risk_scoring"]["sanity_baseline_logreg_test_auc"] = round(auc, 4)
        summary["risk_scoring"]["sanity_baseline_note"] = "throwaway check that signal exists; NOT the Phase 5B model"
        need(0.65 < auc < per_split["test"]["oracle_auc"] + 0.02, f"logistic sanity AUC {auc:.3f} implausible")
    except ImportError:
        summary["risk_scoring"]["sanity_baseline_logreg_test_auc"] = "skipped (scikit-learn not installed)"

    # ---- anomaly detection
    need(anom["label_is_anomaly"].isin([0, 1]).all(), "anomaly label not binary")
    need(bool(np.isfinite(anom.select_dtypes("number")).all().all()), "anomaly features contain non-finite numbers")
    types = anom["label_anomaly_type"].value_counts().to_dict()
    need(all(types.get(k, 0) > 0 for k in ("AMOUNT_MISMATCH", "RAPID_RETRIES", "DUPLICATE_REQUEST", "FREQUENCY_BURST")),
         "an anomaly type is missing from the dataset")
    rate = float(anom["label_is_anomaly"].mean())
    need(0.01 <= rate <= 0.05, f"anomaly rate {rate:.3f} outside 1-5%")
    feats = [c for c in anom.columns if c not in ("transaction_id", "application_id", "student_id", "transacted_at",
                                                 "document_type", "payment_status", "split") and not c.startswith("label_")]
    sep = {}
    normal = anom[anom["label_anomaly_type"] == "NONE"]
    for typ in ("AMOUNT_MISMATCH", "RAPID_RETRIES", "DUPLICATE_REQUEST", "FREQUENCY_BURST"):
        sub = anom[anom["label_anomaly_type"] == typ]
        y = np.r_[np.ones(len(sub)), np.zeros(len(normal))]
        best = {}
        for f in feats:
            x = np.r_[sub[f].to_numpy(), normal[f].to_numpy()]
            if f == "amount_ratio":
                x = np.abs(x - 1.0)
            a_ = _auc(y, x)
            best[f] = max(a_, 1 - a_)
        top = max(best, key=best.get)
        sep[typ] = {"rows": len(sub), "best_single_feature": top, "auc": round(best[top], 3)}
    burst_rows = anom[anom["label_anomaly_type"] == "RAPID_RETRIES"]
    summary["anomaly_transactions"] = {
        "rows": len(anom), "anomaly_rate": round(rate, 4), "rows_by_type": types,
        "separability_best_single_feature": sep,
        "rapid_retry_rows_that_are_first_attempts": round(float((burst_rows["attempt_index"] == 1).mean()), 3),
        "note": "first attempt of a retry burst looks like any normal first attempt at row level; "
                "a row-level detector cannot flag it (see docs/DATA_DICTIONARY.md)",
    }
    for typ, v in sep.items():
        need(v["auc"] > 0.75, f"{typ} is not separable from normal rows (best AUC {v['auc']})")
    return summary


def validate(raw: dict, labels: dict, proc: dict, cfg: C.SimConfig) -> tuple[dict, list[str]]:
    failures: list[str] = []
    summary = {"raw": check_raw(raw, labels, cfg, failures)}
    summary.update(check_processed(raw, labels, proc, cfg, failures))
    summary["hard_checks_failed"] = len(failures)
    return summary, failures
