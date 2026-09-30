#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
source_dir="$project_dir/.orgmesh-local/presenton-src"
stage_dir="$project_dir/.orgmesh-local/presenton-build"
revision="2dcbde772ce46687c5c220f4e1e4886bdfe91cc9"
if [[ ! -d "$source_dir/.git" ]]; then
  git clone https://github.com/presenton/presenton.git "$source_dir"
  git -C "$source_dir" checkout "$revision"
fi
[[ "$(git -C "$source_dir" rev-parse HEAD)" == "$revision" ]] || { printf 'Unexpected Presenton revision\n' >&2; exit 1; }
python3 "$project_dir/integrations/presenton/prepare_templates.py" "$source_dir"
python3 "$project_dir/integrations/presenton/prepare_backend.py" "$source_dir"
python3 "$project_dir/integrations/presenton/prepare_frontend.py" "$source_dir"
cd "$source_dir/servers/nextjs"
export NEXT_TELEMETRY_DISABLED=1
export NODE_OPTIONS="${NODE_OPTIONS:---max-old-space-size=3072}"
if [[ ! -d node_modules ]]; then npm ci --ignore-scripts; fi
npm run build
python3 - "$project_dir" "$source_dir" "$stage_dir" <<'PY'
import shutil
import sys
from pathlib import Path
root, source, stage = map(Path, sys.argv[1:])
if stage.exists():
    shutil.rmtree(stage)
stage.mkdir(parents=True)
shutil.copytree(source / 'servers/fastapi', stage / 'fastapi', ignore=shutil.ignore_patterns('.venv', '__pycache__', '.pytest_cache', '*.pyc', 'tests', 'logs'))
shutil.copytree(source / 'servers/nextjs/.next-build/standalone', stage / 'nextjs', symlinks=True, ignore=shutil.ignore_patterns('node_modules'))
shutil.copytree(source / 'servers/nextjs/.next-build/static', stage / 'nextjs/.next-build/static')
shutil.copytree(source / 'servers/nextjs/public', stage / 'nextjs/public', dirs_exist_ok=True)
shutil.copy2(source / 'nginx.conf', stage / 'nginx.conf')
shutil.copytree(source / 'templates', stage / 'templates')
for filename in ('LICENSE', 'NOTICE'):
    shutil.copy2(source / filename, stage / filename)
PY
docker build -t orgmesh-presenton:local -f "$project_dir/integrations/presenton/Dockerfile" "$stage_dir"
