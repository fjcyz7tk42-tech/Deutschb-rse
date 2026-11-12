"""Step 3. Analytics engine: daily_metrics for the whole universe.

Metrics: turnover_eur, return_1d, abnormal_return, rel_volume, xlm_bps, auction turnover and share
(opening, midday, closing), open_gap, close_vs_vwap, participant mix, 20-day median and MAD baselines.
Returns and shares are fractions (0.012 = 1.2 %); facts.py converts for display.
Intraday 5-minute bars are built by the loader (table trade_bars) for every stock and day.
"""
from __future__ import annotations

from backend.config import load_config
from backend.db import connect

BASELINED = ("rel_volume", "xlm_bps", "abnormal_return", "open_auction_share", "mid_auction_share", "close_auction_share")


def build_daily_metrics() -> None:
    cfg = load_config()
    n, size = int(cfg["baseline_window_days"]), float(cfg["order_size_eur"])
    con = connect()
    prev = f"ROWS BETWEEN {n} PRECEDING AND 1 PRECEDING"
    con.execute(f"""CREATE OR REPLACE TABLE daily_metrics AS
    WITH base AS (
        SELECT o.date, o.isin, coalesce(m.idx, e.idx) AS idx, m.idx IS NOT NULL AS is_member, e.sector,
               o.turnover AS turnover_eur, o.volume AS volume_shares, o.vwap,
               coalesce(o.close_auction_price, o.close_price) AS close,
               o.open_auction_price, o.close_auction_price
        FROM ohlc o JOIN entities e USING (isin) LEFT JOIN members m ON m.isin = o.isin AND m.date = o.date),
    r AS (
        SELECT *, close / lag(close) OVER (PARTITION BY isin ORDER BY date) - 1 AS return_1d,
               lag(close) OVER (PARTITION BY isin ORDER BY date) AS prev_close,
               turnover_eur / nullif(median(turnover_eur) OVER (PARTITION BY isin ORDER BY date {prev}), 0) AS rel_volume_raw,
               count(turnover_eur) OVER (PARTITION BY isin ORDER BY date {prev}) AS hist
        FROM base),
    mk AS (SELECT date, idx, median(return_1d) AS market_return FROM r WHERE is_member GROUP BY ALL),
    sc AS (SELECT date, sector, median(return_1d) AS sector_median_return FROM r WHERE is_member GROUP BY ALL),
    au AS (SELECT date, isin, sum(turnover) FILTER (auction = 'open') AS open_auction_turnover,
                  sum(turnover) FILTER (auction = 'mid') AS mid_auction_turnover,
                  sum(turnover) FILTER (auction = 'close') AS close_auction_turnover FROM auction_sums GROUP BY ALL),
    tb AS (SELECT date, isin, sum(turnover) AS trades_turnover FROM trade_bars GROUP BY ALL),
    fl AS (SELECT date, isin, mm_volume, agent_volume, prop_volume, aggressive_volume, passive_volume, auction_volume,
                  mm_flow_qty, agent_flow_qty, prop_flow_qty
           FROM flows WHERE NOT delayed_release AND reported_flow_dates = strftime(date, '%Y-%m-%d')),
    x AS (SELECT date, isin, impact_bps AS xlm_bps FROM xlm WHERE notional = {size})
    SELECT r.date, r.isin, r.idx, r.is_member, r.sector, r.turnover_eur, r.volume_shares, r.vwap, r.close, r.prev_close,
        r.return_1d, mk.market_return, sc.sector_median_return, r.return_1d - mk.market_return AS abnormal_return,
        CASE WHEN r.hist = {n} THEN r.rel_volume_raw END AS rel_volume,
        x.xlm_bps,
        CASE WHEN tb.isin IS NOT NULL THEN coalesce(au.open_auction_turnover, 0) END AS open_auction_turnover,
        CASE WHEN tb.isin IS NOT NULL THEN coalesce(au.mid_auction_turnover, 0) END AS mid_auction_turnover,
        CASE WHEN tb.isin IS NOT NULL THEN coalesce(au.close_auction_turnover, 0) END AS close_auction_turnover,
        tb.trades_turnover,
        coalesce(au.open_auction_turnover, 0) / nullif(tb.trades_turnover, 0) AS open_auction_share,
        coalesce(au.mid_auction_turnover, 0) / nullif(tb.trades_turnover, 0) AS mid_auction_share,
        coalesce(au.close_auction_turnover, 0) / nullif(tb.trades_turnover, 0) AS close_auction_share,
        r.open_auction_price / r.prev_close - 1 AS open_gap,
        r.close_auction_price / nullif(r.vwap, 0) - 1 AS close_vs_vwap,
        fl.mm_volume / nullif(fl.mm_volume + fl.agent_volume + fl.prop_volume, 0) AS mm_share,
        fl.agent_volume / nullif(fl.mm_volume + fl.agent_volume + fl.prop_volume, 0) AS agent_share,
        fl.prop_volume / nullif(fl.mm_volume + fl.agent_volume + fl.prop_volume, 0) AS prop_share,
        fl.aggressive_volume / nullif(fl.aggressive_volume + fl.passive_volume + fl.auction_volume, 0) AS aggressive_share,
        fl.passive_volume / nullif(fl.aggressive_volume + fl.passive_volume + fl.auction_volume, 0) AS passive_share,
        fl.auction_volume / nullif(fl.aggressive_volume + fl.passive_volume + fl.auction_volume, 0) AS flow_auction_share,
        fl.mm_flow_qty, fl.agent_flow_qty, fl.prop_flow_qty
    FROM r LEFT JOIN mk USING (date, idx) LEFT JOIN sc USING (date, sector) LEFT JOIN au USING (date, isin)
         LEFT JOIN tb USING (date, isin) LEFT JOIN fl USING (date, isin) LEFT JOIN x USING (date, isin)""")
    # rolling baselines over the previous n rows; null until n values exist
    cols = ", ".join(
        f"CASE WHEN count({m}) OVER w = {n} THEN median({m}) OVER w END AS {m}_median, "
        f"CASE WHEN count({m}) OVER w = {n} THEN mad({m}) OVER w END AS {m}_mad" for m in BASELINED)
    con.execute(f"""CREATE OR REPLACE TABLE daily_metrics AS SELECT *, {cols} FROM daily_metrics
        WINDOW w AS (PARTITION BY isin ORDER BY date {prev})""")
    # participant-mix baseline: same window, used for the "shift" on the card
    con.execute(f"""CREATE OR REPLACE TABLE daily_metrics AS SELECT *,
        median(agent_share) OVER w AS agent_share_median, median(prop_share) OVER w AS prop_share_median,
        median(mm_share) OVER w AS mm_share_median FROM daily_metrics
        WINDOW w AS (PARTITION BY isin ORDER BY date {prev})""")


if __name__ == "__main__":
    build_daily_metrics()
