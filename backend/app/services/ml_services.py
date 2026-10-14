"""Internal service functions for the three Phase 5 ML components (called by API routes and, in Phase 6, the admin dashboard).

Each function is a thin wrapper over the plain-Python prediction function in the top-level `ml/` package.
All outputs are DECISION SUPPORT for the administrator - none of them decides eligibility, rejects a payment, or
changes an application status. Models were trained on SIMULATED data (docs/DATA_DICTIONARY.md).
"""
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]  # sdp-portal/
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def forecast_demand(*, document_type: str, date) -> float:
    """5.1: expected number of applications for `document_type` on `date` (day-ahead)."""
    from ml import forecasting
    return forecasting.predict_demand(document_type=document_type, date=date)


def forecast_tat_hours(**application_features) -> float:
    """5.1: expected turnaround time in hours for one application (see ml.forecasting.predict_tat)."""
    from ml import forecasting
    return forecasting.predict_tat(**application_features)


def score_manual_review_risk(**application_features) -> dict:
    """5.2: {'manual_review_probability', 'flag_threshold', 'flagged_for_review'}. NOT an eligibility decision."""
    from ml import risk_scoring
    p = risk_scoring.predict_risk(**application_features)
    thr = risk_scoring.review_flag_threshold()
    return {"manual_review_probability": round(p, 4), "flag_threshold": thr, "flagged_for_review": p >= thr}


def score_payment_anomaly(**transaction_features) -> dict:
    """5.3: {'anomaly_score', 'threshold', 'model_flagged', 'rule_flags', 'is_anomaly', 'label'} for one payment attempt."""
    from ml import anomaly
    return anomaly.predict_anomaly(**transaction_features)
