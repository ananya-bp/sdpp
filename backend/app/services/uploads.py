"""Validation and storage of supporting-document uploads.

Central upload limits (file count and file size) live in app.core.config.Settings and can be
configured via environment variables MAX_FILES_PER_APPLICATION and MAX_UPLOAD_MB.
Both the backend and the frontend derive their limits from those values.

The limits are exposed through module-level ``__getattr__`` so that consumers importing
``MAX_FILES_PER_APPLICATION`` / ``MAX_UPLOAD_BYTES`` always read the *current* settings value,
never an import-time snapshot (tests monkeypatch settings at runtime).
"""
import hashlib
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException, UploadFile

from app.core.config import settings


def _module_getattr(name: str):
    """Module-level fallback: dynamic constants that track the live centralized settings.

    Consumers importing ``MAX_FILES_PER_APPLICATION`` / ``MAX_UPLOAD_BYTES`` from this module
    always get the current settings value, never an import-time snapshot. Internal code reads
    the settings directly via _max_files() / _max_upload_bytes() below.
    """
    if name == "MAX_FILES_PER_APPLICATION":
        return settings.max_files_per_application
    if name == "MAX_UPLOAD_BYTES":
        return settings.max_upload_bytes
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


import sys  # noqa: E402  (must run at import time: installs the dynamic constants)

sys.modules[__name__].__getattr__ = _module_getattr


def _max_files() -> int:
    """Current per-application file-count limit (live setting, never an import-time snapshot)."""
    return settings.max_files_per_application


def _max_upload_bytes() -> int:
    """Current per-file size limit in bytes (live setting; 5 MB = 5 * 1024 * 1024 by default)."""
    return settings.max_upload_bytes

# extension -> (content type, required leading bytes). The real file type is decided from the
# file's own bytes, never from the browser-supplied content type.
_TYPES = {
    "pdf": ("application/pdf", (b"%PDF-",)),
    "jpg": ("image/jpeg", (b"\xff\xd8\xff",)),
    "jpeg": ("image/jpeg", (b"\xff\xd8\xff",)),
    "png": ("image/png", (b"\x89PNG\r\n\x1a\n",)),
}
ALLOWED_DESCRIPTION = "PDF, JPG or PNG"
ALLOWED_EXTENSIONS = frozenset(_TYPES)  # pdf, jpg, jpeg, png — single source of truth


@dataclass
class ValidatedUpload:
    original_filename: str
    extension: str
    content_type: str
    data: bytes

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


def _clean_filename(name: str) -> str:
    """Keep only the base name (no directories) and cap the length."""
    base = os.path.basename(name.replace("\\", "/")).strip()
    return (base or "file")[:255]


def validate_upload(upload: UploadFile) -> ValidatedUpload:
    filename = _clean_filename(upload.filename or "")
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in _TYPES:
        raise HTTPException(400, f"'{filename}': only {ALLOWED_DESCRIPTION} files are allowed.")

    # Read one byte past the limit so an oversized file is detected without loading all of it.
    # _max_upload_bytes() always resolves to the *current* centralized setting.
    limit_bytes = _max_upload_bytes()
    data = upload.file.read(limit_bytes + 1)
    if len(data) > limit_bytes:
        raise HTTPException(413, f"'{filename}': file is larger than {settings.max_upload_mb} MB.")
    if not data:
        raise HTTPException(400, f"'{filename}': file is empty.")

    content_type, signatures = _TYPES[extension]
    if not data.startswith(signatures):
        raise HTTPException(400, f"'{filename}': file content does not match its {extension.upper()} extension.")

    return ValidatedUpload(filename, extension, content_type, data)


def validate_uploads(uploads: list[UploadFile]) -> list[ValidatedUpload]:
    """Validate a batch of uploads: type, signature, size, count, and duplicates.

    Duplicate policy (compatible with the existing workflow):
    - The same file (same name AND same bytes) sent twice in one request is treated as an
      accidental repeat — it is stored once instead of failing the whole application.
    - Identical bytes uploaded under DIFFERENT names are rejected: that pattern indicates a
      student trying to pass one document off as two separate supporting documents.
    """
    # Browsers send an empty file part when no file was chosen; ignore those.
    real = [u for u in uploads if u.filename]
    limit = _max_files()  # live: current centralized setting

    validated: list[ValidatedUpload] = []
    seen_exact: set[tuple[str, int]] = set()   # (filename, size) already accepted this batch
    seen_content: dict[str, str] = {}          # sha256 -> filename it first appeared with
    for u in real:
        item = validate_upload(u)  # also enforces the per-file size limit
        key = (item.original_filename, len(item.data))
        if key in seen_exact:
            continue  # same file sent twice under the same name: keep one copy
        h = item.sha256
        previous = seen_content.get(h)
        if previous is not None:
            raise HTTPException(
                400,
                f"'{item.original_filename}': duplicate file — the same content was already "
                f"added as '{previous}'.",
            )
        seen_content[h] = item.original_filename
        seen_exact.add(key)
        validated.append(item)
        if len(validated) > limit:
            raise HTTPException(400, f"At most {limit} files can be uploaded per application.")
    return validated


def store_file(application_id: int, item: ValidatedUpload) -> str:
    """Write the file under UPLOAD_DIR/<application_id>/ with a random name; return the relative path."""
    folder = settings.upload_path / str(application_id)
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}.{'jpg' if item.extension == 'jpeg' else item.extension}"
    (folder / name).write_bytes(item.data)
    return f"{application_id}/{name}"


def remove_stored_files(relative_paths: list[str]) -> None:
    """Best-effort cleanup used when saving an application fails part-way."""
    for rel in relative_paths:
        try:
            (settings.upload_path / rel).unlink(missing_ok=True)
        except OSError:
            pass
    for folder in {Path(rel).parent for rel in relative_paths}:
        try:
            (settings.upload_path / folder).rmdir()  # only succeeds if empty
        except OSError:
            pass
