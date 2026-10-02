#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir/vendor/genoffice"
npm ci --ignore-scripts --no-audit --no-fund
npm run typecheck -w @genoffice/docs
npm run build:browser -w @genoffice/docs
cd "$project_dir"
node tools/check_genoffice_browser_boundary.mjs
node tools/stage_word_browser.mjs
