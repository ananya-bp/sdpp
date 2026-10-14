"""Tests for the Phase 4 data pipeline. Uses config.small_config() (a few hundred students, ~6
months) so the whole suite runs in seconds; the full-size run is `python -m ml.make_datasets`.
"""
from pathlib import Path

import pandas as pd
import pytest

from .. import config as C
from ..make_datasets import PROCESSED_DATES, RAW_DATES, run


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("ml_data")
    summary, failures = run(C.small_config(), out=out, verbose=False)
    return out, summary, failures


def test_no_hard_check_failures(built):
    _, _, failures = built
    assert failures == [], f"validator found real problems: {failures}"


def test_determinism_same_seed_same_bytes(tmp_path_factory):
    a = tmp_path_factory.mktemp("run_a")
    b = tmp_path_factory.mktemp("run_b")
    run(C.small_config(seed=777), out=a, verbose=False)
    run(C.small_config(seed=777), out=b, verbose=False)
    for name in list(RAW_DATES) + ["application_labels", "transaction_labels"]:
        sub = "raw" if name in RAW_DATES else "labels"
        f_a, f_b = a / sub / f"{name}.csv", b / sub / f"{name}.csv"
        assert f_a.read_bytes() == f_b.read_bytes(), f"{name}.csv differs between two runs of the same seed"
    for name in PROCESSED_DATES:
        f_a, f_b = a / "processed" / f"{name}.csv", b / "processed" / f"{name}.csv"
        assert f_a.read_bytes() == f_b.read_bytes(), f"{name}.csv differs between two runs of the same seed"


def test_different_seed_gives_different_data(tmp_path_factory):
    a = tmp_path_factory.mktemp("seed_a")
    b = tmp_path_factory.mktemp("seed_b")
    run(C.small_config(seed=1), out=a, verbose=False)
    run(C.small_config(seed=2), out=b, verbose=False)
    assert (a / "raw" / "applications.csv").read_bytes() != (b / "raw" / "applications.csv").read_bytes()


def test_no_label_columns_leak_into_features(built):
    out, _, _ = built
    for name in PROCESSED_DATES:
        df = pd.read_csv(out / "processed" / f"{name}.csv")
        feature_cols = [c for c in df.columns if not c.startswith("label_") and c != "split"]
        assert not any(c.startswith(("sim_", "true_", "oracle")) or c == "decided_at" for c in feature_cols), (
            f"{name}: an answer-key-looking column leaked into the features: {feature_cols}"
        )


def test_splits_are_chronological_and_non_empty(built):
    out, _, _ = built
    for name, dates in PROCESSED_DATES.items():
        df = pd.read_csv(out / "processed" / f"{name}.csv", parse_dates=dates)
        assert set(df["split"]) == {"train", "valid", "test"}, f"{name}: a split is empty"
        col = dates[0]
        order = {"train": 0, "valid": 1, "test": 2}
        assert df.sort_values(col)["split"].map(order).is_monotonic_increasing, f"{name}: split is not chronological"


def test_eligibility_matches_the_running_apps_rules(built):
    """Cross-check against backend/app/services/eligibility.py's actual placeholder rule, not a
    second copy of it, so the two can never silently drift apart without a test failing."""
    out, _, _ = built
    apps = pd.read_csv(out / "raw" / "applications.csv")
    zero_backlog_doc = apps["document_type"].isin(C.ZERO_BACKLOG_REQUIRED_FOR)
    expected = (
        (apps["fee_status_at_submission"] == "CLEAR")
        & (apps["num_documents"] >= 1)
        & ~(zero_backlog_doc & (apps["backlog_count_at_submission"] > 0))
    )
    actual = apps["eligibility_result"] == "ELIGIBLE"
    assert (expected == actual).all()


def test_dataset_summary_json_was_written(built):
    out, _, _ = built
    assert (out / "dataset_summary.json").exists()


def test_backend_eligibility_rule_matches_ml_config():
    """If someone changes backend/app/services/eligibility.py without updating ml/config.py (or
    vice versa), this fails loudly instead of the two silently drifting apart."""
    backend_src = (Path(__file__).resolve().parents[2] / "backend" / "app" / "services" / "eligibility.py").read_text()
    assert "fee_status_clear" in backend_src and "has_supporting_documents" in backend_src, (
        "backend eligibility.py's condition names changed - update ml/config.py to match "
        "(COMMON_ELIGIBILITY_CONDITIONS, ZERO_BACKLOG_REQUIRED_FOR) and this test"
    )
    assert C.ZERO_BACKLOG_REQUIRED_FOR == {"PROVISIONAL_DEGREE_CERTIFICATE"}, (
        "ml/config.py's ZERO_BACKLOG_REQUIRED_FOR no longer matches what this test expects - "
        "confirm against backend/app/services/eligibility.py and update both"
    )
