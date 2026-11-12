"""EQS News: ad hoc, corporate news, AGM notices, directors' dealings, voting rights for all universe stocks.

Access: eqs-news.com's robots.txt blocks AI and scraping bots. The team confirmed permission to fetch
(11 Nov 2026), so this module fetches anyway, slowly: one request per 1.1 s, honest user agent,
raw responses kept in data/raw_events/eqs/ and reused on the next run (no repeated downloads).

How the site works (checked 11 Nov 2026):
- /search-results/?searchtype=company&searchword=<ISIN> links the company page
  /company/<slug>/news/<company-uuid>.
- The company page lists the newest 30 items. Older pages come from
  POST /wp/wp-admin/admin-ajax.php action=fetch_eqs_financial_news_data (pageNo=2, 3, ...).
- Items are grouped under <p data-financial-news-date-grouped>3 September 2026</p>; each item has
  the time (Berlin), the EQS category and the item URL. Voting rights items have no headline in the
  list; their title is built from the URL slug, which names the notifying party.
"""
from __future__ import annotations

import csv
import html as htmlmod
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from backend.fetcher import ROOT, Event, classify
from backend.fetcher._days import local_to_utc

log = logging.getLogger(__name__)

BASE = "https://www.eqs-news.com"
AJAX = f"{BASE}/wp/wp-admin/admin-ajax.php?lang=en"
UA = "IssuerIntelligenceHub/0.1 (hackathon prototype; 1 request per second)"
RAW = ROOT / "data" / "raw_events" / "eqs"
FOCUS = ("DE000CBK1001", "DE000DWS1007", "DE0008019001")
UNIVERSE = ROOT / "data" / "reference" / "sectors.csv"
# Index line -> the share class EQS files the company under (Drägerwerk: preference shares in the SDAX,
# EQS lists the ordinary shares). Items of the alias count for the index line.
ISIN_ALIASES = {"DE0005550636": "DE0005550602"}
YEAR = 2026
DELAY = 1.1

# EQS category -> (our type, keep?). Buyback reports and announcements of future reports are noise for matching.
CATEGORIES: dict[str, tuple[str, bool]] = {
    "ad-hoc": ("ad_hoc", True),
    "corporate news": ("press_release", True),
    "corporate": ("press_release", True),
    "uk regulatory": ("press_release", False),  # same text as the corporate news, sent to London
    "directors' dealings": ("directors_dealing", True),
    "directors": ("directors_dealing", True),
    "advance financial reports": ("other", False),  # announces the date of a future report
    "agm announcements": ("other", True),
    "voting rights": ("voting_rights", True),
    "total voting rights": ("voting_rights", True),
    "other capital market information": ("other", False),
    "financial reports": ("other", False),
    "annual financial reports": ("other", False),
    "agm/egm": ("other", True),
    "press releases": ("press_release", True),
}

MONTHS = {m: i for i, m in enumerate(
    "january february march april may june july august september october november december".split(), 1)}


@dataclass
class Item:
    url: str
    day: date
    time: str  # HH:MM Berlin
    category: str
    isin: str
    heading: str


# ---------------------------------------------------------------- http with cache and rate limit

_last = 0.0


def _get(url: str, cache: Path, data: dict | None = None) -> str:
    global _last
    if cache.exists():
        return cache.read_text()
    import httpx

    wait = DELAY - (time.monotonic() - _last)
    if wait > 0:
        time.sleep(wait)
    headers = {"User-Agent": UA}
    r = httpx.post(url, data=data, headers=headers, timeout=30) if data else httpx.get(url, headers=headers, timeout=30, follow_redirects=True)
    _last = time.monotonic()
    r.raise_for_status()
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(r.text)
    return r.text


# ---------------------------------------------------------------- parsing (pure, tested on saved pages)

_DATE_RX = re.compile(r"data-financial-news-date-grouped[^>]*>\s*(\d{1,2}) ([A-Za-z]+) (\d{4})\s*<")
_ITEM_RX = re.compile(r'<a\s+href="(https://www\.eqs-news\.com/news/[^"]+)"\s+data-wio="news-feed-list-item"')


def parse_list(page: str) -> list[Item]:
    """Items in page order, each with the date of the group it sits under."""
    marks = [(m.start(), "d", m) for m in _DATE_RX.finditer(page)] + [(m.start(), "i", m) for m in _ITEM_RX.finditer(page)]
    marks.sort(key=lambda t: t[0])
    out: list[Item] = []
    current: date | None = None
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
        out.append(Item(
            url=m.group(1),
            day=current,
            time=tm.group(1) if tm else "",
            category=htmlmod.unescape(cat.group(1)).strip() if cat else "",
            isin=isin.group(1) if isin else "",
            heading=_clean(head.group(1)) if head else "",
        ))
    return out


