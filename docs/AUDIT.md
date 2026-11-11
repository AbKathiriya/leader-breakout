# Audit: live entry model and gap look-ahead (Nov 2026)

On `main` since 2026-11-10 (from branch `audit/live-entry-model`). All switches are off by default, so `python run_backtest.py` gives the published model.
Run `python -m research.audit_live` to reproduce. Output: `data/audit_live.log` and `data/audit_trades_<variant>.csv`.

Prices were downloaded again from Yahoo on 2026-11-10. `base` is 38.5% CAGR here, the same as `data/bt_summary.json` and the README.
The first audit run (2026-11-09 download) gave 38.8%. A new download changes each number by 1 to 2 CAGR points.
The universe is still today's listings (survivorship bias). Idle cash is in SPY in every variant.

## What was wrong

1. **Look-ahead on fills at the open.** When the open is above the trigger, the fill is at the open. The day's low
   comes after the fill. The old model used that low as the stop on up-close days, and skipped the trade if that low
   was too far away. On down-close days it closed the trade at the open price. 107 of 193 base trades are fills at the
   open, and they give 230 of the 384 points of summed trade P&L (% of equity).
2. **The backtest was not the live procedure.** Live tickets use a stop-limit (trigger + 1%), a sell-stop at the max
   stop, score priority, half cash size in caution, and EMA exits at the next open.

## Variants

| Variant | What it models |
|---|---|
| `base` | Published model |
| `gap_fix` | Base. A fill at the open gets the max stop, and is stopped the same day if the low reaches it |
| `monitored` | `gap_fix` + 1% chase limit + EMA exits at the next open + score priority. Stop is the low of the day at the fill (you watch the fill) |
| `live` | Ticket procedure with no one watching: resting order always fills, stop at the max stop on day 0, entry-day low after that |
| `live_worst` | `live`, and each entry-day low at or below the max stop is a stop-out |
| `*_cost` | Slippage 0.3% per side, 0.5% on stop exits (default is 0.1%) |

## Results (2015 – 10 Nov 2026, $10k start, SPY CAGR 13.4%)

| Variant | CAGR | Max DD | Sharpe | Trades | Win % | Profit factor | Sum of trade P&L without top 5 (% of equity) |
|---|---|---|---|---|---|---|---|
| base | 38.5% | −35.4% | 1.18 | 193 | 24.9 | 4.99 | +154.3 |
| gap_fix | 23.2% | −41.5% | 0.79 | 209 | 21.5 | 1.98 | +27.2 |
| monitored | 19.8% | −39.9% | 0.74 | 156 | 22.4 | 1.96 | −32.1 |
| monitored_cost | 15.2% | −42.7% | 0.61 | 147 | 21.1 | 1.52 | −78.9 |
| live | 12.2% | −49.8% | 0.50 | 285 | 30.2 | 1.09 | −92.1 |
| live_cost | 4.6% | −64.1% | 0.30 | 290 | 28.3 | 0.89 | −179.8 |
| live_worst | −27.5% | −98.3% | −0.93 | 410 | 6.8 | 0.32 | −604.3 |

Split periods (CAGR 2015–2020 / 2021–2026): base 26.2 / 53.5, gap_fix 16.5 / 31.5, monitored 15.6 / 25.3,
live 14.6 / 8.8, live_cost 10.0 / −1.6.

By entry type, `monitored`: breakouts 76 trades, +166.9 points; EPs 80 trades, +19.5 points (−13.5 with costs).

## Conclusions

1. About 15 CAGR points of the published result came from the look-ahead on fills at the open.
2. The `monitored` model is the nearest to the real procedure when the fill is watched. It gives 19.8% CAGR against
   13.4% for SPY, with a deeper drawdown, and the result is negative without its 5 best trades.
3. The unwatched ticket procedure (`live`) does not beat SPY, and loses with realistic costs.
4. EPs add almost nothing after the fix. Breakouts carry the result.
5. `monitored` still assumes that the low came before the fill on up-close days. Only intraday bars can test that.

## Not done yet

- Point-in-time universe (delisted stocks, historical market cap).
- Intraday replay of the triggers. Robinhood returns 5-minute bars for March 2026 but not for March 2025.
- Walk-forward test with frozen parameters.
