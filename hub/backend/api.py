"""Step 7. Query API. All views read only from here. Contract: docs/api_contract.md"""
from __future__ import annotations

import csv
from functools import cache
from statistics import median, quantiles

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend.config import ROOT, load_config
from backend.db import connect
from backend.facts import day_facts, impact_facts
from backend.forensics import CONTEXT_ONLY, percentile, similar_cases
from backend.tradingdays import trading_days

app = FastAPI(title="Issuer Intelligence Hub")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# metric -> (SQL value over daily_metrics d, SQL baseline, unit, display scale, source, anomaly metric)
AUCTION = "(d.open_auction_share + d.mid_auction_share + d.close_auction_share)"
METRICS = {
    "turnover_eur": ("d.turnover_eur", "d.turnover_eur / nullif(d.rel_volume, 0)", "EUR", 1, "XETRA_OHLC", "rel_volume"),
    "rel_volume": ("d.rel_volume", "d.rel_volume_median", "x", 1, "XETRA_OHLC", "rel_volume"),
    "xlm_bps": ("d.xlm_bps", "d.xlm_bps_median", "bp", 1, "XLM", "xlm_bps"),
    "auction_share": (AUCTION, None, "%", 100, "XETRA_ONBOOK_TRADES", None),
    "abnormal_return": ("d.abnormal_return", "d.abnormal_return_median", "pp", 100, "XETRA_OHLC", "abnormal_return"),
    "close": ("d.close", None, "EUR", 1, "XETRA_OHLC", None),
    "auction_share_open": ("d.open_auction_share", "d.open_auction_share_median", "%", 100, "XETRA_ONBOOK_TRADES", None),
    "auction_share_midday": ("d.mid_auction_share", "d.mid_auction_share_median", "%", 100, "XETRA_ONBOOK_TRADES", None),
    "auction_share_close": ("d.close_auction_share", "d.close_auction_share_median", "%", 100, "XETRA_ONBOOK_TRADES", None),
    "mm_share": ("d.mm_share", "d.mm_share_median", "%", 100, "XETRA_FLOW_DYNAMICS_EQUITY", None),
    "agent_share": ("d.agent_share", "d.agent_share_median", "%", 100, "XETRA_FLOW_DYNAMICS_EQUITY", None),
    "prop_share": ("d.prop_share", "d.prop_share_median", "%", 100, "XETRA_FLOW_DYNAMICS_EQUITY", None),
}
N = int(load_config()["baseline_window_days"])


def q(sql: str, params: list | None = None, con=None) -> list[dict]:
    cur = (con or connect(read_only=True)).execute(sql, params or [])
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def metric_or_400(metric: str):
    if metric not in METRICS:
        raise HTTPException(400, f"metric must be one of {list(METRICS)}")
    return METRICS[metric]


def entity_or_404(isin: str) -> dict:
    rows = q("SELECT * FROM entities WHERE isin = ?", [isin])
    if not rows:
        raise HTTPException(404, f"unknown isin {isin}")
    return rows[0]


def scaled(v, scale):
    return None if v is None else round(v * scale, 4)


def iso(d):
    return d.isoformat() if d is not None else None


@app.get("/companies")
def companies():
    # current: member of DAX, MDAX or SDAX on the last trading day (false for leavers and pre-swap ISINs of FRE, QIA)
    rows = q("""SELECT isin, ticker, name, idx AS index, sector, focus,
        isin IN (SELECT isin FROM members WHERE date = (SELECT max(date) FROM members)) AS current
        FROM entities ORDER BY NOT focus, idx, ticker""")
    return {"companies": rows}


