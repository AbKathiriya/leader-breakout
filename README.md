# Leader Breakout

This is a rules-based swing system from the SRxTrades guide "How to make money in stocks". It trades leading stocks in leading groups, entering on tight-base breakouts with low-of-day stops and trimming on the 8/21/50 EMAs.

| Piece | Where | What it does |
|---|---|---|
| TradingView indicator | `pine/leader_breakout_framework.pine` | Shows the regime, EMAs, current base, trigger and undercut levels, breakout and undercut entries, stop and first target, the trim and exit signals, an info table, and alerts |
| Engine | `engine/framework.py` | Holds the rules: regime, sector and industry ranking, leader filters, base detection, first target |
| Weekly scan | `python -m engine.scan` | Writes `data/scan_latest.json` and `data/ranks_latest.json` |
| Ticker check | `python -m engine.scan --tickers NVDA,RKLB` | Gives the verdict inputs for any ticker (used by the skill) |
| Report page | `python -m engine.report data/scan_latest.json -o report.html` | Renders the watchlist page |
| Backtest | `python run_backtest.py` | Replays the weekly scan from 2015 on daily bars, plus variants |
| Claude skill | `skills/leader-breakout/SKILL.md` | Runs the ticker check and adds Robinhood options alternatives |

## Rules (growth mode: cash account under $100k)

1. **Regime (SPY and QQQ).** Both above their 8/21/50 EMAs means risk-on, full size. Both above the 50 means caution, half size. Anything else means risk-off: no new entries.
2. **Groups.** Rank stocks by an IBD-style RS composite (40% 3-month, 20% each for 6, 9 and 12 months). An industry scores 0.7 × the median member RS rating + 30 × the share of members above their 50 EMA. Take the top 15 industries and the top 5 stocks in each that pass the leader filters. Sectors are shown for context only; gating on them cut returns.
3. **Leader filters** (from the article's scanner). Price > $3, 10-day average volume > 500k, ADR > 2%, close above the 21 and 50 EMAs, and close within 15% of the 52-week high (George & Hwang's 52-week-high effect: +3.6 points of CAGR, better in both halves).
4. **Breakout base.**
   - ≥ 5 bars since the 40-bar high.
   - Depth ≤ max(25%, 3×ADR), capped at 40%.
   - The stock rose ≥ 25% into the high within the prior 60 bars, on heavy volume: the leg's average volume is ≥ 1.2× the 50 days before it, and up-day volume is ≥ 1.2× down-day volume.
   - The last 5 bars' range is ≤ 2×ADR, on volume ≤ the 50-day average.
   - Close > 21 EMA > 50 EMA.
5. **Episodic pivot (EP).** The stock gaps ≥ 15% on ≥ 5× its 50-day volume, closes in the upper half of the day's range, and the day's range is ≥ 2× its ADR. The range test filters out buyout announcements, which gap and then pin. Found daily after the close.
6. **Entries.**
   - Breakout: buy-stop at the base high, valid all week.
   - EP: buy-stop at the gap day's high, valid the next session only.
   - The stop is the entry day's low. Skip or exit if that low is more than ½ ADR or 3% below the fill.
   - No undercut entries; they lost money in growth mode.
7. **Size.** Up to 2 positions. The first fill can use the whole account; the 5% risk cap rarely binds with stops this tight. Half size in caution. Cash only, no margin.
8. **Idle cash** sits in SPY. Sell enough SPY at the open on days with a live ticket.
9. **Exits.**
   - Sell ¼ at the first target (the nearest overhead swing high ≥ 1R away, otherwise 3R), then move the stop to breakeven.
   - Sell ¼ on a close below the 8 EMA, ¼ on a close below the 21 EMA, and the rest below the 50 EMA.
10. **Above $100k,** switch to standard mode: 2% risk, 25% position cap, up to 8 positions, breakouts only.

Account settings live in `data/account.json` (equity, monthly deposit, slots, idle ETF).

## Known limitations

- **Survivorship bias.** The universe is today's listings, so stocks that were delisted are missing. That flatters the results.
- **Industry labels.** Groups use today's Nasdaq sector and industry labels for the whole history.
- **Daily bars only.** The backtest can't replay the 5-minute sniper entry or the intraday low-of-day stop. It reports three entry models (`touch_pess`, `touch_opt`, `close_conf`) to bracket reality.
- **No options history.** Options are not backtested because no free historical options data exists. The skill builds an options alternative from live Robinhood chains.

