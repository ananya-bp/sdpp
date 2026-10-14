"""Phase 5.2 - thin risk-scoring endpoint (admin decision support only).

Returns the model's 0-1 probability that an application will need MANUAL REVIEW. It is NOT an eligibility
decision: ELIGIBLE / NOT_ELIGIBLE still comes only from services/eligibility.py. Wraps ml/risk_scoring.py;
the trained artifact lives in ml/models/. No DB schema changes. Model trained on SIMULATED data.
"""
import sys
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.routes.forecast import require_admin  # same admin-only convention as Phase 5.1
from app.models import User

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

router = APIRouter(prefix="/risk", tags=["risk"])


class RiskIn(BaseModel):
    document_type: Literal["TRANSCRIPT", "MIGRATION_CERTIFICATE", "DUPLICATE_GRADE_CARD", "PROVISIONAL_DEGREE_CERTIFICATE"]
    department: str = Field(description="Department code (CSE, ECE, EEE, MEC, CIV) or full name")
    semester: int = Field(ge=1, le=8)
    cgpa: float = Field(ge=0, le=10)
    backlog_count: int = Field(ge=0, le=30)
    is_alumni: bool = False
    past_fee_delays_12m: int = Field(default=0, ge=0, le=12)
    prior_apps_count: int = Field(default=0, ge=0)
    prior_review_count_lagged: int = Field(default=0, ge=0)
    num_documents: int = Field(default=1, ge=1, le=5)
    ocr_failed: bool = False
    ocr_detected_cgpa: float | None = Field(default=None, ge=0, le=10)


class RiskOut(BaseModel):
    manual_review_probability: float = Field(ge=0.0, le=1.0)
    flag_threshold: float
    flagged_for_review: bool
    note: str = "Decision support only - not an eligibility decision. The administrator makes the final call."


@router.post("/score", response_model=RiskOut)
def score_risk(body: RiskIn, _: User = Depends(require_admin)):
    try:
        from ml import risk_scoring as rs
        rs._load()
    except FileNotFoundError:
        raise HTTPException(status_code=503, detail="Risk model not trained yet (run python -m ml.risk_scoring)")
    try:
        p = rs.predict_risk(**body.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    thr = rs.review_flag_threshold()
    return RiskOut(manual_review_probability=round(p, 4), flag_threshold=thr, flagged_for_review=p >= thr)
