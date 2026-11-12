"""Figure check on generated text. Owner: Track B."""
import json
from pathlib import Path

import pytest

from backend import text
from backend.text import figures_ok, numbers_in, template

# tests/fixtures/ holds real API responses from the Deutsche Börse data: local only, not in git (get it with the seed)
REAL_PATH = Path(__file__).parent / "fixtures" / "impact.json"


def _f(key, value, unit, baseline=None, status="found", source="XETRA_OHLC"):
    return {"key": key, "value": value, "unit": unit, "baseline": baseline, "date": "2026-05-06",
            "source": source, "status": status, "reason": None if status == "found" else "trades not loaded yet"}


# Own facts so the tests do not depend on the values in Track A's fixture.
FACTS = [
    _f("rel_volume", 3.3, "x", 1.0), _f("return_1d", 4.1, "%"), _f("market_return", 0.3, "%"),
    _f("sector_return", 0.4, "%"), _f("company_return", 3.4, "%"), _f("abnormal_return", 3.8, "pp", 0.0),
    _f("xlm_bps", 92.0, "bp", 67.5, source="XLM"),
    _f("opening_auction_turnover", None, "EUR", status="not_checked", source="XETRA_ONBOOK_TRADES"),
    _f("closing_auction_turnover", None, "EUR", status="not_checked", source="XETRA_ONBOOK_TRADES"),
    _f("open_gap", 1.2, "%"), _f("close_vs_vwap", 0.4, "%"), _f("days_to_normal", 2, "days"),
]
EVENT = {"id": 1, "type": "earnings", "title": "Q1 2026 results", "effective_trading_day": "2026-05-06"}


def test_text_with_a_number_missing_from_facts_is_rejected():
    assert not figures_ok("Turnover was 4.7x the baseline.", FACTS)


def test_text_with_fact_numbers_passes():
    t = "On 6 May 2026 turnover was 3.3x the 20-day baseline and the spread 92.0 bp against 67.5 bp."
    assert figures_ok(t, FACTS)


def test_rounding_must_match_the_fact():
    assert figures_ok("abnormal return of +3.8 pp", FACTS)
    assert not figures_ok("abnormal return of +3.9 pp", FACTS)


def test_calculated_difference_is_rejected():
    # 92.0 - 67.5 = 24.5 is not a fact: the model must not calculate
    assert not figures_ok("The spread widened by 24.5 bp.", FACTS)


def test_numbers_glued_to_letters_are_checked():
    assert not figures_ok("the 93rd percentile", FACTS)
    assert not figures_ok("in Q7", FACTS)  # "Q3" would pass: 3 is 3.3 rounded


def test_compact_euro_amounts():
    facts = [{"key": "opening_auction_turnover", "value": 1234567.0, "unit": "EUR", "baseline": None,
              "date": "2026-05-06", "source": "x", "status": "found", "reason": None}]
    assert figures_ok("EUR 1.2m in the opening auction", facts)
    assert not figures_ok("EUR 1.5m in the opening auction", facts)
    assert numbers_in("EUR 1.2m") == [(1200000.0, -5)]


def test_event_title_numbers_are_allowed():
    assert not figures_ok("Q1 2027 results", FACTS)
    assert figures_ok("Q1 2026 results", FACTS, extra_text="Q1 2026 results")


def test_template_passes_its_own_check_and_wording():
    t = template(FACTS, EVENT)
    assert figures_ok(t, FACTS, EVENT["title"])
    assert not text._banned(t)
    assert "On the same day" in t
    assert "No data for opening auction turnover and closing auction turnover" in t


def test_template_without_event_says_cause_unclear():
    t = template(FACTS, None)
    assert "cause is unclear" in t
    assert figures_ok(t, FACTS)


def test_template_never_shows_values_of_missing_facts():
    facts = [dict(f, status="not_checked", value=None) for f in FACTS]
    t = template(facts, None)
    assert figures_ok(t, facts)
    assert "not available" in t


def test_explain_falls_back_to_template_without_key(monkeypatch):
    monkeypatch.setattr(text, "_config", lambda: {"DEEPSEEK_API_KEY": "", "llm": {}})
    assert text.explain(FACTS, event=EVENT) == template(FACTS, EVENT)


