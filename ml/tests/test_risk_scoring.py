"""Phase 5.2 tests: artifact, fresh-process reload, leakage, output range, split sizes, metric reproducibility."""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ml import risk_scoring as R

PROJECT_ROOT = Path(R.__file__).resolve().parents[1]
SAMPLE = dict(document_type="TRANSCRIPT", department="CSE", semester=7, cgpa=7.5, backlog_count=1)


@pytest.fixture(scope="module")
def metrics():
    return R.train()  # real training run (seconds); writes artifact + metrics


def test_artifact_created_and_small(metrics):
    assert R.MODEL_PATH.exists() and R.MODEL_PATH.stat().st_size < 1_000_000
    assert json.loads(R.METRICS_PATH.read_text())["chosen"]["C"] == metrics["chosen"]["C"]


def test_feature_set_and_leakage():
    df = pd.read_csv(R.DATA)
    assert R.TARGET not in R.FEATURES
    assert set(R.FEATURES) <= set(df.columns)
    assert set(R.FEATURES) | set(R.EXCLUDED) == set(df.columns)  # every column is either used or explicitly excluded
    assert not set(R.FEATURES) & {"label_needs_manual_review", "application_id", "student_id", "submitted_at", "split"}
    banned = ("sim_", "true_", "oracle", "decided", "label_")
    assert not [f for f in R.FEATURES if f.startswith(banned) or f in ("status", "eligibility_result")]


def test_split_sizes_match_phase4(metrics):
    ref = json.loads(R.SUMMARY.read_text())["risk_scoring"]["per_split"]
    for k in ("train", "valid", "test"):
        assert metrics[k]["at_0.5"]["n"] == ref[k]["rows"]
    df = pd.read_csv(R.DATA)
    d = pd.to_datetime(df.submitted_at)
    assert d[df.split == "train"].max() < d[df.split == "valid"].min() <= d[df.split == "valid"].max() < d[df.split == "test"].min()


def test_test_auc_reasonable_and_below_oracle(metrics):
    auc, oracle = metrics["test"]["at_0.5"]["roc_auc"], metrics["oracle_auc"]["test"]
    assert 0.75 < auc < oracle  # above oracle would mean leakage


def test_metrics_reproducible(metrics):
    again = R.train()
    assert again["test"]["at_0.5"]["roc_auc"] == metrics["test"]["at_0.5"]["roc_auc"]
    assert again["test"]["at_0.5"]["f1"] == metrics["test"]["at_0.5"]["f1"]


def test_prediction_numeric_in_range():
    p = R.predict_risk(**SAMPLE)
    assert isinstance(p, float) and 0.0 <= p <= 1.0


def test_prediction_after_reload_matches():
    p1 = R.predict_risk(**SAMPLE)
    R._ART = None
    assert R.predict_risk(**SAMPLE) == pytest.approx(p1)


def test_fresh_process_prediction():
    code = ("from ml.risk_scoring import predict_risk; "
            "print(predict_risk(document_type='TRANSCRIPT', department='CSE', semester=7, cgpa=7.5, backlog_count=1))")
    out = subprocess.run([sys.executable, "-W", "ignore", "-c", code], cwd=PROJECT_ROOT, capture_output=True, text=True, check=True)
    assert abs(float(out.stdout.strip()) - R.predict_risk(**SAMPLE)) < 1e-9


def test_risky_scores_higher_than_fine():
    fine = R.predict_risk(**{**SAMPLE, "cgpa": 9.3, "backlog_count": 0})
    risky = R.predict_risk(**{**SAMPLE, "cgpa": 5.9, "backlog_count": 4, "past_fee_delays_12m": 3})
    assert risky > fine


def test_accepts_full_department_name_and_rejects_bad_input():
    a = R.predict_risk(**SAMPLE)
    b = R.predict_risk(**{**SAMPLE, "department": "Computer Science and Engineering"})
    assert a == pytest.approx(b)
    for bad in ({"cgpa": 12}, {"department": "XYZ"}, {"document_type": "NOPE"}, {"backlog_count": -1}):
        with pytest.raises(ValueError):
            R.predict_risk(**{**SAMPLE, **bad})


def test_dev_seed_ordering():
    from ml.score_dev_seed import score_dev_seed
    df = score_dev_seed().set_index("usn")
    assert len(df) == 12 and df.risk_prob.between(0, 1).all()
    assert df.loc["SIM23CIV002", "risk_prob"] > df.loc["SIM23CSE003", "risk_prob"]
