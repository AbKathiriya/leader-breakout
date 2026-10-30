import json, sys
sys.path.insert(0, ".")
import pandas as pd
from engine.backtest import GROWTH_CASH, Config, run
from engine.data import DATA, load_prices, load_universe
from engine.framework import Params, atr_frame, indicators, regime_series
u = load_universe(); px = load_prices(sorted(set(u.index) | {"SPY", "QQQ", "IWM"}))
p0 = Params(); ind, atr, reg = indicators(px, p0), atr_frame(px), regime_series(px, p0)
print("last bar", px["Close"].index[-1].date())
r = run(px, ind, atr, u, reg, p0, Config(**{**GROWTH_CASH, "ep_day1": True, "ep1_gap": 0.10, "start": "2025-10-01"}))
tr = r["trades"]
O, C = px["Open"], px["Close"]
rows = []
for _, t in tr.iterrows():
    d = pd.Timestamp(t.entry_date)
    if d < pd.Timestamp("2026-04-01"):
        continue
    k = C.index.get_loc(d)
    gap = O[t.ticker].iloc[k] / C[t.ticker].iloc[k - 1] - 1
    rows.append({**{c: t[c] for c in ["ticker", "kind", "entry_date", "exit_date", "entry", "stop0", "R", "ret_pct"]},
                 "day1": bool(gap >= 0.10), "open": float(O[t.ticker].iloc[k]), "gap": round(float(gap), 3),
                 "same_day_stop": "stop_same_day" in str(t.exits), "exits": str(t.exits)})
df = pd.DataFrame(rows); df.to_csv(DATA / "ep_day1_trades.csv", index=False)
print(df[["ticker", "kind", "entry_date", "day1", "gap", "entry", "stop0", "R", "same_day_stop"]].to_string())
