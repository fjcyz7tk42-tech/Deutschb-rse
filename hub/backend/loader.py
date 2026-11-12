"""Step 1. Bulk loader: raw csv.gz files -> tables in data/hub.duckdb, filtered to the universe.

Datasets: index (constituents), ohlc, flows, xlm, trades. Raw trades are not stored: they become
5-minute bars (trade_bars) and auction sums (auction_sums) at load.
Usage: python -m backend.loader --all | --date 2026-10-30 [--dataset ohlc]
Re-runnable: a day already loaded with status ok is skipped unless --force.
"""
from __future__ import annotations

import argparse
from backend.config import ROOT
from backend.db import connect
from backend.tradingdays import trading_days

RAW = ROOT / "data" / "raw"
GLOBS = {  # {d} = YYYYMMDD
    "index": "index_constituents/*_CONSTITUENTS_{d}.csv.gz",
    "ohlc": "XETRA/XETRA_OHLC/XETRA_OHLC_{d}.csv.gz",
    "flows": "XETRA/XETRA_FLOW_DYNAMICS_EQUITY/XETRA_FLOW_DYNAMICS_EQUITY_{d}.csv.gz",
    "xlm": "XLM/dax_mdax_sdax_xlm.{d}.csv",
    "trades": "XETRA/XETRA_ONBOOK_TRADES/XETRA_ONBOOK_TRADES_{d}.csv.gz",
}
ORDER = ("index", "ohlc", "flows", "xlm", "trades")  # index first: it defines the universe

SCHEMA = """
CREATE TABLE IF NOT EXISTS coverage (dataset VARCHAR, date DATE, rows_raw BIGINT, rows_kept BIGINT,
    status VARCHAR, message VARCHAR, PRIMARY KEY (dataset, date));
CREATE TABLE IF NOT EXISTS members (idx VARCHAR, date DATE, isin VARCHAR, ticker VARCHAR, wkn VARCHAR, security_id BIGINT);
CREATE TABLE IF NOT EXISTS ohlc (date DATE, isin VARCHAR, security_id BIGINT, name VARCHAR, volume DOUBLE, turnover DOUBLE,
    open_price DOUBLE, high_price DOUBLE, low_price DOUBLE, close_price DOUBLE,
    open_auction_price DOUBLE, open_auction_ts VARCHAR, mid_auction_price DOUBLE, mid_auction_ts VARCHAR,
    close_auction_price DOUBLE, close_auction_ts VARCHAR, vwap DOUBLE);
CREATE TABLE IF NOT EXISTS flows (date DATE, isin VARCHAR, security_id BIGINT, ticker VARCHAR, wkn VARCHAR,
    reported_flow_dates VARCHAR, unreported_flow_dates VARCHAR, delayed_release BOOLEAN, execution_count BIGINT,
    mm_volume DOUBLE, agent_volume DOUBLE, prop_volume DOUBLE,
    aggressive_volume DOUBLE, passive_volume DOUBLE, auction_volume DOUBLE,
    mm_flow_qty DOUBLE, agent_flow_qty DOUBLE, prop_flow_qty DOUBLE);
CREATE TABLE IF NOT EXISTS xlm (date DATE, isin VARCHAR, notional DOUBLE, impact_bps DOUBLE);
CREATE TABLE IF NOT EXISTS trade_bars (date DATE, isin VARCHAR, bar VARCHAR, turnover DOUBLE, shares DOUBLE,
    price DOUBLE, buy_turnover DOUBLE, sell_turnover DOUBLE, trades BIGINT);
CREATE TABLE IF NOT EXISTS auction_sums (date DATE, isin VARCHAR, auction VARCHAR, turnover DOUBLE, shares DOUBLE,
    trades BIGINT);
CREATE OR REPLACE VIEW universe AS SELECT DISTINCT isin FROM members;
"""


def _vol(groups, roles, sides=("BUY", "SELL")):
    cols = [f'coalesce(TRY_CAST("{g}_{r}_{s}_EXECUTION_VOLUME" AS DOUBLE), 0)' for g in groups for r in roles for s in sides]
    return " + ".join(cols)


GROUPS, ROLES = ("MM", "AGENT", "PROP"), ("AGGRESSIVE", "PASSIVE", "AUCTION")
CENSORED = "REPORTED_FLOW_DATES IS NULL"  # below 7 executions: flow columns empty -> null, never 0


def _nullable(expr):
    return f"CASE WHEN {CENSORED} THEN NULL ELSE {expr} END"


