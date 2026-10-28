"""Ideas from Minervini / Stockbee / George-Hwang / Qullamaggie, each tested against growth mode."""
import sys, json
sys.path.insert(0, ".")
from dataclasses import replace
from engine.backtest import GROWTH_CASH, Config, run, metrics
from engine.data import load_prices, load_universe
from engine.framework import Params, atr_frame, indicators, regime_series
u = load_universe(); px = load_prices(sorted(set(u.index) | {"SPY", "QQQ", "IWM"}))
p0 = Params(trend_template=False)
pX = replace(p0, pth_min=0.0001)   # forces the extra indicators to be computed once
ind, atr, reg = indicators(px, pX), atr_frame(px), regime_series(px, p0); spy = px["Close"]["SPY"]
K = ["CAGR %", "Max drawdown %", "Sharpe", "Trades", "Win rate %", "Avg R", "Profit factor"]
def go(name, po={}, co={}, start=None, end=None):
    out = {"name": name}
    for tag, extra in (("all", {}), ("15-20", {"end": "2020-12-31"}), ("21-26", {"start": "2021-01-01"})):
        r = run(px, ind, atr, u, reg, replace(p0, **po), Config(**{**GROWTH_CASH, **co, **extra}))
        m = metrics(r, spy)
        out[tag] = {k: m[k] for k in K} if tag == "all" else {"CAGR %": m["CAGR %"], "Max drawdown %": m["Max drawdown %"]}
    print(json.dumps(out), flush=True)
go("baseline growth mode")
go("Minervini trend template", po={"trend_template": True})
go("52w-high proximity >= 85%", po={"pth_min": 0.85})
go("52w-high proximity >= 90%", po={"pth_min": 0.90})
go("not up 3 days in a row", po={"no_3_up": True})
go("EP price >= $5", co={"ep_min_price": 5.0})
go("EP neglected: 60d return <= +20%", co={"ep_max_prior": 0.20})
go("EP neglected: 60d return <= +50%", co={"ep_max_prior": 0.50})
