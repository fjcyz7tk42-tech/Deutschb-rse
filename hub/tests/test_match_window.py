"""Matching window covers the whole unusual period, not only the peak day. On a copy of the database.

Real episode used: PBB 6 Oct to 8 Oct 2026, peak 6 Oct (three trading days).
Written by Track B on request of the team (11 Nov); the matching code itself is Track A's.
"""
import shutil
from pathlib import Path

import pytest

from backend.config import load_config

DB = Path(load_config()["DB_PATH"])
pytestmark = pytest.mark.skipif(not DB.exists(), reason="data/hub.duckdb not built")
PBB = "DE0008019001"

# 8 Oct: last day of the period, two trading days after the peak -> missed when only the peak counts.
# 9 Oct: one trading day after the end -> inside the default window [-1, +1] around the period.
# 13 Oct: three trading days after the end -> outside.
SAMPLE = f"""isin,type,title,published_at_utc,effective_trading_day,source,url,confidence
{PBB},ad_hoc,PBB ad hoc on the last day of the period,2026-10-08T06:00:00Z,2026-10-08,eqs,https://example.com/last,1.0
{PBB},press_release,PBB press release after the period,2026-10-13T06:00:00Z,2026-10-13,eqs,https://example.com/late,1.0
"""


@pytest.fixture(scope="module")
def con(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("db")
    shutil.copy(DB, tmp / "hub.duckdb")
    with pytest.MonkeyPatch.context() as mp:  # the real database is never written
        mp.setenv("DB_PATH", str(tmp / "hub.duckdb"))
        from backend import forensics
        from backend.db import connect
        csv = tmp / "events.csv"
        csv.write_text(SAMPLE)
        forensics.load_events(csv)
        forensics.match_episodes()
        c = connect(read_only=True)
        yield c
        c.close()


def _case(con):
    return con.execute("""SELECT c.status, e.title FROM cases c LEFT JOIN events e ON e.id = c.event_id
                          WHERE c.isin = ? AND c.start = '2026-10-06'""", [PBB]).fetchone()


def test_period_is_the_one_we_think(con):
    row = con.execute("""SELECT start::VARCHAR, "end"::VARCHAR, peak_date::VARCHAR FROM episodes
                         WHERE isin = ? AND start = '2026-10-06'""", [PBB]).fetchone()
    assert row == ("2026-10-06", "2026-10-08", "2026-10-06")


def test_event_on_last_day_of_period_is_matched(con):
    status, title = _case(con)
    assert status == "matched"
    assert title == "PBB ad hoc on the last day of the period"


def test_event_far_after_the_period_is_not_a_candidate(con):
    titles = [r[0] for r in con.execute("""SELECT e.title FROM episode_events ee JOIN events e ON e.id = ee.event_id
        JOIN episodes ep ON ep.id = ee.episode_id WHERE ep.isin = ? AND ep.start = '2026-10-06'""", [PBB]).fetchall()]
    assert "PBB press release after the period" not in titles