# Each: (raw read, SELECT that keeps universe rows, date column in raw, unique key, rows the key applies to)
SQL = {
    "index": ("read_csv('{f}', all_varchar=true, filename=true)",
              # date from the file name: a stale file (MDAX 9 Oct holds the 8 Oct list) is that day's list
              """SELECT Index, strptime(regexp_extract(filename, '(\\d{8})[^/]*$', 1), '%Y%m%d')::DATE, Isin, Mnemonic, right(Wkn, 6), SecurityID::BIGINT FROM raw""",
              "strptime(Date, '%Y%m%d')::DATE",
              "(Index, Isin)", "true"),
    "ohlc": ("read_csv('{f}', all_varchar=true, filename=true)",
             """SELECT FACT_DATE::DATE, ISIN, SECURITY_ID::BIGINT, INSTRUMENT_NAME, TRADED_VOLUME::DOUBLE, TRADED_VALUE::DOUBLE,
                OPEN_PRICE::DOUBLE, HIGH_PRICE::DOUBLE, LOW_PRICE::DOUBLE, CLOSE_PRICE::DOUBLE,
                OPEN_AUCTION_PRICE::DOUBLE, OPEN_AUCTION_PRICE_TS, MID_AUCTION_PRICE::DOUBLE, MID_AUCTION_PRICE_TS,
                CLOSE_AUCTION_PRICE::DOUBLE, CLOSE_AUCTION_PRICE_TS, VWAP::DOUBLE
                FROM raw WHERE SEGMENT_NAME = 'EQUITIES' AND CURRENCY = 'EUR' AND ISIN IN (SELECT isin FROM universe)""",
             "FACT_DATE::DATE",
             "SECURITY_ID", "true"),
    "flows": ("read_csv('{f}', all_varchar=true, filename=true)",
              f"""SELECT DATE::DATE, ISIN, SECURITY_ID::BIGINT, TICKER, WKN, REPORTED_FLOW_DATES, UNREPORTED_FLOW_DATES,
                 coalesce(DELAYED_RELEASE = '1', false), EXECUTION_COUNT::BIGINT,
                 {_nullable(_vol(['MM'], ROLES))}, {_nullable(_vol(['AGENT'], ROLES))}, {_nullable(_vol(['PROP'], ROLES))},
                 {_nullable(_vol(GROUPS, ['AGGRESSIVE']))}, {_nullable(_vol(GROUPS, ['PASSIVE']))}, {_nullable(_vol(GROUPS, ['AUCTION']))},
                 {', '.join(_nullable(' + '.join(f'coalesce(TRY_CAST("{g}_{r}_FLOW_EXECUTION_QTY" AS DOUBLE), 0)' for r in ROLES)) for g in GROUPS)}
                 FROM raw WHERE CURRENCY = 'EUR' AND ISIN IN (SELECT isin FROM universe)""",
              "DATE::DATE",
              "SECURITY_ID", "coalesce(DELAYED_RELEASE, '') <> '1'"),
    "xlm": ("read_csv('{f}', all_varchar=true, filename=true)",
            """SELECT strptime(Date, '%Y%m%d')::DATE, ISIN, Notional_CCY::DOUBLE,
                      CASE WHEN lower(Impact_bps) = 'nan' THEN NULL ELSE TRY_CAST(Impact_bps AS DOUBLE) END  -- empty values arrive as 'nan'
               FROM raw WHERE ISIN IN (SELECT isin FROM universe)""",
            "strptime(Date, '%Y%m%d')::DATE",
            "(ISIN, Notional_CCY)", "true"),
}
TABLES = {"index": ["members"], "ohlc": ["ohlc"], "flows": ["flows"], "xlm": ["xlm"], "trades": ["trade_bars", "auction_sums"]}


def _load_trades(con, f: str, day) -> tuple[int, int]:
    """Aggregate one day of trades. Auction trades (SIDE empty) are matched to the OHLC auction times
    (local HH:MM:SS, 2 s tolerance); auction trades at other times are 'other' (volatility interruptions etc.)."""
    con.execute(f"""CREATE OR REPLACE TEMP TABLE t AS
        SELECT ISIN AS isin, QUANTITY::DOUBLE AS q, PRICE::DOUBLE AS p, SIDE AS side,
               timezone('Europe/Berlin', FACT_TIMESTAMP::TIMESTAMP::TIMESTAMPTZ) AS ts_local
        FROM read_csv('{f}') WHERE CURRENCY = 'EUR' AND ISIN IN (SELECT isin FROM universe)""")
    raw = con.execute(f"SELECT count(*) FROM read_csv('{f}')").fetchone()[0]
    kept = con.execute("SELECT count(*) FROM t").fetchone()[0]
    con.execute(f"""INSERT INTO trade_bars SELECT DATE '{day}', isin, strftime(time_bucket(INTERVAL 5 MINUTE, ts_local), '%H:%M'),
        sum(q*p), sum(q), arg_max(p, ts_local), sum(q*p) FILTER (side = 1), sum(q*p) FILTER (side = 2), count(*)
        FROM t GROUP BY ALL""")
    con.execute(f"""INSERT INTO auction_sums
        WITH a AS (SELECT t.isin, q, p, ts_local::TIME AS tm, o.open_auction_ts, o.mid_auction_ts, o.close_auction_ts
                   FROM t LEFT JOIN ohlc o ON o.isin = t.isin AND o.date = DATE '{day}' WHERE side IS NULL),
        near AS (SELECT *, CASE
            WHEN abs(epoch(tm) - epoch(TRY_CAST(open_auction_ts AS TIME))) <= 2 THEN 'open'
            WHEN abs(epoch(tm) - epoch(TRY_CAST(mid_auction_ts AS TIME))) <= 2 THEN 'mid'
            WHEN abs(epoch(tm) - epoch(TRY_CAST(close_auction_ts AS TIME))) <= 2 THEN 'close'
            ELSE 'other' END AS auction FROM a)
        SELECT DATE '{day}', isin, auction, sum(q*p), sum(q), count(*) FROM near GROUP BY ALL""")
    return raw, kept


