"""Step 6. Forensic investigator.

Episode -> candidate events inside the match window -> status: matched, market_day, sector_day or unmatched.
Event -> reaction (event_impact), even when no anomaly occurred.
"""
from __future__ import annotations

from datetime import datetime, timezone

from backend.config import ROOT, load_config
from backend.db import connect
from backend.tradingdays import effective_trading_day

EVENTS_CSV = ROOT / "data" / "reference" / "events.csv"
MARKET_CALENDAR = ROOT / "data" / "reference" / "market_calendar.csv"
# Rank of candidate types when two events are equally close to the peak day.
TYPE_RANK = ("earnings", "ad_hoc", "m_and_a", "dividend", "index_change", "press_release",
             "directors_dealing", "voting_rights", "short_position", "other")
# Holding notices: listed as events, but never decide a case status on their own (decision 11 Nov, Q2).
CONTEXT_ONLY = ("voting_rights", "directors_dealing")
TD = "(SELECT date, row_number() OVER (ORDER BY date) AS n FROM (SELECT DISTINCT date FROM daily_metrics))"

# Reaction of one stock on one day d0. Used for every event (event_impact) and for any notable day (facts.py).
IMPACT_SQL = f"""
WITH td AS {TD},
p AS (SELECT p.*, td.n AS n0 FROM pairs p JOIN td ON td.date = p.day),
w AS (SELECT p.key, p.isin, td.n - p.n0 AS k, d.* EXCLUDE (isin, date), d.date
      FROM p JOIN td ON td.n BETWEEN p.n0 - 20 AND p.n0 + 30
      LEFT JOIN daily_metrics d ON d.isin = p.isin AND d.date = td.date)
SELECT key, isin,
  any_value(date) FILTER (k = 0) AS day,
  any_value(rel_volume) FILTER (k = 0) AS rel_volume,
  any_value(return_1d) FILTER (k = 0) AS return_1d,
  any_value(market_return) FILTER (k = 0) AS market_return,
  any_value(sector_median_return - market_return) FILTER (k = 0) AS sector_return,
  any_value(return_1d - sector_median_return) FILTER (k = 0) AS company_return,
  any_value(abnormal_return) FILTER (k = 0) AS abnormal_return,
  CASE WHEN count(abnormal_return) FILTER (k BETWEEN 0 AND 5) = 6 THEN sum(abnormal_return) FILTER (k BETWEEN 0 AND 5) END AS car_5,
  any_value(xlm_bps) FILTER (k = 0) AS xlm_bps,
  any_value(xlm_bps_median) FILTER (k = 0) AS xlm_bps_baseline,
  any_value(open_auction_turnover) FILTER (k = 0) AS opening_auction_turnover,
  median(open_auction_turnover) FILTER (k BETWEEN -20 AND -1) AS opening_auction_baseline,
  any_value(close_auction_turnover) FILTER (k = 0) AS closing_auction_turnover,
  median(close_auction_turnover) FILTER (k BETWEEN -20 AND -1) AS closing_auction_baseline,
  any_value(open_gap) FILTER (k = 0) AS open_gap,
  any_value(close_vs_vwap) FILTER (k = 0) AS close_vs_vwap,
  any_value(agent_share) FILTER (k = 0) AS agent_share, any_value(agent_share_median) FILTER (k = 0) AS agent_share_baseline,
  any_value(prop_share) FILTER (k = 0) AS prop_share, any_value(prop_share_median) FILTER (k = 0) AS prop_share_baseline,
  any_value(mm_share) FILTER (k = 0) AS mm_share, any_value(mm_share_median) FILTER (k = 0) AS mm_share_baseline,
  any_value(agent_flow_qty) FILTER (k = 0) AS agent_net_flow, any_value(prop_flow_qty) FILTER (k = 0) AS prop_net_flow,
  any_value(mm_flow_qty) FILTER (k = 0) AS mm_net_flow,
  min(k) FILTER (k >= 0 AND rel_volume < 1.5) AS days_to_normal
FROM w GROUP BY key, isin
"""


