#!/usr/bin/env bash
# Copies what the stack needs from the team repo futury_4_2026 into hub/:
#   backend/ (code), config.yaml, data/reference/ (CSVs and the Parquet seed the database is built from).
# Not copied: data/hub.duckdb (built from the seed in the image), data/raw_events/ (only for the offline fetch),
# .env (secrets: DEEPSEEK_API_KEY goes into this repo's .env), docs, tests, scripts.
#
#   scripts/sync-hub.sh                     # team repo next to this one
#   HUB_DIR=/path/to/futury_4_2026 scripts/sync-hub.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${HUB_DIR:-$ROOT/../futury_4_2026}"
DST="$ROOT/hub"

[ -f "$SRC/backend/api.py" ] || { echo "No team repo at $SRC (set HUB_DIR)" >&2; exit 1; }

mkdir -p "$DST/data/reference"
rsync -a --delete --exclude '__pycache__/' --exclude '*.pyc' "$SRC/backend/" "$DST/backend/"
cp "$SRC/config.yaml" "$DST/config.yaml"
rsync -a --delete --exclude '.DS_Store' "$SRC/data/reference/" "$DST/data/reference/"

# Which state was copied, so a later sync shows what changed.
{
  echo "Copied from futury_4_2026 by scripts/sync-hub.sh on $(date -u +%Y-%m-%dT%H:%MZ)"
  echo "commit: $(git -C "$SRC" rev-parse --short HEAD 2>/dev/null || echo unknown)"
  dirty="$(git -C "$SRC" status --porcelain -- backend config.yaml data/reference 2>/dev/null || true)"
  if [ -n "$dirty" ]; then echo "uncommitted changes included:"; echo "$dirty"; fi
} > "$DST/SOURCE.txt"

cat "$DST/SOURCE.txt"
du -sh "$DST"
