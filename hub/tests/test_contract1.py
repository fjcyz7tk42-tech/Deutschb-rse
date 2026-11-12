from datetime import date, datetime, timezone

from backend.config import load_config
from backend.tradingdays import effective_trading_day, trading_days

UTC = timezone.utc


def test_trading_days_file():
    days = trading_days()
    assert len(days) == 213
    assert days[0] == date(2026, 1, 2) and days[-1] == date(2026, 10, 30)


def test_publication_after_1735_counts_for_next_trading_day():
    # summer (CEST, UTC+2): 17:35 local = 15:35 UTC
    assert effective_trading_day(datetime(2026, 6, 10, 15, 35, tzinfo=UTC)) == date(2026, 6, 10)
    assert effective_trading_day(datetime(2026, 6, 10, 15, 36, tzinfo=UTC)) == date(2026, 6, 11)
    # winter (CET, UTC+1): 17:35 local = 16:35 UTC
    assert effective_trading_day(datetime(2026, 2, 10, 16, 35, tzinfo=UTC)) == date(2026, 2, 10)
    assert effective_trading_day(datetime(2026, 2, 10, 16, 36, tzinfo=UTC)) == date(2026, 2, 11)


def test_weekend_and_out_of_range():
    assert effective_trading_day(datetime(2026, 10, 10, 9, 0, tzinfo=UTC)) == date(2026, 10, 12)  # Saturday
    assert effective_trading_day(datetime(2026, 10, 30, 18, 0, tzinfo=UTC)) is None


def test_config():
    cfg = load_config()
    assert cfg["focus_stocks"] == ["CBK", "DWS", "PBB"] and cfg["DB_PATH"].endswith(".duckdb")
