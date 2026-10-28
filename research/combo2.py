import sys, json
sys.path.insert(0, ".")
from dataclasses import replace
from engine.backtest import GROWTH_CASH, Config, run, metrics
from engine.data import load_prices, load_universe
from engine.framework import Params, atr_frame, indicators, regime_series
u = load_universe(); px = load_prices(sorted(set(u.index) | {"SPY", "QQQ", "IWM"}))
p0 = Params(pth_min=0.0001); ind, atr, reg = indicators(px, p0), atr_frame(px), regime_series(px, p0); spy = px["Close"]["SPY"]
K = ["CAGR %", "Max drawdown %", "Sharpe", "Trades", "Avg R", "Profit factor"]
def go(name, po={}, co={}):
    out = {"name": name}
    for tag, extra in (("all", {}), ("15-20", {"end": "2020-12-31"}), ("21-26", {"start": "2021-01-01"}), ("worst", {"entry_mode": "touch_worst"})):
        r = run(px, ind, atr, u, reg, replace(Params(), **po), Config(**{**GROWTH_CASH, **co, **extra}))
        m = metrics(r, spy); out[tag] = {k: m[k] for k in K}
    print(json.dumps(out), flush=True)
go("TT + PTH>=85%", {"trend_template": True, "pth_min": 0.85})
go("PTH>=80%", {"pth_min": 0.80})
go("PTH>=85% + pocket pivots", {"pth_min": 0.85}, {"pocket_pivot": True})
go("TT only (repeat w/ worst)", {"trend_template": True})
go("PTH>=85% (repeat w/ worst)", {"pth_min": 0.85})
