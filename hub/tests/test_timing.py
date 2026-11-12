"""Publication timing groups: Berlin time, the 17:35 cut-off and 'time not known' (00:00 Berlin)."""
from datetime import date, datetime, timezone

from backend.api import timing_slot


def test_winter_time():
    d = date(2026, 3, 5)  # CET, UTC+1
    assert timing_slot(datetime(2026, 3, 5, 6, 2), d) == ("pre_open", "07:02")
    assert timing_slot(datetime(2026, 3, 5, 8, 0), d) == ("trading", "09:00")
    assert timing_slot(datetime(2026, 3, 5, 16, 35), d) == ("trading", "17:35")
    assert timing_slot(datetime(2026, 3, 4, 16, 36), d) == ("before_day", "17:36")


def test_summer_time():
    d = date(2026, 7, 30)  # CEST, UTC+2
    assert timing_slot(datetime(2026, 7, 30, 6, 59), d) == ("pre_open", "08:59")
    assert timing_slot(datetime(2026, 7, 30, 7, 0), d) == ("trading", "09:00")
    assert timing_slot(datetime(2026, 7, 30, 7, 0, tzinfo=timezone.utc), d) == ("trading", "09:00")


def test_weekend_publication_counts_before_the_day():
    assert timing_slot(datetime(2026, 8, 1, 10, 0), date(2026, 8, 3)) == ("before_day", "12:00")


def test_unknown_or_inconsistent_time_is_not_grouped():
    assert timing_slot(datetime(2026, 3, 4, 23, 0), date(2026, 3, 5)) == (None, None)  # 00:00 Berlin = time not known
    assert timing_slot(None, date(2026, 3, 5)) == (None, None)
    assert timing_slot(datetime(2026, 3, 5, 17, 0), date(2026, 3, 5))[0] is None  # 18:00 belongs to the next day
