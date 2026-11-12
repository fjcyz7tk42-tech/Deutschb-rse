"""Mail alerts: a new live announcement for a stock goes to every address subscribed to that stock.

One mail per recipient and poll (several announcements are bundled), each address gets its own mail (no CC),
every mail carries an unsubscribe link per stock. Holding notices (voting rights, directors' dealings, short
positions) are not mailed. tagesschau.de items are mailed as a link only, like in the UI (their terms forbid
republishing).

Environment:
    SMTP_HOST         mail server; empty -> no mail goes out (subscriptions are still stored)
    SMTP_PORT         default 587
    SMTP_SECURITY     starttls | ssl | none   (default starttls; none for Mailpit)
    SMTP_USER         optional login
    SMTP_PASSWORD
    SMTP_FROM         sender (default alerts@issuer-hub.local; real servers usually want the login address)
    PUBLIC_URL        where the app is reachable, for the links in the mail (default http://localhost:8080)
    ALERT_MAX_AGE_H   only announcements published in the last N hours are mailed (default 6), so the first
                      start, or a restart after a pause, does not mail the backlog of the EQS and tagesschau pages
"""
from __future__ import annotations

import html
import logging
import os
import re
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from zoneinfo import ZoneInfo

from live.store import MINOR_TYPES, Store

log = logging.getLogger("live.notify")
BERLIN = ZoneInfo("Europe/Berlin")

SMTP_HOST = os.environ.get("SMTP_HOST", "").strip()
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_SECURITY = os.environ.get("SMTP_SECURITY", "starttls").strip().lower()
SMTP_USER = os.environ.get("SMTP_USER", "").strip()
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM", "").strip() or "alerts@issuer-hub.local"
PUBLIC_URL = os.environ.get("PUBLIC_URL", "http://localhost:8080").rstrip("/")
MAX_AGE = timedelta(hours=float(os.environ.get("ALERT_MAX_AGE_H", "6")))

TYPE_LABELS = {
    "earnings": "Results", "dividend": "Dividend", "ad_hoc": "Ad hoc", "press_release": "Press release",
    "m_and_a": "M&A", "index_change": "Index change", "news": "News", "other": "Other",
}
TAGESSCHAU_LINK_TEXT = "Article on tagesschau.de"
EMAIL_RX = re.compile(r"^[^@\s<>,;\"']+@[^@\s<>,;\"']+\.[A-Za-z]{2,}$")


def enabled() -> bool:
    return bool(SMTP_HOST)


def info() -> dict:
    return {"enabled": enabled(), "host": SMTP_HOST or None, "port": SMTP_PORT if SMTP_HOST else None,
            "max_age_h": MAX_AGE.total_seconds() / 3600}


def normalise_email(raw: str) -> str | None:
    e = raw.strip().lower()
    return e if len(e) <= 254 and EMAIL_RX.match(e) else None


def _send(to: str, subject: str, text: str, html_body: str, unsubscribe_url: str | None) -> None:
    msg = EmailMessage()
    msg["From"] = f"IssuerLens <{SMTP_FROM}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=False)
    msg["Message-ID"] = make_msgid(domain=SMTP_FROM.split("@")[-1])
    if unsubscribe_url:
        msg["List-Unsubscribe"] = f"<{unsubscribe_url}>"
    msg.set_content(text)
    msg.add_alternative(html_body, subtype="html")

    if SMTP_SECURITY == "ssl":
        smtp = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=20, context=ssl.create_default_context())
    else:
        smtp = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20)
    with smtp:
        if SMTP_SECURITY == "starttls":
            smtp.starttls(context=ssl.create_default_context())
        if SMTP_USER:
            smtp.login(SMTP_USER, SMTP_PASSWORD)
        smtp.send_message(msg)


def _label(company: dict, isin: str) -> str:
    t, n = company.get("ticker"), company.get("name")
    return f"{n} ({t})" if n and t else t or n or isin


def _berlin(iso_utc: str) -> str:
    return datetime.strptime(iso_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) \
        .astimezone(BERLIN).strftime("%d %b %Y, %H:%M %Z")


def _title(ev: dict) -> str:
    return TAGESSCHAU_LINK_TEXT if ev["source"] == "tagesschau" else ev["title"]


def _page(body: str) -> str:
    return ("<!doctype html><html><body style=\"font-family:Arial,Helvetica,sans-serif;font-size:14px;"
            f"color:#1b1f24;max-width:640px\">{body}</body></html>")


def _footer_html(unsub: list[tuple[str, str]]) -> str:
    links = " · ".join(f'<a href="{html.escape(u)}" style="color:#5b6573">{html.escape(lbl)}</a>' for lbl, u in unsub)
    return (f'<p style="font-size:12px;color:#5b6573;margin-top:24px">You get this mail because your address was '
            f'entered for these stocks in the IssuerLens. Unsubscribe: {links}</p>')


def _unsub_url(token: str) -> str:
    return f"{PUBLIC_URL}/live/unsubscribe?token={token}"


