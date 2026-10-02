#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "${ORGMESH_BUILD_WORD:-false}" == "true" ]]; then
  bash "$project_dir/deployment/build_orgmesh_word.sh"
fi
cd "$project_dir/web"

export NEXT_PUBLIC_DISABLE_LOGOUT=false
export NEXT_TELEMETRY_DISABLED=1
export NEXT_PRIVATE_STANDALONE=true
export NODE_OPTIONS="${NODE_OPTIONS:---max-old-space-size=3072}"
export GOMAXPROCS="${GOMAXPROCS:-2}"
export RAYON_NUM_THREADS="${RAYON_NUM_THREADS:-2}"

bun install --frozen-lockfile --ignore-scripts
(cd lib/shared && bun run build)
# The web app type-checks Opal source through its @opal alias.
# Runtime bundling needs JavaScript and CSS, not a separate declaration bundle.
(cd lib/opal && ./node_modules/.bin/tsup --no-dts && node scripts/bundle-css.mjs)
bun run types:check
bun run build

python3 - <<'PY'
from pathlib import Path
import shutil

root = Path.cwd().parent
stage = root / ".orgmesh-local" / "frontend"
if stage.exists():
    shutil.rmtree(stage)
stage.mkdir(parents=True)
shutil.copy2(root / "web/.next/standalone/server.js", stage / "server.js")
shutil.copytree(root / "web/.next/standalone/.next", stage / "next", symlinks=True)
shutil.copytree(root / "web/.next/static", stage / "static")
shutil.copytree(root / "web/public", stage / "public")
PY

docker build -t orgmesh-web:local -f "$project_dir/deployment/Dockerfile.orgmesh-web" "$project_dir/.orgmesh-local/frontend"