@app.get("/companies/{isin}/timeseries")
def timeseries(isin: str, metric: str, start: str | None = None, end: str | None = None, order_size: float | None = None):
    """value, baseline (20-day median), peer_median (same index that day), anomaly. order_size switches xlm_bps."""
    entity_or_404(isin)
    val, base, unit, scale, source, anom = metric_or_400(metric)
    src, con = "daily_metrics", connect(read_only=True)
    if metric == "xlm_bps" and order_size:  # other order sizes come straight from the XLM table
        src = "xlm_at_size"
        con.execute(f"""CREATE TEMP TABLE xlm_at_size AS SELECT d.* EXCLUDE (xlm_bps, xlm_bps_median), x.impact_bps AS xlm_bps,
                   median(x.impact_bps) OVER (PARTITION BY d.isin ORDER BY d.date ROWS BETWEEN {N} PRECEDING AND 1 PRECEDING) AS xlm_bps_median
                   FROM daily_metrics d LEFT JOIN xlm x ON x.isin = d.isin AND x.date = d.date AND x.notional = {float(order_size)}""")
    base = base or f"median({val}) OVER (PARTITION BY d.isin ORDER BY d.date ROWS BETWEEN {N} PRECEDING AND 1 PRECEDING)"
    rows = q(f"""WITH d AS (SELECT * FROM {src} d),
        me AS (SELECT d.date, {val} AS value, {base} AS baseline FROM d WHERE d.isin = ?),
        pm AS (SELECT d.date, median({val}) AS peer_median FROM d
               WHERE d.is_member AND d.idx = (SELECT idx FROM entities WHERE isin = ?) AND d.isin <> ? GROUP BY d.date)
        SELECT me.*, pm.peer_median, a.isin IS NOT NULL AS anomaly FROM me LEFT JOIN pm USING (date)
        LEFT JOIN anomalies a ON a.isin = ? AND a.date = me.date AND a.metric = ?
        WHERE me.date BETWEEN coalesce(?::DATE, DATE '2000-01-01') AND coalesce(?::DATE, DATE '2100-01-01') ORDER BY me.date""",
             [isin, isin, isin, isin, anom, start, end], con)
    points = [{"date": iso(r["date"]), "value": scaled(r["value"], scale), "baseline": scaled(r["baseline"], scale),
               "peer_median": scaled(r["peer_median"], scale), "anomaly": r["anomaly"]} for r in rows]
    return {"isin": isin, "metric": metric, "unit": unit, "source": source,
            "order_size": order_size or load_config()["order_size_eur"] if metric == "xlm_bps" else None, "points": points}


@app.get("/indices/timeseries")
def indices_timeseries(metric: str, start: str | None = None, end: str | None = None):
    """DAX vs MDAX vs SDAX side by side: median of the metric over each index's members per day."""
    val, _, unit, scale, source, _ = metric_or_400(metric)
    rows = q(f"""SELECT d.date, d.idx, median({val}) AS value FROM daily_metrics d WHERE d.is_member
        AND d.date BETWEEN coalesce(?::DATE, DATE '2000-01-01') AND coalesce(?::DATE, DATE '2100-01-01')
        GROUP BY ALL ORDER BY d.date""", [start, end])
    points: dict = {}
    for r in rows:
        points.setdefault(iso(r["date"]), {"date": iso(r["date"])})[r["idx"]] = scaled(r["value"], scale)
    return {"metric": metric, "unit": unit, "source": source, "stat": "median of index members", "points": list(points.values())}


@app.get("/companies/{isin}/trend")
def trend(isin: str):
    """Median of the last 20 trading days vs the 60 before, for turnover, spread and auction share. Facts only."""
    entity_or_404(isin)
    out = []
    for key, m in (("turnover_eur", "turnover_eur"), ("xlm_bps", "xlm_bps"), ("auction_share", "auction_share")):
        val, _, unit, scale, source, _ = METRICS[m]
        r = q(f"""WITH d AS (SELECT d.date, {val} AS v, row_number() OVER (ORDER BY d.date DESC) AS k FROM daily_metrics d WHERE d.isin = ?)
            SELECT max(date) FILTER (k = 1) AS last, median(v) FILTER (k <= 20) AS recent, median(v) FILTER (k BETWEEN 21 AND 80) AS before,
                   min(date) FILTER (k = 80) AS first FROM d""", [isin])[0]
        found = r["recent"] is not None and r["before"] is not None
        out.append({"key": f"{key}_trend", "value": scaled(r["recent"], scale), "unit": unit, "baseline": scaled(r["before"], scale),
                    "date": iso(r["last"]), "source": source, "status": "found" if found else "not_found",
                    "reason": None if found else "fewer than 80 trading days of data",
                    "window": f"median {iso(r['first'])} to {iso(r['last'])}: last 20 trading days (value) vs the 60 before (baseline)"})
    return {"isin": isin, "facts": out}


