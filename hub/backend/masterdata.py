"""Step 2. Entities, index membership, index changes, sectors, size cohorts, peer groups."""
from __future__ import annotations

from backend.config import ROOT, load_config
from backend.db import connect

SECTORS = ROOT / "data" / "reference" / "sectors.csv"

# Trading-day number per date, so "consecutive" means consecutive trading days.
TD = "(SELECT date, row_number() OVER (ORDER BY date) AS n FROM (SELECT DISTINCT date FROM members))"


def build_entities() -> None:
    """entities: one row per ISIN with its latest ticker, name, WKN, index and sector."""
    con = connect()
    focus = load_config()["focus_stocks"]
    con.execute(f"""CREATE OR REPLACE TABLE entities AS
        WITH m AS (SELECT isin, arg_max(ticker, date) AS ticker, arg_max(wkn, date) AS wkn, arg_max(idx, date) AS idx
                   FROM members GROUP BY isin),
             o AS (SELECT isin, trim(arg_max(name, date)) AS name FROM ohlc GROUP BY isin),
             s AS (SELECT isin, name, sector, checked FROM read_csv('{SECTORS}', all_varchar=true))
        SELECT m.isin, m.ticker, coalesce(s.name, o.name) AS name, m.wkn,  -- sectors.csv carries the readable name
                m.idx, s.sector, s.checked AS sector_checked,
               m.ticker IN (SELECT unnest(?::VARCHAR[])) AS focus
        FROM m LEFT JOIN o USING (isin) LEFT JOIN s USING (isin)""", [focus])
    con.execute("""CREATE OR REPLACE TABLE index_membership AS
        WITH x AS (SELECT m.isin, m.idx, m.date, td.n, td.n - row_number() OVER (PARTITION BY m.isin, m.idx ORDER BY m.date) AS g
                   FROM members m JOIN """ + TD + """ td USING (date))
        SELECT isin, idx, min(date) AS valid_from, max(date) AS valid_to, count(*) AS days FROM x GROUP BY isin, idx, g""")


def derive_index_changes() -> None:
    """Additions and removals per index, one-day members excluded. Also stored as events of type index_change.

    An ISIN swap (same ticker leaves and joins the same index on the same day) is not an index change.
    The event day of an addition is the rebalancing day: the last trading day before first membership.
    """
    con = connect()
    con.execute(f"""CREATE OR REPLACE TABLE index_changes AS
        WITH td AS {TD}, first AS (SELECT min(date) d FROM td), last AS (SELECT max(date) d FROM td),
        sp AS (SELECT s.*, e.ticker FROM index_membership s JOIN entities e USING (isin) WHERE s.days > 1),
        ch AS (
            SELECT isin, ticker, idx, 'addition' AS direction, valid_from AS effective_date,
                   (SELECT max(date) FROM td WHERE date < valid_from) AS event_day
            FROM sp WHERE valid_from > (SELECT d FROM first)
            UNION ALL
            SELECT isin, ticker, idx, 'removal', (SELECT min(date) FROM td WHERE date > valid_to), valid_to
            FROM sp WHERE valid_to < (SELECT d FROM last))
        SELECT * EXCLUDE (ticker) FROM ch a
        WHERE NOT EXISTS (SELECT 1 FROM ch b WHERE b.ticker = a.ticker AND b.idx = a.idx
                          AND b.effective_date = a.effective_date AND b.direction <> a.direction)""")
    # published_at_utc is a plain TIMESTAMP holding UTC: TIMESTAMPTZ would need pytz to reach Python.
    # Recreated here; forensics.load_events adds Track B's events afterwards (scripts/build.sh order).
    con.execute("""CREATE OR REPLACE TABLE events (id INTEGER PRIMARY KEY, isin VARCHAR, type VARCHAR, title VARCHAR,
        published_at_utc TIMESTAMP, effective_trading_day DATE, source VARCHAR, url VARCHAR, confidence DOUBLE)""")
    # ids 1..999 are index changes, events.csv rows start at 1000 (backend/forensics.py)
    con.execute("""INSERT INTO events SELECT row_number() OVER (ORDER BY effective_date, idx, isin), isin, 'index_change',
        'Added to ' || idx, NULL, event_day, 'index_constituents', NULL, 1.0
        FROM index_changes WHERE direction = 'addition'""")


def build_peers() -> None:
    """Three groups per stock: same index, same sector, same size cohort (turnover terciles within the index).

    Index and size peers are the index's members on the last day; a stock that left keeps its last index.
    """
    con = connect()
    cur = "(SELECT isin FROM members WHERE date = (SELECT max(date) FROM members))"
    con.execute(f"""CREATE OR REPLACE TABLE size_cohort AS
        SELECT e.isin, e.idx, ntile(3) OVER (PARTITION BY e.idx ORDER BY avg(o.turnover)) AS cohort, avg(o.turnover) AS avg_turnover
        FROM entities e JOIN ohlc o USING (isin) WHERE e.isin IN {cur} GROUP BY e.isin, e.idx""")
    # a stock that left all indices gets the cohort its turnover would have in its last index
    con.execute(f"""INSERT INTO size_cohort SELECT e.isin, e.idx,
        (SELECT coalesce(max(s.cohort), 1) FROM size_cohort s WHERE s.idx = e.idx AND s.avg_turnover <= a.t), a.t
        FROM entities e JOIN (SELECT isin, avg(turnover) t FROM ohlc GROUP BY isin) a USING (isin) WHERE e.isin NOT IN {cur}""")
    con.execute(f"""CREATE OR REPLACE TABLE peers AS
        SELECT a.isin, b.isin AS peer_isin, 'index' AS basis FROM entities a JOIN entities b ON a.idx = b.idx AND a.isin <> b.isin
            AND b.isin IN {cur}
        UNION ALL
        SELECT a.isin, b.isin, 'sector' FROM entities a JOIN entities b ON a.sector = b.sector AND a.isin <> b.isin
        UNION ALL
        SELECT a.isin, b.isin, 'size' FROM size_cohort a JOIN size_cohort b
            ON a.idx = b.idx AND a.cohort = b.cohort AND a.isin <> b.isin AND b.isin IN {cur}""")


def build_all() -> None:
    build_entities()
    derive_index_changes()
    build_peers()


if __name__ == "__main__":
    build_all()
