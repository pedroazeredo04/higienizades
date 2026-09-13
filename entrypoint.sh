#!/bin/sh
# Migrate, then serve. Running migrations here (rather than inside the app)
# keeps startup explicit and means a failed migration stops the container
# instead of leaving it half-working.
set -e

alembic upgrade head

# One worker on purpose: SQLite serialises writes cleanly within a single
# process, and a household of flatmates is nowhere near one worker's limit.
exec uvicorn app.main:app --host 0.0.0.0 --port 3000 --workers 1