@app.get("/companies/{isin}/peers")
def peers(isin: str, basis: str = "index", metric: str = "xlm_bps", start: str | None = None, end: str | None = None):
    """Median of the metric over the period for the stock and its peer group; rank 1 = lowest value."""
    e = entity_or_404(isin)
    if basis not in ("index", "sector", "size"):
        raise HTTPException(400, "basis must be index, sector or size")
    val, _, unit, scale, source, _ = metric_or_400(metric)
    rows = q(f"""SELECT d.isin, en.ticker, median({val}) AS value FROM daily_metrics d JOIN entities en USING (isin)
        WHERE (d.isin = ? OR d.isin IN (SELECT peer_isin FROM peers WHERE isin = ? AND basis = ?))
          AND d.date BETWEEN coalesce(?::DATE, DATE '2000-01-01') AND coalesce(?::DATE, DATE '2100-01-01')
        GROUP BY ALL ORDER BY value NULLS LAST""", [isin, isin, basis, start, end])
    group = {"index": e["idx"], "sector": e["sector"]}.get(basis)
    if basis == "size":
        c = q("SELECT cohort FROM size_cohort WHERE isin = ?", [isin])[0]["cohort"]
        group = f"{e['idx']} turnover tercile {c} of 3"
    dist = [{"isin": r["isin"], "ticker": r["ticker"], "value": scaled(r["value"], scale)} for r in rows]
    vals = [d["value"] for d in dist if d["value"] is not None]
    me = next(d for d in dist if d["isin"] == isin)
    return {"isin": isin, "basis": basis, "group": group, "metric": metric, "unit": unit, "source": source,
            "value": me["value"], "rank": vals.index(me["value"]) + 1 if me["value"] is not None else None,
            "of": len(vals), "median": round(median(vals), 4) if vals else None, "distribution": dist}


@cache
def _market_calendar() -> dict:
    """data/reference/market_calendar.csv: market-wide dates with a public source. Read once per process."""
    with open(ROOT / "data" / "reference" / "market_calendar.csv", newline="") as f:
        return {r["date"]: {"label": r["label"], "source": r["source"], "url": r["url"]} for r in csv.DictReader(f)}


def _market_event(day: str | None) -> dict | None:
    """A market-wide calendar event on the same day, or None. A match, not a cause."""
    return _market_calendar().get(day)


def _sector_days(isin: str, day: str | None = None) -> dict:
    """date -> {label, source, url, sector, anomalous, members} for the sector-wide days of the stock's sector."""
    rows = q("""SELECT sd.* FROM sector_days sd JOIN entities en ON en.sector = sd.sector
        WHERE en.isin = ? AND sd.sector_wide AND (?::DATE IS NULL OR sd.date = ?::DATE)""", [isin, day, day])
    return {iso(r["date"]): {"label": f"{r['anomalous']} of {r['members']} {r['sector']} stocks in DAX, MDAX and SDAX had unusual turnover that day",
                             "source": "Xetra trading data, own calculation", "url": None, "sector": r["sector"],
                             "anomalous": r["anomalous"], "members": r["members"]} for r in rows}


def _sector_event(isin: str, day: str | None) -> dict | None:
    """The stock's sector was unusual as a whole on that day (triage.flag_sector_days), or None. A match, not a cause."""
    return _sector_days(isin, day).get(day) if day else None


def _event_obj(event_id: int | None, full: bool = False) -> dict | None:
    if event_id is None:
        return None
    r = q("SELECT * FROM events WHERE id = ?", [event_id])[0]
    if not full:
        return {"id": r["id"], "type": r["type"], "title": r["title"], "url": r["url"]}
    return {"id": r["id"], "isin": r["isin"], "type": r["type"], "title": r["title"],
            "published_at_utc": r["published_at_utc"].strftime("%Y-%m-%dT%H:%M:%SZ") if r["published_at_utc"] else None,
            "effective_trading_day": iso(r["effective_trading_day"]), "source": r["source"], "url": r["url"]}


@app.get("/companies/{isin}/cases")
def cases(isin: str):
    """Episodes and events in one list, each with a status. counts covers the episodes (unusual days) only.
    Events not matched to an episode appear as kind 'event' with status 'matched' (matched to their trading day)."""
    entity_or_404(isin)
    eps = q("""SELECT * FROM cases WHERE isin = ? ORDER BY start""", [isin])
    sectors = _sector_days(isin)
    linked = {e["event_id"] for e in eps}
    evs = q("SELECT * FROM events WHERE isin = ? AND effective_trading_day IS NOT NULL ORDER BY effective_trading_day", [isin])
    out = [{"id": f"ep-{e['id']}", "kind": "episode", "start": iso(e["start"]), "end": iso(e["end"]), "peak_date": iso(e["peak_date"]),
            "metrics": e["metrics"], "score": e["score"], "status": e["status"], "event": _event_obj(e["event_id"]),
            "market_event": _market_event(iso(e["peak_date"])), "sector_event": sectors.get(iso(e["peak_date"]))} for e in eps]
    out += [{"id": f"ev-{v['id']}", "kind": "event", "start": iso(v["effective_trading_day"]), "end": iso(v["effective_trading_day"]),
             "peak_date": iso(v["effective_trading_day"]), "metrics": [], "score": 0, "status": "matched", "event": _event_obj(v["id"]),
             "market_event": _market_event(iso(v["effective_trading_day"])), "sector_event": sectors.get(iso(v["effective_trading_day"]))}
            for v in evs if v["id"] not in linked]
    out.sort(key=lambda c: c["start"])
    counts = {s: sum(e["status"] == s for e in eps) for s in ("matched", "market_day", "sector_day", "unmatched")}
    return {"isin": isin, "counts": counts, "cases": out}


