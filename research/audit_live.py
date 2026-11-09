"""Audit: does the published growth-mode result survive when the backtest follows the live procedure?

  python -m research.audit_live            → data/audit_live.log (one JSON line per variant)

Variants
  base             the published model (bar-path entry, stop at the low of the day at the fill)
  gap_fix          base, but a fill at the open no longer uses that day's (future) low as its stop
  monitored        gap_fix + what the tickets do: 1% chase limit, EMA exits at the next open, score priority
  live             ticket procedure: resting buy-stop-limit, sell-stop at the max stop on the entry day,
                   tightened to the entry day's low afterwards, exits at the next open, score priority
  live_worst       live, and any entry-day low at or below the max stop counts as a stop-out
  *_cost           same model with 0.3% slippage per side and 0.5% on stop exits
"""
from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
from engine.backtest import GROWTH_CASH, Config, metrics, run  # noqa: E402
from engine.data import DATA, load_prices, load_universe  # noqa: E402
from engine.framework import Params, atr_frame, indicators, regime_series  # noqa: E402

TICKET = dict(exit_next_open=True, chase_limit_pct=1.0, priority="score")
COST = dict(slippage=0.003, stop_slippage=0.005)
VARIANTS = {
    "base": {},
    "gap_fix": {"gap_fix": True},
    "monitored": {"gap_fix": True, **TICKET},
    "live": {"entry_mode": "live", **TICKET},
    "live_worst": {"entry_mode": "live", "live_worst": True, **TICKET},
    "monitored_cost": {"gap_fix": True, **TICKET, **COST},
    "live_cost": {"entry_mode": "live", **TICKET, **COST},
}
SPLITS = {"all": {}, "15-20": {"end": "2020-12-31"}, "21-26": {"start": "2021-01-01"}}
KEYS = ["CAGR %", "Max drawdown %", "Sharpe", "Trades", "Win rate %", "Profit factor", "Benchmark CAGR %"]


def trade_stats(res, px, slip) -> dict:
    """Per-trade P&L as % of account equity at the previous close (R is unstable when stops are tiny)."""
    tr, eq = res["trades"], res["curve"]["equity"]
    if not len(tr):
        return {}
    prev = eq.shift(1).bfill()
    ed = pd.to_datetime(tr.entry_date)
    pct = 100 * tr.pnl.to_numpy() / prev.reindex(ed).to_numpy()
    o = np.array([px["Open"].at[d, t] for d, t in zip(ed, tr.ticker)])
    gap = np.isclose(tr.entry.to_numpy() / (1 + slip), o, rtol=1e-4)
    same_day = (pd.to_datetime(tr.exit_date) == ed).to_numpy()
    srt = np.sort(pct)[::-1]
    by_kind = {k: {"n": int(m.sum()), "sum_pct": round(float(pct[m].sum()), 1)}
               for k in tr.kind.unique() for m in [(tr.kind == k).to_numpy()]}
    return {
        "avg_trade_pct_eq": round(float(pct.mean()), 2), "median_trade_pct_eq": round(float(np.median(pct)), 2),
        "avg_loss_pct_eq": round(float(pct[pct <= 0].mean()), 2) if (pct <= 0).any() else None,
        "worst_trade_pct_eq": round(float(pct.min()), 1), "best_trade_pct_eq": round(float(pct.max()), 1),
        "sum_pct_eq": round(float(pct.sum()), 1),
        "sum_without_top5": round(float(srt[5:].sum()), 1), "sum_without_top10": round(float(srt[10:].sum()), 1),
        "same_day_stops": int(same_day.sum()), "gap_open_fills": int(gap.sum()),
        "gap_open_sum_pct": round(float(pct[gap].sum()), 1), "by_kind": by_kind,
    }


def main():
    u = load_universe()
    px = load_prices(sorted(set(u.index) | {"SPY", "QQQ", "IWM"}))
    p = Params()
    ind, atr, reg, spy = indicators(px, p), atr_frame(px), regime_series(px, p), px["Close"]["SPY"]
    cache: dict = {}
    out = open(DATA / "audit_live.log", "w")
    for name, co in VARIANTS.items():
        for split, so in SPLITS.items():
            cfg = Config(**{**GROWTH_CASH, **co, **so})
            res = run(px, ind, atr, u, reg, p, cfg, watch_cache=cache)
            m = metrics(res, spy)
            row = {"name": name, "split": split, **{k: m[k] for k in KEYS}}
            if split == "all":
                row.update(trade_stats(res, px, cfg.slippage))
                res["trades"].to_csv(DATA / f"audit_trades_{name}.csv", index=False)
            line = json.dumps(row)
            print(line, flush=True)
            out.write(line + "\n")
            out.flush()
    out.close()


if __name__ == "__main__":
    main()
