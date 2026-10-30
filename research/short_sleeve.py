"""Risk-off sleeve without margin: what idle cash holds when SPY/QQQ are below trend (regime 0)."""
import json, sys
sys.path.insert(0, ".")
import pandas as pd
from engine.backtest import GROWTH_CASH, Config, metrics, run
from engine.data import load_prices, load_universe
from engine.framework import Params, atr_frame, indicators, regime_series
u = load_universe(); px = load_prices(sorted(set(u.index) | {"SPY", "QQQ", "IWM"}))
inv = load_prices(["SH", "PSQ", "SDS", "SQQQ"], cache="prices_inverse.parquet")
for f in px:
    px[f] = pd.concat([px[f], inv[f].reindex(px[f].index)], axis=1)
p0 = Params(); ind, atr, reg = indicators(px, p0), atr_frame(px), regime_series(px, p0); spy = px["Close"]["SPY"]
cache = {}
K = ["CAGR %", "Max drawdown %", "Sharpe", "Trades"]
for name, co in [("current: SPY always", {}), ("cash when risk-off", {"idle_off": "cash"}),
                 ("SH (-1x SPY) when risk-off", {"idle_off": "SH"}), ("PSQ (-1x QQQ) when risk-off", {"idle_off": "PSQ"}),
                 ("SDS (-2x SPY) when risk-off", {"idle_off": "SDS"}), ("SQQQ (-3x QQQ) when risk-off", {"idle_off": "SQQQ"})]:
    out = {"name": name}
    for span, c2 in [("all", {}), ("15-20", {"end": "2020-12-31"}), ("21-26", {"start": "2021-01-01"})]:
        r = run(px, ind, atr, u, reg, p0, Config(**{**GROWTH_CASH, **co, **c2}), watch_cache=cache.setdefault(span, {}))
        m = metrics(r, spy); out[span] = {k: round(m[k], 2) for k in K}
    print(json.dumps(out), flush=True)
