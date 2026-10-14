"""Phase 5.1 - thin forecasting endpoints (admin decision support only).

Wraps ml/forecasting.py; the trained artifact lives in ml/models/. No DB schema changes.
The model was trained on SIMULATED data (docs/DATA_DICTIONARY.md).
"""
import sys
from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import get_current_user
from app.models import User

# make the sibling `ml/` package importable (project layout: sdp-portal/{backend,ml})
_PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

router = APIRouter(prefix="/forecast", tags=["forecast"])


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin account required")
    return user


def _forecasting():
    try:
        from ml import forecasting
        forecasting._load()
        return forecasting
    except FileNotFoundError:
        raise HTTPException(status_code=503, detail="Forecast model not trained yet (run python -m ml.forecasting)")


class DemandOut(BaseModel):
    document_type: str
    date: date
    expected_applications: float


class TatIn(BaseModel):
    document_type: str
    num_documents: int = Field(ge=0, le=20)
    is_alumni: bool = False
    submitted_at: datetime
    queue_open_at_submission: int = Field(ge=0)
    apps_prev_24h: int = Field(ge=0)
    apps_prev_7d: int = Field(ge=0)
    doc_apps_prev_7d: int = Field(ge=0)


class TatOut(BaseModel):
    expected_tat_hours: float


@router.get("/demand", response_model=DemandOut)
def forecast_demand(document_type: str, date: date, _: User = Depends(require_admin)):
    """Day-ahead expected application count (date must be the day after the last day of history, or inside it)."""
    f = _forecasting()
    if document_type not in f._load()["demand"]["cats"]["document_type"]:
        raise HTTPException(status_code=422, detail="Unknown document_type for the forecasting model")
    try:
        value = f.predict_demand(document_type=document_type, date=date)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return DemandOut(document_type=document_type, date=date, expected_applications=round(value, 2))


@router.post("/tat", response_model=TatOut)
def forecast_tat(body: TatIn, _: User = Depends(require_admin)):
    """Expected turnaround (hours) for one application, from submission-time information."""
    f = _forecasting()
    if body.document_type not in f._load()["tat"]["cats"]["document_type"]:
        raise HTTPException(status_code=422, detail="Unknown document_type for the forecasting model")
    hours = f.predict_tat(**{**body.model_dump(), "is_alumni": int(body.is_alumni)})
    return TatOut(expected_tat_hours=round(hours, 2))