def dispatch(store: Store, new_events: list[dict], companies: dict[str, dict], test: bool = False) -> int:
    """Mails the new announcements of one poll to their subscribers; returns the number of mails sent.
    test=True marks subject and text as a test (used by POST /subscriptions/test)."""
    cutoff = datetime.now(timezone.utc) - MAX_AGE
    events = [e for e in new_events if e["type"] not in MINOR_TYPES
              and datetime.strptime(e["published_at_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) >= cutoff]
    if not events:
        return 0
    recipients = store.recipients({e["isin"] for e in events})
    if not recipients:
        return 0
    if not enabled():
        log.info("%d new announcements for %d subscribers, but SMTP_HOST is not set: no mail sent",
                 len(events), len(recipients))
        return 0

    sent = 0
    for email, tokens in recipients.items():
        mine = sorted((e for e in events if e["isin"] in tokens), key=lambda e: e["published_at_utc"], reverse=True)
        isins = list(dict.fromkeys(e["isin"] for e in mine))
        first = mine[0]
        who = companies.get(first["isin"], {}).get("ticker") or first["isin"]
        if len(mine) == 1:
            subject = f"[Issuer Hub] {who}: {TYPE_LABELS.get(first['type'], first['type'])}: {_title(first)}"
        else:
            subject = f"[Issuer Hub] {len(mine)} new announcements: " + ", ".join(
                companies.get(i, {}).get("ticker") or i for i in isins)
        intro = "New announcements for the stocks you follow:"
        if test:
            subject = "[TEST] " + subject
            intro = ("This is a test alert from the IssuerLens. The announcement below is a sample, "
                     "not a real one. Real alerts look the same.")

        lines, rows = [], []
        for e in mine:
            c = companies.get(e["isin"], {})
            src = "EQS News" if e["source"] == "eqs" else "tagesschau.de"
            kind = TYPE_LABELS.get(e["type"], e["type"])
            hub = f"{PUBLIC_URL}/#{c['ticker']}" if c.get("ticker") else None
            lines.append(f"{_label(c, e['isin'])}\n{kind} · {src} · {_berlin(e['published_at_utc'])}\n"
                         f"{_title(e)}\n{e['url']}" + (f"\nIn the hub: {hub}" if hub else ""))
            rows.append(
                f'<div style="border-left:3px solid #00a86b;padding:4px 0 4px 12px;margin:14px 0">'
                f'<div style="font-weight:bold">{html.escape(_label(c, e["isin"]))}</div>'
                f'<div style="font-size:12px;color:#5b6573">{html.escape(kind)} · {src} · '
                f'{_berlin(e["published_at_utc"])}</div>'
                f'<div style="margin-top:4px"><a href="{html.escape(e["url"])}">{html.escape(_title(e))}</a></div>'
                + (f'<div style="font-size:12px;margin-top:4px"><a href="{html.escape(hub)}" style="color:#5b6573">'
                   f'Open in the hub</a></div>' if hub else "") + "</div>")

        unsub = [(companies.get(i, {}).get("ticker") or i, _unsub_url(tokens[i])) for i in isins]
        text = (intro + "\n\n" + "\n\n".join(lines)
                + "\n\nThe trading data in the hub ends on 30 Oct 2026, so these announcements are not yet matched to "
                  "unusual trading days.\n\nUnsubscribe:\n" + "\n".join(f"{lbl}: {u}" for lbl, u in unsub))
        body = _page(f"<p>{html.escape(intro)}</p>" + "".join(rows)
                     + '<p style="font-size:12px;color:#5b6573">The trading data in the hub ends on 30 Oct 2026, so '
                       "these announcements are not yet matched to unusual trading days.</p>" + _footer_html(unsub))
        ids = [e["id"] for e in mine if e.get("id")]
        kind = "test" if test else "alert"
        try:
            _send(email, subject, text, body, unsub[0][1] if len(unsub) == 1 else None)
            store.log_alert(email, kind, ids, True, None)
            sent += 1
        except Exception as ex:
            store.log_alert(email, kind, ids, False, f"{type(ex).__name__}: {ex}"[:300])
            log.warning("alert mail to %s failed: %s", email, ex)
    log.info("%s: %d new announcements, %d mails sent", "test alert" if test else "alerts", len(events), sent)
    return sent


def sample_event(isin: str, company: dict) -> dict:
    """A made-up ad hoc announcement for the test alert; it is not stored in the feed."""
    name = company.get("name") or company.get("ticker") or isin
    return {"id": None, "isin": isin, "source": "eqs", "type": "ad_hoc", "category": "Ad-hoc",
            "title": f"{name}: sample ad hoc announcement (test alert, not a real announcement)",
            "url": "https://www.eqs-news.com/", "published_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


def send_confirmation(store: Store, sub: dict, company: dict) -> None:
    """Tells a newly entered address what it will receive and how to stop it."""
    if not enabled():
        return
    lbl = _label(company, sub["isin"])
    unsub = _unsub_url(sub["token"])
    text = (f"Your address was entered for mail alerts on {lbl} in the IssuerLens.\n\n"
            f"You will get a mail when EQS News publishes a new announcement on {lbl} (results, ad hoc, press "
            f"release, dividend, ...) or tagesschau.de reports on it. Holding notices are not mailed.\n\n"
            f"Unsubscribe: {unsub}")
    body = _page(f"<p>Your address was entered for mail alerts on <b>{html.escape(lbl)}</b> in the Issuer "
                 f"Intelligence Hub.</p><p>You will get a mail when EQS News publishes a new announcement on "
                 f"{html.escape(lbl)} (results, ad hoc, press release, dividend, ...) or tagesschau.de reports on it. "
                 f"Holding notices are not mailed.</p>" + _footer_html([(company.get("ticker") or sub["isin"], unsub)]))
    try:
        _send(sub["email"], f"[Issuer Hub] Mail alerts for {company.get('ticker') or sub['isin']} switched on",
              text, body, unsub)
        store.log_alert(sub["email"], "confirmation", [], True, None)
    except Exception as ex:
        store.log_alert(sub["email"], "confirmation", [], False, f"{type(ex).__name__}: {ex}"[:300])
        log.warning("confirmation mail to %s failed: %s", sub["email"], ex)
