#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if ! command -v quarto >/dev/null 2>&1; then
  echo "error: Quarto is required to build the project site" >&2
  exit 1
fi

quarto render "$ROOT_DIR/site"

test -s "$ROOT_DIR/site/_site/index.html"
test -s "$ROOT_DIR/site/_site/tui.html"
test -s "$ROOT_DIR/site/_site/paper/paper.html"
test -s "$ROOT_DIR/site/_site/paper/OASIS_technical_report.pdf"
test -s "$ROOT_DIR/site/_site/publication.json"
test -s "$ROOT_DIR/site/_site/SHA256SUMS"

python3 "$ROOT_DIR/scripts/check-site.py"

echo "Rendered OASIS project site: $ROOT_DIR/site/_site"
