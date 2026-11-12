"""Step 5. Fetcher and news filter. One module per source, same interface, run in SOURCES order.

Each module exposes: fetch() -> list[Event]

    python -m backend.fetcher          writes data/reference/events.csv
"""
from __future__ import annotations

import csv
import importlib
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

EVENT_TYPES = (
    "earnings", "dividend", "ad_hoc", "press_release", "m_and_a", "index_change",
    "directors_dealing", "voting_rights", "short_position", "news", "other",
)

# Earlier sources win on duplicates.
SOURCES = ("manual_csv", "eqs", "calendars", "tagesschau", "short_positions")

ROOT = Path(__file__).resolve().parents[2]
EVENTS_CSV = ROOT / "data" / "reference" / "events.csv"
COLUMNS = ("isin", "type", "title", "published_at_utc", "effective_trading_day", "source", "url", "confidence")

log = logging.getLogger(__name__)


@dataclass
class Event:
    isin: str
    type: str
    title: str
    published_at_utc: datetime
    source: str
    url: str
    confidence: float = 1.0
    effective_trading_day: date | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        self.title = clean_title(self.title)
        if self.type not in EVENT_TYPES:
            raise ValueError(f"unknown event type {self.type!r} for {self.isin} {self.title!r}")
        if self.published_at_utc.tzinfo is None:
            raise ValueError(f"published_at_utc must be timezone-aware: {self.title!r}")


def clean_title(title: str) -> str:
    """Readable title: umlauts composed, single spaces.

    EQS sends some umlauts as letter + spacing diaeresis U+00A8 ("Mu¨nchen"), others as letter +
    combining diaeresis U+0308. Both become one character ("München").
    """
    title = re.sub(r"(?<=[A-Za-z])\u00a8", "\u0308", title)
    return " ".join(unicodedata.normalize("NFC", title).split())


def normalise_title(title: str) -> str:
    """Lower case, no accents, no punctuation, single spaces. Used for duplicate detection only."""
    t = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", t).split())


def dedupe_key(e: Event) -> tuple[str, str, str, str]:
    return (e.isin, e.type, str(e.effective_trading_day), normalise_title(e.title))


# Results and dividends happen once per day: a second source reporting the same one is a duplicate
# even when its title differs (manual "Q1 2026 results" vs EQS "Commerzbank delivers strong first quarter").
ONE_PER_DAY = ("earnings", "dividend")


def dedupe(events: list[Event]) -> list[Event]:
    """Keep the first event per (isin, type, effective_trading_day, normalised title).

    For ONE_PER_DAY types, keep only the first event per (isin, type, effective_trading_day).
    """
    seen: set[tuple[str, ...]] = set()
    out = []
    for e in events:
        k = dedupe_key(e)
        day_key = (e.isin, e.type, str(e.effective_trading_day))
        if k in seen or (e.type in ONE_PER_DAY and day_key in seen):
            continue
        seen.add(k)
        if e.type in ONE_PER_DAY:
            seen.add(day_key)
        out.append(e)
    return out


# Rules on the title, checked in order. German and English, since EQS publishes both.
_RULES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (t, re.compile(p, re.IGNORECASE))
    for t, p in (
        ("directors_dealing", r"eqs-dd|directors'? dealings?|managers'? transactions|eigengesch[aä]fte von f[uü]hrungskr[aä]ften|art\.? ?19 mar"),
        ("voting_rights", r"eqs-pvr|voting rights|stimmrechtsmitteilung|stimmrechtsanteil|wphg|total number of voting"),
        ("short_position", r"net short position|netto-leerverkaufsposition"),
        ("m_and_a", r"takeover|tender offer|exchange offer|acquisition of|merger|[uü]bernahmeangebot|[uü]bernahme|erwerbsangebot|fusion|offer document|angebotsunterlage"),
        ("earnings", r"results?|quarter|quarterly|half[- ]year|interim (report|statement)|annual report|figures|earnings|"
                     r"quartal|halbjahr|jahresergebnis|gesch[aä]ftszahlen|zwischenmitteilung|gesch[aä]ftsbericht|q[1-4] 20\d\d|fy ?20\d\d|9m|nine months|"
                     r"profit target|net profit|operating result|record result"),
        ("dividend", r"dividend|ex-tag|aussch[uü]ttung"),
    )
)


def classify(title: str, body: str | None = None, source_category: str | None = None) -> tuple[str, float]:
    """Rules on the source's own category first, then on the title. Small model only for what stays 'other'.

    Returns (type, confidence). Confidence 1.0 for the source category, 0.8 for a title rule,
    0.5 for 'other' (to be checked by the small model in step 5's second pass).
    """
    if source_category:
        cat = source_category.lower()
        if "ad hoc" in cat or "adhoc" in cat or "ad-hoc" in cat or "art. 17" in cat:
            # an ad hoc can still be results or M&A; keep the more specific type if the title says so
            t, _ = _title_rule(title)
            return (t if t in ("earnings", "m_and_a", "dividend") else "ad_hoc"), 1.0
        for t in ("directors_dealing", "voting_rights"):
            if t.replace("_", " ") in cat.replace("'", ""):
                return t, 1.0
    t, conf = _title_rule(title)
    if t != "other":
        return t, conf
    if body:
        t, conf = _title_rule(body[:500])
        if t != "other":
            return t, 0.6
    return "other", 0.5


def _title_rule(text: str) -> tuple[str, float]:
    for t, rx in _RULES:
        if rx.search(text):
            return t, 0.8
    return "other", 0.5


def run_all(sources: tuple[str, ...] = SOURCES, out: Path = EVENTS_CSV) -> list[Event]:
    """Fetch every source, set the event day, dedupe, write data/reference/events.csv.

    Never opens the database. index_change events are added by the pipeline (backend/masterdata.py).
    Events after the last trading day of the dataset are dropped (logged).
    """
    from backend.fetcher._days import effective_trading_day

    events: list[Event] = []
    for name in sources:
        mod = importlib.import_module(f"backend.fetcher.{name}")
        try:
            got = mod.fetch()
        except NotImplementedError:
            log.info("source %s: not built yet, skipped", name)
            continue
        log.info("source %s: %d events", name, len(got))
        events.extend(got)

    kept = []
    for e in events:
        if e.type == "index_change":
            continue
        e.effective_trading_day = effective_trading_day(e.published_at_utc)
        if e.effective_trading_day is None:
            log.info("outside the dataset, dropped: %s %s %s", e.isin, e.published_at_utc.date(), e.title)
            continue
        kept.append(e)
    kept = dedupe(kept)
    kept.sort(key=lambda e: (e.effective_trading_day, e.isin, e.published_at_utc))
    write_csv(kept, out)
    return kept


def write_csv(events: list[Event], path: Path = EVENTS_CSV) -> None:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        for e in events:
            w.writerow([
                e.isin, e.type, e.title,
                e.published_at_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                e.effective_trading_day.isoformat() if e.effective_trading_day else "",
                e.source, e.url, f"{e.confidence:.2f}",
            ])