## Setup

```
pip install -r requirements.txt
python -m engine.scan          # first run downloads ~3,800 tickers (≈30 min); later runs top up
```

Yahoo endpoints needed: `query1.finance.yahoo.com`, `query2.finance.yahoo.com`, `fc.yahoo.com`.

## Backtest (2015 – Oct 2026, daily bars)

Run `python run_backtest.py`; `data/bt_summary.json` holds every variant. Daily bars can't show whether the entry day's low came before or after the fill at the trigger, so three models bracket the 5-minute entry:

- **Bar-path (default).** Up-close day: open → low → high → close, so the low came first and the trader either skips or uses it as the stop. Down-close day: open → high → low → close, so the trader is filled and then stopped the same day.
- **Optimistic.** The low always came before the fill.
- **Worst case.** Every ambiguous day is a fill followed by a stop at the max stop.

| Variant (from $10k, 2015 – Oct 2026) | CAGR | Max DD | Sharpe | Trades | Profit factor |
|---|---|---|---|---|---|
| **Growth mode (default)** | **40.1%** | **−35.4%** | **1.21** | 190 | 5.52 |
| Optimistic intraday entry | 45.4% | −35.4% | 1.33 | 83 | 14.2 |
| Worst-case intraday entry | −19.3% | −95.4% | −0.47 | 432 | 0.43 |
| No 52-week-high filter | 36.4% | −35.5% | 1.17 | 198 | 4.91 |
| Add Minervini trend template | 38.8% | −35.4% | 1.19 | 175 | 4.72 |
| Add pocket-pivot entries | 41.4% | −34.7% | 1.20 | 221 | 4.37 |
| Idle cash stays cash | 31.4% | −24.6% | 1.11 | 190 | 5.49 |
| Idle cash in QQQ | 42.4% | −29.5% | 1.22 | 190 | 5.52 |
| Breakouts only (no EPs) | 29.6% | −35.4% | 1.18 | 91 | 4.41 |
| Add undercut entries | 40.9% | −35.5% | 1.22 | 208 | 4.44 |
| No volume-profile check | 38.2% | −32.2% | 1.19 | 311 | 3.83 |
| No market-regime filter | 28.6% | −38.6% | 0.96 | 213 | 4.47 |
| Stops up to 1 ADR | 14.1% | −44.8% | 0.55 | 270 | 1.06 |
| Standard mode (8 × 25%) | 6.1% | −9.1% | 0.88 | 136 | 3.49 |
| SPY buy and hold | 13.7% | −33.7% | | | |

Split periods: 28.2% CAGR in 2015–2020 and 54.7% in 2021–2026. Time to $100k from $10k with $1,500/month deposits, across every start month: 2.6 / 3.2 / 3.7 years (25th / median / 75th percentile), versus about 3.7 years median for SPY alone. The edge rests on entering intraday at the trigger with a low-of-day stop. Entering at the close instead earns almost nothing, and allowing wide stops doubles the drawdown. Requiring a heavy-volume leg up cuts trades by two-thirds but makes the strategy far less sensitive to how entry days play out (worst case −1.6% CAGR instead of −15%). Results are very sensitive to how failed intraday breakouts play out (see the worst case), so execution discipline is the strategy: skip if the low is already below the max stop, and honour the stop immediately. Over this period the strategy does not beat SPY's return, though its drawdowns are smaller. Survivorship bias (today's listings only) means real results would be lower.

## Intraday check of the entry model

Robinhood keeps about 3 months of intraday bars. Every breakout and EP trigger from Aug–Oct 2026 (27 days) was checked against 30-minute bars. The bar-path model matched on 21; of the 4 mismatches, 2 were better and 2 worse than the model; 2 were ambiguous. The same check found that 6 of 15 EP fills were buyout announcements, which led to the range filter.

## Weekly (Sunday) run

```
python -m engine.scan                       # refresh prices, rank groups, find setups
python -m engine.weekly options-plan        # which option strikes to quote for each ready setup
#   …agent pulls quotes from Robinhood, writes quotes.json…
python -m engine.weekly options-input quotes.json && python -m engine.options data/options_input.json > data/options_latest.json
python -m engine.report data/scan_latest.json --options data/options_latest.json --backtest data/bt_report.json -o report
```

Daily after the close: `python -m engine.ep_scan` (writes `data/ep_latest.json`), then rebuild the report the same way. EP tickets and charts are added automatically.
