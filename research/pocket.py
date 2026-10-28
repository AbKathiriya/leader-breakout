import sys, json
sys.path.insert(0, ".")
from engine.backtest import GROWTH_CASH, Config, run, metrics
from engine.data import load_prices, load_universe
from engine.framework import Params, atr_frame, indicators, regime_series
u = load_universe(); px = load_prices(sorted(set(u.index) | {"SPY", "QQQ", "IWM"}))
p0 = Params(); ind, atr, reg = indicators(px, p0), atr_frame(px), regime_series(px, p0); spy = px["Close"]["SPY"]
cache = {}
K = ["CAGR %", "Max drawdown %", "Sharpe", "Trades", "Avg R", "Profit factor"]
for name, co in [("pocket pivot early entries", {"pocket_pivot": True}),
                 ("  2015-2020", {"pocket_pivot": True, "end": "2020-12-31"}),
                 ("  2021-2026", {"pocket_pivot": True, "start": "2021-01-01"})]:
    r = run(px, ind, atr, u, reg, p0, Config(**{**GROWTH_CASH, **co}), watch_cache=cache)
    m = metrics(r, spy); tr = r["trades"]
    by = tr.groupby("kind").agg(n=("R", "size"), avgR=("R", "mean")).round(2).to_dict("index")
    print(json.dumps({"name": name, **{k: m[k] for k in K}, "by_kind": by}), flush=True)
