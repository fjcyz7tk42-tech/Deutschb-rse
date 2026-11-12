"""Trading calendar and the event-day rule. Every module uses these two functions; nobody re-implements them."""
from __future__ import annotations

from bisect import bisect_right
from datetime import date, datetime, time
from functools import cache
from zoneinfo import ZoneInfo

from backend.config import ROOT

BERLIN = ZoneInfo("Europe/Berlin")
CUTOFF = time(17, 35)
CSV = ROOT / "data" / "reference" / "trading_days.csv"


@cache
def trading_days() -> list[date]:
    """Trading days of 2026, taken from the dataset file names (data/reference/trading_days.csv)."""
    return [date.fromisoformat(s) for s in CSV.read_text().split()]


def effective_trading_day(published_at_utc: datetime) -> date | None:
    """Trading day on which a publication could first be traded.

    After 17:35 Europe/Berlin or on a non-trading day: the next trading day.
    None when that day lies after the last day in the data.
    """
    if published_at_utc.tzinfo is None:
        raise ValueError("published_at_utc must be timezone-aware")
    local = published_at_utc.astimezone(BERLIN)
    days = trading_days()
    d = local.date()
    if d in days and local.time() <= CUTOFF:
        return d
    i = bisect_right(days, d)
    return days[i] if i < len(days) else None
