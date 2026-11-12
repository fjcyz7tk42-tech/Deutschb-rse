"""Live feed service: polls EQS News and tagesschau.de in the background, serves the newest announcements.

    uvicorn live.app:app --port 8003

Needs the team repo on PYTHONPATH (backend.fetcher: EQS categories, title rules, tagesschau name list).
Environment:
    HUB_API_URL           Hub API for the company list   (default http://127.0.0.1:8000)
    LIVE_DATA_DIR         SQLite file and raw responses   (default ./live-data)
    EQS_INTERVAL_S        seconds between EQS polls        (default 120  -> 30 requests per hour)
    TAGESSCHAU_INTERVAL_S seconds between tagesschau polls (default 300  -> 12 per hour; API limit 60)
    SMTP_*, PUBLIC_URL, ALERT_MAX_AGE_H   mail alerts, see live/notify.py

The live feed is separate from the analysis: the Deutsche Börse dataset ends on 30 Oct 2026, so new
announcements have no trading data yet. They are listed, not matched.
"""
from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import urllib.request
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from live import notify, sources
from live.store import Store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("live")

HUB_API_URL = os.environ.get("HUB_API_URL", "http://127.0.0.1:8000").rstrip("/")
DATA_DIR = Path(os.environ.get("LIVE_DATA_DIR", "live-data"))
INTERVALS = {
    "eqs": max(60, int(os.environ.get("EQS_INTERVAL_S", "120"))),
    "tagesschau": max(120, int(os.environ.get("TAGESSCHAU_INTERVAL_S", "300"))),  # never above 30/h
}
POLLERS = {"eqs": sources.poll_eqs, "tagesschau": sources.poll_tagesschau}

store = Store(DATA_DIR / "live.sqlite")
companies: dict[str, dict] = {}
next_poll: dict[str, str] = {}


def load_companies() -> dict[str, dict]:
    """Current DAX/MDAX/SDAX members from the Hub API; fallback: the ISINs of the tagesschau name list."""
    try:
        with urllib.request.urlopen(f"{HUB_API_URL}/companies", timeout=10) as r:
            cs = json.load(r)["companies"]
        return {c["isin"]: {"ticker": c["ticker"], "name": c["name"], "index": c["index"]}
                for c in cs if c.get("current") or c.get("focus")}
    except Exception as e:  # the hub may start later; the feed still works by ISIN
        log.warning("company list from %s not available (%s); using the name list", HUB_API_URL, e)
        return {isin: {"ticker": None, "name": None, "index": None} for isin in sources.ALIASES}


async def poll_forever(source: str) -> None:
    global companies
    while True:
        if not companies or all(v["ticker"] is None for v in companies.values()):
            companies = await asyncio.to_thread(load_companies)
        try:
            n_items, items = await asyncio.to_thread(POLLERS[source], set(companies), DATA_DIR / "raw")
            new = store.add(items)
            store.log_poll(source, True, n_items, len(items), len(new), None)
            log.info("%s: %d items, %d for the index stocks, %d new", source, n_items, len(items), len(new))
        except Exception as e:
            new = []
            store.log_poll(source, False, None, None, None, f"{type(e).__name__}: {e}"[:300])
            log.warning("%s poll failed: %s", source, e)
        if new:
            try:
                await asyncio.to_thread(notify.dispatch, store, new, companies)
            except Exception as e:  # a mail problem must never stop the feed
                log.warning("alert dispatch failed: %s", e)
        nxt = datetime.now(timezone.utc) + timedelta(seconds=INTERVALS[source])
        next_poll[source] = nxt.strftime("%Y-%m-%dT%H:%M:%SZ")
        await asyncio.sleep(INTERVALS[source])


@asynccontextmanager
async def lifespan(_app: FastAPI):
    tasks = [asyncio.create_task(poll_forever(s)) for s in POLLERS]
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title="IssuerLens, live feed", lifespan=lifespan)


