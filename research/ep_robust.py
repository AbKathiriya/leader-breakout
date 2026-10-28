import sys, json
sys.path.insert(0, ".")
from dataclasses import replace
import pandas as pd
from engine.backtest import Config, run, metrics
from engine.data import DATA, load_prices, load_universe
from engine.framework import Params, atr_frame, indicators, regime_series
from research.growth_grid import rolling_stats
u = load_universe(); px = load_prices(sorted(set(u.index) | {"SPY", "QQQ", "IWM"}))
p0 = Params(); ind, atr, reg = indicators(px, p0), atr_frame(px), regime_series(px, p0); spy = px["Close"]["SPY"]
CASH = dict(capital=10_000, risk_pct=0.05, max_positions=2, max_pos_pct=1.0, leverage=1.0, ep=True)
cache = {}
K = ["CAGR %", "Max drawdown %", "Sharpe", "Trades", "Win rate %", "Avg R", "Profit factor"]
def go(name, co={}, save=False):
    r = run(px, ind, atr, u, reg, p0, Config(**{**CASH, **co}), watch_cache=cache)
    m = metrics(r, spy); tr = r["trades"]
    by = tr.groupby("kind").agg(n=("R", "size"), avgR=("R", "mean"), pnl=("pnl", "sum")).round(2).to_dict("index") if len(tr) else {}
    print(json.dumps({"name": name, **{k: m[k] for k in K}, "by_kind": by}), flush=True)
    if save:
        r["curve"].to_csv(DATA / "growth_curve.csv"); tr.to_csv(DATA / "growth_trades.csv", index=False)
    return r
go("EP default (gap10 vol3)", save=True)
go("EP 2015-2020", {"end": "2020-12-31"})
go("EP 2021-2026", {"start": "2021-01-01"})
go("EP worst-case entry", {"entry_mode": "touch_worst"})
go("EP optimistic entry", {"entry_mode": "touch_opt"})
go("EP gap 7%", {"ep_gap": 0.07})
go("EP gap 15%", {"ep_gap": 0.15})
go("EP vol 2x", {"ep_vol": 2.0})
go("EP vol 5x", {"ep_vol": 5.0})
go("EP no regime filter", {"regime_filter": False})
go("EP with $1.5k/month deposits", {"contribution": 1500})
