#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$project_dir/deployment/docker_compose"
if [[ ! -f .env.private ]]; then
  printf 'Run deployment/init_orgmesh_private.py first. See README.orgmesh.md.\n' >&2
  exit 1
fi
if [[ $# -eq 0 ]]; then
  set -- up -d --no-build --wait --wait-timeout 600
fi
presenton_files=()
while IFS= read -r env_line; do
  if [[ "$env_line" == ORGMESH_PRESENTON_SECRET=* ]]; then
    presenton_files=(-f docker-compose.orgmesh-presenton.yml)
    break
  fi
done < .env.private
exec docker compose --env-file .env.private --project-name orgmesh-private \
  -f docker-compose.yml -f docker-compose.orgmesh-full.yml \
  -f docker-compose.orgmesh-private.yml "${presenton_files[@]}" "$@"