def _intraday(isin: str, day: str) -> list[dict]:
    rows = q("""SELECT bar, turnover, price, buy_turnover / nullif(coalesce(buy_turnover, 0) + coalesce(sell_turnover, 0), 0) AS buy_share
        FROM trade_bars WHERE isin = ? AND date = ? ORDER BY bar""", [isin, day])
    return [{"time": r["bar"], "turnover": round(r["turnover"], 2), "price": r["price"],
             "buy_share": None if r["buy_share"] is None else round(r["buy_share"], 3)} for r in rows]


def _text(facts, event: dict | None, market_event: dict | None, sector_event: dict | None = None) -> str | None:
    try:
        from backend.text import explain  # Track B owns what happens inside
        return explain(facts, event=event, market_event=market_event, sector_event=sector_event)
    except Exception:  # not built yet or the model failed: the card shows facts without text
        return None


def _day_status(isin: str, day: str) -> tuple[str, int | None]:
    """Status of the episode containing the day; otherwise matched if an event falls on it, else market_day
    (index-wide or in the market calendar), sector_day or unmatched. Same order as forensics.match_episodes."""
    ep = q("SELECT status, event_id FROM cases WHERE isin = ? AND ? BETWEEN start AND \"end\"", [isin, day])
    if ep:
        return ep[0]["status"], ep[0]["event_id"]
    ev = q("SELECT id FROM events WHERE isin = ? AND effective_trading_day = ? ORDER BY id LIMIT 1", [isin, day])
    if ev:
        return "matched", ev[0]["id"]
    md = q("""SELECT market_wide FROM market_days WHERE date = ? AND idx = (SELECT idx FROM entities WHERE isin = ?)""", [day, isin])
    if (md and md[0]["market_wide"]) or _market_event(day):
        return "market_day", None
    return ("sector_day" if _sector_event(isin, day) else "unmatched"), None


def _card(isin: str, day: str, status: str, event_id: int | None, facts) -> dict:
    sim = similar_cases(event_id) if event_id else {}
    event = _event_obj(event_id, full=True)
    market_event = _market_event(day)
    sector_event = _sector_event(isin, day)
    return {"isin": isin, "date": day, "status": status, "event": event, "market_event": market_event,
            "sector_event": sector_event, "facts": [f.dict() for f in facts], "intraday": _intraday(isin, day),
            "similar": sim.get("index"), "similar_groups": list(sim.values()),
            "text": _text(facts, event, market_event, sector_event)}


@app.get("/impact/{event_id}")
def impact(event_id: int):
    ev = q("SELECT isin, effective_trading_day FROM events WHERE id = ?", [event_id])
    if not ev:
        raise HTTPException(404, f"unknown event {event_id}")
    isin, day = ev[0]["isin"], iso(ev[0]["effective_trading_day"])
    status, _ = _day_status(isin, day)
    return _card(isin, day, status, event_id, impact_facts(event_id))


@app.get("/impact/day/{isin}/{day}")
def impact_day(isin: str, day: str):
    entity_or_404(isin)
    facts = day_facts(isin, day)
    if not facts:
        raise HTTPException(404, f"no trading data for {isin} on {day}")
    status, event_id = _day_status(isin, day)
    return _card(isin, day, status, event_id, facts)


@app.get("/compare")
def compare(type: str, index: str | None = None, sector: str | None = None, metric: str = "rel_volume", selected: int | None = None):
    """All events of one type as a distribution; percentile of each within the filtered group."""
    cols = {"rel_volume": ("x", 1), "abnormal_return": ("pp", 100), "xlm_bps": ("bp", 1), "car_5": ("pp", 100),
            "closing_auction_turnover": ("EUR", 1), "opening_auction_turnover": ("EUR", 1)}
    if metric not in cols:
        raise HTTPException(400, f"metric must be one of {list(cols)}")
    unit, scale = cols[metric]
    rows = q(f"""SELECT ev.id AS event_id, ev.isin, en.ticker, ev.effective_trading_day AS date, ei.{metric} AS value
        FROM events ev JOIN entities en USING (isin) JOIN event_impact ei ON ei.event_id = ev.id
        WHERE ev.type = ? AND (?::VARCHAR IS NULL OR en.idx = ?) AND (?::VARCHAR IS NULL OR en.sector = ?)
        ORDER BY ev.effective_trading_day""", [type, index, index, sector, sector])
    vals = [r["value"] for r in rows if r["value"] is not None]
    items = [{"event_id": r["event_id"], "isin": r["isin"], "ticker": r["ticker"], "date": iso(r["date"]),
              "value": scaled(r["value"], scale), "percentile": percentile(r["value"], vals), "selected": r["event_id"] == selected}
             for r in rows]
    qs = quantiles(vals, n=4, method="inclusive") if len(vals) >= 2 else [None, vals[0] if vals else None, None]
    return {"type": type, "index": index, "sector": sector, "metric": metric, "unit": unit, "n": len(vals),
            "median": scaled(qs[1], scale), "p25": scaled(qs[0], scale), "p75": scaled(qs[2], scale), "items": items}