@app.get("/events")
def events(isin: str | None = None, limit: int = Query(30, ge=1, le=200), minor: bool = False):
    """Newest announcements first. minor=true also lists voting rights and directors' dealings."""
    rows = store.events(isin, limit, minor)
    for r in rows:
        c = companies.get(r["isin"], {})
        r["ticker"], r["name"] = c.get("ticker"), c.get("name")
    return {"isin": isin, "events": rows}


@app.get("/status")
def status():
    s = store.status()
    return {
        "sources": {
            src: {
                "interval_s": INTERVALS[src],
                "last_poll": s["last_poll"].get(src),
                "last_ok_utc": s["last_ok"].get(src),
                "next_poll_utc": next_poll.get(src),
                "events": s["events"].get(src, 0),
            }
            for src in POLLERS
        },
        "companies": len(companies),
        "alerts": {**notify.info(), "subscriptions": s["subscriptions"], "last": s["last_alert"]},
    }


# ------------------------------------------------------------------ mail subscriptions

class SubscriptionIn(BaseModel):
    email: str
    isin: str


@app.get("/subscriptions")
def list_subscriptions(isin: str | None = None):
    return {"isin": isin, "subscriptions": store.subscriptions(isin), "mail": notify.info()}


@app.post("/subscriptions", status_code=201)
def add_subscription(body: SubscriptionIn, background: BackgroundTasks):
    email = notify.normalise_email(body.email)
    if not email:
        raise HTTPException(400, "Not a valid e-mail address.")
    if companies and body.isin not in companies:
        raise HTTPException(404, "Unknown stock: only DAX, MDAX and SDAX members can be followed.")
    sub, created = store.subscribe(email, body.isin)
    if created:
        background.add_task(notify.send_confirmation, store, sub, companies.get(body.isin, {}))
    return {"subscription": {k: sub[k] for k in ("id", "email", "isin", "created_at_utc")},
            "created": created, "mail": notify.info()}


class TestIn(BaseModel):
    isin: str


@app.post("/subscriptions/test")
def test_alert(body: TestIn):
    """Demo: sends a sample announcement to every address subscribed to the stock, the same way as a real one."""
    if companies and body.isin not in companies:
        raise HTTPException(404, "Unknown stock.")
    n_subs = len(store.subscriptions(body.isin))
    if not n_subs:
        raise HTTPException(400, "Add an address first.")
    if not notify.enabled():
        raise HTTPException(503, "Mail delivery is off (SMTP_HOST is not set).")
    sent = notify.dispatch(store, [notify.sample_event(body.isin, companies.get(body.isin, {}))], companies, test=True)
    if sent < n_subs:
        last = store.status()["last_alert"] or {}
        raise HTTPException(502, f"Sent {sent} of {n_subs} mails. Mail server: {last.get('error') or 'unknown error'}")
    return {"sent": sent, "mail": notify.info()}


@app.delete("/subscriptions/{sub_id}")
def delete_subscription(sub_id: int):
    if not store.unsubscribe(sub_id=sub_id):
        raise HTTPException(404, "No such subscription.")
    return {"deleted": sub_id}


@app.get("/unsubscribe", response_class=HTMLResponse)
def unsubscribe(token: str):
    """Target of the link in every mail: removes that one stock subscription."""
    sub = store.unsubscribe(token=token)
    if sub:
        c = companies.get(sub["isin"], {})
        what = html.escape(c.get("ticker") or sub["isin"])
        msg = f"<b>{html.escape(sub['email'])}</b> no longer gets mail alerts for <b>{what}</b>."
    else:
        msg = "This link was already used, or the subscription was removed in the hub."
    return ("<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
            "<title>Unsubscribed</title></head><body style='font-family:Arial,sans-serif;max-width:560px;"
            f"margin:48px auto;padding:0 16px'><h2>IssuerLens</h2><p>{msg}</p></body></html>")
