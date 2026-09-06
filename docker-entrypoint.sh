#!/bin/sh
# Migrate, then serve. Decision D86.
#
# The retry is not superstition. On Railway the private network comes up a moment after the
# container does, and on a first deploy the database service may still be starting, so the
# very first connection this process makes is the one most likely to fail for a reason that
# has nothing to do with the application. Ten attempts is about thirty seconds of patience.
#
# It gives up loudly rather than starting anyway. A server running against a schema that was
# never migrated fails later, further from the cause, and looks like a bug in the product.

set -e

attempt=1
until alembic upgrade head; do
    if [ "$attempt" -ge 10 ]; then
        echo "distill: migrations failed after $attempt attempts, giving up" >&2
        exit 1
    fi
    echo "distill: database not ready (attempt $attempt), retrying in 3s" >&2
    attempt=$((attempt + 1))
    sleep 3
done

# One worker, always. The document queue and the event bus are both in-process (decisions
# D9 and D14), so a second worker is a second queue whose events no browser can see.
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1
