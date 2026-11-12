# IssuerLens

Futury Build Days 2026, Deutsche Börse challenge "Issuer Intelligence Hub and corporate event impact tracker".

A self-service view for IR teams of DAX, MDAX and SDAX companies: how their share trades on Xetra day to day (Part A, the dashboard) and how trading reacted to a corporate event or a notable day (Part B, the impact card), with an exportable short report.

This repo holds the whole stack: the frontend, the live feed, the Docker setup and, in `hub/`, the team's Hub API (`hub/backend/api.py`) with the data it serves. The figures are built from the Deutsche Börse datasets (Xetra OHLC, on-book trades, Flow Dynamics, XLM) and public event sources.

`hub/` is a copy of the needed parts of the team repo `futury_4_2026`: the code (`backend/`), `config.yaml` and `data/reference/` with the finished tables as a Parquet seed (`data/reference/seed/`). The DuckDB database is built from the seed. **The seed is processed Deutsche Börse data and is not in git** (this repo is public; the data must not be passed on): `scripts/sync-hub.sh` copies it locally, and on the server it is copied by hand, e.g. `rsync -a hub/data/reference/seed/ server:<repo>/hub/data/reference/seed/`. `hub/SOURCE.txt` names the copied commit. To take over newer work from the team repo (next to this one, or `HUB_DIR=/path`):

```bash
scripts/sync-hub.sh
```

Change the Hub API in the team repo and sync, not in `hub/` directly, or the next sync overwrites it.

## Run with Docker

