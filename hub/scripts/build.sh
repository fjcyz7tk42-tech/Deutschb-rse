#!/usr/bin/env sh
# Build data/hub.duckdb from data/raw: load, master data, metrics, triage, forensics. Re-runnable.
set -e
cd "$(dirname "$0")/.."
uv run python -m backend.loader --all
uv run python -m backend.masterdata
uv run python -m backend.analytics
uv run python -m backend.triage
uv run python -m backend.forensics