@pytest.mark.parametrize("bad", [
    "Turnover was 9.9x the baseline.",                      # invented figure
    "Turnover was 3.3x the baseline because of results.",   # causal wording
])
def test_explain_rejects_model_text_twice_then_template(monkeypatch, bad):
    calls = []
    monkeypatch.setattr(text, "_config", lambda: {"DEEPSEEK_API_KEY": "k", "llm": {}})
    monkeypatch.setattr(text, "_chat", lambda messages, cfg, **kw: calls.append(1) or {"content": bad})
    assert text.explain(FACTS, event=EVENT) == template(FACTS, EVENT)
    assert len(calls) == 2


def test_explain_accepts_clean_model_text(monkeypatch):
    good = "Turnover was 3.3x the 20-day baseline on the same day as the results publication."
    monkeypatch.setattr(text, "_config", lambda: {"DEEPSEEK_API_KEY": "k", "llm": {}})
    monkeypatch.setattr(text, "_chat", lambda messages, cfg, **kw: {"content": good})
    assert text.explain(FACTS, event=EVENT) == good


@pytest.mark.skipif(not REAL_PATH.exists(), reason="tests/fixtures not present (local only)")
def test_template_on_real_api_response_passes_check():
    REAL = json.loads(REAL_PATH.read_text())
    t = template(REAL["facts"], REAL["event"])
    assert figures_ok(t, REAL["facts"], REAL["event"]["title"])
    assert not text._banned(t)


# Track A, 11 Nov: a card for 11 May shows PBB's Q1 results, which count on 12 May. The model wrote
# "12 May" and the check rejected it twice, so event cards never got model text.
PBB_EVENT = {"id": 1000, "type": "earnings", "title": "Q1 2026 results", "effective_trading_day": "2026-05-12",
             "published_at_utc": "2026-05-11T16:00:00Z"}


def test_event_dates_may_be_quoted(monkeypatch):
    facts = [dict(f, date="2026-05-11") for f in FACTS]
    good = "Turnover was 3.3x the 20-day baseline on 11 May; the Q1 2026 results count on 12 May, published 11 May at 18:00."
    calls = []
    monkeypatch.setattr(text, "_config", lambda: {"DEEPSEEK_API_KEY": "k", "llm": {}})
    monkeypatch.setattr(text, "_chat", lambda messages, cfg, **kw: calls.append(messages) or {"content": good})
    assert text.explain(facts, event=PBB_EVENT) == good
    assert len(calls) == 1
    assert '"published_berlin": "2026-05-11 18:00"' in calls[0][1]["content"]


def test_event_dates_do_not_open_other_numbers(monkeypatch):
    facts = [dict(f, date="2026-05-11") for f in FACTS]
    monkeypatch.setattr(text, "_config", lambda: {"DEEPSEEK_API_KEY": "k", "llm": {}})
    monkeypatch.setattr(text, "_chat", lambda messages, cfg, **kw: {"content": "Turnover was 7.7x the baseline on 12 May."})
    assert text.explain(facts, event=PBB_EVENT) == template(facts, PBB_EVENT)


def test_rejection_reason_is_sent_back(monkeypatch):
    sent = []
    monkeypatch.setattr(text, "_config", lambda: {"DEEPSEEK_API_KEY": "k", "llm": {}})
    monkeypatch.setattr(text, "_chat", lambda messages, cfg, **kw: sent.append(list(messages)) or {"content": "Turnover was 9.9x the baseline."})
    text.explain(FACTS, event=EVENT)
    assert "number 9.9 is not in FACTS" in sent[1][-1]["content"]


# Track A, 11 Nov: PBB card for 11 May said "On the same day" for results that count on 12 May.
def test_relation_counts_trading_days():
    assert text.relation("2026-05-11", "2026-05-11") == "on the same day"
    assert text.relation("2026-05-11", "2026-05-12") == "one trading day later"
    assert text.relation("2026-05-12", "2026-05-11") == "one trading day earlier"
    assert text.relation("2026-04-02", "2026-04-07") == "one trading day later"  # Good Friday, Easter Monday
    assert text.relation("2026-05-08", "2026-05-12") == "two trading days later"  # weekend in between


