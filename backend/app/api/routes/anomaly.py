"""Phase 5.3 - thin anomaly-scoring endpoint (admin decision support only).

Flags a payment attempt as NORMAL or ANOMALOUS for administrator review. It never blocks, rejects or changes anything.
Wraps ml/anomaly.py (Isolation Forest + a deterministic amount-mismatch rule) via services/ml_services.py.
Artifact lives in ml/models/. No DB schema changes. Model trained on SIMULATED data.
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.routes.forecast import require_admin  # same admin-only convention as Phase 5.1 / 5.2
from app.models import User
from app.services import ml_services

router = APIRouter(prefix="/anomaly", tags=["anomaly"])


class AnomalyIn(BaseModel):
    document_type: Literal["TRANSCRIPT", "MIGRATION_CERTIFICATE", "DUPLICATE_GRADE_CARD", "PROVISIONAL_DEGREE_CERTIFICATE"]
    amount: float = Field(ge=0)
    payment_status: Literal["FAILED", "PENDING", "SUCCESS"]
    attempt_index: int = Field(default=1, ge=1)
    failed_attempts_before: int = Field(default=0, ge=0)
    seconds_since_prev_attempt: float = Field(default=86400.0, ge=0, description="86400 for a first attempt (dataset convention)")
    student_txns_prior_24h: int = Field(default=0, ge=0)
    student_other_apps_24h: int = Field(default=0, ge=0)
    student_other_apps_7d: int = Field(default=0, ge=0)
    same_doc_other_apps_7d: int = Field(default=0, ge=0)
    same_doc_other_paid_apps_7d: int = Field(default=0, ge=0)


class AnomalyOut(BaseModel):
    label: Literal["NORMAL", "ANOMALOUS"]
    is_anomaly: bool
    anomaly_score: float
    threshold: float
    model_flagged: bool
    rule_flags: list[str]
    note: str = "Decision support only - nothing is blocked or rejected automatically. The administrator makes the final call."


@router.post("/score", response_model=AnomalyOut)
def score_anomaly(body: AnomalyIn, _: User = Depends(require_admin)):
    try:
        return AnomalyOut(**ml_services.score_payment_anomaly(**body.model_dump()))
    except FileNotFoundError:
        raise HTTPException(status_code=503, detail="Anomaly model not trained yet (run python -m ml.anomaly)")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