# ---------------------------------------------------------------- alerts (build guide step 11)
# shortcut: the replay position lives in memory and resets on restart; store it in the database when /ingest loads real new days
_REPLAY: dict = {"as_of": None}
METRIC_WORDS = {"rel_volume": "turnover", "xlm_bps": "spread", "abnormal_return": "return vs index"}
EVENT_WORDS = {"earnings": "Results", "dividend": "Dividend", "ad_hoc": "Ad hoc announcement", "press_release": "Press release",
               "m_and_a": "M&A announcement", "index_change": "Index change", "other": "Company event"}


def _priority(score: int | None, event_type: str | None, a: dict) -> str:
    """HIGH / MED / LOW. With an unusual day: from its score. Event only: MED for results, ad hoc, M&A, else LOW."""
    if score is not None:
        return "HIGH" if score >= a["high"] else "MED" if score >= a["medium"] else "LOW"
    return "MED" if event_type in a["medium_event_types"] else "LOW"


def _alerts() -> dict:
    a = load_config()["alerts"]
    days = [d.isoformat() for d in trading_days()]
    as_of = _REPLAY["as_of"] or a["replay_from"]
    later = [d for d in days if d > as_of]
    eps = q("""SELECT ca.id, ca.isin, en.ticker, en.name, ca.start, ca.peak_date, ca.score, ca.status, ca.metrics, ca.event_id,
                      ev.type AS event_type, ev.title AS event_title
               FROM cases ca JOIN entities en USING (isin) LEFT JOIN events ev ON ev.id = ca.event_id
               WHERE en.focus AND ca.start BETWEEN ?::DATE AND ?::DATE""", [a["list_from"], as_of])
    linked = {e["event_id"] for e in eps}
    evs = q(f"""SELECT ev.id, ev.isin, en.ticker, en.name, ev.effective_trading_day AS day, ev.type, ev.title
                FROM events ev JOIN entities en USING (isin)
                WHERE en.focus AND ev.type NOT IN {CONTEXT_ONLY} AND ev.effective_trading_day BETWEEN ?::DATE AND ?::DATE""",
            [a["list_from"], as_of])
    out = []
    for e in eps:
        what = ", ".join(METRIC_WORDS.get(m, m) for m in e["metrics"])
        title = f"Unusual {what}" + (f", on the same days as: {EVENT_WORDS.get(e['event_type'], 'event').lower()}" if e["event_id"] else "")
        out.append({"id": f"ep-{e['id']}", "kind": "episode", "isin": e["isin"], "ticker": e["ticker"], "name": e["name"],
                    "date": iso(e["start"]), "priority": _priority(e["score"], None, a), "score": e["score"], "status": e["status"],
                    "title": title, "detail": e["event_title"], "market_event": _market_event(iso(e["peak_date"])),
                    "link": f"/c/{e['isin']}/impact/day/{iso(e['peak_date'])}"})
    for v in evs:
        if v["id"] in linked:
            continue
        out.append({"id": f"ev-{v['id']}", "kind": "event", "isin": v["isin"], "ticker": v["ticker"], "name": v["name"],
                    "date": iso(v["day"]), "priority": _priority(None, v["type"], a), "score": None, "status": None,
                    "title": f"{EVENT_WORDS.get(v['type'], 'Company event')}, no unusual trading flagged", "detail": v["title"],
                    "market_event": _market_event(iso(v["day"])), "link": f"/c/{v['isin']}/impact/event/{v['id']}"})
    for x in out:
        x["new"] = x["date"] > a["replay_from"]  # arrived through "Load new trading day" in this session
    rank = {"HIGH": 0, "MED": 1, "LOW": 2}
    out.sort(key=lambda x: x["date"], reverse=True)
    out.sort(key=lambda x: (not x["new"], rank[x["priority"]]))
    rule = (f"Priority ranks how unusual the day was, not whether it was favourable. With an unusual day it follows the "
            f"episode score (0 to 100, from the size of the deviation and the number of unusual metrics): HIGH from {a['high']}, "
            f"MED from {a['medium']}, LOW below. An event without unusual trading is MED for results, ad hoc and M&A "
            f"announcements, otherwise LOW. Voting rights and directors' dealings raise no alert.")
    return {"as_of": as_of, "next_day": later[0] if later else None, "replay": True, "priority_rule": rule,
            "counts": {p: sum(x["priority"] == p for x in out) for p in rank}, "new": sum(x["new"] for x in out), "alerts": out}


