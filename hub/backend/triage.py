"""Step 4. Anomaly triage: robust z-scores, market days, episodes, score 0 to 100."""
from __future__ import annotations

from backend.config import load_config
from backend.db import connect

METRICS = ("rel_volume", "xlm_bps", "abnormal_return")
MAD_SCALE = 1.4826


def robust_z(value: float, median: float, mad: float) -> float | None:
    """(value - median) / (1.4826 * MAD). None when MAD is 0 or history is shorter than the window."""
    if value is None or median is None or not mad:
        return None
    return (value - median) / (MAD_SCALE * mad)


def flag_anomalies() -> None:
    """anomalies: one row per stock, day and metric with |z| >= z_threshold."""
    z = float(load_config()["z_threshold"])
    con = connect()
    parts = [f"""SELECT date, isin, idx, is_member, '{m}' AS metric, {m} AS value, {m}_median AS median, {m}_mad AS mad,
                 ({m} - {m}_median) / ({MAD_SCALE} * nullif({m}_mad, 0)) AS z FROM daily_metrics""" for m in METRICS]
    con.execute(f"CREATE OR REPLACE TABLE anomalies AS SELECT * FROM ({' UNION ALL '.join(parts)}) WHERE abs(z) >= {z}")


def flag_market_days() -> None:
    """market_days: share of an index's members with a rel_volume anomaly that day; market_wide from the threshold per index.

    Only rel_volume counts: the thresholds in config.yaml were tuned on it (docs/data_dictionary.md).
    """
    thr = load_config()["market_day_threshold"]
    con = connect()
    con.execute("CREATE OR REPLACE TEMP TABLE thr (idx VARCHAR, t DOUBLE)")
    con.executemany("INSERT INTO thr VALUES (?, ?)", list(thr.items()))
    con.execute("""CREATE OR REPLACE TABLE market_days AS
        SELECT m.date, m.idx, count(DISTINCT a.isin) AS anomalous, count(DISTINCT m.isin) AS members,
               count(DISTINCT a.isin) / count(DISTINCT m.isin) AS share,
               count(DISTINCT a.isin) / count(DISTINCT m.isin) >= thr.t AS market_wide
        FROM members m JOIN thr USING (idx) LEFT JOIN anomalies a ON a.isin = m.isin AND a.date = m.date AND a.metric = 'rel_volume'
        GROUP BY m.date, m.idx, thr.t""")


def flag_sector_days() -> None:
    """sector_days: share of a sector's index members (DAX, MDAX and SDAX together) with a rel_volume anomaly that day.

    sector_wide when at least sector_day_threshold.min_stocks members and sector_day_threshold.share of them are
    unusual. With a base rate of about 7 % unusual stock days, 3 of 8 or 9 of 34 on one day is rare by chance.
    Added 12 Nov (team request): 40 % of the unmatched unusual days sat in such clusters.
    """
    t = load_config()["sector_day_threshold"]
    con = connect()
    con.execute(f"""CREATE OR REPLACE TABLE sector_days AS
        SELECT m.date, en.sector, count(DISTINCT a.isin) AS anomalous, count(DISTINCT m.isin) AS members,
               count(DISTINCT a.isin) / count(DISTINCT m.isin) AS share,
               count(DISTINCT a.isin) >= {int(t["min_stocks"])} AND count(DISTINCT a.isin) / count(DISTINCT m.isin) >= {float(t["share"])} AS sector_wide
        FROM members m JOIN entities en USING (isin)
        LEFT JOIN anomalies a ON a.isin = m.isin AND a.date = m.date AND a.metric = 'rel_volume'
        WHERE en.sector IS NOT NULL
        GROUP BY m.date, en.sector""")


def build_episodes() -> None:
    """Consecutive anomalous days of one stock become one episode (start, end, peak_date, metrics).

    score = 70 * min(max|z|, 10) / 10 + 15 per extra metric, capped at 100.
    market_day: the peak day is a market day in the stock's index.
    sector_day: the peak day is a sector-wide day in the stock's sector.
    """
    con = connect()
    con.execute("""CREATE OR REPLACE TABLE episodes AS
        WITH td AS (SELECT date, row_number() OVER (ORDER BY date) AS n FROM (SELECT DISTINCT date FROM daily_metrics)),
        d AS (SELECT a.isin, a.date, td.n, max(abs(a.z)) AS z, list(DISTINCT a.metric ORDER BY a.metric) AS metrics
              FROM anomalies a JOIN td USING (date) GROUP BY ALL),
        g AS (SELECT *, n - row_number() OVER (PARTITION BY isin ORDER BY date) AS grp FROM d),
        e AS (SELECT isin, min(date) AS start, max(date) AS "end", arg_max(date, z) AS peak_date, max(z) AS max_z,
                     list_sort(list_distinct(flatten(list(metrics)))) AS metrics, count(*) AS days
              FROM g GROUP BY isin, grp)
        SELECT row_number() OVER (ORDER BY e.start, e.isin)::INTEGER AS id, e.*,
               least(100, round(70 * least(e.max_z, 10) / 10 + 15 * (len(e.metrics) - 1)))::INTEGER AS score,
               coalesce(md.market_wide, false) AS market_day,
               coalesce(sd.sector_wide, false) AS sector_day
        FROM e JOIN entities en USING (isin)
        LEFT JOIN market_days md ON md.date = e.peak_date AND md.idx = en.idx
        LEFT JOIN sector_days sd ON sd.date = e.peak_date AND sd.sector = en.sector""")


def build_all() -> None:
    flag_anomalies()
    flag_market_days()
    flag_sector_days()
    build_episodes()


if __name__ == "__main__":
    build_all()
