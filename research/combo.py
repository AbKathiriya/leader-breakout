import sys, json
sys.path.insert(0, ".")
import pandas as pd
from engine.backtest import Config, run, metrics, yearly
from engine.data import DATA, load_prices, load_universe
from engine.framework import Params, atr_frame, indicators, regime_series
from research.growth_grid import rolling_stats
u = load_universe(); px = load_prices(sorted(set(u.index) | {"SPY", "QQQ", "IWM"}))
p0 = Params(); ind, atr, reg = indicators(px, p0), atr_frame(px), regime_series(px, p0); spy = px["Close"]["SPY"]
G = dict(capital=10_000, risk_pct=0.05, max_positions=2, max_pos_pct=1.0, leverage=1.0, ep=True, ep_gap=0.15, ep_vol=5.0, use_undercut=False, ep_min_range_adr=float(sys.argv[1]) if len(sys.argv) > 1 else 2.0)
cache = {}
K = ["CAGR %", "Max drawdown %", "Sharpe", "Trades", "Win rate %", "Avg R", "Profit factor", "Exposure % (days with a position)"]
def go(name, co={}, save=False):
    r = run(px, ind, atr, u, reg, p0, Config(**{**G, **co}), watch_cache=cache)
    m = metrics(r, spy); tr = r["trades"]
    by = tr.groupby("kind").agg(n=("R", "size"), avgR=("R", "mean")).round(2).to_dict("index")
    rs = rolling_stats(r["curve"]["nav"], target=3.0)
    print(json.dumps({"name": name, **{k: m[k] for k in K}, "by_kind": by, "3y": rs["3y multiple p10/p50/p90"]}), flush=True)
    if save:
        r["curve"].to_csv(DATA / "growth_curve.csv"); tr.to_csv(DATA / "growth_trades.csv", index=False)
        print(yearly(r, spy).to_string(), flush=True)
    return r
go("GROWTH: EP15/5x, no undercut", save=True)
go("  2015-2020", {"end": "2020-12-31"})
go("  2021-2026", {"start": "2021-01-01"})
go("  worst-case entry", {"entry_mode": "touch_worst"})
go("  optimistic entry", {"entry_mode": "touch_opt"})
go("  breakouts only (no EP)", {"ep": False})
go("  EP 20% / 5x", {"ep_gap": 0.20})
go("  EP 15% / 8x", {"ep_vol": 8.0})
