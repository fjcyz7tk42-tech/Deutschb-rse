"""Status order with the market calendar and sector days (12 Nov). On the real database, read-only.

Written by Track B on request of the team; the triage and matching code is Track A's.
"""
from pathlib import Path

import duckdb
import pytest

from backend.config import load_config

DB = Path(load_config()["DB_PATH"])
pytestmark = pytest.mark.skipif(not DB.exists(), reason="data/hub.duckdb not built")


@pytest.fixture(scope="module")
def con():
    c = duckdb.connect(str(DB), read_only=True)
    yield c
    c.close()


def test_sector_day_rule_matches_threshold(con):
    t = load_config()["sector_day_threshold"]
    bad = con.execute(f"""SELECT count(*) FROM sector_days WHERE sector_wide <>
        (anomalous >= {t['min_stocks']} AND anomalous / members >= {t['share']})""").fetchone()[0]
    assert bad == 0


def test_status_order(con):
    rows = con.execute("""SELECT c.status, c.market_day, c.event_id IS NOT NULL AS has_event, c.sector_day,
        c.peak_date IN (SELECT date::DATE FROM read_csv('data/reference/market_calendar.csv', header=true, all_varchar=true)) AS cal
        FROM cases c""").fetchall()
    for status, market, has_event, sector, cal in rows:
        expected = ("market_day" if market else "matched" if has_event else "market_day" if cal
                    else "sector_day" if sector else "unmatched")
        assert status == expected


def test_holding_notices_never_set_status(con):
    n = con.execute("""SELECT count(*) FROM cases c JOIN events e ON e.id = c.event_id
        WHERE e.type IN ('voting_rights', 'directors_dealing')""").fetchone()[0]
    assert n == 0
