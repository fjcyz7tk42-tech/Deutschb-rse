"""A fresh clone has no database: the seed must rebuild every table with the same row counts."""
from pathlib import Path

import duckdb
import pytest

from backend import seed
from backend.config import load_config

DB = Path(load_config()["DB_PATH"])
pytestmark = pytest.mark.skipif(not DB.exists() or not any(seed.SEED.glob("*.parquet")), reason="database or seed missing")


def counts(con):
    tables = [r[0] for r in con.execute("SELECT table_name FROM duckdb_tables() ORDER BY 1").fetchall()]
    return {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables}


def test_seed_matches_database(tmp_path, monkeypatch):
    fresh = tmp_path / "hub.duckdb"
    monkeypatch.setenv("DB_PATH", str(fresh))
    from backend.db import connect
    con = connect(read_only=True)  # no file yet: connect() loads the seed
    assert counts(con) == counts(duckdb.connect(str(DB), read_only=True))
    assert con.execute("SELECT count(*) FROM universe").fetchone()[0] == 174
    assert con.execute("SELECT metrics FROM cases WHERE len(metrics) > 1 LIMIT 1").fetchone()[0]  # list columns survive
