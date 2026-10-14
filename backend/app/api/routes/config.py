"""Student-facing configuration endpoints.

Exposes ONLY public, non-secret configuration the student portal needs so the frontend never
keeps conflicting hardcoded copies of backend limits:

  GET /api/config/limits  -> current upload limits + allowed file types (live settings)
  GET /api/config/forms   -> per-request-type form fields & document checklists

Limits are read dynamically at request time from app.core.config.Settings, so changing
MAX_UPLOAD_MB / MAX_FILES_PER_APPLICATION (env or runtime) is reflected immediately and stays
consistent with what POST /api/applications enforces server-side.

No administrative configuration, secrets, or eligibility-rule internals are exposed here.
"""
from fastapi import APIRouter

from app.core.config import settings
from app.services import request_specs
from app.services import uploads

router = APIRouter(prefix="/config", tags=["config"])


@router.get("/limits")
def get_upload_limits():
    """Current centralized upload limits, read live from settings (never an import-time snapshot)."""
    return {
        "max_upload_mb": settings.max_upload_mb,
        "max_upload_bytes": uploads._max_upload_bytes(),
        "max_files_per_application": uploads._max_files(),
        "allowed_extensions": sorted(uploads.ALLOWED_EXTENSIONS),
        "allowed_description": uploads.ALLOWED_DESCRIPTION,
    }


@router.get("/forms")
def get_form_specs():
    """Request-specific fields and supporting-document checklists for the four request types.
    Every spec carries verified=false until confirmed against official KLE Tech policy; the UI
    must label these requirements as unverified.
    """
    return request_specs.forms_payload()


@router.get("/checklists")
def get_checklists():
    """Document-based eligibility checklists for the four application types (live policy).

    Conditional ("if required by the university") items are shown with their CURRENT configured
    requirement state — read live from settings, so a toggled policy flag is reflected without
    code changes. Items remain labelled UNVERIFIED until confirmed against official policy.
    """
    from app.services import document_checklist

    codes = [
        "TRANSCRIPT",
        "MIGRATION_CERTIFICATE",
        "DUPLICATE_GRADE_CARD",
        "PROVISIONAL_DEGREE_CERTIFICATE",
    ]
    return {"checklists": [document_checklist.checklist_payload(c) for c in codes]}
