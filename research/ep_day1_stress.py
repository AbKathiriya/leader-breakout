"""Stress the same-day EP entry: worst-case and pessimistic intraday paths, wider slippage, later ORB trigger, gap 15%."""
import json, sys
sys.path.insert(0, ".")
from engine.backtest import GROWTH_CASH, Config, metrics, run
from engine.data import load_prices, load_universe
from engine.framework import Params, atr_frame, indicators, regime_series
u = load_universe(); px = load_prices(sorted(set(u.index) | {"SPY", "QQQ", "IWM"}))
p0 = Params(); ind, atr, reg = indicators(px, p0), atr_frame(px), regime_series(px, p0); spy = px["Close"]["SPY"]
D1 = {"ep_day1": True, "ep1_gap": 0.10}
VARS = {
    "day1 gap10 fixed stop, worst ordering": {**D1, "ep1_stop": "max"},
    "  15-20": {**D1, "ep1_stop": "max", "end": "2020-12-31"},
    "  21-26": {**D1, "ep1_stop": "max", "start": "2021-01-01"},
    "day1 gap15 fixed stop, worst ordering": {**D1, "ep1_gap": 0.15, "ep1_stop": "max"},
    "day1 gap10 fixed stop, worst ordering, slippage 0.5%": {**D1, "ep1_stop": "max", "slippage": 0.005},
    "base worst-entry (reference)": {"entry_mode": "touch_worst"},
    "day1 gap10 worst-entry": {**D1, "entry_mode": "touch_worst"},
    "day1 gap10 pessimistic (close<entry = stopped)": {**D1, "entry_mode": "touch_pess"},
    "day1 gap10 slippage 0.5%": {**D1, "slippage": 0.005},
    "day1 gap10 ORB +2%": {**D1, "ep1_orb": 0.02},
    "day1 gap10 ORB +2% worst-entry": {**D1, "ep1_orb": 0.02, "entry_mode": "touch_worst"},
    "day1 gap15 worst-entry": {**D1, "ep1_gap": 0.15, "entry_mode": "touch_worst"},
}
only = sys.argv[1:]
for name, co in VARS.items():
    if only and name not in only:
        continue
    r = run(px, ind, atr, u, reg, p0, Config(**{**GROWTH_CASH, **co}))
    m = metrics(r, spy); tr = r["trades"]
    print(json.dumps({"name": name, **{k: round(m[k], 2) for k in ["CAGR %", "Max drawdown %", "Sharpe", "Trades", "Avg R", "Profit factor"]},
                      "by_kind": tr.groupby("kind").R.agg(["size", "mean"]).round(2).to_dict("index") if len(tr) else {}}), flush=True)
