"""All three Phase 5 models called together through the internal service layer, in one process (no DB needed)."""
from app.services import ml_services as S


def test_three_models_work_together_without_interfering():
    d1 = S.forecast_demand(document_type="TRANSCRIPT", date="2026-09-01")
    t1 = S.forecast_tat_hours(document_type="TRANSCRIPT", num_documents=1, is_alumni=0, submitted_at="2026-09-02 10:00",
                              queue_open_at_submission=12, apps_prev_24h=5, apps_prev_7d=30, doc_apps_prev_7d=15)
    r1 = S.score_manual_review_risk(document_type="TRANSCRIPT", department="CSE", semester=7, cgpa=7.5, backlog_count=1)
    a1 = S.score_payment_anomaly(document_type="TRANSCRIPT", amount=200.0, payment_status="SUCCESS")
    # interleave again in a different order: results must be identical (no shared state / cross-talk)
    a2 = S.score_payment_anomaly(document_type="TRANSCRIPT", amount=200.0, payment_status="SUCCESS")
    r2 = S.score_manual_review_risk(document_type="TRANSCRIPT", department="CSE", semester=7, cgpa=7.5, backlog_count=1)
    t2 = S.forecast_tat_hours(document_type="TRANSCRIPT", num_documents=1, is_alumni=0, submitted_at="2026-09-02 10:00",
                              queue_open_at_submission=12, apps_prev_24h=5, apps_prev_7d=30, doc_apps_prev_7d=15)
    d2 = S.forecast_demand(document_type="TRANSCRIPT", date="2026-09-01")
    assert (d1, t1, r1, a1) == (d2, t2, r2, a2)
    assert 0 <= d1 < 40 and 0 < t1 < 300
    assert 0 <= r1["manual_review_probability"] <= 1 and "eligible" not in str(r1).lower().replace("eligibility", "")
    assert a1["label"] in ("NORMAL", "ANOMALOUS")
