import sys, json
sys.path.insert(0, ".")
import pandas as pd, numpy as np
from engine.backtest import Config, run, metrics, yearly
from engine.data import DATA, load_prices, load_universe
from engine.framework import Params, atr_frame, indicators, regime_series
u = load_universe(); px = load_prices(sorted(set(u.index) | {"SPY", "QQQ", "IWM"}))
p0 = Params(); ind, atr, reg = indicators(px, p0), atr_frame(px), regime_series(px, p0); spy = px["Close"]["SPY"]
G = dict(capital=10_000, risk_pct=0.05, max_positions=2, max_pos_pct=1.0, leverage=1.0, ep=True, ep_gap=0.15, ep_vol=5.0,
         use_undercut=False, ep_min_range_adr=2.0)
cache = {}
def months_to(rets, dep, start=10_000, goal=100_000):
    e = start
    for k, x in enumerate(rets, 1):
        e = e * (1 + x) + dep
        if e >= goal: return k
    return None
for name, co in [("growth, idle cash", {}), ("idle in SPY (risk-on/caution only)", {"idle": "SPY"}),
                 ("idle in QQQ (risk-on/caution only)", {"idle": "QQQ"}), ("idle in SPY always", {"idle": "SPY", "idle_regime": False})]:
    r = run(px, ind, atr, u, reg, p0, Config(**{**G, **co}), watch_cache=cache)
    m = metrics(r, spy)
    nav = r["curve"]["nav"]; mr = nav.resample("ME").last().pct_change().dropna()
    res = {}
    for dep in (1000, 1500, 2000):
        hits = [months_to(mr.iloc[s:].values, dep) for s in range(len(mr) - 36)]
        hits = [h for h in hits if h]
        res[dep] = [round(np.percentile(hits, q) / 12, 1) for q in (25, 50, 75)]
    print(json.dumps({"name": name, **{k: m[k] for k in ("CAGR %", "Max drawdown %", "Sharpe", "Trades")}, "yrs to 100k p25/50/75 by deposit": res}), flush=True)
    if co.get("idle") == "SPY" and co.get("idle_regime", True):
        r["curve"].to_csv(DATA / "growth_curve.csv"); r["trades"].to_csv(DATA / "growth_trades.csv", index=False)
        print(yearly(r, spy).to_string(), flush=True)
