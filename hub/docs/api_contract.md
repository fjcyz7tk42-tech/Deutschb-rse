# API contract

Owner: Track A. The JSON files in `tests/fixtures/` are the response shapes. The frontend builds against them until an endpoint is live. Field names and nesting must not change without a line in both handoff files.

## Endpoints

| Method | Path | Shape |
|---|---|---|
| GET | /companies | `fixtures/companies.json` |
| GET | /companies/{isin}/timeseries?metric&start&end&order_size | `fixtures/timeseries.json` |
| GET | /companies/{isin}/peers?basis=index\|sector\|size&metric&start&end | `fixtures/peers.json` |
| GET | /companies/{isin}/cases | `fixtures/cases.json` |
| GET | /impact/{event_id} | `fixtures/impact.json` |
| GET | /impact/day/{isin}/{day} | `fixtures/impact.json`, `event` may be null |
| GET | /compare?type&index&sector&metric&selected | `fixtures/compare.json` |
| GET | /indices/timeseries?metric&start&end | `{metric, unit, source, stat, points: [{date, DAX, MDAX, SDAX}]}`: median of each index's members, for the DAX vs SDAX switch |
| GET | /companies/{isin}/trend | `{isin, facts}`: `turnover_eur_trend`, `xlm_bps_trend`, `auction_share_trend`; value = median of the last 20 trading days, baseline = median of the 60 before, extra field `window` |
| POST | /ask?isin&question | `{"text": "...", "facts": [fact, ...]}` |

`metric` values for timeseries and peers: `turnover_eur`, `rel_volume`, `xlm_bps`, `auction_share`, `abnormal_return`, `close` (EUR), `auction_share_open`, `auction_share_midday`, `auction_share_close`, `mm_share`, `agent_share`, `prop_share` (all %).

Case `status`: `matched`, `market_day`, `unmatched`. Case `kind`: `episode` or `event`.

## Fact object

Every number on screen is one fact. Defined in `backend/facts.py`.

```json
{"key": "rel_volume", "value": 3.3, "unit": "x", "baseline": 1.0,
 "date": "2026-05-06", "source": "XETRA_OHLC", "status": "found", "reason": null}
```

`status`: `found`, `not_found` (looked, nothing there), `not_checked` (source not available yet). `value` is null unless `found`.

Fact keys on the impact card: `rel_volume`, `return_1d`, `market_return`, `sector_return`, `company_return`, `abnormal_return`, `xlm_bps`, `opening_auction_turnover`, `closing_auction_turnover`, `open_gap`, `close_vs_vwap`, `agent_share`, `prop_share`, `mm_share`, `days_to_normal`.

## Notes from Track A (live since Wed evening)

- All fixtures are real responses now; each `_note` says which request produced it and what was trimmed.
- Values are display-ready: `%` and `pp` are already multiplied by 100; `EUR` is whole euros; `bp` one decimal.
- `timeseries`: `baseline` is the median of the previous 20 trading days, `peer_median` the median of the other index members that day. `order_size` (EUR) only applies to `xlm_bps`; default 25,000. `anomaly` marks always refer to the 25,000 EUR spread. For `turnover_eur` the anomaly mark is the `rel_volume` anomaly; `auction_share` has none.
- `timeseries` also returns `order_size` (null for other metrics).
- `peers`: `value` and `median` are medians over the period (default: all of 2026). `rank` 1 = lowest value. `group` is the index, the sector, or e.g. "SDAX turnover tercile 2 of 3". Index and size peers are the index members on 30 Oct 2026.
- `cases`: `counts` covers episodes (unusual days) only. Rows of kind `event` are events not matched to an episode; their status is `matched` (matched to their trading day). An episode on a market day has status `market_day` even when an event falls in its window; the event is still shown. Voting rights and directors' dealings never decide a status: an episode with only such notices stays `unmatched`; the notices appear as rows of kind `event`.
- `impact`: extra fields `similar_groups` (index, sector and universe, each with `n` and `percentile`) and the fact `abnormal_return_5d` (cumulative abnormal return day 0 to +5). `similar` is the index entry of `similar_groups`. `text` is null when `backend.text.explain` fails or is not built.
- `compare`: `metric` is one of `rel_volume` (default), `abnormal_return`, `xlm_bps`, `car_5`, `opening_auction_turnover`, `closing_auction_turnover`. Percentiles are within the filtered group.
- `POST /ask` returns 501 until `backend.text.answer` works; `facts` is an empty list for now.
- `companies`: extra field `current` (member of DAX, MDAX or SDAX on 30 Oct 2026). 174 entries, 160 current. Use it to filter the stock picker; keep non-current entries for lookups.
- `impact` and `cases`: extra field `market_event` (`{label, source, url}` or null): a market-wide calendar event on the card's day or the case's peak day, from `data/reference/market_calendar.csv` (MSCI index reviews 27 Feb, 29 May, 31 Aug; Eurex quarterly expiry 20 Mar, 19 Jun, 18 Sep). Only dates with a public source are listed. It is a match on the day, not a cause.
- `impact`: three more facts, `agent_net_flow`, `prop_net_flow`, `mm_net_flow` (unit `shares`, source XETRA_FLOW_DYNAMICS_EQUITY): shares bought minus shares sold by the group that day. Positive = the group bought more than it sold. The three add up to 0.

## Alerts (step 11, demo replay)

| Method | Path | Shape |
|---|---|---|
| GET | /alerts | `{as_of, next_day, replay, priority_rule, counts: {HIGH, MED, LOW}, new, alerts: [alert]}` |
| POST | /alerts/load_next | same, plus `loaded_day` and `loaded` (the alerts of that day); 409 after the last day |
| POST | /alerts/reset | same; back to the start day |

`alert`: `{id, kind: episode|event, isin, ticker, name, date, priority, score, status, title, detail, market_event, link, new}`. Focus stocks only. Order: new first, then HIGH, MED, LOW, then newest date.

- **Priority** ranks how unusual the day was, not whether it was favourable. With an unusual day it follows the episode score (0 to 100; `backend/triage.py`: 70 x min(largest |z|, 10) / 10, plus 15 per additional unusual metric): HIGH from 70, MED from 40, LOW below. An event without unusual trading is MED for results, ad hoc and M&A announcements, otherwise LOW. Voting rights and directors' dealings raise no alert. Thresholds: `config.yaml`, `alerts`.
- **Replay**: all data is real and already in the database. The app starts "as of" 23 Oct 2026 (`alerts.replay_from`); each `load_next` moves one trading day on and its alerts get `new: true`. Only the alert list follows the replay day; the other pages always show data up to 30 Oct. The position is kept in memory and resets when the API restarts.

## Briefing and assistant

| Method | Path | Shape |
|---|---|---|
| GET | /companies/{isin}/briefing?type=earnings | `{isin, ticker, type, data_until, upcoming: [{date, title, url}], past: [{event_id, date, title, url, rel_volume, return_1d, abnormal_return, xlm_bps, xlm_bps_baseline, days_to_normal, percentile}], units, n_all, rel_volume_range, source, note}`. Past event days only, no forecast. `upcoming` holds dates after the data ends, from `events_manual.csv`. |
| GET | /ask/questions | `{questions: [{id, text}]}`: the four example questions |
| POST | /ask?isin&question&day | `{intent, text, facts, links: [{label, to}]}`. Fixed sentence patterns over the fact layer, no language model (the "why" question reuses the card text of the day, default: the highest-scored unusual period). Unknown questions get `intent: null` and the list of questions. |
