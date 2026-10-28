"""Cash-only growth mode: test practitioner ideas one at a time against the same baseline."""
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
CASH = dict(capital=10_000, risk_pct=0.05, max_positions=2, max_pos_pct=1.0, leverage=1.0)
cache = {}
K = ["CAGR %", "Max drawdown %", "Sharpe", "Trades", "Win rate %", "Avg R", "Profit factor", "Exposure % (days with a position)"]
def go(name, po={}, co={}, use_cache=True):
    r = run(px, ind, atr, u, reg, replace(p0, **po), Config(**{**CASH, **co}), watch_cache=cache if use_cache else None)
    m = metrics(r, spy); rs = rolling_stats(r["curve"]["nav"], target=3.0, horizon_years=5)
    row = {"name": name, **{k: m[k] for k in K}, "3x in 5y %": rs["hit 3x within 5y %"],
           "3y mult p10/50/90": rs["3y multiple p10/p50/p90"]}
    print(json.dumps(row), flush=True); return r
go("0 baseline: 2 slots, 100%, cash")
go("1 priority by setup quality", co={"priority": "score"})
go("2 Qull exits: 1/2 after 4d, trail 10SMA", co={"exit_mode": "qull", "trail_sma": 10})
go("3 Qull exits: 1/2 after 4d, trail 20SMA", co={"exit_mode": "qull", "trail_sma": 20})
go("4 Qull exits: 1/3 after 4d, trail 20SMA", co={"exit_mode": "qull", "trail_sma": 20, "qull_frac": 0.33})
go("5 + episodic pivots", co={"ep": True})
go("6 3 slots at 50%", co={"max_positions": 3, "max_pos_pct": 0.5})
go("7 1 slot at 100%", co={"max_positions": 1})
go("8 RS top-24 universe (no groups)", co={"selection": "rs_only"}, use_cache=False)
go("9 Q stops up to 1 ADR", po={"max_risk_adr": 1.0, "max_risk_pct": 100.0}, use_cache=False)
