"""Step 9. Explanation text and assistant answers. The model words Facts; it never calculates.

Model: DeepSeek through its OpenAI-compatible endpoint, called with httpx (config.yaml: llm). No SDK.
If the call fails or the figure check fails twice, return a template sentence built from the Facts.

Only fact objects and public announcement text are sent to the model. Never raw data rows.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Iterable

from backend.facts import Fact

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]

# Numbers the text may use without a fact: rule constants that the card itself states.
RULE_NUMBERS = {20.0, 1.5, 25.0, 25000.0, 17.0, 35.0}

LABELS = {
    "rel_volume": "turnover relative to the 20-day baseline",
    "return_1d": "daily return",
    "market_return": "market part (index median)",
    "sector_return": "sector part",
    "company_return": "company-specific part",
    "abnormal_return": "abnormal return",
    "xlm_bps": "spread at EUR 25,000",
    "opening_auction_turnover": "opening auction turnover",
    "closing_auction_turnover": "closing auction turnover",
    "open_gap": "opening gap",
    "close_vs_vwap": "close vs VWAP",
    "agent_share": "agent share of turnover",
    "prop_share": "proprietary traders' share",
    "mm_share": "market makers' share",
    "days_to_normal": "days until turnover was back below 1.5x",
    "abnormal_return_5d": "abnormal return summed over this day and the five trading days after",
    "agent_net_flow": "net shares bought by agents (negative: net sold)",
    "prop_net_flow": "net shares bought by proprietary traders (negative: net sold)",
    "mm_net_flow": "net shares bought by market makers (negative: net sold)",
}

EVENT_LABELS = {
    "earnings": "results publication", "dividend": "dividend event", "ad_hoc": "ad hoc announcement",
    "press_release": "press release", "m_and_a": "M&A announcement", "index_change": "index change",
    "directors_dealing": "directors' dealing", "voting_rights": "voting rights notification",
    "short_position": "net short position", "other": "company event",
}


# ---------------------------------------------------------------- facts in, plain dicts out

def _as_dict(f: Fact | dict) -> dict:
    if isinstance(f, dict):
        return f
    if is_dataclass(f):
        return asdict(f)
    raise TypeError(f"not a fact: {f!r}")


def _facts(facts: Iterable[Fact | dict]) -> list[dict]:
    return [_as_dict(f) for f in facts]


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


# ---------------------------------------------------------------- figure check

_NUM_RX = re.compile(r"(?<![\d.,])[+\-−]?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?(?:\s?(bn|m|k)(?![a-z]))?", re.IGNORECASE)
_EXP = {"k": 3, "m": 6, "bn": 9}


def numbers_in(text: str) -> list[tuple[float, int]]:
    """Every number in the text as (absolute value, precision as round() digits).

    '3.3' -> (3.3, 1); '81st' -> (81, 0); 'EUR 1.2m' -> (1200000, -5).
    """
    out = []
    for m in _NUM_RX.finditer(text):
        whole, frac, suffix = m.group(1).replace(",", ""), m.group(2), (m.group(3) or "").lower()
        value = float(f"{whole}.{frac}" if frac else whole)
        decimals = len(frac) if frac else 0
        if suffix:
            out.append((value * 10 ** _EXP[suffix], decimals - _EXP[suffix]))
        else:
            out.append((value, decimals))
    return out


def allowed_numbers(facts: Iterable[Fact | dict], extra_text: str = "") -> set[float]:
    """Values, baselines and date parts of the facts, plus numbers in the event title and the rule constants."""
    allowed = set(RULE_NUMBERS)
    for f in _facts(facts):
        for v in (f.get("value"), f.get("baseline")):
            if (x := _num(v)) is not None:
                allowed.add(abs(x))
        if f.get("date"):
            y, mth, d = str(f["date"])[:10].split("-")
            allowed.update({float(y), float(int(mth)), float(int(d))})
    for x, _ in numbers_in(extra_text):
        allowed.add(x)
    return allowed


def figures_ok(text: str, facts: list[Fact], extra_text: str = "") -> bool:
    """True when every number in the text appears in the facts. Failing text is regenerated or replaced by a template.

    A number written with d decimals matches a fact value that rounds to it at d decimals,
    so '3.3' matches 3.31 but '3.4' does not. 'EUR 1.2m' matches 1,234,567.
    """
    x = unknown_number(text, facts, extra_text)
    if x is not None:
        log.info("figure check failed on %s", x)
    return x is None


def unknown_number(text: str, facts: Iterable[Fact | dict], extra_text: str = "") -> float | None:
    """The first number in the text that no fact (or extra_text) backs, or None."""
    allowed = allowed_numbers(facts, extra_text)
    for x, decimals in numbers_in(text):
        if not any(abs(round(a, decimals) - x) < 10 ** (-decimals) / 2 + 1e-9 for a in allowed):
            return x
    return None


# ---------------------------------------------------------------- template fallback

def _fmt(v: float, unit: str | None, signed: bool = False) -> str:
    sign = "+" if signed and v > 0 else ""
    if unit == "x":
        return f"{v:.1f}x"
    if unit == "%":
        return f"{sign}{v:.1f}%"
    if unit == "pp":
        return f"{sign}{v:.1f} pp"
    if unit == "bp":
        return f"{v:.1f} bp"
    if unit == "EUR":
        a = abs(v)
        return f"EUR {v / 1e6:.1f}m" if a >= 1e6 else f"EUR {v / 1e3:.0f}k" if a >= 1e3 else f"EUR {v:.0f}"
    if unit == "days":
        return f"{v:.0f} {'day' if v == 1 else 'days'}"
    if unit == "shares":
        return f"{v:+,.0f}" if signed else f"{v:,.0f}"
    return f"{v:g}"


def _human_date(iso: str) -> str:
    months = "January February March April May June July August September October November December".split()
    y, m, d = iso[:10].split("-")
    return f"{int(d)} {months[int(m) - 1]} {y}"


def template(facts: list[Fact | dict], event: dict | None = None, market_event: dict | None = None,
             sector_event: dict | None = None) -> str:
    """Plain sentences built only from found facts. Descriptive, no causes, no judgement."""
    fs = {f["key"]: f for f in _facts(facts)}

    def found(k: str) -> dict | None:
        f = fs.get(k)
        return f if f and f.get("status") == "found" and _num(f.get("value")) is not None else None

    day = next((f["date"] for f in fs.values() if f.get("date")), None)
    parts: list[str] = []
    lead = f"On {_human_date(day)}" if day else "On this day"
    if f := found("rel_volume"):
        parts.append(f"{lead}, turnover was {_fmt(f['value'], 'x')} the 20-day baseline.")
    else:
        parts.append(f"{lead}, turnover relative to the baseline is not available.")
    if f := found("return_1d"):
        s = f"The share price changed by {_fmt(f['value'], '%', True)}"
        comp = [(k, found(k)) for k in ("market_return", "sector_return", "company_return")]
        if all(c for _, c in comp):
            m, sct, co = (c["value"] for _, c in comp)
            s += (f"; the market part was {_fmt(m, '%', True)}, the sector part {_fmt(sct, '%', True)} "
                  f"and the company-specific part {_fmt(co, '%', True)}")
        parts.append(s + ".")
    if f := found("abnormal_return"):
        parts.append(f"The return against the index median was {_fmt(f['value'], 'pp', True)}.")
    if f := found("xlm_bps"):
        b = _num(f.get("baseline"))
        parts.append(f"The spread was {_fmt(f['value'], 'bp')}" + (f" against a baseline of {_fmt(b, 'bp')}." if b is not None else "."))
    auctions = [(k, found(k)) for k in ("opening_auction_turnover", "closing_auction_turnover")]
    for k, f in auctions:
        if f:
            parts.append(f"{LABELS[k].capitalize()} was {_fmt(f['value'], 'EUR')}.")
    missing = [LABELS[k] for k, f in auctions if not f and k in fs]
    if missing:
        parts.append(f"No data for {' and '.join(missing)}.")
    if f := found("days_to_normal"):
        parts.append(f"Turnover was back below 1.5x the baseline after {_fmt(f['value'], 'days')}.")
    flows = [(k, found(k)) for k in ("agent_net_flow", "prop_net_flow", "mm_net_flow")]
    if all(f for _, f in flows):
        names = {"agent_net_flow": "agents", "prop_net_flow": "proprietary traders", "mm_net_flow": "market makers"}
        parts.append("Net shares bought (bought minus sold): " +
                     ", ".join(f"{names[k]} {_fmt(f['value'], 'shares', True)}" for k, f in flows) + ".")
    if event:
        label = EVENT_LABELS.get(event.get("type", ""), "company event")
        rel = relation(day, event.get("effective_trading_day"))
        parts.append(f"{rel.capitalize()}: {label}, \"{event.get('title', '').strip()}\".")
    elif market_event or sector_event:
        parts.append("No company event was found for this day.")
    else:
        parts.append("No company event was found for this day, so the cause is unclear.")
    if market_event and market_event.get("label"):
        parts.append(f"On the same day as a market-wide event: {market_event['label'].strip()}.")
    if sector_event and sector_event.get("label"):
        parts.append(f"On the same day, {sector_event['label'].strip()}.")
    return " ".join(parts)


_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five"}


def relation(card_day: str | None, event_day: str | None) -> str:
    """Where the event's trading day lies from the card's day, in words (no digits, so the figure check
    is not affected): "on the same day", "one trading day later", "two trading days earlier".
    """
    if not card_day or not event_day or str(card_day)[:10] == str(event_day)[:10]:
        return "on the same day"
    a, b = str(card_day)[:10], str(event_day)[:10]
    try:
        from backend.tradingdays import trading_days

        days = [d.isoformat() for d in trading_days()]
    except Exception:
        days = []
    n = days.index(b) - days.index(a) if a in days and b in days else (1 if b > a else -1)
    count = _WORDS.get(abs(n), "several")
    unit = "trading day" if abs(n) == 1 else "trading days"
    return f"{count} {unit} {'later' if n > 0 else 'earlier'}"


def _berlin(published_at_utc: str | None) -> str | None:
    """'YYYY-MM-DD HH:MM' in Berlin, or just the date when the time is not known (stored as 00:00 Berlin)."""
    if not published_at_utc:
        return None
    from datetime import datetime
    from zoneinfo import ZoneInfo

    local = datetime.fromisoformat(str(published_at_utc).replace("Z", "+00:00")).astimezone(ZoneInfo("Europe/Berlin"))
    return local.strftime("%Y-%m-%d") if (local.hour, local.minute) == (0, 0) else local.strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------- language model

def _config() -> dict:
    try:
        from backend.config import load_config

        return load_config()
    except NotImplementedError:
        import yaml  # local fallback until contract 1 is merged

        cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
        env = ROOT / ".env"
        if env.exists():
            for line in env.read_text().splitlines():
                if line.startswith("DEEPSEEK_API_KEY="):
                    cfg["DEEPSEEK_API_KEY"] = line.split("=", 1)[1].strip()
        cfg.setdefault("DEEPSEEK_API_KEY", os.environ.get("DEEPSEEK_API_KEY", ""))
        return cfg


SYSTEM = """You write a short explanation for an investor-relations impact card.
Rules:
- Use only the figures in FACTS. Copy numbers exactly as given, rounded to one decimal at most. Never calculate, add, subtract or compare numbers yourself.
- Facts with status not_found or not_checked have no value: say "no data" for them.
- Descriptive only. Never use: good, bad, strong, weak, should, because, due to, caused, driven by. No forecasts.
- A matched event is a match in time, not a cause. Place it with EVENT.relation_to_this_day exactly as given
  ("on the same day as", "one trading day later", ...). Never write "on the same day" when the relation says otherwise.