def impact_rows(con, pairs: list[tuple]) -> list[dict]:
    """pairs: (key, isin, day). Returns one dict per pair with the reaction figures."""
    con.execute("CREATE OR REPLACE TEMP TABLE pairs (key VARCHAR, isin VARCHAR, day DATE)")
    con.executemany("INSERT INTO pairs VALUES (?, ?, ?)", [(str(k), i, d) for k, i, d in pairs])
    cur = con.execute(IMPACT_SQL)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def load_events(path=None) -> dict:
    """Track B's data/reference/events.csv into events (ids from 1000, in file order). Index changes come from masterdata.

    Tolerant of B's quirks: an empty effective_trading_day is derived from published_at_utc with the 17:35 rule;
    empty confidence is 1.0. Rows without a usable day or with an ISIN outside the universe are skipped and counted.
    """
    path = path or EVENTS_CSV
    con = connect()
    con.execute("DELETE FROM events WHERE id >= 1000")
    if not path.exists():
        return {"loaded": 0, "skipped": []}
    cur = con.execute(f"SELECT * FROM read_csv('{path}', all_varchar=true, header=true)")
    cols, data = [c[0] for c in cur.description], cur.fetchall()  # fetch before the next query reuses the connection
    universe = {r[0] for r in con.execute("SELECT isin FROM entities").fetchall()}
    rows, skipped = [], []
    for i, raw in enumerate(data, start=2):  # line 1 is the header
        r = {k: (v.strip() if isinstance(v, str) and v.strip() else None) for k, v in zip(cols, raw)}
        pub = _utc(r.get("published_at_utc"))
        day = r.get("effective_trading_day") or (effective_trading_day(pub).isoformat() if pub and effective_trading_day(pub) else None)
        if r.get("isin") not in universe or not day:
            skipped.append(f"line {i}: {'isin not in universe' if r.get('isin') not in universe else 'no trading day'}")
            continue
        conf = float(r["confidence"]) if r.get("confidence") else 1.0
        naive_utc = pub.astimezone(timezone.utc).replace(tzinfo=None) if pub else None
        rows.append([999 + len(rows) + 1, r["isin"], r.get("type") or "other", r.get("title"), naive_utc, day, r.get("source"), r.get("url"), conf])
    if rows:
        con.executemany("INSERT INTO events VALUES (?, ?, ?, ?, ?, ?::DATE, ?, ?, ?)", rows)
    return {"loaded": len(rows), "skipped": skipped}


def _utc(s: str | None):
    """ISO time with Z or an offset; a naive time is read as UTC."""
    if not s:
        return None
    t = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def match_episodes() -> None:
    """episode_events: candidates per episode; cases: one status per episode.

    Status, first that applies (a matched event is still shown on market and sector days):
      market_day  the peak day is a market day in the stock's index (share of unusual members, config)
      matched     a company event lies in the window
      market_day  the peak day is in data/reference/market_calendar.csv (ECB decision, MSCI review, Eurex expiry)
      sector_day  the peak day is a sector-wide day in the stock's sector (triage.flag_sector_days)
      unmatched   none of these
    The calendar and sector rules were added 12 Nov (team request); they come after matched, since a company's
    own event is the closer match.
    Voting rights and directors' dealings (CONTEXT_ONLY) stay in episode_events but never set the status.

    The window runs around the whole episode: from start + lo to end + hi trading days (config
    event_match_window). For a one-day episode that is the same as around the peak day. Among candidates
    the one closest to the peak day still wins. (Changed 11 Nov on team request: before, only the peak day
    counted, so an event on the last day of a three-day episode was missed.)
    """
    win = load_config()["event_match_window"]
    con = connect()
    con.execute("CREATE OR REPLACE TEMP TABLE win (type VARCHAR, lo INTEGER, hi INTEGER)")
    con.executemany("INSERT INTO win VALUES (?, ?, ?)", [(t, *v) for t, v in win.items()])
    con.execute("CREATE OR REPLACE TEMP TABLE tr (type VARCHAR, r INTEGER)")
    con.executemany("INSERT INTO tr VALUES (?, ?)", [(t, i) for i, t in enumerate(TYPE_RANK)])
    con.execute(f"""CREATE OR REPLACE TABLE episode_events AS
        WITH td AS {TD}
        SELECT ep.id AS episode_id, ev.id AS event_id, te.n - tp.n AS offset_days,
               ev.type IN {CONTEXT_ONLY} AS context_only,
               row_number() OVER (PARTITION BY ep.id ORDER BY ev.type IN {CONTEXT_ONLY}, abs(te.n - tp.n), coalesce(tr.r, 99), ev.id) AS rank
        FROM episodes ep JOIN td tp ON tp.date = ep.peak_date
        JOIN td ts ON ts.date = ep.start JOIN td tz ON tz.date = ep."end"
        JOIN events ev ON ev.isin = ep.isin JOIN td te ON te.date = ev.effective_trading_day
        JOIN win ON win.type = CASE WHEN ev.type IN (SELECT type FROM win) THEN ev.type ELSE 'default' END
        LEFT JOIN tr ON tr.type = ev.type
        WHERE te.n BETWEEN ts.n + win.lo AND tz.n + win.hi""")
    con.execute(f"""CREATE OR REPLACE TABLE cases AS
        WITH cal AS (SELECT DISTINCT date::DATE AS date FROM read_csv('{MARKET_CALENDAR}', header=true, all_varchar=true))
        SELECT ep.*, ee.event_id,
               CASE WHEN ep.market_day THEN 'market_day' WHEN ee.event_id IS NOT NULL THEN 'matched'
                    WHEN cal.date IS NOT NULL THEN 'market_day' WHEN ep.sector_day THEN 'sector_day' ELSE 'unmatched' END AS status
        FROM episodes ep LEFT JOIN episode_events ee ON ee.episode_id = ep.id AND ee.rank = 1 AND NOT ee.context_only
        LEFT JOIN cal ON cal.date = ep.peak_date""")


