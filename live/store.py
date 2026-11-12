"""SQLite store for the live feed: one row per (company, announcement), a log of every poll, mail subscriptions
per stock and a log of every alert mail."""
from __future__ import annotations

import secrets
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS live_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    isin TEXT NOT NULL,
    source TEXT NOT NULL,
    type TEXT NOT NULL,
    category TEXT,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    published_at_utc TEXT NOT NULL,
    fetched_at_utc TEXT NOT NULL,
    UNIQUE (isin, url)
);
CREATE INDEX IF NOT EXISTS live_events_isin ON live_events (isin, published_at_utc DESC);
CREATE INDEX IF NOT EXISTS live_events_time ON live_events (published_at_utc DESC);
CREATE TABLE IF NOT EXISTS polls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    at_utc TEXT NOT NULL,
    ok INTEGER NOT NULL,
    items INTEGER,
    matched INTEGER,
    new INTEGER,
    error TEXT
);
CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL,
    isin TEXT NOT NULL,
    token TEXT NOT NULL UNIQUE,          -- for the unsubscribe link in every mail
    created_at_utc TEXT NOT NULL,
    UNIQUE (email, isin)
);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL,
    kind TEXT NOT NULL,                  -- alert | confirmation | test
    event_ids TEXT,                      -- comma-separated live_events ids
    at_utc TEXT NOT NULL,
    ok INTEGER NOT NULL,
    error TEXT
);
"""

# Holding notices: hidden by default in the feed and never mailed.
MINOR_TYPES = ("voting_rights", "directors_dealing", "short_position")


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._con = sqlite3.connect(path, check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._con.executescript(SCHEMA)
            self._con.commit()

    def add(self, items) -> list[dict]:
        """Insert new items; returns the rows that were new (already known announcements are skipped)."""
        fetched = now_utc()
        new = []
        with self._lock:
            for i in items:
                row = {"isin": i.isin, "source": i.source, "type": i.type, "category": i.category, "title": i.title,
                       "url": i.url, "published_at_utc": i.published_at_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                       "fetched_at_utc": fetched}
                cur = self._con.execute(
                    "INSERT OR IGNORE INTO live_events (isin, source, type, category, title, url, published_at_utc,"
                    " fetched_at_utc) VALUES (:isin, :source, :type, :category, :title, :url, :published_at_utc,"
                    " :fetched_at_utc)", row)
                if cur.rowcount == 1:
                    new.append({"id": cur.lastrowid, **row})
            self._con.commit()
        return new

    def log_poll(self, source: str, ok: bool, items: int | None, matched: int | None, new: int | None, error: str | None):
        with self._lock:
            self._con.execute("INSERT INTO polls (source, at_utc, ok, items, matched, new, error) VALUES (?, ?, ?, ?, ?, ?, ?)",
                              (source, now_utc(), int(ok), items, matched, new, error))
            self._con.commit()

    def events(self, isin: str | None, limit: int, minor: bool) -> list[dict]:
        where, args = [], []
        if isin:
            where.append("isin = ?")
            args.append(isin)
        if not minor:
            where.append(f"type NOT IN ({', '.join('?' * len(MINOR_TYPES))})")
            args.extend(MINOR_TYPES)
        sql = "SELECT * FROM live_events" + (" WHERE " + " AND ".join(where) if where else "")
        sql += " ORDER BY published_at_utc DESC, id DESC LIMIT ?"
        with self._lock:
            return [dict(r) for r in self._con.execute(sql, [*args, limit]).fetchall()]

    def status(self) -> dict:
        with self._lock:
            last = {r["source"]: dict(r) for r in self._con.execute(
                "SELECT p.* FROM polls p JOIN (SELECT source, max(id) id FROM polls GROUP BY source) m USING (id)")}
            last_ok = {r["source"]: r["at"] for r in self._con.execute(
                "SELECT source, max(at_utc) at FROM polls WHERE ok = 1 GROUP BY source")}
            counts = {r["source"]: r["n"] for r in self._con.execute(
                "SELECT source, count(*) n FROM live_events GROUP BY source")}
            subs = self._con.execute("SELECT count(*) FROM subscriptions").fetchone()[0]
            last_alert = self._con.execute("SELECT * FROM alerts ORDER BY id DESC LIMIT 1").fetchone()
        return {"last_poll": last, "last_ok": last_ok, "events": counts,
                "subscriptions": subs, "last_alert": dict(last_alert) if last_alert else None}

    # ------------------------------------------------------------ mail subscriptions

    def subscribe(self, email: str, isin: str) -> tuple[dict, bool]:
        """(subscription, created). An existing (email, isin) pair is returned unchanged."""
        with self._lock:
            cur = self._con.execute(
                "INSERT OR IGNORE INTO subscriptions (email, isin, token, created_at_utc) VALUES (?, ?, ?, ?)",
                (email, isin, secrets.token_urlsafe(18), now_utc()))
            self._con.commit()
            row = self._con.execute("SELECT * FROM subscriptions WHERE email = ? AND isin = ?", (email, isin)).fetchone()
        return dict(row), cur.rowcount == 1

    def subscriptions(self, isin: str | None = None) -> list[dict]:
        sql, args = "SELECT id, email, isin, created_at_utc FROM subscriptions", []
        if isin:
            sql, args = sql + " WHERE isin = ?", [isin]
        with self._lock:
            return [dict(r) for r in self._con.execute(sql + " ORDER BY email", args).fetchall()]

    def unsubscribe(self, sub_id: int | None = None, token: str | None = None) -> dict | None:
        """Removes one subscription by id or by its token; returns it, or None if there was none."""
        col, val = ("id", sub_id) if sub_id is not None else ("token", token)
        with self._lock:
            row = self._con.execute(f"SELECT * FROM subscriptions WHERE {col} = ?", (val,)).fetchone()
            if row:
                self._con.execute("DELETE FROM subscriptions WHERE id = ?", (row["id"],))
                self._con.commit()
        return dict(row) if row else None

    def recipients(self, isins: set[str]) -> dict[str, dict[str, str]]:
        """email -> {isin: unsubscribe token} for the given stocks."""
        if not isins:
            return {}
        out: dict[str, dict[str, str]] = {}
        with self._lock:
            rows = self._con.execute(
                f"SELECT email, isin, token FROM subscriptions WHERE isin IN ({', '.join('?' * len(isins))})",
                sorted(isins)).fetchall()
        for r in rows:
            out.setdefault(r["email"], {})[r["isin"]] = r["token"]
        return out

    def log_alert(self, email: str, kind: str, event_ids: list[int], ok: bool, error: str | None):
        with self._lock:
            self._con.execute("INSERT INTO alerts (email, kind, event_ids, at_utc, ok, error) VALUES (?, ?, ?, ?, ?, ?)",
                              (email, kind, ",".join(map(str, event_ids)) or None, now_utc(), int(ok), error))
            self._con.commit()