@app.get("/alerts")
def alerts():
    """Alerts for the focus stocks up to the replay day, new ones first, then by priority and date."""
    return _alerts()


@app.post("/alerts/load_next")
def alerts_load_next():
    """Demo replay of "Load new trading day": moves the as-of day one trading day on. The data is already in the database."""
    nxt = _alerts()["next_day"]
    if nxt is None:
        raise HTTPException(409, "no later trading day in the data")
    _REPLAY["as_of"] = nxt
    out = _alerts()
    return out | {"loaded_day": nxt, "loaded": [x for x in out["alerts"] if x["date"] == nxt]}


@app.post("/alerts/reset")
def alerts_reset():
    _REPLAY["as_of"] = None
    return _alerts()


# ---------------------------------------------------------------- results-day briefing and assistant
RESULT_COLS = (("rel_volume", "x", 1, 2), ("return_1d", "%", 100, 2), ("abnormal_return", "pp", 100, 2), ("xlm_bps", "bp", 1, 1),
               ("xlm_bps_baseline", "bp", 1, 1), ("days_to_normal", "days", 1, 0))


@app.get("/companies/{isin}/briefing")
def briefing(isin: str, type: str = "earnings"):
    """What the stock's own past events of one type looked like in trading, plus the next known date. Past only, no forecast."""
    e = entity_or_404(isin)
    rows = q("""SELECT ev.id AS event_id, ev.title, ev.url, ei.* EXCLUDE (event_id, isin) FROM events ev
                JOIN event_impact ei ON ei.event_id = ev.id WHERE ev.isin = ? AND ev.type = ? ORDER BY ei.day""", [isin, type])
    allv = [r["rel_volume"] for r in q("""SELECT ei.rel_volume FROM events ev JOIN event_impact ei ON ei.event_id = ev.id
                                          WHERE ev.type = ?""", [type])]
    past = [{"event_id": r["event_id"], "date": iso(r["day"]), "title": r["title"], "url": r["url"],
             "percentile": percentile(r["rel_volume"], allv),
             **{c: (None if r[c] is None else round(r[c] * sc, dec)) for c, _, sc, dec in RESULT_COLS}} for r in rows]
    last = trading_days()[-1].isoformat()
    with open(ROOT / "data" / "reference" / "events_manual.csv", newline="") as f:  # dates after the data ends are only here
        upcoming = [{"date": r["published_at_local"][:10], "title": r["title"], "url": r["url"]} for r in csv.DictReader(f)
                    if r["isin"] == isin and r["type"] == type and r["published_at_local"][:10] > last]
    vals = [p["rel_volume"] for p in past if p["rel_volume"] is not None]
    return {"isin": isin, "ticker": e["ticker"], "type": type, "data_until": last, "upcoming": upcoming, "past": past,
            "units": {c: u for c, u, _, _ in RESULT_COLS}, "n_all": sum(v is not None for v in allv),
            "rel_volume_range": [min(vals), max(vals)] if vals else None,
            "source": "XETRA_OHLC, XLM; event dates from the company's public announcements",
            "note": "Past event days only. No forecast."}


QUESTIONS = {
    "why_move": "Why did the share move on this day?",
    "liquidity": "Has our liquidity improved?",
    "spread_peers": "How does our spread compare with our peers?",
    "results": "How did the market react to our quarterly results?",
}


def _intent(question: str) -> str | None:
    t = question.lower()
    if "liquidity" in t:
        return "liquidity"
    if "peer" in t:
        return "spread_peers"
    if "result" in t or "earnings" in t:
        return "results"
    if "why" in t or "fall" in t or "fell" in t or "move" in t:
        return "why_move"
    return None


@app.get("/ask/questions")
def ask_questions():
    return {"questions": [{"id": k, "text": v} for k, v in QUESTIONS.items()]}