def load_dataset(dataset: str, day: str | None = None, force: bool = False) -> None:
    con = connect()
    con.execute(SCHEMA)
    days = [day] if day else [d.isoformat() for d in trading_days()]
    if not force:
        done = {str(r[0]) for r in con.execute("SELECT date FROM coverage WHERE dataset = ? AND status = 'ok'", [dataset]).fetchall()}
        days = [d for d in days if d not in done]
    if not days:
        return
    for t in TABLES[dataset]:
        con.execute(f"DELETE FROM {t} WHERE date IN (SELECT unnest(?::DATE[]))", [days])
    con.execute("DELETE FROM coverage WHERE dataset = ? AND date IN (SELECT unnest(?::DATE[]))", [dataset, days])
    if dataset == "trades":
        for d in days:
            f = RAW / GLOBS["trades"].format(d=d.replace("-", ""))
            if not f.exists():
                _cover(con, dataset, d, 0, 0, "missing", f"no file {f.name}")
                continue
            raw, kept = _load_trades(con, str(f), d)
            _cover(con, dataset, d, raw, kept, *_check(con, dataset, d, raw))
        return
    files = [str(RAW / GLOBS[dataset].format(d=d.replace("-", ""))) for d in days] if day else [str(RAW / GLOBS[dataset].format(d="*"))]
    read, keep, date_col, key, keyed = SQL[dataset]
    con.execute(f"CREATE OR REPLACE TEMP TABLE raw AS SELECT * FROM {read.format(f=files[0])}")
    con.execute("""DELETE FROM raw WHERE strftime(strptime(regexp_extract(filename, '(\\d{8})[^/]*$', 1), '%Y%m%d'), '%Y-%m-%d')
        NOT IN (SELECT unnest(?::VARCHAR[]))""", [days])  # only days still to load
    con.execute(f"INSERT INTO {TABLES[dataset][0]} {keep}")
    # delayed-release flow rows carry earlier dates by design, so the date check skips them too
    checks = con.execute(f"""SELECT regexp_extract(filename, '(\\d{{8}})[^/]*$', 1) AS d, count(*),
        count(*) FILTER ({keyed} AND {date_col} <> strptime(d, '%Y%m%d')::DATE),
        count(*) FILTER ({keyed}) - count(DISTINCT {key}) FILTER ({keyed})
        FROM raw GROUP BY d""").fetchall()
    kept = dict(con.execute(f"SELECT strftime(date, '%Y%m%d'), count(*) FROM {TABLES[dataset][0]} GROUP BY 1").fetchall())
    for d, raw, bad_dates, dups in checks:
        status, msg = "ok", ""
        if bad_dates and dataset == "index":
            msg = f"{bad_dates} rows dated differently from the file name; the list is used for the file's day"
        elif bad_dates:
            status, msg = "fail", f"{bad_dates} rows with a date other than the file name"
        elif dups:
            status, msg = "fail", f"{dups} duplicate keys"
        _cover(con, dataset, f"{d[:4]}-{d[4:6]}-{d[6:]}", raw, kept.get(d, 0), status, msg)
    for d in set(days) - {f"{c[0][:4]}-{c[0][4:6]}-{c[0][6:]}" for c in checks}:
        _cover(con, dataset, d, 0, 0, "missing", "no file")


def _check(con, dataset: str, d: str, raw: int) -> tuple[str, str]:
    if raw == 0:
        return "fail", "no rows"
    over = con.execute("""SELECT count(*) FROM (SELECT isin, sum(turnover) FILTER (auction <> 'other') AS a FROM auction_sums
        WHERE date = ? GROUP BY isin) s JOIN (SELECT isin, sum(turnover) AS t FROM trade_bars WHERE date = ? GROUP BY isin) b
        USING (isin) WHERE a > t * 1.000001""", [d, d]).fetchone()[0]
    return ("fail", f"{over} stocks with auction turnover above daily turnover") if over else ("ok", "")


def _cover(con, dataset, d, raw, kept, status, msg):
    con.execute("INSERT INTO coverage VALUES (?, ?, ?, ?, ?, ?)", [dataset, d, raw, kept, status, msg])


def validate(dataset: str, day: str) -> dict:
    """Coverage row for one dataset and day: rows_raw, rows_kept, status, message."""
    con = connect(read_only=True)
    r = con.execute("SELECT rows_raw, rows_kept, status, message FROM coverage WHERE dataset = ? AND date = ?", [dataset, day]).fetchone()
    return dict(zip(("rows_raw", "rows_kept", "status", "message"), r)) if r else {"status": "missing"}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--date")
    ap.add_argument("--dataset", choices=ORDER)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    if not (a.all or a.date):
        ap.error("--all or --date")
    for ds in ([a.dataset] if a.dataset else ORDER):
        load_dataset(ds, a.date, a.force)
        print(ds, "done")
