import json
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ folder and backend/.env, resolved relative to this file so it works from any cwd
BACKEND_DIR = Path(__file__).resolve().parents[2]
ENV_FILE = BACKEND_DIR / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "SDP Document Portal API"
    database_url: str  # required: no default on purpose, so a missing .env fails loudly
    cors_origins: str = "http://localhost:3000"

    # --- Phase 2: authentication ---
    secret_key: str  # required; signs JWT login tokens
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # --- Phase 2: uploads ---
    upload_dir: str = "uploads"  # relative paths are resolved against backend/
    max_upload_mb: int = 5
    max_files_per_application: int = 5  # maximum files per application (configurable)

    # --- Eligibility policy configuration (externalised from the engine code) ---
    # JSON dict mapping a rule name -> {"verified": bool}. The eligibility ENGINE decides how a
    # named rule is evaluated; this setting only controls whether that rule counts as confirmed
    # institutional policy. A failed VERIFIED mandatory rule -> NOT_ELIGIBLE; a failed UNVERIFIED
    # rule -> MANUAL_REVIEW (never an automatic academic rejection). Unknown names in the JSON are
    # ignored by the engine, so this can never invent new restrictions on its own.
    # Defaults mirror the documented placeholder policy (see SDP_BUILD_GUIDE section 1.4 and the
    # engine docstring): fee-clearance blocks every request type and zero backlogs is required for
    # a Provisional Degree Certificate. These are the project's established working policy — the
    # existing stored-status behaviour (NOT_ELIGIBLE on failure) is preserved by keeping them
    # verified=true here. To reclassify either rule as unconfirmed institutional policy, set
    # ELIGIBILITY_POLICY_JSON with "verified": false; failing rules then route to MANUAL_REVIEW
    # instead of an automatic academic rejection. has_supporting_documents is a completeness check
    # (an application with no documents cannot be processed), verified=true.
    eligibility_policy_json: str = (
        '{"fee_status_clear": {"verified": true},'
        ' "no_outstanding_backlogs": {"verified": true},'
        ' "has_supporting_documents": {"verified": true}}'
    )

    @field_validator("eligibility_policy_json")
    @classmethod
    def eligibility_policy_must_be_valid_json(cls, v: str) -> str:
        parsed = json.loads(v)  # raises loudly at startup if misconfigured
        if not isinstance(parsed, dict):
            raise ValueError("ELIGIBILITY_POLICY_JSON must be a JSON object")
        for name, cfg in parsed.items():
            if not isinstance(cfg, dict) or not isinstance(cfg.get("verified"), bool):
                raise ValueError(
                    f"ELIGIBILITY_POLICY_JSON['{name}'] must be an object with a boolean 'verified'"
                )
        return v

    @property
    def eligibility_policy(self) -> dict[str, dict]:
        """Parsed eligibility policy (re-read every call so runtime overrides apply live)."""
        return json.loads(self.eligibility_policy_json)

    @field_validator("secret_key")
    @classmethod
    def secret_key_must_be_real(cls, v: str) -> str:
        if v.startswith("CHANGE_ME") or len(v) < 32:
            raise ValueError(
                "SECRET_KEY must be a random value of at least 32 characters. Generate one with: "
                'python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def upload_path(self) -> Path:
        p = Path(self.upload_dir)
        return p if p.is_absolute() else BACKEND_DIR / p

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


settings = Settings()
