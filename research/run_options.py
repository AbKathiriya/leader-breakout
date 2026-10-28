import sys, json, itertools
sys.path.insert(0, ".")
import pandas as pd
from engine.backtest import Config, run, metrics
from engine.data import DATA, load_prices, load_universe
from engine.framework import Params, atr_frame, indicators, regime_series
from research.options_sim import simulate
from research.growth_grid import rolling_stats
u = load_universe(); px = load_prices(sorted(set(u.index) | {"SPY", "QQQ", "IWM"}))
p = Params(); ind, atr, reg = indicators(px, p), atr_frame(px), regime_series(px, p)
closes = px["Close"].astype(float)
rows = []
for maxpos in (2, 3, 5):
    # trade list where only the slot count limits which setups are taken (cash never binds)
    res = run(px, ind, atr, u, reg, p, Config(capital=10_000, max_positions=maxpos, max_pos_pct=50, leverage=50, risk_pct=0.02, margin_rate=0))
    tr = res["trades"]
    tr.to_csv(DATA / f"trades_slots{maxpos}.csv", index=False)
    for risk, ivm in itertools.product((0.02, 0.05, 0.10), (1.0, 1.3)):
        curve, ot = simulate(tr, closes, capital=10_000, risk_pct=risk, iv_mult=ivm)
        yrs = (curve.index[-1] - curve.index[0]).days / 365.25
        dd = (curve / curve.cummax() - 1).min()
        row = {"slots": maxpos, "risk": risk, "iv_mult": ivm, "trades": len(ot), "final": round(curve.iloc[-1]),
               "CAGR %": round(100 * ((curve.iloc[-1] / curve.iloc[0]) ** (1 / yrs) - 1), 1),
               "maxDD %": round(100 * dd, 1), "avg R": round(ot.R.mean(), 2) if len(ot) else None,
               "median premium % equity": round(100 * ot.premium_pct_equity.median(), 1) if len(ot) else None,
               **rolling_stats(curve)}
        rows.append(row); print(json.dumps(row), flush=True)
pd.DataFrame(rows).to_csv(DATA / "options_grid.csv", index=False)
