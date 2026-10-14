#!/bin/sh
# Container start-up: migrate, seed (both idempotent), then start the API.
# Compose only starts this container once PostgreSQL reports healthy; the retry loop below is a
# second safety net for the moment right after the database accepts connections.
set -e

echo "[entrypoint] Applying database migrations (alembic upgrade head)..."
attempt=1
until alembic upgrade head; do
  if [ "$attempt" -ge 10 ]; then
    echo "[entrypoint] Migrations still failing after $attempt attempts - giving up." >&2
    exit 1
  fi
  echo "[entrypoint] Database not ready yet (attempt $attempt/10); retrying in 3s..."
  attempt=$((attempt + 1))
  sleep 3
done

echo "[entrypoint] Seeding document types and SIMULATED students (safe to re-run; adds only missing rows)..."
python -m app.db.seed
python -m app.db.seed_students

echo "[entrypoint] Starting: $*"
exec "$@"
