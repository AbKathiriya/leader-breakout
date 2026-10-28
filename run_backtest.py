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

from engine.backtest import Config, metrics, run, yearly
from engine.data import DATA, load_prices, load_universe
from engine.framework import Params, atr_frame, indicators, regime_series

VARIANTS = {
    # name: (Params overrides, Config overrides). "base" = current defaults.
    "base": ({}, {}),
    "optimistic_entry": ({}, {"entry_mode": "touch_opt"}),
    "close_confirm_entry": ({}, {"entry_mode": "close_conf"}),
    "no_regime_filter": ({}, {"regime_filter": False}),
    "no_undercut": ({}, {"use_undercut": False}),
    "t1_3R": ({"t1_mode": "r"}, {}),
    "sector_gate_top4": ({"top_sectors": 4}, {}),
    "article_scope_8x3": ({"top_industries": 8, "stocks_per_industry": 3, "top_sectors": 4}, {}),
    "wide_stops_1adr": ({"max_risk_adr": 1.0, "max_risk_pct": 100.0}, {}),
    "rs_only_no_groups": ({}, {"selection": "rs_only"}),
    "pos_cap_40": ({}, {"max_pos_pct": 0.40}),
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
        cfg = Config(start=a.start, **co)
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
