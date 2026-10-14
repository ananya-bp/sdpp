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
