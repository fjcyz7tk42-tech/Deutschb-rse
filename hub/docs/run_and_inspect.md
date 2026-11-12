# Run the app and inspect the data

## Run after a fresh clone (no data files needed)

```
uv sync
uv run uvicorn backend.api:app          # the first request builds data/hub.duckdb from the seed, about 1 second
cd frontend && npm ci && npm run dev    # open the URL it prints
```

The seed in `data/reference/seed/` (20 Parquet files, 67 MB) holds every table the app reads, for all 174 stocks and all 213 trading days of 2026: daily metrics, unusual days, events, event reactions, peers, spreads for 14 order sizes and 5-minute bars. `data/hub.duckdb` itself is not in git.

Optional: `.env` with `DEEPSEEK_API_KEY=...` for model-written card texts. Without it the cards use the template text.

## Inspect the database

DuckDB is a SQL database in one file. Open it with the DuckDB command line (`brew install duckdb`) or DBeaver, read-only while the API runs:

```
duckdb -readonly data/hub.duckdb
```

```sql
SHOW TABLES;
-- one stock, one day: every metric the card shows
SELECT * FROM daily_metrics WHERE isin = 'DE0008019001' AND date = '2026-08-31';
-- unusual periods of a stock with their status and score
SELECT start, "end", peak_date, metrics, score, status FROM cases WHERE isin = 'DE0008019001' ORDER BY start;
-- which raw files were loaded, and with what result
SELECT dataset, status, count(*) FROM coverage GROUP BY ALL;
```

## Update the seed

After the database changed (`scripts/build.sh`, or `uv run python -m backend.forensics` for new events):

```
uv run python -m backend.seed export
```

Commit the changed files in `data/reference/seed/`. To throw the database away and rebuild it from the seed: delete `data/hub.duckdb`, or run `uv run python -m backend.seed load`.

A rebuild from the raw exchange files still needs `FUTURY_MDS_DATA.zip` (dataset notes: `docs/data_dictionary.md`, local only, not in git).
