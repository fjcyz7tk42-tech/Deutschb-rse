"""Financial calendar from the AGM notices on EQS News: AGM day and ex-dividend day, for all universe stocks.

Source: the convening notices (category "AGM announcements", EQS-HV) that EQS already lists for each company,
read from the cached company pages of backend/fetcher/eqs.py. The notice title names the AGM date
("Einberufung zur Hauptversammlung am 23.04.2026", "General Meeting in Bonn on 01.04.2026"). The notice text
holds agenda item "Verwendung des Bilanzgewinns" / "appropriation of the net profit" with the proposed
dividend per share; each notice page is fetched once (1.1 s apart, cached in data/raw_events/eqs/agm/).

Events per AGM:
- "Annual General Meeting 2026" (type other) on the AGM date, time not known.
- Ex-dividend day (type dividend) on the first trading day after the AGM, only for German issuers (DE ISIN:
  the dividend claim falls due on the third business day after the AGM, so the share trades ex dividend on the
  next trading day) and only when the notice proposes a dividend. The title says "proposed": the notice
  precedes the vote. No dividend in the notice -> no ex-dividend event (not "no dividend").

Corrections of a notice ("Korrektur: ...") and the German and English versions of the same notice give one
AGM: one per stock and date.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime

from backend.fetcher import Event
from backend.fetcher import eqs
from backend.fetcher._days import local_to_utc, trading_days

log = logging.getLogger(__name__)

AGM_CATEGORIES = ("agm announcements", "agm/egm")
_DATE = re.compile(r"(?:Hauptversammlung|General Meeting)\b.*?\b(?:am|on) (\d{2})\.(\d{2})\.(\d{4})")
_EXTRA = re.compile(r"au(?:ß|ss)erordentlich|extraordinary", re.IGNORECASE)
# "Dividende von 1,00 Euro je", "Dividende in Höhe von EUR 1,10 je", "dividend of EUR 1.10 per", "dividend of € 0.35 per"
_DIV = re.compile(
    r"(?:Dividende (?:von|in Höhe von)|dividend (?:of|in the amount of))\s*(?:EUR|€|Euro)?\s*([0-9]+[.,][0-9]{2})\s*(?:EUR|€|Euro)?\s*(?:je|pro|per)\b",
    re.IGNORECASE)


def agm_date(title: str) -> date | None:
    m = _DATE.search(title)
    if not m:
        return None
    d, mth, y = (int(x) for x in m.groups())
    try:
        return date(y, mth, d)
    except ValueError:
        return None


def proposed_dividend(text: str) -> str | None:
    """Dividend per share from the profit appropriation item, e.g. '1.00'. None when none is named."""
    m = _DIV.search(text)
    return m.group(1).replace(",", ".") if m else None


def ex_day(agm: date) -> date | None:
    """First trading day after the AGM. None after the last trading day of the dataset."""
    return next((d for d in trading_days() if d > agm), None)


def _notice_text(url: str) -> str:
    slug = re.sub(r"[^0-9a-f-]", "", url.rstrip("/").rsplit("/", 1)[-1])[:60] or "notice"
    return eqs._clean(eqs._get(url, eqs.RAW / "agm" / f"{slug}.html"))


def fetch(isins: tuple[str, ...] | None = None) -> list[Event]:
    events: list[Event] = []
    for isin in isins or eqs.universe():
        try:
            items = eqs._items_for(isin)
        except Exception as e:  # no EQS page: nothing to read here
            log.info("calendar %s: %s", isin, e)
            continue
        seen: set[date] = set()
        for it in items:
            if it.category.lower() not in AGM_CATEGORIES:
                continue
            title = it.heading or eqs.title_from_url(it.url, it.category)
            agm = agm_date(title)
            if not agm or agm.year != eqs.YEAR or agm in seen:
                continue
            seen.add(agm)
            kind = "Extraordinary General Meeting" if _EXTRA.search(title) else "Annual General Meeting"
            events.append(Event(isin=isin, type="other", title=f"{kind} {agm.year}",
                                published_at_utc=local_to_utc(agm.isoformat()), source="eqs_agm", url=it.url))
            if kind != "Annual General Meeting" or not isin.startswith("DE"):
                continue
            try:
                div = proposed_dividend(_notice_text(it.url))
            except Exception as e:
                log.warning("calendar %s: notice not readable: %s", isin, e)
                continue
            exd = ex_day(agm)
            if div and exd:
                events.append(Event(
                    isin=isin, type="dividend",
                    title=f"Ex-dividend day: EUR {div} per share proposed for the AGM on {agm.strftime('%d %b %Y').lstrip('0')}",
                    published_at_utc=local_to_utc(exd.isoformat()), source="eqs_agm", url=it.url, confidence=0.9))
    log.info("calendar: %d AGM and ex-dividend events (%s)", len(events), datetime.now().isoformat(timespec="seconds"))
    return events
