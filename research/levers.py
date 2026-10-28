import sys, json
sys.path.insert(0, ".")
from dataclasses import replace
import numpy as np, pandas as pd
from engine.backtest import Config, run, metrics
from engine.data import DATA, load_prices, load_universe
from engine.framework import Params, atr_frame, indicators, regime_series
from research.growth_grid import rolling_stats
u = load_universe(); px = load_prices(sorted(set(u.index) | {"SPY", "QQQ", "IWM"}))
p0 = Params(); ind, atr, reg = indicators(px, p0), atr_frame(px), regime_series(px, p0); spy = px["Close"]["SPY"]
AGG = dict(capital=10_000, risk_pct=0.05, max_positions=2, max_pos_pct=2.0, leverage=2.0)
K = ["CAGR %", "Max drawdown %", "Sharpe", "Trades", "Win rate %", "Avg R", "Exposure % (days with a position)"]
def go(name, po={}, co={}, save=False):
    r = run(px, ind, atr, u, reg, replace(p0, **po), Config(**{**AGG, **co}))
    m = metrics(r, spy); rs = rolling_stats(r["curve"]["equity"])
    row = {"name": name, **{k: m[k] for k in K}, **rs}; print(json.dumps(row), flush=True)
    if save:
        r["curve"].to_csv(DATA / "agg_curve.csv"); r["trades"].to_csv(DATA / "agg_trades.csv", index=False)
    return r
r = go("A concentrated 2x margin", save=True)
go("A, cash account (no margin, 100%)", co={"leverage": 1.0, "max_pos_pct": 1.0})
go("A, 1 slot", co={"max_positions": 1})
go("B top 25 industries", po={"top_industries": 25})
go("C no volume profile", po={"volume_profile": False})
go("D no regime filter", co={"regime_filter": False})
go("E optimistic entry", co={"entry_mode": "touch_opt"})
go("F worst-case entry", co={"entry_mode": "touch_worst"})
go("G 2015-2020 only", co={"end": "2020-12-31"})
go("H 2021-2026 only", co={"start": "2021-01-01"})
eq = r["curve"]["equity"]
print("yearly:", (eq.groupby(eq.index.year).last() / eq.groupby(eq.index.year).last().shift(1).fillna(eq.iloc[0]) - 1).round(3).to_dict())
