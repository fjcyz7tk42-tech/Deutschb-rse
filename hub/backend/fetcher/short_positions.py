"""Bundesanzeiger net short positions (EU short selling regulation).

Source: https://www.bundesanzeiger.de/pub/de/nlp, the official German publication of net short positions of
at least 0.5 % of the issued shares, with every change of 0.1 percentage point (pp) above that. Columns:
holder, issuer, ISIN, position in % of the issued shares, position date. robots.txt disallows /nlp at the
root, not /pub/de/nlp; download() makes three requests (page, historical search, CSV) a second apart.

download() stores the historical CSV in data/raw_events/short_positions/ (not in git). fetch() reads only
that file and needs no network.

One event per stock and position date, only when the net change summed over all holders is at least
MIN_CHANGE_PP. Smaller changes happen almost daily at heavily shorted stocks and would match nearly every
unusual day. A holder's first row counts as a change from just below 0.5 % (lower bound: position - 0.5),
since smaller positions are not published. The history starts on HISTORY_FROM, so positions opened before
2026 have their earlier rows.

Day: the position date (Datum), read as "time not known" (00:00 Berlin). The Bundesanzeiger publishes on
the next trading day, so this is the day the trading took place, not the publication day.
"""
from __future__ import annotations

import csv
import html
import logging
import re
import time
from collections import defaultdict
from pathlib import Path

from backend.fetcher import ROOT, Event
from backend.fetcher._days import local_to_utc

log = logging.getLogger(__name__)

PAGE = "https://www.bundesanzeiger.de/pub/de/nlp"
UA = "IssuerIntelligenceHub/0.1 (hackathon prototype; 1 request per second)"
RAW = ROOT / "data" / "raw_events" / "short_positions"
CSV_FILE = RAW / "net_short_positions_historical.csv"
HISTORY_FROM = "01.01.2024"
YEAR = "2026"
MIN_CHANGE_PP = 0.3
THRESHOLD = 0.5  # publication threshold in % of the issued shares
UNIVERSE = ROOT / "data" / "reference" / "sectors.csv"


def download(path: Path = CSV_FILE) -> Path:
    """Historical CSV since HISTORY_FROM: page, search form with 'Historie', CSV link. Three requests."""
    import httpx

    with httpx.Client(headers={"User-Agent": UA}, follow_redirects=True, timeout=120) as c:
        page = c.get(PAGE + "?0").text
        m = re.search(r'<form class="search-form"[^>]*action="([^"]+)">(.*?)</form>', page, re.S)
        if not m:
            raise RuntimeError("Bundesanzeiger: search form not found, page layout changed")
        fields = {}
        for tag in re.findall(r"<input[^>]*>", m.group(2)):
            name, value, typ = (re.search(rf'{a}="([^"]*)"', tag) for a in ("name", "value", "type"))
            if name and (not typ or typ.group(1) not in ("checkbox", "submit")):
                fields[name.group(1)] = value.group(1) if value else ""
        fields.update({"datumVon": HISTORY_FROM, "isHistorical": "true", "nlp-search-button": "Leerverkäufe suchen"})
        time.sleep(1.1)
        result = c.post(html.unescape(m.group(1)), data=fields).text
        link = re.search(r'href="([^"]*top~csv~form~panel-form-csv~resource~link)"', result)
        if not link:
            raise RuntimeError("Bundesanzeiger: CSV link not found after the historical search")
        time.sleep(1.1)
        r = c.get(html.unescape(link.group(1)))
        r.raise_for_status()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(r.content)
    log.info("Bundesanzeiger: %d bytes to %s", len(r.content), path)
    return path


def _pct(s: str) -> float:
    return float(s.strip().replace(",", "."))


def daily_changes(rows: list[dict]) -> dict[tuple[str, str], list[tuple[str, float, float]]]:
    """(isin, position date) -> [(holder, previous %, new %)]. previous is min(new, 0.5) for a holder's first row."""
    last: dict[tuple[str, str], float] = {}
    out: dict[tuple[str, str], list[tuple[str, float, float]]] = defaultdict(list)
    for r in sorted(rows, key=lambda r: r["Datum"]):
        key = (r["Positionsinhaber"].strip(), r["ISIN"].strip())
        new = _pct(r["Position"])
        prev = last.get(key, min(new, THRESHOLD))
        out[(key[1], r["Datum"].strip())].append((key[0], prev, new))
        last[key] = new
    return out


def _universe() -> set[str]:
    with UNIVERSE.open(newline="") as f:
        return {r["isin"] for r in csv.DictReader(f)}


def fetch(path: Path = CSV_FILE, isins: set[str] | None = None) -> list[Event]:
    if not path.exists():
        log.warning("short positions: %s missing, run python -m backend.fetcher.short_positions", path)
        return []
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    isins = isins if isins is not None else _universe()
    events = []
    for (isin, day), changes in sorted(daily_changes(rows).items()):
        if isin not in isins or not day.startswith(YEAR):
            continue
        net = sum(new - prev for _, prev, new in changes)
        if abs(net) < MIN_CHANGE_PP - 1e-9:
            continue
        changes.sort(key=lambda c: -abs(c[2] - c[1]))
        parts = [f"{h} {new:.2f} % ({new - prev:+.2f} pp)" for h, prev, new in changes[:3]]
        more = f", {len(changes) - 3} more" if len(changes) > 3 else ""
        events.append(Event(
            isin=isin, type="short_position",
            title=f"Net short positions {'up' if net > 0 else 'down'} {abs(net):.2f} pp: {'; '.join(parts)}{more}",
            published_at_utc=local_to_utc(day), source="bundesanzeiger", url=PAGE, confidence=1.0,
        ))
    log.info("short positions: %d stock days with a net change of at least %.1f pp", len(events), MIN_CHANGE_PP)
    return events


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    download()
    print(len(fetch()), "events")
