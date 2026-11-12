"""Live sources. Each poll is one HTTP request; the raw response is kept (gzip) for traceability.

EQS News: the homepage lists the 30 newest announcements of all issuers with ISIN, category and time
(Europe/Berlin). One request per poll covers every DAX/MDAX/SDAX company at once, much gentler than one
request per company. Classification reuses the team fetcher (backend.fetcher.eqs.CATEGORIES, classify).

tagesschau.de: news?ressort=wirtschaft returns the latest business news (about a week). Terms: private use,
no publication, at most 60 requests per hour. Company matching reuses backend.fetcher.tagesschau.ALIASES.
"""
from __future__ import annotations

import gzip
import html as htmlmod
import json
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from backend.fetcher import classify
from backend.fetcher.eqs import CATEGORIES, title_from_url
from backend.fetcher.tagesschau import ALIASES, companies_in

log = logging.getLogger("live")
BERLIN = ZoneInfo("Europe/Berlin")
UA = "IssuerIntelligenceHub/0.1 (hackathon prototype; live feed, one request every few minutes)"

EQS_HOME = "https://www.eqs-news.com/"
TAGESSCHAU = "https://www.tagesschau.de/api2u/news/?ressort=wirtschaft"

MONTHS = {m: i for i, m in enumerate(
    "january february march april may june july august september october november december".split(), 1)}


@dataclass
class LiveItem:
    isin: str
    source: str        # eqs | tagesschau
    type: str          # team event types, plus "news"
    category: str      # the source's own category
    title: str
    url: str
    published_at_utc: datetime


def _get(url: str, raw_dir: Path, source: str) -> str:
    r = httpx.get(url, headers={"User-Agent": UA}, timeout=30, follow_redirects=True)
    r.raise_for_status()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = raw_dir / source / f"{stamp}.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(r.content))
    return r.text


def _clean(s: str) -> str:
    return " ".join(htmlmod.unescape(re.sub(r"<[^>]+>", " ", s)).replace("\xa0", " ").split())


def _berlin_to_utc(day: date, hhmm: str) -> datetime:
    h, m = (int(x) for x in hhmm.split(":")) if hhmm else (0, 0)
    return datetime(day.year, day.month, day.day, h, m, tzinfo=BERLIN).astimezone(timezone.utc)


# ------------------------------------------------------------------ EQS homepage

_DATE_RX = re.compile(r"data-realtime-news-date-grouped[^>]*>\s*(\d{1,2}) ([A-Za-z]+) (\d{4})\s*<")
_ITEM_RX = re.compile(r'<a\s+href="(https://www\.eqs-news\.com/news/[^"]+)"\s+data-wio="news-feed-list-item"')


def parse_eqs_home(page: str) -> list[dict]:
    """Items in page order with the date of the group they sit under."""
    marks = [(m.start(), "d", m) for m in _DATE_RX.finditer(page)] + [(m.start(), "i", m) for m in _ITEM_RX.finditer(page)]
    marks.sort(key=lambda t: t[0])
    out, current = [], None
    for pos, kind, m in marks:
        if kind == "d":
            current = date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1)))
            continue
        if current is None:
            continue
        chunk = page[pos: pos + 4000]
        cat = re.search(r"data-news-category='([^']*)'", chunk)
        isin = re.search(r'data-news-isin="([^"]*)"', chunk)
        tm = re.search(r'class="news__time">\s*(\d{1,2}:\d{2})', chunk)
        head = re.search(r'class="news__heading">(.*?)</p>', chunk, re.S)
        out.append({
            "url": m.group(1), "day": current, "time": tm.group(1) if tm else "",
            "category": htmlmod.unescape(cat.group(1)).strip() if cat else "",
            "isin": isin.group(1) if isin else "", "heading": _clean(head.group(1)) if head else "",
        })
    return out


def poll_eqs(universe: set[str], raw_dir: Path) -> tuple[int, list[LiveItem]]:
    """(items on the page, items for our universe)."""
    items = parse_eqs_home(_get(EQS_HOME, raw_dir, "eqs"))
    out = []
    for it in items:
        if it["isin"] not in universe:
            continue
        our_type, keep = CATEGORIES.get(it["category"].lower(), ("other", True))
        if not keep:
            continue
        title = it["heading"] or title_from_url(it["url"], it["category"])
        t, _ = classify(title, source_category=it["category"])
        if our_type in ("directors_dealing", "voting_rights"):
            t = our_type
        elif t in ("other", "ad_hoc") and our_type == "press_release":
            t = "press_release"
        out.append(LiveItem(it["isin"], "eqs", t, it["category"], title or it["category"], it["url"],
                            _berlin_to_utc(it["day"], it["time"])))
    return len(items), out


# ------------------------------------------------------------------ tagesschau

_COMPILED = {isin: re.compile(p) for isin, p in ALIASES.items()}


def poll_tagesschau(universe: set[str], raw_dir: Path) -> tuple[int, list[LiveItem]]:
    items = json.loads(_get(TAGESSCHAU, raw_dir, "tagesschau")).get("news", [])
    out = []
    for it in items:
        url = it.get("shareURL") or it.get("detailsweb")
        if not url or not it.get("date"):
            continue
        title = f"{it['topline']}: {it.get('title', '')}" if it.get("topline") else it.get("title", "")
        for isin in companies_in(it, _COMPILED, universe):
            out.append(LiveItem(isin, "tagesschau", "news", it.get("ressort") or "wirtschaft", title, url,
                                datetime.fromisoformat(it["date"]).astimezone(timezone.utc)))
    return len(items), out