def compute_event_impact(event_id: int | None = None) -> None:
    """event_impact for one event, or for all events when event_id is None.

    rel_volume day 0, abnormal_return day 0 and cumulative to +5, xlm change, auction turnover vs
    baseline, open_gap, close_vs_vwap, participant mix shift, days until rel_volume < 1.5.
    """
    con = connect()
    where = "WHERE effective_trading_day IS NOT NULL" + (f" AND id = {int(event_id)}" if event_id else "")
    con.execute(f"CREATE OR REPLACE TEMP TABLE pairs AS SELECT id::VARCHAR AS key, isin, effective_trading_day AS day FROM events {where}")
    sql = f"SELECT key::INTEGER AS event_id, * EXCLUDE (key) FROM ({IMPACT_SQL})"
    if event_id is None:
        con.execute(f"CREATE OR REPLACE TABLE event_impact AS {sql}")
    else:
        con.execute("DELETE FROM event_impact WHERE event_id = ?", [event_id])
        con.execute(f"INSERT INTO event_impact {sql}")


def decompose_return(isin: str, day: str) -> dict:
    """market = index median; sector = sector median - index median; company = remainder. Fractions; they add up to total."""
    con = connect(read_only=True)
    r = con.execute("""SELECT return_1d, market_return, sector_median_return - market_return, return_1d - sector_median_return
        FROM daily_metrics WHERE isin = ? AND date = ?""", [isin, day]).fetchone()
    return dict(zip(("total", "market", "sector", "company"), r)) if r else {}


def percentile(value: float, group: list[float]) -> int | None:
    """Share of the group at or below value, 0 to 100."""
    vals = [v for v in group if v is not None]
    if value is None or not vals:
        return None
    return round(100 * sum(v <= value for v in vals) / len(vals))


def similar_cases(event_id: int, metric: str = "rel_volume") -> dict:
    """Same event type in the same index, sector and universe; percentile of this reaction per group."""
    con = connect(read_only=True)
    me = con.execute(f"""SELECT ev.type, en.idx, en.sector, ei.{metric} FROM events ev JOIN entities en USING (isin)
        JOIN event_impact ei ON ei.event_id = ev.id WHERE ev.id = ?""", [event_id]).fetchone()
    if not me:
        return {}
    typ, idx, sector, value = me
    out = {}
    for basis, cond, group in (("index", "en.idx = ?", idx), ("sector", "en.sector = ?", sector), ("universe", "?::VARCHAR IS NOT NULL", "all")):
        vals = [r[0] for r in con.execute(f"""SELECT ei.{metric} FROM events ev JOIN entities en USING (isin)
            JOIN event_impact ei ON ei.event_id = ev.id WHERE ev.type = ? AND {cond}""", [typ, group]).fetchall()]
        out[basis] = {"type": typ, "basis": basis, "group": group, "metric": metric,
                      "n": sum(v is not None for v in vals), "percentile": percentile(value, vals)}
    return out


def build_all() -> None:
    print("events.csv:", load_events())
    match_episodes()
    compute_event_impact()


if __name__ == "__main__":
    build_all()
