# IssuerLens

IssuerLens puts company news next to the price chart. Each trading day on the candlestick chart carries a marker for the news articles published that day, so price moves and news can be read side by side.

## Features

- **News on the chart**: markers on the candlestick chart show the articles for each date. Clicking a marker opens the articles for that company and day.
- **Filter by category**: market, earnings, product, policy, competition or management.
- **Similar days**: lists historical days with a similar news pattern and the returns that followed them.
- **Range questions**: select a date range and ask a language model to summarise the news published in that range.
- **Model forecast**: an XGBoost model outputs an up/down direction based on the last 30 days of news and price features.

## How the model works

The model combines news sentiment with technical indicators.

**Features (31 in total):**
- **News**: article count, sentiment score, positive/negative ratio, 3/5/10-day rolling averages, sentiment momentum
- **Technical**: price returns (1/3/5/10 days), volatility, volume ratio, RSI-14, moving-average crossover

**Steps:**
1. Claude Haiku (Batch API) labels each article with a sentiment, a short summary and the up/down arguments it contains.
2. The labels are joined with OHLC prices into one feature vector per trading day.
3. XGBoost classifiers output an up/down direction for T+1, T+3 and T+5.
4. Cosine similarity on the feature vectors finds historical periods with a similar pattern and shows the returns that followed.

> Experimental tool. Not financial advice.

## Architecture

```
Frontend (React + Vite + D3.js)          Backend (FastAPI + SQLite)
+---------------------------------+      +----------------------------+
|  CandlestickChart (D3.js)       |      |  /api/stocks/{sym}/ohlc    |
|  +- news dots on each date      |----->|  /api/news/{sym}?date=     |
|  +- crosshair + click to lock   |      |  /api/news/{sym}/categories|
|                                  |      |                            |
|  NewsPanel (right sidebar)       |<-----|  SQLite: issuerlens.db     |
|  +- sentiment sorted             |      |  +- ohlc (51K+ rows)      |
|  +- up/down reasons              |      |  +- news_raw (61K+)       |
|  +- T+1/T+5 returns              |      |  +- layer1_results (97K+) |
|                                  |      |                            |
|  PredictionPanel                 |<-----|  /api/predict/{sym}/forecast|
|  +- 7-day & 30-day forecasts     |      |  +- XGBoost models         |
|  +- similar historical periods   |      |  +- cosine similarity      |
+---------------------------------+      +----------------------------+
```

## Data Pipeline

```
Polygon API --> Layer 0 (rule filter) --> Layer 1 (Haiku Batch API) --> Layer 2 (Sonnet, on-demand)
  OHLC + News    reject spam/listicles    sentiment + up/down reasons     deep analysis on click
                  ~17% rejected            50 articles per batch call      cached in DB
```

## Quick Start

The repo includes a pre-built database (`issuerlens.db`) with historical data, so you can run it immediately — **no API keys needed**.

```bash
git clone https://github.com/fjcyz7tk42-tech/Deutschb-rse.git
cd Deutschb-rse

# Unpack the pre-built database and models
gunzip -k issuerlens.db.gz
tar xzf models.tar.gz -C backend/ml/

# Backend (Python 3.10+)
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Frontend (Node.js 18+)
cd frontend && npm install && cd ..
```

Then start both services (in two terminal windows):

```bash
# Terminal 1: Backend
source venv/bin/activate
uvicorn backend.api.main:app --reload

# Terminal 2: Frontend
cd frontend && npm run dev
```

Open **http://localhost:7777/IssuerLens/** in the browser.

### Updating data (optional)

If you want to fetch the latest stock data and run AI analysis, you'll need API keys:

```bash
cp .env.example .env
# Edit .env and fill in your keys:
```

| Key | Where to get it | Cost |
|-----|-----------------|------|
| `POLYGON_API_KEY` | [polygon.io](https://polygon.io/) | Free tier |
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com/) | Pay-as-you-go |

```bash
# Fetch new OHLC + news
python -m backend.bulk_fetch

# Run AI analysis
python -m backend.batch_submit --top 50
python -m backend.batch_collect <batch_id>
```

## Project Structure

```
.env                          # API keys (gitignored)
issuerlens.db                 # SQLite database (gitignored)
requirements.txt              # Python dependencies

backend/
  config.py                   # pydantic-settings, loads .env
  database.py                 # SQLite schema
  bulk_fetch.py               # Bulk download OHLC + news for many tickers
  batch_submit.py             # Submit Layer 1 to Anthropic Batch API
  batch_collect.py            # Collect Batch API results
  weekly_update.py            # Incremental weekly data update
  polygon/
    client.py                 # Polygon API with retry/backoff
  pipeline/
    layer0.py                 # Rule-based filter (free)
    layer1.py                 # Claude Haiku batch analysis
    layer2.py                 # Sonnet on-demand deep analysis
    alignment.py              # News -> trading day + forward returns
    similarity.py             # Similar news pattern matching
  ml/
    features.py               # 31-feature engineering (news + technical)
    model.py                  # XGBoost training (per-ticker + unified)
    inference.py              # Forecast generation + similar period analysis
    backtest.py               # Backtesting framework
    lstm_model.py             # Experimental LSTM model
  api/
    main.py                   # FastAPI app + CORS
    routers/
      stocks.py               # GET /api/stocks, /search, /{sym}/ohlc
      news.py                 # GET /api/news/{sym}, /{sym}/timeline
      analysis.py             # POST /api/analysis/deep, /story
      pipeline.py             # POST /api/pipeline/fetch, /process
      predict.py              # GET /api/predict/{sym}/forecast

frontend/
  src/
    App.tsx                   # Main layout (chart + panels)
    components/
      CandlestickChart.tsx    # D3.js chart with news dots
      NewsPanel.tsx           # Sentiment-sorted news cards
      NewsCategoryPanel.tsx   # Filter by impact category
      PredictionPanel.tsx     # AI forecast + similar periods
      RangeQueryPopup.tsx     # "Why did it drop?" range analysis
      SimilarDaysPanel.tsx    # Historical pattern matches
      StockSelector.tsx       # Ticker search + tabs
```

## Weekly Update

```bash
# Fetch new OHLC + news since last update
python -m backend.weekly_update

# Run AI analysis on new articles
python -m backend.batch_submit --top 50
python -m backend.batch_collect <batch_id>
```

## Cost Summary

| Item | Cost |
|------|------|
| Polygon data (free tier) | $0 |
| Layer 1 Batch API (per 1000 articles) | ~$0.35 |
| Layer 2 on-demand (per article) | ~$0.003 |
| Weekly incremental update | ~$1-2 |

## Tech Stack

- **Frontend**: React, TypeScript, Vite, D3.js
- **Backend**: FastAPI, SQLite (WAL mode), Pydantic
- **AI**: Claude Haiku 4.5 (batch sentiment), Claude Sonnet (deep analysis)
- **ML**: XGBoost (prediction), cosine similarity (pattern matching)
- **Data**: Polygon.io REST API
