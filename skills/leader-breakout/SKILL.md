---
name: leader-breakout
description: Run one or more tickers through the leader-breakout swing framework (market regime → group leadership → tight base → breakout/undercut entry, low-of-day stop, EMA trims) and say whether each is tradable now, with trigger, stop, first target, size and an options alternative from Robinhood.
---

# Leader Breakout: ticker check

Use when the user gives a ticker or list and asks whether it's a setup, where to enter, or to "run the framework". The rules come from the SRxTrades "How to make money in stocks" guide (Qullamaggie-style swing trading). The engine in the `AbKathiriya/leader-breakout` repo implements them, and the same code runs the weekly scan and the backtest. This skill is analysis only. Never place orders.

## 1. Get the engine and run it

1. Attach and clone the repo: `add_repo` owner `AbKathiriya`, repo `leader-breakout` (read access), then `git clone --depth 1 https://github.com/AbKathiriya/leader-breakout`.
2. `pip install -q --break-system-packages -r requirements.txt`
3. From the repo root: `python -m engine.scan --tickers NVDA,RKLB,...`, with uppercase tickers comma-separated. It prints JSON:
   - `regime` (2 risk-on, 1 caution, 0 risk-off) and `regime_text`
   - per ticker: `rs_rating` (1–99 versus the whole universe), `industry_rank` / `industry_count`, `sector_rank`, `adr`, EMAs, `leader_filters`, and `setup`, which has `ready`, `checks`, `trigger`, `undercut`, `max_stop`, `t1`, `rr_at_max_stop`, `base_len`, `depth`, `prior_move`, `tight_pct`, `dry` and `ext_atr`
   - Group ranks and RS ratings come from `data/ranks_latest.json`, which the Sunday scan commits. State `ranks_as_of` in the answer. If it is more than 8 days old, say so.
4. If Yahoo is unreachable (the shell gets HTTP 000 or 403, or the JSON says "no price data" for everything), tell the user to allow `query1.finance.yahoo.com`, `query2.finance.yahoo.com` and `fc.yahoo.com` under claude.ai Settings → Capabilities. Then fall back to section 5.

## 2. Verdict per ticker

Lead with the market. If `regime == 0`, say no new longs this week whatever the chart shows, and still give the levels for when the regime turns.