def parse_title(article: str) -> str:
    m = re.search(r'<meta property="og:title" content="([^"]*)"', article) or re.search(r"<h1[^>]*>(.*?)</h1>", article, re.S)
    return _clean(m.group(1)) if m else ""


def title_from_url(url: str, category: str) -> str:
    """Voting rights items have no headline in the list; the URL slug names the notifying party."""
    parts = url.rstrip("/").split("/")
    slug = parts[-2] if len(parts) >= 2 else ""
    words = " ".join(w.capitalize() if len(w) > 3 else w for w in slug.split("-"))
    return f"{category}: {words}" if words else category


def _clean(s: str) -> str:
    return " ".join(htmlmod.unescape(re.sub(r"<[^>]+>", " ", s)).replace("\xa0", " ").split())


def _company(isin: str) -> tuple[str, str]:
    """(company page URL, company uuid) from the EQS company search."""
    page = _get(f"{BASE}/search-results/?searchtype=company&searchword={isin}", RAW / f"search_{isin}.html")
    found = list(dict.fromkeys(re.findall(r'href="(https://www\.eqs-news\.com/company/([^"/]+)/news/([0-9a-f-]{36}))"', page)))
    if not found:
        raise LookupError(f"EQS: no company page for {isin}")
    # Several pages for one ISIN after a rename (ADVA -> Adtran Networks): take the one whose slug shares a word
    # with the exchange name; otherwise the first.
    words = set(re.findall(r"[a-z]{4,}", _names().get(isin, "").lower()))
    best = next((f for f in found if words & set(f[1].split("-"))), found[0])
    return best[0], best[2]


def _names() -> dict[str, str]:
    with UNIVERSE.open(newline="") as f:
        return {r["isin"]: r["name"] for r in csv.DictReader(f)}


def universe() -> tuple[str, ...]:
    """All ISINs of data/reference/sectors.csv: every stock in DAX, MDAX or SDAX on at least one day in 2026."""
    return tuple(_names())


def _nonce(page: str) -> str:
    m = re.search(r'data-financial-news-wrapper[^>]*data-nonce="([^"]+)"', page) or re.search(r'data-nonce="([^"]+)"', page)
    return m.group(1) if m else ""


def _items_for(isin: str, max_pages: int = 20) -> list[Item]:
    url, uuid = _company(ISIN_ALIASES.get(isin, isin))
    first = _get(url, RAW / f"{isin}_p1.html")
    items = parse_list(first)
    name = re.search(r'data-cdn="([^"]*)"', first)
    nonce = _nonce(first)
    page_no = 2
    while items and items[-1].day.year >= YEAR and page_no <= max_pages:
        # the cache name has no date: delete data/raw_events/eqs to refresh
        page = _get(AJAX, RAW / f"{isin}_p{page_no}.html", data={
            "action": "fetch_eqs_financial_news_data", "newsType": "ALL", "pageLimit": "30", "pageNo": str(page_no),
            "loadFrom": "mysql", "companyName": name.group(1) if name else "", "companyId": uuid,
            "parseBy": "newsgrouping", "nonce": nonce, "additional[is_new]": "false",
        })
        more = parse_list(page)
        if not more:
            break
        items += more
        page_no += 1
    return [i for i in items if i.day.year == YEAR]


def fetch(isins: tuple[str, ...] | None = None) -> list[Event]:
    """All universe stocks by default (about 530 requests on an empty cache, 10 minutes)."""
    events: list[Event] = []
    for isin in isins or universe():
        try:
            items = _items_for(isin)
        except Exception as e:  # one company failing must not stop the others
            log.warning("EQS %s: %s", isin, e)
            continue
        kept = 0
        for it in items:
            our_type, keep = CATEGORIES.get(it.category.lower(), ("other", True))
            if not keep or (it.isin and it.isin not in (isin, ISIN_ALIASES.get(isin))):
                continue
            title = it.heading or title_from_url(it.url, it.category)
            t, conf = classify(title, source_category=it.category)
            if our_type in ("directors_dealing", "voting_rights"):
                t, conf = our_type, 1.0
            elif t in ("other", "ad_hoc") and our_type == "press_release":
                t, conf = "press_release", 0.8
            events.append(Event(
                isin=isin, type=t, title=title or it.category,
                published_at_utc=local_to_utc(f"{it.day.isoformat()} {it.time}" if it.time else it.day.isoformat()),
                source="eqs", url=it.url, confidence=conf,
            ))
            kept += 1
        log.info("EQS %s: %d items in %d, %d kept", isin, len(items), YEAR, kept)
    (RAW / "summary.json").write_text(json.dumps({"fetched_at": datetime.now().isoformat(timespec="seconds"), "events": len(events)}))
    return events
