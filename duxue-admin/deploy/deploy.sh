#!/bin/sh
set -eu
cd /home/duxue/duxue-admin
# Shared secret/database/provider settings remain only on ECS.
export DUXUE_ADMIN_IMAGE="$1" DUXUE_ADMIN_EXECUTOR_IMAGE="$2"
compose() { docker compose --env-file .env.prod -f docker-compose.yml "$@"; }
compose pull
compose run --rm --no-deps -T admin node ops/setup.cjs migrate
if ! compose up -d --wait --wait-timeout 180; then
  if [ -f images.env ]; then
    # This file is generated below and contains only immutable image references.
    . ./images.env
    export DUXUE_ADMIN_IMAGE DUXUE_ADMIN_EXECUTOR_IMAGE
    compose up -d --wait --wait-timeout 180
  fi
  exit 1
fi
if ! curl --fail --retry 10 --retry-delay 3 --retry-connrefused http://127.0.0.1:3021/api/health; then
  if [ -f images.env ]; then
    . ./images.env
    export DUXUE_ADMIN_IMAGE DUXUE_ADMIN_EXECUTOR_IMAGE
    compose up -d --wait --wait-timeout 180
  fi
  exit 1
fi
# Preserve exact images for restart/rollback; do not expose secret values.
printf 'DUXUE_ADMIN_IMAGE=%s\nDUXUE_ADMIN_EXECUTOR_IMAGE=%s\n' "$DUXUE_ADMIN_IMAGE" "$DUXUE_ADMIN_EXECUTOR_IMAGE" > images.env