| Verdict | When |
|---|---|
| **TRADE** | `setup.ready`, all `leader_filters` true except `above_8` (which may be false inside a base), `rs_rating ≥ 70`, regime ≥ 1, and `ext_atr < 3` |
| **WATCH** | Leader filters pass and 1–2 setup checks fail. Say exactly what would complete it: "needs 2–3 more quiet days" (tight), "volume still heavy" (volume_dry), "only N days since the high" (base_length) |
| **AVOID** | Trend fails (below 21/50 EMA, or 21 below 50), ADR < 2%, 10-day volume < 500k, `rs_rating < 50`, depth fails badly, or extended more than 3 ATR above the 8 EMA (don't chase) |

Group context sharpens the call. A stock in a top-10 industry with RS ≥ 80 is the article's ideal. A ready base in a bottom-half industry is a lower-quality trade, so say so.

## 3. Entry plan (TRADE, and WATCH names that are one check away)

- **Breakout:** buy-stop a few cents above `trigger`. The article's "sniper" entry is the first 5- or 15-minute candle that clears the trigger with volume pacing at least 1.5× normal. If the user asks during market hours, pull today's 5-minute bars with Robinhood `get_equity_historicals` (interval `5minute`) to see whether it has already triggered, and on how much volume.
- **Stop:** low of the entry day. `max_stop` is the trigger minus the smaller of ½ ADR and 3%. If the day's low is already below `max_stop`, skip the trade. The backtest showed the whole edge comes from these tight-risk entries: trades with 3–10% stops lost money.
- **Undercut & rally (alternative):** price dips below `undercut` (the base low), then reclaims it. Enter on the reclaim, with the stop at the day's low.
- **Size:** shares = (account × 2% × regime factor) ÷ (entry − stop). The regime factor is 1 in risk-on and 0.5 in caution. Cap any position at 25% of the account. With stops this tight the cap usually binds, so real risk is about 0.25–0.75% of the account. Say so. If the account size isn't known, give the formula and a per-$100k example.
- **First target:** `t1`, the nearest overhead swing high at least 1R away, otherwise 3R. Report R:R using `max_stop` as the worst case. Below 2R at the max stop, call it marginal.
- **Management:** sell ¼ at `t1` and move the stop to breakeven. Sell ¼ on a daily close below the 8 EMA, ¼ on a close below the 21 EMA, and the rest on a close below the 50 EMA.
- **Earnings:** check `get_earnings_results` for the ticker. If a report falls within ~10 trading days, flag it. A low-of-day stop doesn't protect against an earnings gap, so either wait or size for the gap.

## 4. Options alternative (TRADE names), via Robinhood MCP

1. `get_option_chains` (underlying_symbol). Pick the first monthly expiration 45–90 days out, and after the next earnings date when possible.
2. For 3–4 strikes between 90% and 101% of the trigger, call `get_option_instruments` with `chain_symbol`, `expiration_dates`, `type: call` **and `strike_price`** (e.g. `"110.0000"`). Make one call per strike, in parallel. Unfiltered listings return every strike and flood the context. Strikes step by $2.50, $5 or $10 depending on price.
3. `get_option_quotes` for those instrument ids. Note `mark_price`, `bid_price`, `ask_price`, `delta`, `gamma`, `theta`, `implied_volatility` and `open_interest`.
4. Write a JSON list to a file, one object per ticker: `{"ticker", "spot" (last close), "trigger", "stop" (max_stop), "t1", "adr", "account", "risk_pct": 0.02, "regime_factor", "calls": [{"strike", "mark", "bid", "ask", "delta", "gamma", "theta", "iv", "oi", "expiration"}]}`. Then run `python -m engine.options that_file.json`.
5. The script values each call at the trigger, the stop and the target using a delta-gamma expansion from today's spot. It pays half the spread on entry and exit and charges theta over about 10 days. It applies a liquidity gate (spread ≤ 6% of mid, OI ≥ 500), compares option R:R with share R:R, and flags IV more than 1.3× realized, in which case a call debit spread up to the target strike is the better structure. Report its `summary` line. If the options are too thin, say "trade shares". Options cap a gap-through-the-stop loss at the premium, while shares don't decay; mention that trade-off when the two are close.

## 5. Fallback without the engine

Pull 1 year of daily bars for the tickers plus SPY and QQQ with Robinhood `get_equity_historicals` (interval `day`, 10 symbols per call). Write them to CSV and compute the rules in Python:

- **Regime:** risk-on if SPY and QQQ both close above their 8/21/50 EMAs. Caution if both are above the 50 but not all three. Otherwise risk-off.
- **Leader:** price > 3, 10-day average volume > 500k, ADR% (20-day mean of high/low − 1) > 2, and close above the 21 and 50 EMAs.
- **Base:** k = bars since the highest high of the last 40 bars, with k ≥ 5. Depth = (that high − lowest low since) ÷ high ≤ min(40%, max(25%, 3×ADR)). The prior move from the lowest low of the 60 bars before the high must be ≥ 25%. The last 5 bars' range must be ≤ 2×ADR% of the close. The last 5 bars' average volume must be ≤ the 50-day average. Trend: close > 21 EMA > 50 EMA.
- **Levels:** trigger = base high, undercut = base low, max stop = trigger × (1 − min(½·ADR%, 3%)), t1 as in section 3.

Without the group ranks file, say that sector, industry and RS context are unavailable.

## 6. Answer format

Start with one line on the regime. Then a table: Ticker · Verdict · Trigger · Max stop · Undercut · First target · R:R · Note. Follow with 2–4 lines per TRADE/WATCH name: why it qualifies, the earnings date, and the options line. Keep AVOID names to one line each. End with the ranks date, and note that the TradingView indicator `pine/leader_breakout_framework.pine` in the repo draws the same levels.