@app.post("/ask")
def ask(isin: str, question: str, day: str | None = None):
    """Answers the four example questions from the fact layer. Fixed sentence patterns; every figure has a date and a source.
    No language model here, except the card text reused for the 'why' question."""
    e = entity_or_404(isin)
    name, intent = e["name"], _intent(question)
    if intent == "liquidity":
        facts = trend(isin)["facts"]
        f = {x["key"]: x for x in facts}
        t, x, au = f["turnover_eur_trend"], f["xlm_bps_trend"], f["auction_share_trend"]
        word = lambda v, b: "above" if v > b else "below" if v < b else "equal to"
        text = (f"Over the last 20 trading days to {t['date']}, {name}'s median daily turnover was EUR {t['value']:,.0f}, "
                f"{word(t['value'], t['baseline'])} the EUR {t['baseline']:,.0f} of the 60 trading days before (source: {t['source']}). "
                f"The median spread for a EUR 25,000 order was {x['value']:.1f} bp, {word(x['value'], x['baseline'])} the "
                f"{x['baseline']:.1f} bp before (source: {x['source']}). The auction share of turnover was {au['value']:.1f}%, "
                f"{word(au['value'], au['baseline'])} the {au['baseline']:.1f}% before (source: {au['source']}).")
        return {"intent": intent, "text": text, "facts": facts, "links": [{"label": "Overview charts", "to": f"/c/{isin}"}]}
    if intent == "spread_peers":
        groups = [peers(isin, basis=b, metric="xlm_bps") for b in ("index", "sector", "size")]
        parts = [f"rank {g['rank']} of {g['of']} in {g['group']} (group median {g['median']:.1f} bp)" for g in groups]
        text = (f"{name}'s median spread for a EUR 25,000 order in 2026 was {groups[0]['value']:.1f} bp: {'; '.join(parts)}. "
                f"Rank 1 is the lowest spread. Period 2 Jan to 30 Oct 2026, source: XLM.")
        facts = [{"key": f"xlm_bps_rank_{g['basis']}", "value": g["rank"], "unit": f"of {g['of']}", "baseline": g["median"],
                  "date": "2026-10-30", "source": "XLM", "status": "found", "reason": None} for g in groups]
        return {"intent": intent, "text": text, "facts": facts, "links": [{"label": "Peers", "to": f"/c/{isin}/peers"}]}
    if intent == "results":
        b = briefing(isin)
        if not b["past"]:
            return {"intent": intent, "text": f"No results dates for {name} are in the event list.", "facts": [], "links": []}
        parts = [f"on {p['date']} ({p['title']}) turnover was {p['rel_volume']}x the 20-day baseline and the return against the "
                 f"index median {p['abnormal_return']:+.2f} pp" if p["rel_volume"] is not None else
                 f"on {p['date']} ({p['title']}) the return against the index median was {p['abnormal_return']:+.2f} pp "
                 f"(no turnover baseline yet)" for p in b["past"]]
        text = f"{name} has {len(b['past'])} results days in the 2026 data: " + "; ".join(parts) + ". Source: XETRA_OHLC."
        if b["upcoming"]:
            text += f" Next date in the company calendar: {b['upcoming'][0]['title']} on {b['upcoming'][0]['date']} (after the data ends)."
        return {"intent": intent, "text": text, "facts": [], "briefing": b,
                "links": [{"label": p["date"], "to": f"/c/{isin}/impact/event/{p['event_id']}"} for p in b["past"]]}
    if intent == "why_move":
        if not day:  # without a day: the stock's highest-scored unusual period
            top = q("SELECT peak_date FROM cases WHERE isin = ? ORDER BY score DESC, peak_date DESC LIMIT 1", [isin])
            if not top:
                return {"intent": intent, "text": f"No unusual day is flagged for {name} in 2026.", "facts": [], "links": []}
            day = iso(top[0]["peak_date"])
        card = impact_day(isin, day)
        return {"intent": intent, "text": card["text"], "facts": card["facts"], "day": day,
                "links": [{"label": f"Impact card {day}", "to": f"/c/{isin}/impact/day/{day}"}]}
    return {"intent": None, "facts": [], "links": [],
            "text": "I can answer these four questions from the verified figures: " + " ".join(QUESTIONS.values())}