- If EVENT.published_berlin has no time, the time is not known: do not state a time.
- If MARKET_EVENT is given, say that the day was the same day as it, using its wording. It is a match in time, not a cause.
- If SECTOR_DAY is given, say that on the same day it also applied, using its wording. It is a match in time, not a cause.
- Name the most striking figures first. If none of EVENT, MARKET_EVENT and SECTOR_DAY is given, say openly that the cause is unclear.
- Write dates like "31 August 2026". When you quote a net flow, name its group.
- Net flows (unit "shares") are shares bought minus sold by one participant group.
- At most {max_words} words, one paragraph, English, no lists, no markdown."""


def _chat(messages: list[dict], cfg: dict, model_key: str = "text_model", **kw: Any) -> dict:
    import httpx

    key = cfg.get("DEEPSEEK_API_KEY")
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY not set")
    llm = cfg["llm"]
    r = httpx.post(
        f"{llm['base_url'].rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": llm[model_key], "messages": messages, "temperature": 0.2,
              # thinking is on by default at DeepSeek: it took 5-8 s per card and ran into the timeout
              "thinking": {"type": "disabled"}, **kw},
        timeout=8,  # the card must be ready in under 10 s; on timeout the template is used
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]


def _prompt_facts(facts: list[dict]) -> list[dict]:
    # short prompt, short wait: found facts carry no status or reason, missing ones no value
    out = []
    for f in facts:
        found = f.get("status") == "found"
        keep = ("value", "unit", "baseline") if found else ("status", "reason")
        out.append({"label": LABELS.get(f["key"], f["key"])} | {k: f[k] for k in keep if f.get(k) is not None})
    return out


# shortcut: accepted model texts are kept per process, so a card opened twice is instant; lost on restart
_CACHE: dict[str, str] = {}


def explain(facts: list[Fact], max_words: int = 120, event: dict | None = None, market_event: dict | None = None,
            sector_event: dict | None = None) -> str:
    """At most max_words words built from the facts. Falls back to template() when the model is
    not reachable or the figure check fails twice.

    market_event: a market-wide calendar event on the card's day ({label, source, url}), if any.
    sector_event: the stock's sector was unusual as a whole that day ({label, ...}), if any.
    """
    fs = _facts(facts)
    card_day = next((f["date"] for f in fs if f.get("date")), None)
    ev = _prompt_event(event, card_day)
    allowed_extra = " ".join(str(v) for k, v in (ev or {}).items() if v and k != "relation_to_this_day")
    market = (market_event or {}).get("label")
    sector = (sector_event or {}).get("label")
    allowed_extra += " " + (market or "") + " " + (sector or "")  # the labels may be quoted
    try:
        cfg = _config()
        user = json.dumps({"DAY": _human_date(card_day) if card_day else None, "FACTS": _prompt_facts(fs),
                           "EVENT": ev, "MARKET_EVENT": market, "SECTOR_DAY": sector}, default=str)
        if cfg.get("DEEPSEEK_API_KEY") and user in _CACHE:
            return _CACHE[user]
        messages = [{"role": "system", "content": SYSTEM.format(max_words=max_words - 20)}, {"role": "user", "content": user}]
        for attempt in (1, 2):
            text = (_chat(messages, cfg).get("content") or "").strip()
            problem = _problem(text, fs, allowed_extra, max_words)
            if not problem:
                _CACHE[user] = text
                return text
            log.info("explain: attempt %d rejected (%s)", attempt, problem)
            messages += [{"role": "assistant", "content": text},
                         {"role": "user", "content": f"Rewrite it. Problem: {problem}."}]
    except Exception as e:  # network, key, quota: the card must still show a text
        log.info("explain: model not used (%s)", e)
    return template(fs, event, market_event, sector_event)


def _prompt_event(event: dict | None, card_day: str | None = None) -> dict | None:
    """The event as the model sees it. Its dates may be quoted, so they are allowed in the figure check too."""
    if not event:
        return None
    out = {k: event.get(k) for k in ("type", "title", "effective_trading_day")}
    if published := _berlin(event.get("published_at_utc")):
        out["published_berlin"] = published
    out["relation_to_this_day"] = relation(card_day, event.get("effective_trading_day"))
    return out


def _problem(text: str, facts: list[dict], allowed_extra: str, max_words: int) -> str | None:
    """Why a model text is not usable, or None."""
    if not text:
        return "empty answer"
    if len(text.split()) > max_words:
        return f"longer than {max_words} words"
    if (x := unknown_number(text, facts, allowed_extra)) is not None:
        return f"number {x:g} is not in FACTS"
    if m := _BANNED.search(text):
        return f"banned word '{m.group(0)}'"
    return None


_BANNED = re.compile(r"\b(good|bad|strong|weak|should|because|due to|caused|driven by|will)\b", re.IGNORECASE)


def _banned(text: str) -> bool:
    return bool(_BANNED.search(text))


def answer(question: str, isin: str) -> str:
    """Free-text assistant. After the core (CLAUDE.md): until then a fixed answer."""
    return ("The assistant is not available yet. Open the impact card of a day for its figures, "
            "each with date and source.")
