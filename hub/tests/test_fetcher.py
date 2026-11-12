"""Event fetcher: event-day rule, duplicates, classification, manual file. Owner: Track B."""
from datetime import date, datetime, timezone

import pytest

from backend.fetcher import EVENT_TYPES, Event, classify, dedupe, normalise_title, run_all
from backend.fetcher._days import effective_trading_day, local_to_utc
from backend.fetcher import manual_csv

UTC = timezone.utc


def test_before_close_counts_same_day_summer():
    # 17:30 CEST = 15:30 UTC, Friday 8 May 2026
    assert effective_trading_day(datetime(2026, 5, 8, 15, 30, tzinfo=UTC)) == date(2026, 5, 8)


def test_after_close_moves_to_next_trading_day_summer():
    # 17:46 CEST on Wed 20 May 2026 -> Thu 21 May
    assert effective_trading_day(local_to_utc("2026-05-20 17:46")) == date(2026, 5, 21)


def test_after_close_winter_uses_cet():
    # 17:36 CET = 16:36 UTC on Tue 10 Feb 2026 -> Wed 11 Feb; 17:34 CET stays
    assert effective_trading_day(datetime(2026, 2, 10, 16, 36, tzinfo=UTC)) == date(2026, 2, 11)
    assert effective_trading_day(datetime(2026, 2, 10, 16, 34, tzinfo=UTC)) == date(2026, 2, 10)


def test_weekend_and_holiday_move_forward():
    assert effective_trading_day(local_to_utc("2026-03-07 10:00")) == date(2026, 3, 9)  # Saturday
    assert effective_trading_day(local_to_utc("2026-04-03 09:00")) == date(2026, 4, 7)  # Good Friday, Easter Monday


def test_date_without_time_counts_that_day():
    assert local_to_utc("2026-02-11") == datetime(2026, 2, 10, 23, 0, tzinfo=UTC)
    assert effective_trading_day(local_to_utc("2026-02-11")) == date(2026, 2, 11)


def test_after_last_trading_day_is_none():
    assert effective_trading_day(local_to_utc("2026-11-05 07:00")) is None


def _ev(title, t="earnings", day=date(2026, 5, 8)):
    e = Event("DE000CBK1001", t, title, datetime(2026, 5, 8, 5, 0, tzinfo=UTC), "x", "https://x")
    e.effective_trading_day = day
    return e


def test_dedupe_on_normalised_title_keeps_first():
    a, b = _ev("Q1 2026 Results!"), _ev("q1 2026 results")
    b.source = "eqs"
    assert dedupe([a, b]) == [a]
    assert dedupe([a, b])[0].source == "x"


def test_dedupe_keeps_different_day_or_type():
    assert len(dedupe([_ev("Q1"), _ev("Q1", day=date(2026, 5, 11)), _ev("Q1", t="ad_hoc")])) == 3


def test_normalise_title():
    assert normalise_title("  Übernahme-Angebot: UniCredit  ") == "ubernahme angebot unicredit"


@pytest.mark.parametrize("title,expected", [
    ("Commerzbank delivers strong first quarter", "earnings"),
    ("DWS With Solid Start into the Year", "other"),
    ("EQS-DD: Commerzbank AG: Bettina Orlopp, Kauf", "directors_dealing"),
    ("Stimmrechtsmitteilung gemäß WpHG", "voting_rights"),
    ("Release according to Article 40, Section 1 of the WpHG", "voting_rights"),
    ("UniCredit publishes offer document for Commerzbank shares", "m_and_a"),
    ("Eigengeschäfte von Führungskräften", "directors_dealing"),
    ("Halbjahresfinanzbericht / Halbjahr 2026", "earnings"),
])
def test_classify_title_rules(title, expected):
    assert classify(title)[0] == expected