# ---------- Publication timing ----------
# Events of one type, grouped by when they were published (Europe/Berlin) relative to their trading day.
# Descriptive only: how trading looked on day 0 in each group. No forecast, no recommendation.
TIMING_SLOTS = (
    ("before_day", "Before the trading day", "earlier day: after 17:35, weekend or holiday"),
    ("pre_open", "Before the open", "same day, before 09:00"),
    ("trading", "During trading", "same day, 09:00 to 17:35"),
)
# key -> (SQL over event_impact ei and daily_metrics d of day 0, unit, display scale, source)
TIMING_METRICS = {
    "open_gap_abs": ("abs(ei.open_gap)", "pp", 100, "XETRA_OHLC"),
    "rel_volume": ("ei.rel_volume", "x", 1, "XETRA_OHLC"),
    "abnormal_return_abs": ("abs(ei.abnormal_return)", "pp", 100, "XETRA_OHLC"),
    "xlm_ratio": ("ei.xlm_bps / nullif(ei.xlm_bps_baseline, 0)", "x", 1, "XLM"),
    "open_auction_share": ("d.open_auction_share", "%", 100, "XETRA_ONBOOK_TRADES"),
    "close_auction_share": ("d.close_auction_share", "%", 100, "XETRA_ONBOOK_TRADES"),
}
TIMING_TYPES = ("earnings", "ad_hoc", "m_and_a", "dividend", "press_release")


def timing_slot(published_at_utc, day):
    """(slot, 'HH:MM' Europe/Berlin) of a publication for its effective trading day.

    None as slot: time not known (stored as 00:00 Berlin, date-only sources) or the time does not fit the day."""
    from datetime import time, timezone
    from backend.tradingdays import BERLIN, CUTOFF
    if published_at_utc is None or day is None:
        return None, None
    utc = published_at_utc if published_at_utc.tzinfo else published_at_utc.replace(tzinfo=timezone.utc)
    t = utc.astimezone(BERLIN)
    if t.time() == time(0):
        return None, None
    hhmm = t.strftime("%H:%M")
    if t.date() < day:
        return "before_day", hhmm
    if t.date() == day and t.time() < time(9):
        return "pre_open", hhmm
    if t.date() == day and t.time() <= CUTOFF:
        return "trading", hhmm
    return None, hhmm


@app.get("/timing")
def timing(type: str = "earnings", index: str | None = None, sector: str | None = None):
    """Day-0 trading of all events of one type, grouped by publication time. Quartiles per group and metric."""
    if type not in TIMING_TYPES:
        raise HTTPException(400, f"type must be one of {list(TIMING_TYPES)} (other types have no publication time)")
    cols = ", ".join(f"{sql} AS {k}" for k, (sql, *_) in TIMING_METRICS.items())
    rows = q(f"""SELECT ev.id AS event_id, ev.isin, en.ticker, ev.title, ev.source, ev.url, ev.published_at_utc,
               ev.effective_trading_day AS date, {cols}
        FROM events ev JOIN entities en USING (isin) JOIN event_impact ei ON ei.event_id = ev.id
        LEFT JOIN daily_metrics d ON d.isin = ev.isin AND d.date = ev.effective_trading_day
        WHERE ev.type = ? AND (?::VARCHAR IS NULL OR en.idx = ?) AND (?::VARCHAR IS NULL OR en.sector = ?)
        ORDER BY ev.effective_trading_day, en.ticker""", [type, index, index, sector, sector])
    items, unknown = [], 0
    for r in rows:
        slot, hhmm = timing_slot(r["published_at_utc"], r["date"])
        if slot is None:
            unknown += 1
            continue
        items.append({"event_id": r["event_id"], "isin": r["isin"], "ticker": r["ticker"], "date": iso(r["date"]),
                      "published_at_utc": r["published_at_utc"].isoformat() + "Z", "time_berlin": hhmm, "slot": slot,
                      "title": r["title"], "source": r["source"], "url": r["url"],
                      "values": {k: scaled(r[k], m[2]) for k, m in TIMING_METRICS.items()}})

    def stats(vals):
        if not vals:
            return {"n": 0, "median": None, "p25": None, "p75": None}
        qs = quantiles(vals, n=4, method="inclusive") if len(vals) >= 2 else [vals[0]] * 3
        return {"n": len(vals), "median": round(qs[1], 4), "p25": round(qs[0], 4), "p75": round(qs[2], 4)}

    metrics = [{"key": k, "unit": unit, "source": source,
                "by_slot": {s: stats([i["values"][k] for i in items if i["slot"] == s and i["values"][k] is not None])
                            for s, *_ in TIMING_SLOTS}}
               for k, (_, unit, _, source) in TIMING_METRICS.items()]
    return {"type": type, "index": index, "sector": sector, "n": len(items), "n_time_unknown": unknown,
            "time_source": "events.published_at_utc, shown in Europe/Berlin",
            "slots": [{"key": s, "label": label, "rule": rule, "n": sum(i["slot"] == s for i in items)}
                      for s, label, rule in TIMING_SLOTS],
            "metrics": metrics, "items": items}
