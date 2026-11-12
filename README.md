# IssuerLens

Futury Build Days 2026, Deutsche Börse challenge "Issuer Intelligence Hub and corporate event impact tracker".

A self-service view for IR teams of DAX, MDAX and SDAX companies: how their share trades on Xetra day to day (Part A, the dashboard) and how trading reacted to a corporate event or a notable day (Part B, the impact card), with an exportable short report.

This repo holds the frontend and the Docker setup for the whole stack. All figures come from the team's Hub API (`futury_4_2026`, `backend/api.py`), which builds them from the Deutsche Börse datasets (Xetra OHLC, on-book trades, Flow Dynamics, XLM) and public event sources.

## Run with Docker

The team repo `futury_4_2026` (with `data/hub.duckdb`) must sit next to this repo.

```bash
docker compose up --build -d
```

- App: <http://localhost:8080>
- Hub API directly: <http://localhost:8001/docs>
- Live feed directly: <http://localhost:8003/status>
- Alert mails (Mailpit): <http://localhost:8025>

Four containers:

| Service | Image | What it does |
|---|---|---|
| `live` | `docker/live.Dockerfile` (Python 3.13) | Live feed (`live/`): polls the EQS News homepage every 2 min (one request covers all issuers, filtered to the 160 index stocks) and tagesschau.de business news every 5 min (API limit: 60 requests/hour). Stores new announcements in SQLite (volume `live-data`, raw responses gzipped next to it). Reuses the team fetcher's EQS categories, title rules and tagesschau name list. Announcements after 30 Oct have no trading data, so they are listed, not matched. |
| `hub-api` | `docker/hub-api.Dockerfile` (Python 3.13) | The team's FastAPI app (`futury_4_2026/backend`), with the exact package versions of its `uv.lock` (`docker/hub-api.requirements.txt`). `data/` and `config.yaml` are mounted read-only; the API never writes. `DEEPSEEK_API_KEY` comes from `futury_4_2026/.env` at runtime and is not stored in the image. |
| `frontend` | `docker/frontend.Dockerfile` (Node build, nginx) | The built frontend; nginx forwards `/api/*` to `hub-api` and `/live/*` to `live`. |
| `mailpit` | `axllent/mailpit` | Catches the alert mails and shows them in a web UI, so the demo sends nothing real. |

### Mail alerts

In the live panel, addresses can be entered per stock ("Mail alerts for CBK"). When the live feed finds a new announcement for that stock (EQS News or tagesschau.de), every address entered for it gets a mail with the time, type, source and link (`live/notify.py`). Several announcements from one poll go into one mail; each address gets its own mail. A new address first gets a confirmation mail; every mail has an unsubscribe link per stock (`/live/unsubscribe?token=…`).

