"""Seed data: the finished tables as Parquet in data/reference/seed/, so the app runs after a plain `git pull`.

    python -m backend.seed export    database -> seed files (run after scripts/build.sh or backend.forensics)
    python -m backend.seed load      seed files -> data/hub.duckdb (replaces the database)

backend.db.connect() loads the seed by itself when data/hub.duckdb does not exist.
The seed holds every table the API reads, for all 174 stocks. A rebuild from the raw files still needs the ZIP.
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb

from backend.config import ROOT, load_config

SEED = ROOT / "data" / "reference" / "seed"


def export() -> int:
    con = duckdb.connect(load_config()["DB_PATH"], read_only=True)
    SEED.mkdir(parents=True, exist_ok=True)
    tables = [r[0] for r in con.execute("SELECT table_name FROM duckdb_tables() ORDER BY 1").fetchall()]
    for old in SEED.glob("*.parquet"):
        old.unlink()
    for t in tables:
        con.execute(f"COPY {t} TO '{SEED / (t + '.parquet')}' (FORMAT parquet, COMPRESSION zstd)")
    return len(tables)


def load(db_path: str | None = None) -> int:
    """Build the database from the seed files. Writes to a temporary file first, so a failed load leaves nothing behind."""
    files = sorted(SEED.glob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"no seed files in {SEED}")
    target = Path(db_path or load_config()["DB_PATH"])
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".seeding")
    tmp.unlink(missing_ok=True)
    con = duckdb.connect(str(tmp))
    for f in files:
        con.execute(f"CREATE TABLE {f.stem} AS SELECT * FROM read_parquet('{f}')")
    con.execute("CREATE OR REPLACE VIEW universe AS SELECT DISTINCT isin FROM members")  # as in backend/loader.py
    con.close()
    tmp.replace(target)
    return len(files)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd not in ("export", "load"):
        sys.exit("usage: python -m backend.seed export|load")
    print(cmd, {"export": export, "load": load}[cmd](), "tables")
