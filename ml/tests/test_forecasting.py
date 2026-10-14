"""Phase 5.1 tests: artifact exists, reloads, predicts plausibly, beats Phase 4 baselines, no leakage columns."""
import json

import numpy as np
import pandas as pd
import pytest

from ml import forecasting as F


@pytest.fixture(scope="module")
def metrics():
    F.train()  # real training run (fast, ~seconds); writes artifact + metrics
    return json.loads(F.METRICS_PATH.read_text())


def test_artifact_created_and_small(metrics):
    assert F.MODEL_PATH.exists() and F.MODEL_PATH.stat().st_size < 5_000_000


def test_no_leakage_columns():
    banned = {"mean_tat_hours", "n_tat_observed", "tat_censored", "applications_submitted", "split", "date"}
    assert not banned & set(F.DEMAND_FEATURES)
    assert not {"tat_hours", "application_id", "submitted_at", "split"} & set(F.TAT_FEATURES)


def test_beats_baselines_on_test(metrics):
    b = json.loads(F.SUMMARY.read_text())
    assert metrics["demand"]["test"]["mae"] < b["forecasting_sanity_baselines"]["train_mean_mae"]
    assert metrics["demand"]["test"]["mae"] < b["forecasting_sanity_baselines"]["seasonal_naive_lag7_mae"]
    assert metrics["tat"]["test"]["mae"] < b["tat_sanity_baseline"]["train_median_mae_hours"]


def test_split_sizes_match_phase4(metrics):
    b = json.loads(F.SUMMARY.read_text())["split_sizes"]
    for k in ("train", "valid", "test"):
        assert metrics["demand"][k]["n"] == b["forecast_daily"][k]
        assert metrics["tat"][k]["n"] == b["tat_applications"][k]


def test_reload_and_predict():
    F._ART = None
    d = F.predict_demand(document_type="TRANSCRIPT", date="2026-09-01")
    t = F.predict_tat(document_type="TRANSCRIPT", num_documents=1, is_alumni=0, submitted_at="2026-09-02 10:00",
                      queue_open_at_submission=12, apps_prev_24h=5, apps_prev_7d=30, doc_apps_prev_7d=15)
    assert 0 <= d < 40 and 0 < t < 300


def test_tat_increases_with_queue():
    kw = dict(document_type="TRANSCRIPT", num_documents=1, is_alumni=0, submitted_at="2026-09-02 10:00",
              apps_prev_24h=5, apps_prev_7d=30, doc_apps_prev_7d=15)
    assert F.predict_tat(queue_open_at_submission=60, **kw) > F.predict_tat(queue_open_at_submission=2, **kw)


def test_demand_rejects_far_future():
    with pytest.raises(ValueError):
        F.predict_demand(document_type="TRANSCRIPT", date="2027-03-01")
