"""Liquidity Pulse: the rules (no database) and the endpoint (with the database)."""
from pathlib import Path

import pytest

from backend.api import pulse_context, pulse_direction, pulse_state
from backend.config import load_config


@pytest.mark.parametrize("change, lower_is_better, expected", [
    (None, True, None),
    (0.0, True, 0),
    (0.099, True, 0),        # below ±10 %: steady
    (-0.099, False, 0),
    (-0.10, True, 1),        # spread down 10 %: better
    (0.10, True, -1),        # spread up 10 %: worse
    (0.25, False, 1),        # turnover up: better
    (-0.25, False, -1),      # turnover down: worse
])
def test_direction(change, lower_is_better, expected):
    assert pulse_direction(change, lower_is_better) == expected


@pytest.mark.parametrize("spread, turnover, expected", [
    (None, 0.5, None),       # no spread, no verdict: the spread is the measure of trading cost
    (0.02, -0.05, "steady"),
    (-0.15, 0.02, "stronger"),
    (0.01, 0.30, "stronger"),  # turnover alone can move it when the spread holds
    (-0.15, 0.30, "stronger"),
    (0.20, 0.0, "weaker"),
    (0.05, -0.40, "weaker"),
    (-0.15, -0.25, "mixed"),   # cheaper to trade, but less traded
    (0.20, 0.30, "mixed"),
    (-0.15, None, "stronger"),
])
def test_state(spread, turnover, expected):
    assert pulse_state(spread, turnover) == expected


def test_context():
    assert pulse_context([]) is None
    assert pulse_context([(0.20, None)]) is None
    assert pulse_context([(0.20, 0.15)]) == "market-wide"        # 5 points from the index median
    assert pulse_context([(0.20, 0.05)]) == "stock-specific"     # 15 points
    assert pulse_context([(0.20, 0.15), (-0.30, 0.0)]) == "partly market-wide"


@pytest.mark.skipif(not Path(load_config()["DB_PATH"]).exists(), reason="data/hub.duckdb not built")
@pytest.mark.parametrize("isin", ["DE000CBK1001", "DE000DWS1007", "DE0008019001", "DE0005545503"])
def test_endpoint(isin):
    from backend.api import pulse
    p = pulse(isin)
    assert p["status"] == "found"
    assert p["state"] in ("stronger", "weaker", "mixed", "steady")
    assert (p["context"] is None) == (p["state"] == "steady")
    assert (p["gap_pp"] is None) == (p["state"] != "mixed")
    spread, turnover = p["metrics"]
    assert spread["key"] == "xlm_bps" and turnover["key"] == "turnover_eur"
    assert p["state"] == pulse_state(spread["change_pct"] / 100, turnover["change_pct"] / 100)
    assert p["text"].startswith(f"Liquidity Pulse for ") and p["label"] in p["text"]
