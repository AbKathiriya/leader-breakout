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

## Rules

1. **Regime (SPY and QQQ).** Both above their 8/21/50 EMAs means risk-on, full size. Both above the 50 means caution, half size. Anything else means risk-off: no new entries.
2. **Groups.** Rank stocks by an IBD-style RS composite (40% 3-month, 20% each for 6, 9 and 12 months). A sector or industry scores 0.7 × the median member RS rating + 30 × the share of members above their 50 EMA. Take the top 15 industries, then the top 5 stocks per industry that pass the leader filters. Sectors are still ranked and shown for context. Gating on the top 4 sectors cut returns in the backtest (`sector_gate_top4` variant), so it's off by default.
3. **Leader filters** (from the article's TradingView scan). Price > $3, 10-day average volume > 500k, ADR > 2%, and close above the 21 and 50 EMAs.
4. **Base.**
   - It has been ≥ 5 bars since the 40-bar high.
   - Depth is ≤ max(25%, 3×ADR), capped at 40%.
   - The stock rose ≥ 25% into the high within the prior 60 bars.
   - The last 5 bars' range is ≤ 2×ADR.
   - The last 5 days' volume is ≤ the 50-day average.
   - Close > 21 EMA > 50 EMA.
5. **Entry.**
   - Breakout: buy-stop at the base high.
   - Undercut and rally: buy on the reclaim of the base low.
   - The stop is the entry day's low. Skip the trade if that stop is more than ½ ADR or 3% away. This rule carries the edge: in testing, trades with 3–10% stops lost money.
6. **Size.** Risk 2% of equity (1% in caution), capped at 25% of equity per position, with at most 8 positions. With stops this tight, the 25% cap usually binds first.
7. **Exits.**
   - Sell ¼ at the first target (the nearest overhead swing high ≥ 1R away, otherwise 3R), then move the stop to breakeven.
   - Sell ¼ on a close below the 8 EMA, ¼ on a close below the 21 EMA, and the rest on a close below the 50 EMA.

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

The table shows `python run_backtest.py` with the default rules. The first two rows bracket the 5-minute entry, which daily bars can't replay.

| Variant | CAGR | Max DD | Sharpe | Trades | Profit factor |
|---|---|---|---|---|---|
| Current rules, pessimistic intraday entry | 7.4% | −20.9% | 0.75 | 321 | 1.92 |
| Current rules, optimistic intraday entry | 9.7% | −15.3% | 0.91 | 317 | 2.37 |
| Enter at the close on volume (no intraday entry) | −0.2% | −18.7% | −0.01 | 160 | 0.95 |
| Stops allowed up to 1 ADR | −3.1% | −55.2% | −0.11 | 818 | 0.89 |
| Article scope (top 4 sectors, 8 industries × 3) | 3.3% | −15.9% | 0.50 | 136 | 2.00 |
| Breakouts only (no undercuts) | 7.3% | −11.2% | 0.85 | 194 | 2.69 |
| SPY buy and hold | 13.7% | −33.7% | | | |

The edge comes from tight low-of-day stops taken intraday at the trigger. Over this period the strategy does not beat SPY's return. Its drawdowns are smaller and it sits in cash about 45% of the time. Survivorship bias (today's listings only) means real results would be lower.

## Weekly (Sunday) run

```
python -m engine.scan                       # refresh prices, rank groups, find setups
python -m engine.weekly options-plan        # which option strikes to quote for each ready setup
#   …agent pulls quotes from Robinhood, writes quotes.json…
python -m engine.weekly options-input quotes.json && python -m engine.options data/options_input.json > data/options_latest.json
python -m engine.report data/scan_latest.json --options data/options_latest.json --backtest data/bt_report.json -o report
```
