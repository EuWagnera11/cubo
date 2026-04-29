#!/bin/sh
# entrypoint multi-mode: roda API, worker ou beat conforme SERVICE_MODE
set -e

MODE="${SERVICE_MODE:-api}"

case "$MODE" in
  api)
    exec uvicorn api.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 2
    ;;
  worker)
    exec celery -A api.workers:celery_app worker --loglevel=info --concurrency=4
    ;;
  beat)
    exec celery -A api.workers:celery_app beat --loglevel=info
    ;;
  *)
    echo "ERROR: SERVICE_MODE deve ser 'api', 'worker' ou 'beat'. Recebido: '$MODE'"
    exit 1
    ;;
esac