```bash
cp .env.example .env    # fill in DEEPSEEK_API_KEY; SMTP only for real mail
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
| `hub-api` | `docker/hub-api.Dockerfile` (Python 3.13) | The FastAPI app in `hub/backend`, with the exact package versions of the team repo's `uv.lock` (`docker/hub-api.requirements.txt`). The image builds `data/hub.duckdb` from the seed in `hub/data/reference/seed/`. `DEEPSEEK_API_KEY` comes from `.env` at runtime and is not stored in the image. |
| `frontend` | `docker/frontend.Dockerfile` (Node build, nginx) | The built frontend; nginx forwards `/api/*` to `hub-api` and `/live/*` to `live`. |
| `mailpit` | `axllent/mailpit` | Catches the alert mails and shows them in a web UI, so the demo sends nothing real. |

### Public HTTPS: www.justklaris.com

Use the HTTPS overlay on a public Docker server where this stack owns ports 80/443 (Docker Compose 2.24.4 or newer):

```bash
docker compose -f docker-compose.yml -f docker-compose.https.yml up --build -d
```

The default address is `https://www.justklaris.com`. Set `APP_DOMAIN` in `.env` to change it; use a hostname without `https://`, a port or a path. The domain's DNS A record (and AAAA record, if present) must point to this server, with inbound TCP ports 80 and 443 reachable. UDP 443 is optional for HTTP/3. Caddy obtains and renews a Let's Encrypt certificate and redirects HTTP to HTTPS automatically; issuance happens when the stack runs on that reachable server. See [Caddy's HTTPS requirements](https://caddyserver.com/docs/automatic-https#overview).

Caddy forwards the app, `/api/*` and `/live/*` to nginx inside Docker. The overlay removes the direct host ports for nginx, both APIs and Mailpit, so only Caddy is exposed. nginx preserves the original HTTPS scheme for the APIs. Certificates and ACME account state persist in `caddy-data` and `caddy-config`; keep these volumes when updating or restarting.

The overlay sets the live service's `PUBLIC_URL` to `https://${APP_DOMAIN}` (default `https://www.justklaris.com`), even if `.env` still contains the local development URL. Stock links and unsubscribe links in newly generated mails therefore use the public HTTPS address. Configure real SMTP in `.env` for delivery to recipients; otherwise mails remain in the internal Mailpit container.

Use the same two `-f` options for updates, `logs` and `down`, so Compose keeps the HTTPS configuration:

```bash
docker compose -f docker-compose.yml -f docker-compose.https.yml logs --tail=100 caddy
docker compose -f docker-compose.yml -f docker-compose.https.yml down
```

If the hosting platform already terminates TLS, use its HTTPS ingress to the frontend's container port 80 instead of adding Caddy. Set `PUBLIC_URL=https://www.justklaris.com` on the live service and route both API prefixes through the frontend. Keep API and Mailpit ports private using the platform's network settings; the base Compose file exposes them for local development.

If Caddy already runs on the server, merge the site block from `docker/Caddyfile` into that proxy's configuration and make the frontend reachable on its internal network. Replace any existing redirect for `www.justklaris.com` with the app route; do not start a second proxy on the same ports. In this setup also set `PUBLIC_URL=https://www.justklaris.com` explicitly on the live service.

### Mail alerts

In the live panel, addresses can be entered per stock ("Mail alerts for CBK"). When the live feed finds a new announcement for that stock (EQS News or tagesschau.de), every address entered for it gets a mail with the time, type, source and link (`live/notify.py`). Several announcements from one poll go into one mail; each address gets its own mail. A new address first gets a confirmation mail; every mail has an unsubscribe link per stock (`/live/unsubscribe?token=…`).

Not mailed: holding notices (voting rights, directors' dealings, short positions) and announcements older than `ALERT_MAX_AGE_H` hours (default 6), so the first start does not mail the backlog. tagesschau.de articles are mailed as a link only, like in the UI.

For the demo, "Send test alert" (below the addresses) sends a sample ad hoc announcement to every address of the stock, through the same path as a real one, marked [TEST] and not stored in the feed (`POST /live/subscriptions/test`).

By default the mails go to Mailpit. For real delivery, copy `.env.example` to `.env`, fill in the SMTP server and run `docker compose up -d`. Subscriptions and a log of every mail (`alerts` table) are kept in the live SQLite database.

These are alerts on new announcements, not on unusual trading: the trading data ends on 30 Oct 2026, and unusual days come from the batch pipeline.

Run only one live poller at a time (the Docker one or the local one, not both), so EQS and tagesschau.de get no duplicate requests.

After code or data changes (also after `scripts/sync-hub.sh`; the team re-exports the seed with `python -m backend.seed export` after a pipeline run): `docker compose up --build -d`. Stop: `docker compose down`.

If the Hub API dependencies change (`uv.lock` in the team repo), refresh the pinned list:
`cd ../futury_4_2026 && uv export --frozen --no-dev --no-hashes --no-emit-project -o ../Deutschb-rse/docker/hub-api.requirements.txt`

## Run without Docker

1. Start the Hub API from `hub/` (the first request builds `hub/data/hub.duckdb` from the seed, a few seconds):

   ```bash
   python3.13 -m venv .venv && .venv/bin/pip install -r docker/hub-api.requirements.txt   # once
   cd hub && set -a && . ../.env && set +a && ../.venv/bin/uvicorn backend.api:app --port 8000
   ```

2. Start this frontend:

   ```bash
   cd frontend
   npm install
   npm run dev
   ```

3. Optional, the live feed (skip it if the Docker `live` container runs; it serves port 8003 too):

   ```bash
   PYTHONPATH=hub:. LIVE_DATA_DIR=live-data .venv/bin/uvicorn live.app:app --port 8003
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
hub/                  Hub API, copied from the team repo by scripts/sync-hub.sh (see SOURCE.txt)
  backend/api.py      FastAPI routes the frontend reads
  config.yaml         thresholds, event windows, LLM model
  data/reference/     CSVs and the Parquet seed the database is built from
live/
  app.py              live feed service: polling loop, /events, /status, /subscriptions, /unsubscribe
  sources.py          EQS News and tagesschau.de parsers
  store.py            SQLite: announcements, polls, subscriptions, sent mails
  notify.py           alert and confirmation mails over SMTP
```
