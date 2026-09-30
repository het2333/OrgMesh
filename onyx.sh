#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$project_dir/deployment/docker_compose"

if [[ ! -f .env ]]; then
  printf 'Missing deployment/docker_compose/.env. See README.orgmesh.md.\n' >&2
  exit 1
fi

if [[ $# -eq 0 ]]; then
  set -- up -d --no-build --wait --wait-timeout 600
fi

exec docker compose --env-file .env --project-name orgmesh "$@"