Not mailed: holding notices (voting rights, directors' dealings, short positions) and announcements older than `ALERT_MAX_AGE_H` hours (default 6), so the first start does not mail the backlog. tagesschau.de articles are mailed as a link only, like in the UI.

For the demo, "Send test alert" (below the addresses) sends a sample ad hoc announcement to every address of the stock, through the same path as a real one, marked [TEST] and not stored in the feed (`POST /live/subscriptions/test`).

By default the mails go to Mailpit. For real delivery, copy `.env.example` to `.env`, fill in the SMTP server and run `docker compose up -d`. Subscriptions and a log of every mail (`alerts` table) are kept in the live SQLite database.

These are alerts on new announcements, not on unusual trading: the trading data ends on 30 Oct 2026, and unusual days come from the batch pipeline.

Run only one live poller at a time (the Docker one or the local one, not both), so EQS and tagesschau.de get no duplicate requests.

After the pipeline rebuilt `hub.duckdb`, a restart is enough: `docker compose restart hub-api`. After code changes in either repo: `docker compose up --build -d`. Another location of the team repo: `HUB_DIR=/path/to/futury_4_2026 docker compose up --build -d`. Stop: `docker compose down`.

If the Hub API dependencies change (`uv.lock`), refresh the pinned list:
`cd ../futury_4_2026 && uv export --frozen --no-dev --no-hashes --no-emit-project -o ../Deutschb-rse/docker/hub-api.requirements.txt`

## Run without Docker

1. Start the Hub API in `futury_4_2026` (it needs `data/hub.duckdb`):

   ```bash
   cd ../futury_4_2026
   uv run uvicorn backend.api:app --port 8000
   ```

2. Start this frontend:

   ```bash
   cd frontend
   npm install
   npm run dev
   ```

3. Optional, the live feed (skip it if the Docker `live` container runs; it serves port 8003 too):

   ```bash
   PYTHONPATH=../futury_4_2026:. LIVE_DATA_DIR=live-data ../futury_4_2026/.venv/bin/uvicorn live.app:app --port 8003
   ```

   Mail alerts need `SMTP_HOST` etc. in the environment (see `.env.example`; for Mailpit: `docker compose up -d mailpit` and `SMTP_HOST=127.0.0.1 SMTP_PORT=1025 SMTP_SECURITY=none`). Without `SMTP_HOST`, addresses are stored but no mail goes out.

4. Open <http://localhost:7777>.

The dev server forwards `/api/*` to `http://127.0.0.1:8000` and `/live/*` to `http://127.0.0.1:8003`. Other addresses: `HUB_API=http://host:port LIVE_API=http://host:port npm run dev`.

## What is on screen

| Challenge item | Where |
|---|---|
| I. Volume, spread and auction participation over time | Price chart with turnover bars; metric chart below (turnover, relative volume, spread at a chosen order size, auction share open/midday/close, participant shares) with 20-day baseline and index peer median |
| II. Peer benchmarking (sector, index, size) | "Peer comparison" panel: rank and median within the index, sector or turnover tercile; drag across the chart to compare a period |
| III. Flag anomalies | Dots under the price line and the "Unusual days & events" list, with the count line: event on the same day, market-wide day, no event found |
| IV. / VIII. Shareable IR snapshot, exportable summary | "Export IR snapshot" and "Export report" on the impact card open a print view; "Print / Save as PDF" |
| V. Impact card | Click any day, dot or list row: turnover vs baseline, return split (market, sector, company), return vs index day 0 and day 0 to +5, spread, opening and closing auction turnover, opening gap, close vs VWAP, who traded and net flows, intraday 5-minute bars, AI-written summary |
| VI. Event calendar matched to trading data | Events from index changes, company IR sites and EQS News, shown on their effective trading day (after 17:35 Berlin: next trading day) |
| VII. Same-type comparison | "Compare events" or the button on an impact card: e.g. all results days in the DAX in 2026, by turnover, return, spread or auction turnover |
| Extra: publication timing | "Publication timing" or "By publication time" on an event card: all results (ad hoc, M&A, ...) of an index grouped by when they were published in Berlin time (before the trading day, before 09:00, during trading), with the publication times over the day, medians of opening gap, turnover, return vs index, spread and auction shares per group, every event as a clickable dot and the stock's own announcements marked. Needs the Hub API route `/timing` |

Deep links for the demo: `#CBK`, `#CBK/2026-02-11` (impact card), `#PBB/2026-08-31/report`, `#CBK/report`, `#CBK/compare/earnings`, `#CBK/timing/earnings`. ISINs work in place of tickers.

## Rules the UI keeps

- Every number is a fact from the API and shows its date and source. Missing values read "no data" or "not checked", never 0.
- Descriptive wording only, no forecasts. An event is "on the same day as" an unusual day, not its cause.
- Trading days are dates; publication times are shown in Europe/Berlin.

## Layout

```
frontend/src/
  api.ts              typed client for the Hub API
  format.ts           labels, units, dates (descriptive wording lives here)
  useFetch.ts         keyed data loading (no stale figures after a stock switch)
  App.tsx             layout, selection state, deep links
  components/
    PriceChart.tsx    price line, turnover bars, case dots, period brush
    MetricChart.tsx   one metric vs baseline and peer median
    PeersPanel.tsx    peer rank and distribution
    CasesPanel.tsx    unusual days and events with the count line
    ImpactCard.tsx    Part B card
    IntradayChart.tsx 5-minute bars of the card's day
    ComparePanel.tsx  same-type event comparison
    TimingPanel.tsx   same-type events grouped by publication time
    ReportView.tsx    print view for the IR snapshot and the card
    LivePanel.tsx     newest announcements from the live feed
    MailAlerts.tsx    addresses for mail alerts per stock
live/
  app.py              live feed service: polling loop, /events, /status, /subscriptions, /unsubscribe
  sources.py          EQS News and tagesschau.de parsers
  store.py            SQLite: announcements, polls, subscriptions, sent mails
  notify.py           alert and confirmation mails over SMTP
```