def test_classify_source_category_wins():
    assert classify("Bettina Orlopp, Kauf", source_category="Directors' Dealings") == ("directors_dealing", 1.0)
    assert classify("pbb lowers guidance", source_category="Ad hoc") == ("ad_hoc", 1.0)
    assert classify("Preliminary results 2025", source_category="EQS-Adhoc")[0] == "earnings"


def test_manual_file_is_valid():
    events = manual_csv.fetch()
    assert events, "events_manual.csv is empty"
    for e in events:
        assert e.type in EVENT_TYPES and e.type != "index_change"
        assert e.url.startswith("https://")
    focus = {"DE000CBK1001", "DE000DWS1007", "DE0008019001"}
    assert focus <= {e.isin for e in events}


def test_run_all_writes_unique_events(tmp_path):
    out = tmp_path / "events.csv"
    events = run_all(sources=("manual_csv",), out=out)
    keys = [(e.isin, e.type, e.effective_trading_day, normalise_title(e.title)) for e in events]
    assert len(keys) == len(set(keys))
    assert all(e.effective_trading_day for e in events)
    assert out.read_text().splitlines()[0] == "isin,type,title,published_at_utc,effective_trading_day,source,url,confidence"
    # CBK AGM result published after the close -> ex-dividend row and AGM on separate days
    cbk = {(e.type, e.effective_trading_day) for e in events if e.isin == "DE000CBK1001"}
    assert ("dividend", date(2026, 5, 21)) in cbk
    assert ("earnings", date(2026, 2, 10)) in cbk


def test_one_result_per_day_earlier_source_wins():
    manual = _ev("Q1 2026 results")
    manual.source = "manual_csv"
    eqs = _ev("Commerzbank delivers strong first quarter")
    eqs.source = "eqs"
    assert [e.source for e in dedupe([manual, eqs])] == ["manual_csv"]


EQS_PAGE = """
<p class="news__date" data-financial-news-date-grouped>3 September 2026</p>
<a href="https://www.eqs-news.com/news/ad-hoc/commerzbank-buyback/30bca5d2_en"
   data-wio="news-feed-list-item" data-news-isin="DE000CBK1001" data-news-category='Ad-hoc'>
 <span class="news__time">15:23</span><p class="news__heading">Commerzbank decides on a buyback</p></a>
<p class="news__date" data-financial-news-date-grouped>31 August 2026</p>
<a href="https://www.eqs-news.com/news/voting-rights/blackrock-inc-wilmington/34d6f2d4_en"
   data-wio="news-feed-list-item" data-news-isin="DE000CBK1001" data-news-category='Voting rights'>
 <span class="news__time">17:27</span><p class="news__heading">&nbsp;</p></a>
"""


def test_eqs_list_parser_takes_date_from_group_and_time_from_item():
    from backend.fetcher.eqs import parse_list, title_from_url

    items = parse_list(EQS_PAGE)
    assert [(i.day, i.time, i.category) for i in items] == [
        (date(2026, 9, 3), "15:23", "Ad-hoc"), (date(2026, 8, 31), "17:27", "Voting rights")]
    assert items[0].heading == "Commerzbank decides on a buyback"
    assert items[1].heading == ""
    assert title_from_url(items[1].url, "Voting rights") == "Voting rights: Blackrock inc Wilmington"
    # 17:27 is before the 17:35 cut-off: same day
    assert effective_trading_day(local_to_utc("2026-08-31 17:27")) == date(2026, 8, 31)


def test_titles_get_composed_umlauts():
    # Track A, 11 Nov: "Mu¨nchen" (u + spacing diaeresis U+00A8) in the PBB AGM convening notice from EQS
    for raw in ("General Meeting in Mu\u00a8nchen", "General Meeting in Mu\u0308nchen", "General  Meeting in M\u00fcnchen"):
        e = Event("DE0008019001", "other", raw, datetime(2026, 4, 2, 8, 0, tzinfo=UTC), "eqs", "https://x")
        assert e.title == "General Meeting in M\u00fcnchen"
