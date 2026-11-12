"""B's events.csv -> events -> matching -> API, on a copy of the database. Guards sync point S2."""
import shutil
from pathlib import Path

import pytest

from backend.config import load_config

DB = Path(load_config()["DB_PATH"])
pytestmark = pytest.mark.skipif(not DB.exists(), reason="data/hub.duckdb not built")
PBB, CBK = "DE0008019001", "DE000CBK1001"

# Quirks on purpose: Z and offset times, an empty effective_trading_day, empty confidence,
# a comma inside a quoted title, an evening publication, an unknown ISIN.
SAMPLE = f"""isin,type,title,published_at_utc,effective_trading_day,source,url,confidence
{PBB},ad_hoc,"PBB: sample ad hoc, with comma",2026-10-06T05:30:00Z,2026-10-06,eqs,https://example.com/a,0.9
{PBB},earnings,PBB sample results,2026-08-13T05:00:00+00:00,,manual_csv,https://example.com/b,
{CBK},earnings,CBK sample results after close,2026-08-05T16:00:00Z,,manual_csv,https://example.com/c,1.0
XX0000000000,other,Unknown company,2026-05-05T08:00:00Z,2026-05-05,eqs,https://example.com/d,1.0
"""


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("db")
    shutil.copy(DB, tmp / "hub.duckdb")
    with pytest.MonkeyPatch.context() as mp:  # the real database is never written
        mp.setenv("DB_PATH", str(tmp / "hub.duckdb"))
        from backend import forensics
        csv = tmp / "events.csv"
        csv.write_text(SAMPLE)
        report = forensics.load_events(csv)
        forensics.match_episodes()
        forensics.compute_event_impact()
        yield report


def test_load_report(built):
    assert built["loaded"] == 3 and built["skipped"] == ["line 5: isin not in universe"]


def test_days_and_matching(built):
    from backend.db import connect
    con = connect(read_only=True)
    days = dict(con.execute("SELECT title, effective_trading_day::VARCHAR FROM events WHERE id >= 1000").fetchall())
    assert days["PBB sample results"] == "2026-08-13"              # derived: 07:00 Berlin, before the cut-off
    assert days["CBK sample results after close"] == "2026-08-06"  # 18:00 Berlin, after 17:35 -> next day
    st = con.execute("SELECT status, event_id FROM cases WHERE isin = ? AND peak_date = '2026-10-06'", [PBB]).fetchone()
    assert st[0] == "matched" and st[1] >= 1000


def test_api_with_events(built):
    from fastapi.testclient import TestClient
    from backend import text
    from backend.api import app
    c = TestClient(app)
    pytest.MonkeyPatch().setattr(text, "_config", lambda: {"DEEPSEEK_API_KEY": "", "llm": {}})  # no model calls
    cases = c.get(f"/companies/{PBB}/cases").json()
    assert cases["counts"]["matched"] >= 1
    card = c.get("/impact/1000").json()
    assert card["event"]["url"] == "https://example.com/a" and card["similar"]["type"] == "ad_hoc"
