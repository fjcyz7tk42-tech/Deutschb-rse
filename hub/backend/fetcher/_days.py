"""Contract 1 as seen from Track B: trading days and the event-day rule.

Uses backend.tradingdays as soon as Track A has built it. Until then a local stub with the same
rule: data/reference/trading_days.csv if present, else weekdays 2 Jan to 30 Oct 2026 without
exchange holidays. Remove this file once contract 1 is merged.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from functools import cache
from pathlib import Path
from zoneinfo import ZoneInfo

BERLIN = ZoneInfo("Europe/Berlin")
CUTOFF = time(17, 35)
ROOT = Path(__file__).resolve().parents[2]
_CSV = ROOT / "data" / "reference" / "trading_days.csv"
_HOLIDAYS = {date(2026, 4, 3), date(2026, 4, 6), date(2026, 5, 1)}


@cache
def _local_trading_days() -> tuple[date, ...]:
    if _CSV.exists():
        lines = [ln.strip() for ln in _CSV.read_text().splitlines() if ln.strip()]
        return tuple(date.fromisoformat(ln) for ln in lines if ln[0].isdigit())
    out, d = [], date(2026, 1, 2)
    while d <= date(2026, 10, 30):
        if d.weekday() < 5 and d not in _HOLIDAYS:
            out.append(d)
        d += timedelta(days=1)
    return tuple(out)


def trading_days() -> list[date]:
    try:
        from backend.tradingdays import trading_days as a_trading_days

        return a_trading_days()
    except NotImplementedError:
        return list(_local_trading_days())


def effective_trading_day(published_at_utc: datetime) -> date | None:
    """Trading day on which a publication could first be traded. None if after the last trading day."""
    try:
        from backend.tradingdays import effective_trading_day as a_effective

        return a_effective(published_at_utc)
    except NotImplementedError:
        pass
    local = published_at_utc.astimezone(BERLIN)
    d = local.date()
    if local.time() > CUTOFF:
        d += timedelta(days=1)
    for td in trading_days():
        if td >= d:
            return td
    return None


def local_to_utc(text: str) -> datetime:
    """'2026-05-08 07:58' or '2026-05-08' in Europe/Berlin -> aware UTC datetime.

    A date without a time means "time not known". It is read as 00:00 local, so the event counts
    on that day if it is a trading day, otherwise on the next one.
    """
    text = text.strip()
    fmt = "%Y-%m-%d %H:%M" if " " in text else "%Y-%m-%d"
    return datetime.strptime(text, fmt).replace(tzinfo=BERLIN).astimezone(ZoneInfo("UTC"))
