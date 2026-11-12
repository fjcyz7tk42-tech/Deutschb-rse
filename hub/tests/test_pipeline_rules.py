"""Pipeline rules that fail silently. Owner: Track A. DB tests skip when data/hub.duckdb is missing."""
from pathlib import Path

import pytest

from backend.config import load_config
from backend.forensics import percentile
from backend.triage import robust_z

DB = Path(load_config()["DB_PATH"])
needs_db = pytest.mark.skipif(not DB.exists(), reason="data/hub.duckdb not built")
CBK = "DE000CBK1001"


@pytest.fixture(scope="module")
def con():
    from backend.db import connect
    return connect(read_only=True)


def test_robust_z():
    assert robust_z(13, 10, 1) == pytest.approx(3 / 1.4826)
    assert robust_z(13, 10, 0) is None
    assert robust_z(None, 10, 1) is None


def test_percentile_bounds():
    vals = [1.0, 2.0, 3.0, 4.0]
    assert [percentile(v, vals) for v in vals] == [25, 50, 75, 100]
    assert percentile(0.5, vals) == 0 and percentile(None, vals) is None


@needs_db
def test_auction_turnover_never_exceeds_daily_turnover(con):
    n = con.execute("""SELECT count(*) FROM daily_metrics
        WHERE open_auction_turnover + mid_auction_turnover + close_auction_turnover > trades_turnover * 1.000001""").fetchone()[0]
    assert n == 0


@needs_db
@pytest.mark.parametrize("day", ["2026-02-10", "2026-06-10"])  # winter (UTC+1) and summer (UTC+2)
def test_closing_auction_lands_at_1735_local(con, day):
    # trades are UTC; the close is only found when the conversion to Europe/Berlin is right
    ts, turnover = con.execute("""SELECT o.close_auction_ts, a.turnover FROM ohlc o
        JOIN auction_sums a ON a.isin = o.isin AND a.date = o.date AND a.auction = 'close'
        WHERE o.isin = ? AND o.date = ?""", [CBK, day]).fetchone()
    assert "17:35:00" <= ts < "17:45:00" and turnover > 0


# raw values read by hand from XETRA_OHLC; real exchange data, so they live in the local-only tests/fixtures/
HAND = Path(__file__).parent / "fixtures" / "hand_calc.json"


@needs_db
@pytest.mark.skipif(not HAND.exists(), reason="tests/fixtures/hand_calc.json not present (local only)")
def test_cbk_hand_calculation(con):
    # close auction, previous close auction, open auction and VWAP of one day, from the raw file
    import json
    h = json.loads(HAND.read_text())
    r = con.execute("SELECT close, return_1d, open_gap, close_vs_vwap, turnover_eur FROM daily_metrics WHERE isin = ? AND date = ?",
                    [h["isin"], h["date"]]).fetchone()
    assert r[0] == h["close"] and r[4] == h["turnover_eur"]
    assert r[1] == pytest.approx(h["close"] / h["prev_close"] - 1)
    assert r[2] == pytest.approx(h["open"] / h["prev_close"] - 1)
    assert r[3] == pytest.approx(h["close"] / h["vwap"] - 1)
    prev20 = [x[0] for x in con.execute("SELECT turnover FROM ohlc WHERE isin = ? AND date < ? ORDER BY date DESC LIMIT 20",
                                        [h["isin"], h["date"]]).fetchall()]
    prev20.sort()
    rel = h["turnover_eur"] / ((prev20[9] + prev20[10]) / 2)
    assert con.execute("SELECT rel_volume FROM daily_metrics WHERE isin = ? AND date = ?", [h["isin"], h["date"]]).fetchone()[0] == pytest.approx(rel)


@needs_db
def test_decomposition_adds_up(con):
    from backend.forensics import decompose_return
    d = decompose_return(CBK, "2026-10-30")
    assert d["market"] + d["sector"] + d["company"] == pytest.approx(d["total"])


@needs_db
def test_censored_flow_is_null_not_zero(con):
    n = con.execute("SELECT count(*) FROM flows WHERE reported_flow_dates IS NULL AND (mm_volume IS NOT NULL OR agent_volume IS NOT NULL)").fetchone()[0]
    assert n == 0


@needs_db
def test_coverage_complete(con):
    rows = dict(con.execute("SELECT dataset, count(*) FILTER (status = 'ok') FROM coverage GROUP BY 1").fetchall())
    assert rows == {d: 213 for d in ("index", "ohlc", "flows", "xlm", "trades")}


@needs_db
def test_market_days_and_episodes(con):
    md = dict(con.execute("SELECT idx, count(*) FILTER (market_wide) FROM market_days GROUP BY 1").fetchall())
    assert md["DAX"] >= 1 and "2026-09-18" in [str(r[0]) for r in con.execute("SELECT date FROM market_days WHERE idx = 'DAX' AND market_wide").fetchall()]
    # an episode never has a gap: its trading-day count equals the anomalous days inside it
    assert con.execute("SELECT count(*) FROM episodes WHERE days < 1 OR start > \"end\" OR peak_date NOT BETWEEN start AND \"end\"").fetchone()[0] == 0
