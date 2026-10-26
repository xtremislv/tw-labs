#!/usr/bin/env bash
# Apply pending migrations (no-op when current), then run the given command:
# uvicorn for the API container, `python -m app.worker` for the worker.
set -euo pipefail
echo "[entrypoint] Applying database migrations..."
alembic upgrade head
echo "[entrypoint] Starting: $*"
exec "$@"
