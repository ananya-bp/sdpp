# Backend image: FastAPI + OCR (Tesseract + Poppler) + the Phase 5 ML package.
# BUILD CONTEXT IS THE PROJECT ROOT (see compose.yaml): the backend imports the top-level `ml/` package,
# and app/services/ml_services.py finds it at <project root>/ml, so the image keeps the same layout:
#   /srv/sdp/backend  (this app)      /srv/sdp/ml  (code + trained *.joblib + data/processed CSVs)
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# tesseract-ocr + poppler-utils: used by pytesseract / pdf2image (app/services/ocr.py)
# libgomp1: OpenMP runtime needed by LightGBM (forecasting model)
# fonts-dejavu-core: the OCR tests draw sample documents with this font (lets `pytest` run in the container)
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng poppler-utils libgomp1 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/sdp/backend

# Dependencies first so code changes don't reinstall them.
COPY backend/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

COPY backend/ ./
COPY ml/ /srv/sdp/ml/

# Normalise line endings (Windows checkouts may use CRLF, which breaks the shebang), make executable.
RUN sed -i 's/\r$//' docker-entrypoint.sh && chmod +x docker-entrypoint.sh

# Run as an unprivileged user. /data/uploads is created and owned by it BEFORE the named volume is
# mounted there, so the volume inherits writable ownership.
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /data/uploads \
    && chown -R app:app /data /srv/sdp
USER app

ENV UPLOAD_DIR=/data/uploads
EXPOSE 8000
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
