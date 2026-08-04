#!/usr/bin/env bash
set -euo pipefail

# Reads only the public APP_BASE_URL from a server environment file. It does
# not source the file because it contains unrelated secrets.
env_file="${1:-duxue-server/.env.prod}"

if [[ ! -f "$env_file" ]]; then
  echo "Environment file not found: $env_file" >&2
  exit 1
fi

api_base_url="$(sed -n 's/^APP_BASE_URL=//p' "$env_file" | tail -n 1 | sed -E 's/^"(.*)"$/\1/; s/^'"'"'(.*)'"'"'$/\1/')"
if [[ -z "$api_base_url" ]]; then
  echo "APP_BASE_URL is required in $env_file" >&2
  exit 1
fi

api_base_url="${api_base_url%/}"

(cd duxue-cam && gradle :app:assembleRelease -PapiBaseUrl="$api_base_url")
(cd duxue-app && flutter build appbundle --release --dart-define=API_BASE_URL="$api_base_url")
