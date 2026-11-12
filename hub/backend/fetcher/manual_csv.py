"""data/reference/events_manual.csv, maintained by hand. Takes precedence.

Columns: isin,type,title,published_at_local,url
published_at_local is Europe/Berlin, 'YYYY-MM-DD HH:MM', or 'YYYY-MM-DD' when the time is not known.
"""
from __future__ import annotations

import csv
from pathlib import Path

from backend.fetcher import ROOT, Event
from backend.fetcher._days import local_to_utc

PATH = ROOT / "data" / "reference" / "events_manual.csv"


def fetch(path: Path = PATH) -> list[Event]:
    with path.open(newline="") as f:
        rows = list(csv.DictReader(f))
    events = []
    for i, r in enumerate(rows, start=2):
        if not r["url"].startswith("http"):
            raise ValueError(f"{path.name} line {i}: every event needs a public URL")
        events.append(Event(
            isin=r["isin"].strip(),
            type=r["type"].strip(),
            title=r["title"].strip(),
            published_at_utc=local_to_utc(r["published_at_local"]),
            source="manual_csv",
            url=r["url"].strip(),
            confidence=1.0,
        ))
    return events
