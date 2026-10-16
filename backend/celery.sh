#!/usr/bin/env bash
# celery worker -A celery_worker.celery --loglevel=DEBUG
#
# OSINT modules are network-bound and very uneven in duration (maigret /
# wayback / whatsmyname take minutes, most others seconds), so:
#   --concurrency      more slots than CPUs (VEILED_WORKERS, default 12)
#   -O fair            hand a task only to a free slot
#   --prefetch-multiplier=1  never queue short tasks behind a slow one
celery -A celery_worker.celery worker --loglevel=INFO \
    --concurrency="${VEILED_WORKERS:-12}" -O fair --prefetch-multiplier=1
