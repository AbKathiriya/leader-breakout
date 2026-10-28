"""Backtest the weekly leader-breakout strategy and a few variants.

  python run_backtest.py                 # all variants, 2015 → today
  python run_backtest.py --only base     # one variant
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import replace

import pandas as pd

from engine.backtest import GROWTH_CASH, Config, metrics, run, yearly
from engine.data import DATA, load_prices, load_universe
from engine.framework import Params, atr_frame, indicators, regime_series

VARIANTS = {
    # name: (Params overrides, Config overrides) on top of GROWTH_CASH. "base" = what the weekly report trades.
    "base": ({}, {}),
    "optimistic_entry": ({}, {"entry_mode": "touch_opt"}),
    "worst_case_entry": ({}, {"entry_mode": "touch_worst"}),
    "idle_cash_not_spy": ({}, {"idle": "cash"}),
    "idle_qqq": ({}, {"idle": "QQQ"}),
    "no_episodic_pivots": ({}, {"ep": False}),
    "with_undercuts": ({}, {"use_undercut": True}),
    "no_volume_profile": ({"volume_profile": False}, {}),
    "no_regime_filter": ({}, {"regime_filter": False}),
    "wide_stops_1adr": ({"max_risk_adr": 1.0, "max_risk_pct": 100.0}, {}),
    "standard_mode_8x25pct": ({}, {"max_positions": 8, "max_pos_pct": 0.25, "risk_pct": 0.02, "ep": False,
                                   "use_undercut": True, "idle": "cash"}),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--start", default="2015-01-01")
    a = ap.parse_args()
    u = load_universe()
    px = load_prices(sorted(set(u.index) | {"SPY", "QQQ", "IWM"}))
    p0 = Params()
    t0 = time.time()
    ind = indicators(px, p0)
    atr = atr_frame(px)
    reg = regime_series(px, p0)
    spy = px["Close"]["SPY"]
    print(f"indicators {time.time() - t0:.0f}s, {px['Close'].shape}")

    names = [a.only] if a.only else list(VARIANTS)
    summary = {}
    for name in names:
        po, co = VARIANTS[name]
        p = replace(p0, **po)
        cfg = Config(**{**GROWTH_CASH, "start": a.start, **co})
        t0 = time.time()
        res = run(px, ind, atr, u, reg, p, cfg)
        m = metrics(res, spy)
        summary[name] = m
        print(f"\n== {name} ({time.time() - t0:.0f}s)\n" + json.dumps(m, indent=1))
        if name == "base":
            res["trades"].to_csv(DATA / "bt_trades.csv", index=False)
            res["curve"].to_csv(DATA / "bt_curve.csv")
            yearly(res, spy).to_csv(DATA / "bt_yearly.csv")
            print(yearly(res, spy).to_string())
            pd.DataFrame(res["watch"]).to_json(DATA / "bt_watch.json", orient="records", date_format="iso")
    (DATA / "bt_summary.json").write_text(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
