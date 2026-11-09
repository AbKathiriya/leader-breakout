# Audit: live entry model and gap look-ahead (Nov 2026)

Branch `audit/live-entry-model`. All switches are off by default, so `python run_backtest.py` gives the published model.
Run `python -m research.audit_live` to reproduce. Output: `data/audit_live.log` and `data/audit_trades_<variant>.csv`.

Prices were downloaded again from Yahoo on 2026-11-09, so `base` is 38.8% CAGR here (README: 40.1%).
The universe is still today's listings (survivorship bias). Idle cash is in SPY in every variant.

## What was wrong

1. **Look-ahead on fills at the open.** When the open is above the trigger, the fill is at the open. The day's low
   comes after the fill. The old model used that low as the stop on up-close days, and skipped the trade if that low
   was too far away. On down-close days it closed the trade at the open price. 107 of 192 base trades are fills at the
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

## Results (2015 – 9 Nov 2026, $10k start, SPY CAGR 13.4%)

| Variant | CAGR | Max DD | Sharpe | Trades | Win % | Profit factor | Sum of trade P&L without top 5 (% of equity) |
|---|---|---|---|---|---|---|---|
| base | 38.8% | −35.4% | 1.19 | 192 | 25.0 | 4.99 | +154.7 |
| gap_fix | 24.1% | −38.9% | 0.82 | 208 | 21.6 | 2.04 | +32.9 |
| monitored | 20.5% | −39.3% | 0.76 | 153 | 22.9 | 2.01 | −31.1 |
| monitored_cost | 15.9% | −42.2% | 0.63 | 144 | 21.5 | 1.56 | −77.6 |
| live | 12.6% | −49.4% | 0.51 | 282 | 30.1 | 1.09 | −92.1 |
| live_cost | 4.0% | −66.0% | 0.29 | 296 | 28.4 | 0.87 | −188.1 |
| live_worst | −26.4% | −98.0% | −0.85 | 418 | 6.9 | 0.33 | −590.3 |

Split periods (CAGR 2015–2020 / 2021–2026): base 26.4 / 54.1, gap_fix 16.6 / 33.3, monitored 15.8 / 26.7,
live 14.7 / 9.3, live_cost 10.1 / −2.7.

By entry type, `monitored`: breakouts 73 trades, +171.7 points; EPs 80 trades, +19.7 points (−13.5 with costs).

## Conclusions

1. About 15 CAGR points of the published result came from the look-ahead on fills at the open.
2. The `monitored` model is the nearest to the real procedure when the fill is watched. It gives 20.5% CAGR against
   13.4% for SPY, with a deeper drawdown, and the result is negative without its 5 best trades.
3. The unwatched ticket procedure (`live`) does not beat SPY, and loses with realistic costs.
4. EPs add almost nothing after the fix. Breakouts carry the result.
5. `monitored` still assumes that the low came before the fill on up-close days. Only intraday bars can test that.

## Not done yet

- Point-in-time universe (delisted stocks, historical market cap).
- Intraday replay of the triggers. Robinhood returns 5-minute bars for March 2026 but not for March 2025.
- Walk-forward test with frozen parameters.
