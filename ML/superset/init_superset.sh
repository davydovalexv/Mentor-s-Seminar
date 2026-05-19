#!/bin/sh
set -e

superset db upgrade
superset fab create-admin \
  --username admin \
  --firstname Admin \
  --lastname User \
  --email admin@local.dev \
  --password admin || true
superset init

exec gunicorn \
  --bind "0.0.0.0:8088" \
  --workers 2 \
  --timeout 120 \
  "superset.app:create_app()"
