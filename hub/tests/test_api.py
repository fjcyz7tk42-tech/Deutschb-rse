"""API responses keep the field names of tests/fixtures and answer within 2 seconds."""
import json
import time
from pathlib import Path

import pytest

from backend.config import load_config

pytestmark = pytest.mark.skipif(not Path(load_config()["DB_PATH"]).exists(), reason="data/hub.duckdb not built")
FIX = Path(__file__).parent / "fixtures"
# tests/fixtures/ holds real API responses from the Deutsche Börse data: local only, not in git (get it with the seed)
PBB = "DE0008019001"
URLS = {
    "companies": "/companies",
    "timeseries": f"/companies/{PBB}/timeseries?metric=rel_volume&start=2026-05-01&end=2026-05-15",
    "peers": f"/companies/{PBB}/peers?basis=index&metric=xlm_bps",
    "cases": f"/companies/{PBB}/cases",
    "impact": "/impact/2",
    "impact_day": f"/impact/day/{PBB}/2026-10-06",
    "compare": "/compare?type=index_change&index=SDAX",
}


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from backend import text
    from backend.api import app
    with pytest.MonkeyPatch.context() as mp:  # tests never call the language model
        mp.setattr(text, "_config", lambda: {"DEEPSEEK_API_KEY": "", "llm": {}})
        yield TestClient(app)


def keys(x):
    if isinstance(x, dict):
        return {k: keys(v) for k, v in x.items() if k != "_note"}
    if isinstance(x, list) and x:
        return [keys(x[0])]
    return None


@pytest.mark.parametrize("name", URLS)
def test_shape_matches_fixture(client, name):
    t = time.time()
    r = client.get(URLS[name])
    assert r.status_code == 200 and time.time() - t < 2
    path = FIX / f"{name.removesuffix('_day')}.json"
    if not path.exists():
        pytest.skip("tests/fixtures not present (local only)")
    fixture = json.loads(path.read_text())
    got, want = keys(r.json()), keys(fixture)
    assert set(want) <= set(got)  # new fields are allowed, none may vanish


def test_impact_event_under_2s(client):
    t = time.time()
    r = client.get("/impact/1")
    assert r.status_code == 200 and time.time() - t < 2
    assert {f["status"] for f in r.json()["facts"]} <= {"found", "not_found", "not_checked"}


def test_indices_and_trend(client):
    r = client.get("/indices/timeseries?metric=xlm_bps&start=2026-10-30").json()
    assert set(r["points"][0]) == {"date", "DAX", "MDAX", "SDAX"}
    facts = client.get("/companies/DE000CBK1001/trend").json()["facts"]
    assert [f["key"] for f in facts] == ["turnover_eur_trend", "xlm_bps_trend", "auction_share_trend"]
    assert all(f["status"] == "found" for f in facts)


def test_net_flow_and_market_event(client):
    card = client.get(f"/impact/day/{PBB}/2026-08-31").json()
    assert card["market_event"]["label"].startswith("MSCI index review") and card["market_event"]["url"].startswith("https://")
    flows = {f["key"]: f["value"] for f in card["facts"] if f["key"].endswith("_net_flow")}
    assert len(flows) == 3 and sum(flows.values()) == 0  # every share bought by one group was sold by another
    assert client.get(f"/impact/day/{PBB}/2026-05-11").json()["market_event"] is None
    cases = client.get(f"/companies/{PBB}/cases").json()["cases"]
    assert [c["market_event"]["label"][:4] for c in cases if c["peak_date"] == "2026-08-31"] == ["MSCI"]


def test_alerts_replay_and_priority(client):
    from backend.api import _priority
    a = {"high": 70, "medium": 40, "medium_event_types": ["earnings"]}
    assert [_priority(s, None, a) for s in (70, 69, 40, 39)] == ["HIGH", "MED", "MED", "LOW"]
    assert _priority(None, "earnings", a) == "MED" and _priority(None, "press_release", a) == "LOW"
    start = client.post("/alerts/reset").json()
    assert start["as_of"] == "2026-10-23" and start["new"] == 0 and start["next_day"] == "2026-10-26"
    assert not any(x["detail"] and x["detail"].startswith("Voting rights") for x in start["alerts"])
    one = client.post("/alerts/load_next").json()
    assert one["loaded_day"] == "2026-10-26" and {x["ticker"] for x in one["loaded"]} == {"PBB", "DWS"}
    pbb = next(x for x in one["loaded"] if x["ticker"] == "PBB")
    assert pbb["priority"] == "MED" and pbb["score"] == 52 and pbb["new"] and one["alerts"][0]["new"]
    client.post("/alerts/reset")


def test_briefing_and_ask(client):
    b = client.get(f"/companies/{PBB}/briefing").json()
    assert [p["date"] for p in b["past"]] == ["2026-03-05", "2026-05-12", "2026-08-13"]
    assert b["upcoming"][0]["date"] == "2026-11-12" and all(p["url"] for p in b["past"])
    qs = [x["text"] for x in client.get("/ask/questions").json()["questions"]]
    for question in qs:
        r = client.post("/ask", params={"isin": PBB, "question": question}).json()
        assert r["intent"] and len(r["text"]) > 40 and ("ource" in r["text"] or r["intent"] == "why_move")
    assert client.post("/ask", params={"isin": PBB, "question": "What is the weather?"}).json()["intent"] is None