def test_template_says_when_event_is_on_another_day():
    facts = [dict(f, date="2026-05-11") for f in FACTS]
    t = template(facts, PBB_EVENT)
    assert "On the same day" not in t
    assert 'One trading day later: results publication, "Q1 2026 results".' in t
    assert figures_ok(t, facts, PBB_EVENT["title"])
    assert "On the same day: results publication" in template(FACTS, EVENT)


def test_prompt_gives_relation_and_hides_unknown_time(monkeypatch):
    facts = [dict(f, date="2026-05-11") for f in FACTS]
    date_only = dict(PBB_EVENT, published_at_utc="2026-05-11T22:00:00Z")  # 00:00 Berlin = time not known
    sent = []
    monkeypatch.setattr(text, "_config", lambda: {"DEEPSEEK_API_KEY": "k", "llm": {}})
    monkeypatch.setattr(text, "_chat", lambda messages, cfg, **kw: sent.append(messages) or {"content": "ok"})
    text.explain(facts, event=date_only)
    user = sent[0][1]["content"]
    assert '"relation_to_this_day": "one trading day later"' in user
    assert '"published_berlin": "2026-05-12"' in user
    assert "00:00" not in user


@pytest.fixture(autouse=True)
def _empty_text_cache():
    text._CACHE.clear()  # accepted model texts are cached per process


def test_market_event_in_template_and_cache(monkeypatch):
    facts = [{"key": "rel_volume", "value": 21.6, "unit": "x", "baseline": 1.0, "date": "2026-08-31",
              "source": "XETRA_OHLC", "status": "found", "reason": None}]
    market = {"label": "MSCI index review: changes implemented at the close"}
    t = text.template(facts, None, market)
    assert "On the same day as a market-wide event: MSCI index review" in t and "cause is unclear" not in t
    calls = []
    good = "On 31 August 2026 turnover was 21.6x the 20-day baseline, on the same day as the MSCI index review."
    monkeypatch.setattr(text, "_config", lambda: {"DEEPSEEK_API_KEY": "k", "llm": {}})
    monkeypatch.setattr(text, "_chat", lambda messages, cfg, **kw: calls.append(messages) or {"content": good})
    assert text.explain(facts, market_event=market) == good == text.explain(facts, market_event=market)
    assert len(calls) == 1 and "MSCI index review" in calls[0][1]["content"]  # second call came from the cache


# Track A bonus features, 11 Nov: net flow per participant group, named market days.
NET = [_f("agent_net_flow", -281924, "shares", source="XETRA_FLOW_DYNAMICS_EQUITY"),
       _f("prop_net_flow", 224481, "shares", source="XETRA_FLOW_DYNAMICS_EQUITY"),
       _f("mm_net_flow", 57443, "shares", source="XETRA_FLOW_DYNAMICS_EQUITY")]
MSCI = {"label": "MSCI index review: changes implemented at the close", "source": "MSCI press release", "url": "https://x"}


def test_template_names_net_flows_with_sign():
    t = template(FACTS + NET, None)
    assert "agents -281,924, proprietary traders +224,481, market makers +57,443" in t
    assert figures_ok(t, FACTS + NET)


def test_template_names_market_event_as_same_day_not_cause():
    t = template(FACTS, None, MSCI)
    assert "On the same day as a market-wide event: MSCI index review" in t
    assert "cause is unclear" not in t
    assert not text._banned(t)


def test_explain_sends_market_event_and_allows_its_label(monkeypatch):
    sent = []
    good = "Turnover was 3.3x the baseline on the same day as the MSCI index review."
    monkeypatch.setattr(text, "_config", lambda: {"DEEPSEEK_API_KEY": "k", "llm": {}})
    monkeypatch.setattr(text, "_chat", lambda messages, cfg, **kw: sent.append(messages) or {"content": good})
    assert text.explain(FACTS, market_event=MSCI) == good
    assert '"MARKET_EVENT": "MSCI index review' in sent[0][1]["content"]
