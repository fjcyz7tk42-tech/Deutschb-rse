"""The fact object: the contract between analytics, text and frontend.

Every number shown anywhere is one Fact. Text generation receives Facts only.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from backend.db import connect
from backend.forensics import impact_rows

OHLC, XLM, TRADES, FLOWS = "XETRA_OHLC", "XLM", "XETRA_ONBOOK_TRADES", "XETRA_FLOW_DYNAMICS_EQUITY"
NO_HISTORY = "fewer than 20 trading days of history"
NO_FLOW = "flow data censored (fewer than 7 executions) or reported as a multi-day sum"


@dataclass
class Fact:
    key: str                      # e.g. "rel_volume"
    value: float | str | None
    unit: str | None              # "x", "bp", "%", "EUR"
    baseline: float | None
    date: str                     # trading day, ISO
    source: str                   # dataset name or event URL
    status: Literal["found", "not_found", "not_checked"] = "found"
    reason: str | None = None     # why value is None

    def dict(self) -> dict:
        return asdict(self)


# key, column in impact row, unit, scale, decimals, source, baseline (column name, constant or None), reason if missing
SPEC = (
    ("rel_volume", "rel_volume", "x", 1, 2, OHLC, 1.0, NO_HISTORY),
    ("return_1d", "return_1d", "%", 100, 2, OHLC, None, "no closing price on this or the previous day"),
    ("market_return", "market_return", "%", 100, 2, OHLC, None, "no index median on this day"),
    ("sector_return", "sector_return", "%", 100, 2, OHLC, None, "no sector median on this day"),
    ("company_return", "company_return", "%", 100, 2, OHLC, None, "no sector median on this day"),
    ("abnormal_return", "abnormal_return", "pp", 100, 2, OHLC, 0.0, "no return on this day"),
    ("abnormal_return_5d", "car_5", "pp", 100, 2, OHLC, 0.0, "fewer than 5 trading days after this day in the data"),
    ("xlm_bps", "xlm_bps", "bp", 1, 1, XLM, "xlm_bps_baseline", "no XLM value: XLM covers index members only and is empty at some order sizes"),
    ("opening_auction_turnover", "opening_auction_turnover", "EUR", 1, 0, TRADES, "opening_auction_baseline", "no trades on this day"),
    ("closing_auction_turnover", "closing_auction_turnover", "EUR", 1, 0, TRADES, "closing_auction_baseline", "no trades on this day"),
    ("open_gap", "open_gap", "%", 100, 2, OHLC, None, "no opening auction on this day"),
    ("close_vs_vwap", "close_vs_vwap", "%", 100, 2, OHLC, None, "no closing auction or VWAP on this day"),
    ("agent_share", "agent_share", "%", 100, 1, FLOWS, "agent_share_baseline", NO_FLOW),
    ("prop_share", "prop_share", "%", 100, 1, FLOWS, "prop_share_baseline", NO_FLOW),
    ("mm_share", "mm_share", "%", 100, 1, FLOWS, "mm_share_baseline", NO_FLOW),
    # shares bought minus shares sold by the group that day; the three groups add up to 0
    ("agent_net_flow", "agent_net_flow", "shares", 1, 0, FLOWS, None, NO_FLOW),
    ("prop_net_flow", "prop_net_flow", "shares", 1, 0, FLOWS, None, NO_FLOW),
    ("mm_net_flow", "mm_net_flow", "shares", 1, 0, FLOWS, None, NO_FLOW),
    ("days_to_normal", "days_to_normal", "days", 1, 0, OHLC, None, "rel_volume stayed at 1.5 or above for 30 trading days"),
)


def _num(v, scale, dec):
    if v is None:
        return None
    x = round(v * scale, dec)
    return int(x) if dec == 0 else x


def facts_from_row(row: dict) -> list[Fact]:
    day = row["day"].isoformat()
    out = []
    for key, col, unit, scale, dec, src, base, reason in SPEC:
        v = _num(row.get(col), scale, dec)
        b = base if not isinstance(base, str) else _num(row.get(base), scale, dec)
        out.append(Fact(key, v, unit, b, day, src, "found" if v is not None else "not_found", None if v is not None else reason))
    return out


def impact_facts(event_id: int) -> list[Fact]:
    con = connect(read_only=True)
    cur = con.execute("SELECT * FROM event_impact WHERE event_id = ?", [event_id])
    r = cur.fetchone()
    if r is None:
        return []
    return facts_from_row(dict(zip([c[0] for c in cur.description], r)))


def day_facts(isin: str, day: str) -> list[Fact]:
    rows = impact_rows(connect(read_only=True), [("d", isin, day)])
    return facts_from_row(rows[0]) if rows and rows[0]["day"] else []
