"""One database connection for every module.

Single DuckDB file at DB_PATH. DuckDB reads the csv.gz files directly.
When the file does not exist yet, it is built from the seed in data/reference/seed/ (backend/seed.py).
"""
from __future__ import annotations

import threading
from pathlib import Path

import duckdb

from backend.config import load_config

_seed_lock = threading.Lock()


def connect(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    path = load_config()["DB_PATH"]
    if not Path(path).exists():
        with _seed_lock:  # first request after a fresh clone: several API threads may arrive at once
            from backend import seed

            if not Path(path).exists() and any(seed.SEED.glob("*.parquet")):
                seed.load(path)
    con = duckdb.connect(path, read_only=read_only)
    con.execute("SET TimeZone = 'UTC'")
    return con
