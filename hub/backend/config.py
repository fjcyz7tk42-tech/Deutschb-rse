"""Reads config.yaml and .env. One place for thresholds and paths."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _dotenv() -> dict:
    path = ROOT / ".env"
    if not path.exists():
        return {}
    pairs = (line.split("=", 1) for line in path.read_text().splitlines() if "=" in line and not line.startswith("#"))
    return {k.strip(): v.strip() for k, v in pairs}


def load_config() -> dict:
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    env = _dotenv()
    cfg["DEEPSEEK_API_KEY"] = os.environ.get("DEEPSEEK_API_KEY") or env.get("DEEPSEEK_API_KEY") or None
    cfg["DB_PATH"] = str(ROOT / (os.environ.get("DB_PATH") or env.get("DB_PATH") or "data/hub.duckdb"))
    return cfg
