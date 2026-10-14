"""Validation and storage of supporting-document uploads.

Central upload limits (file count and file size) live in app.core.config.Settings and can be
configured via environment variables MAX_FILES_PER_APPLICATION and MAX_UPLOAD_MB.
Both the backend and the frontend derive their limits from those values.
"""
import hashlib
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException, UploadFile

from app.core.config import settings

# Module-level alias so `uploads.MAX_FILES_PER_APPLICATION` works without calling Settings.
# Resolved at import time: safe because settings is a singleton.
MAX_FILES_PER_APPLICATION = settings.max_files_per_application

# extension -> (content type, required leading bytes). The real file type is decided from the
# file's own bytes, never from the browser-supplied content type.
_TYPES = {
    "pdf": ("application/pdf", (b"%PDF-",)),
    "jpg": ("image/jpeg", (b"\xff\xd8\xff",)),
    "jpeg": ("image/jpeg", (b"\xff\xd8\xff",)),
    "png": ("image/png", (b"\x89PNG\r\n\x1a\n",)),
}
ALLOWED_DESCRIPTION = "PDF, JPG or PNG"


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
    data = upload.file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(413, f"'{filename}': file is larger than {settings.max_upload_mb} MB.")
    if not data:
        raise HTTPException(400, f"'{filename}': file is empty.")

    content_type, signatures = _TYPES[extension]
    if not data.startswith(signatures):
        raise HTTPException(400, f"'{filename}': file content does not match its {extension.upper()} extension.")

    return ValidatedUpload(filename, extension, content_type, data)


def validate_uploads(uploads: list[UploadFile]) -> list[ValidatedUpload]:
    """Validate a batch of uploads: type, signature, size, count, and duplicates."""
    # Browsers send an empty file part when no file was chosen; ignore those.
    real = [u for u in uploads if u.filename]
    limit = settings.max_files_per_application
    if len(real) > limit:
        raise HTTPException(400, f"At most {limit} files can be uploaded per application.")

    validated: list[ValidatedUpload] = []
    seen_hashes: set[str] = set()
    for u in real:
        item = validate_upload(u)
        h = item.sha256
        if h in seen_hashes:
            raise HTTPException(
                400, f"'{item.original_filename}': duplicate file — this file has already been added."
            )
        seen_hashes.add(h)
        validated.append(item)
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
