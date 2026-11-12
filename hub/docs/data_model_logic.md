# Data, model, logic

One page for the submission (requirement P2). Every number in the hub comes from the fact layer described here; the language model only words these facts.

## Data

- **Deutsche Börse market data, 2 Jan to 30 Oct 2026, 213 trading days** (FUTURY_MDS_DATA.zip): Xetra daily prices and auctions (XETRA_OHLC), every order-book trade (XETRA_ONBOOK_TRADES, about 400,000 a day), participant flows by market maker, agent and proprietary trader (XETRA_FLOW_DYNAMICS_EQUITY), liquidity cost XLM for 14 order sizes, and the daily members of DAX, MDAX and SDAX.
- **Universe:** 174 stocks that were in DAX, MDAX or SDAX on at least one day in 2026. Metrics are computed for all of them, so every stock has peers and every event has comparable cases.
- **Events:** index additions derived from the member lists (28 in 2026), plus company announcements from public sources with a URL (`data/reference/events.csv`).
- **Reference:** a sector for every stock (ten sectors, `data/reference/sectors.csv`) and the trading calendar from the file names.
- **Storage:** one DuckDB file. Raw trades are not kept; they become 5-minute bars and auction sums at load. Every file is validated (rows, date, duplicate keys) and logged in `coverage`.

## Model

- **Statistics, not prediction.** No forecasting model. Baselines are medians of the previous 20 trading days; deviations are robust z-scores: (value − median) / (1.4826 × median absolute deviation).
- **Language model (DeepSeek):** receives only the fact objects of one card and public announcement text, never raw rows. After it answers, every number in its text is checked against the facts; a failed check means regeneration or a template sentence.

## Logic

1. **Metrics per stock and day:** turnover; relative volume (turnover ÷ 20-day median); return from the closing auction; abnormal return (return − index median); XLM spread at EUR 25,000; opening, midday and closing auction turnover matched to the auction second in XETRA_OHLC; open gap; close vs VWAP; turnover shares of market makers, agents and proprietary traders.
2. **Anomaly:** |z| ≥ 3 on relative volume, spread or abnormal return. Consecutive anomalous days of one stock form an episode with a score from 0 to 100.
3. **Market day:** at least 30 % of DAX or MDAX members (20 % for the SDAX) show a relative-volume anomaly on the same day, typically index-expiry Fridays. These days stay visible but are labelled as market-wide.
4. **Matching:** events of the same stock within one trading day of the episode's peak (up to five days after for late-published disclosures). Status: **matched**, **market day** or **unmatched**. A match means "on the same day as", not "because of".
5. **Event day:** a publication after 17:35 Frankfurt time or on a non-trading day counts for the next trading day. An index addition counts on the rebalancing day before first membership.
6. **Impact card:** for an event or any notable day, relative volume, return split into market, sector and company, abnormal return on day 0 and up to day +5, spread vs baseline, auction turnover vs baseline, open gap, close vs VWAP, participant mix vs baseline, days until relative volume falls back below 1.5.
7. **Comparison:** percentile of the reaction among all events of the same type in the same index, sector and the whole universe.
8. **Every fact** carries value, unit, baseline, date and source; a missing value is null with a reason, never 0.
