"""Phase 5.3 tests: artifact, fresh-process reload, label leakage, output shape, evaluation reproducibility."""
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

from ml import anomaly as A

PROJECT_ROOT = Path(A.__file__).resolve().parents[1]
NORMAL = dict(document_type="TRANSCRIPT", amount=200.0, payment_status="SUCCESS")


@pytest.fixture(scope="module")
def metrics():
    return A.train()


def _row_kwargs(r):
    return dict(document_type=r.document_type, amount=r.amount, payment_status=r.payment_status, attempt_index=int(r.attempt_index),
                failed_attempts_before=int(r.failed_attempts_before), seconds_since_prev_attempt=float(r.seconds_since_prev_attempt),
                student_txns_prior_24h=int(r.student_txns_prior_24h), student_other_apps_24h=int(r.student_other_apps_24h),
                student_other_apps_7d=int(r.student_other_apps_7d), same_doc_other_apps_7d=int(r.same_doc_other_apps_7d),
                same_doc_other_paid_apps_7d=int(r.same_doc_other_paid_apps_7d))


def test_artifact_created_and_small(metrics):
    assert A.MODEL_PATH.exists() and A.MODEL_PATH.stat().st_size < 10_000_000


def test_no_label_leakage():
    df = pd.read_csv(A.DATA)
    assert not [f for f in A.FEATURES if f.startswith("label_") or "anomaly" in f]
    assert A.LABEL not in A.FEATURES and A.LABEL_TYPE not in A.FEATURES
    assert {A.LABEL, A.LABEL_TYPE} <= set(A.EXCLUDED)
    assert set(df.columns) <= set(A.RAW_NUMERIC) | set(A.EXCLUDED)  # every column is a feature source or explicitly excluded
    X = A.make_matrix(df)
    assert list(X.columns) == A.FEATURES and not X.isna().any().any()


def test_labels_do_not_change_the_model():
    """Unsupervised: scrambling every label must give an identical fitted model (same scores)."""
    df = pd.read_csv(A.DATA)
    tr = df[df.split == "train"]
    from sklearn.ensemble import IsolationForest
    m1 = IsolationForest(**A.PARAMS).fit(A.make_matrix(tr))
    tr2 = tr.assign(**{A.LABEL: 1 - tr[A.LABEL], A.LABEL_TYPE: "X"})
    m2 = IsolationForest(**A.PARAMS).fit(A.make_matrix(tr2))
    X = A.make_matrix(df[df.split == "valid"])
    assert (m1.score_samples(X) == m2.score_samples(X)).all()


def test_output_structure_and_types():
    out = A.predict_anomaly(**NORMAL)
    assert set(out) == {"anomaly_score", "threshold", "model_flagged", "rule_flags", "is_anomaly", "label"}
    assert isinstance(out["anomaly_score"], float) and isinstance(out["is_anomaly"], bool)
    assert out["label"] in ("NORMAL", "ANOMALOUS") and out["label"] == ("ANOMALOUS" if out["is_anomaly"] else "NORMAL")
    assert "type" not in out and "anomaly_type" not in out  # unsupervised model must not claim a category


def test_prediction_after_reload_and_fresh_process():
    a = A.predict_anomaly(**NORMAL)
    A._ART = None
    assert A.predict_anomaly(**NORMAL) == a
    code = ("import json; from ml.anomaly import predict_anomaly; "
            "print(json.dumps(predict_anomaly(document_type='TRANSCRIPT', amount=200.0, payment_status='SUCCESS')))")
    out = subprocess.run([sys.executable, "-W", "ignore", "-c", code], cwd=PROJECT_ROOT, capture_output=True, text=True, check=True)
    assert json.loads(out.stdout) == a


def test_amount_mismatch_is_caught_by_rule_only():
    out = A.predict_anomaly(**{**NORMAL, "amount": 400.0})
    assert out["is_anomaly"] and out["rule_flags"] == ["AMOUNT_MISMATCH"]
    assert A.predict_anomaly(**NORMAL)["rule_flags"] == []


def test_real_rows_scored_via_prediction_function(metrics):
    df = pd.read_csv(A.DATA)
    te = df[df.split == "test"]
    normal = te[te.label_anomaly_type == "NONE"].head(200)
    burst = te[(te.label_anomaly_type == "RAPID_RETRIES") & (te.attempt_index > 1)]
    n_flag = sum(A.predict_anomaly(**_row_kwargs(r))["is_anomaly"] for r in normal.itertuples())
    b_flag = sum(A.predict_anomaly(**_row_kwargs(r))["is_anomaly"] for r in burst.itertuples())
    assert n_flag / len(normal) < 0.1 and b_flag / len(burst) > 0.4


def test_prediction_function_matches_batch_scoring():
    df = pd.read_csv(A.DATA)
    r = df[df.split == "test"].iloc[7]
    art = A._load()
    batch = float(-art["model"].score_samples(A.make_matrix(df[df.split == "test"].iloc[[7]]))[0])
    assert A.predict_anomaly(**_row_kwargs(r))["anomaly_score"] == pytest.approx(batch, abs=1e-6)


def test_metrics_evaluable_reproducible_and_consistent(metrics):
    again = A.train()
    for k in ("isolation_forest_only", "if_plus_amount_rule"):
        assert again["test"][k]["overall"] == metrics["test"][k]["overall"]
    ref = json.loads((A.ROOT / "data" / "dataset_summary.json").read_text())["split_sizes"]["anomaly_transactions"]
    for k in ("train", "valid", "test"):
        assert metrics[k]["if_plus_amount_rule"]["overall"]["n"] == ref[k]
    t = metrics["test"]["if_plus_amount_rule"]["by_type"]
    assert set(t) >= {"AMOUNT_MISMATCH", "RAPID_RETRIES", "DUPLICATE_REQUEST", "FREQUENCY_BURST"}
    assert sum(t[k]["injected"] for k in ("AMOUNT_MISMATCH", "RAPID_RETRIES", "DUPLICATE_REQUEST", "FREQUENCY_BURST")) == metrics["test"]["if_plus_amount_rule"]["overall"]["anomalies"]


def test_model_beats_random_and_never_uses_test_for_threshold(metrics):
    assert metrics["test"]["isolation_forest_only"]["overall"]["roc_auc"] > 0.85
    assert "test" not in metrics["threshold"]["rule"]
    # threshold is one of the train-score percentiles listed in the grid
    assert metrics["threshold"]["rule"].startswith("flag top")
