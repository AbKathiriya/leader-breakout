"""Ideas from the user's Reddit synthesis (Oct 29) not already tested: 1-month RS leadership, SMA10>20 index regime,
fixed 2R / 2.5R first target, same-day EP opening-range entry."""
import json, sys
sys.path.insert(0, ".")
import numpy as np, pandas as pd
from dataclasses import replace
from engine.backtest import GROWTH_CASH, Config, metrics, run
from engine.data import load_prices, load_universe
from engine.framework import Params, atr_frame, indicators, regime_series

u = load_universe(); px = load_prices(sorted(set(u.index) | {"SPY", "QQQ", "IWM"}))
p0 = Params(); ind, atr, reg = indicators(px, p0), atr_frame(px), regime_series(px, p0); spy = px["Close"]["SPY"]
C = px["Close"]
ok_hist = ind["rs"].notna()
ind_rs21 = {**ind, "rs": (C / C.shift(21) - 1).where(ok_hist)}
ind_blend = {**ind, "rs": (0.5 * (C / C.shift(21) - 1) + 0.5 * ind["rs"]).where(ok_hist)}
q = C["QQQ"]; s_ = C["SPY"]
up = (q.rolling(10).mean() > q.rolling(20).mean()) & (s_.rolling(10).mean() > s_.rolling(20).mean())
reg_sma = up.astype(int) * 2
reg_and = reg.where(up, 0)

VARS = {
    "base": (ind, reg, {}, {}),
    "RS 1-month": (ind_rs21, reg, {}, {}),
    "RS blend 1m + composite": (ind_blend, reg, {}, {}),
    "regime SMA10>20 (replace)": (ind, reg_sma, {}, {}),
    "regime current AND SMA10>20": (ind, reg_and, {}, {}),
    "T1 fixed 2R": (ind, reg, {"t1_mode": "r", "t1_r": 2.0}, {}),
    "T1 fixed 2.5R": (ind, reg, {"t1_mode": "r", "t1_r": 2.5}, {}),
    "EP day-1 ORB gap10 (+day2)": (ind, reg, {}, {"ep_day1": True, "ep1_gap": 0.10}),
    "EP day-1 ORB gap15 (+day2)": (ind, reg, {}, {"ep_day1": True, "ep1_gap": 0.15}),
    "EP day-1 ORB gap15 only": (ind, reg, {}, {"ep_day1": True, "ep1_gap": 0.15, "ep": False}),
}
only = [a for a in sys.argv[1:]]
K = ["CAGR %", "Max drawdown %", "Sharpe", "Trades", "Avg R", "Profit factor"]
for name, (ind_, reg_, po, co) in VARS.items():
    if only and name not in only:
        continue
    for span, c2 in [("", {}), ("  15-20", {"end": "2020-12-31"}), ("  21-26", {"start": "2021-01-01"})]:
        r = run(px, ind_, atr, u, reg_, replace(p0, **po), Config(**{**GROWTH_CASH, **co, **c2}))
        m = metrics(r, spy); tr = r["trades"]
        extra = {}
        if span == "" and len(tr):
            top = tr.R.quantile(0.9)
            extra = {"winrate": round(100 * (tr.pnl > 0).mean(), 1), "avgR_wo_top10pct": round(float(tr.R[tr.R < top].mean()), 2),
                     "by_kind": tr.groupby("kind").R.agg(["size", "mean"]).round(2).to_dict("index")}
        print(json.dumps({"name": name + span, **{k: round(m[k], 2) for k in K}, **extra}), flush=True)
