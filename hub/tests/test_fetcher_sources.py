"""New event sources (12 Nov): Bundesanzeiger short positions, AGM calendar from EQS notices. Owner: Track B."""
from datetime import date

from backend.fetcher import calendars, short_positions
from backend.text import template


def _row(holder, isin, pct, day):
    return {"Positionsinhaber": holder, "Emittent": "X", "ISIN": isin, "Position": pct, "Datum": day}


def test_short_change_uses_previous_row_and_threshold_for_first_row():
    rows = [_row("A", "DE1", "0,62", "2026-03-02"), _row("A", "DE1", "0,91", "2026-03-05"), _row("B", "DE1", "0,49", "2026-03-05")]
    ch = short_positions.daily_changes(rows)
    # first row: published only from 0.5 %, so the change is at least 0.62 - 0.5
    assert [(h, round(p, 2), n) for h, p, n in ch[("DE1", "2026-03-02")]] == [("A", 0.5, 0.62)]
    # a first row below 0.5 % (falling below) counts as no change, never as a jump from 0
    assert sorted((h, round(p, 2), n) for h, p, n in ch[("DE1", "2026-03-05")]) == [("A", 0.62, 0.91), ("B", 0.49, 0.49)]


def test_short_events_only_from_min_change(tmp_path):
    f = tmp_path / "s.csv"
    f.write_text('﻿"Positionsinhaber","Emittent","ISIN","Position","Datum"\n'
                 '"A","X","DE1","0,60","2026-03-02"\n"A","X","DE1","0,70","2026-03-03"\n"A","X","DE1","1,10","2026-03-04"\n',
                 encoding="utf-8")
    ev = short_positions.fetch(f, isins={"DE1"})
    assert len(ev) == 1 and "up 0.40 pp" in ev[0].title  # 0.10 on 2 Mar and 3 Mar stay below 0.3 pp
    assert ev[0].published_at_utc.isoformat() == "2026-03-03T23:00:00+00:00"  # 4 Mar, time not known


def test_agm_date_from_german_and_english_titles():
    assert calendars.agm_date("Beiersdorf AG: Bekanntmachung der Einberufung zur Hauptversammlung am 23.04.2026 in Hamburg") == date(2026, 4, 23)
    assert calendars.agm_date("Deutsche Telekom AG: Announcement of the Convening of the General Meeting in Bonn on 01.04.2026") == date(2026, 4, 1)
    assert calendars.agm_date("Kontron AG: Convocation of the 27th Annual General Meeting") is None


def test_proposed_dividend():
    assert calendars.proposed_dividend("• Ausschüttung einer Dividende von 1,00 Euro je dividendenberechtigter Stückaktie") == "1.00"
    assert calendars.proposed_dividend("payment of a dividend of EUR 5.35 per no-par value share") == "5.35"
    assert calendars.proposed_dividend("Der Bilanzgewinn wird auf neue Rechnung vorgetragen.") is None


def test_ex_day_is_next_trading_day():
    assert calendars.ex_day(date(2026, 4, 30)) == date(2026, 5, 4)  # 1 May is an exchange holiday
    assert calendars.ex_day(date(2026, 5, 20)) == date(2026, 5, 21)


def test_template_names_sector_day_without_cause():
    facts = [{"key": "rel_volume", "status": "found", "value": 3.2, "unit": "x", "date": "2026-09-14"}]
    text = template(facts, sector_event={"label": "14 of 24 Technology stocks in DAX, MDAX and SDAX had unusual turnover that day"})
    assert "No company event was found for this day." in text and "cause is unclear" not in text
    assert "On the same day, 14 of 24 Technology stocks" in text
