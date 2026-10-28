"""List every breakout / EP trigger day (Jul–Oct 2026) with the daily bar and the bar-path model's verdict."""
import sys, json
sys.path.insert(0, ".")
import numpy as np, pandas as pd
from engine.backtest import Config, run, _ep_candidates, week_ends
from engine.data import DATA, load_prices, load_universe
from engine.framework import Params, atr_frame, indicators, regime_series
u = load_universe(); px = load_prices(sorted(set(u.index) | {"SPY", "QQQ", "IWM"}))
p = Params(); ind, atr, reg = indicators(px, p), atr_frame(px), regime_series(px, p)
cache = {}
run(px, ind, atr, u, reg, p, Config(start="2026-07-01", capital=1e9, max_positions=0), watch_cache=cache)
dates = px["Close"].index; cols = list(px["Close"].columns); tix = {t: j for j, t in enumerate(cols)}
O, H, L, C, V = (px[f].to_numpy(float) for f in ("Open", "High", "Low", "Close", "Volume"))
ADR, V50 = ind["adr"].to_numpy(float), ind["vol50"].to_numpy(float)
in_univ = np.array([t in u.index for t in cols])
cfg = Config(ep=True, ep_gap=0.15, ep_vol=5.0)
ev = []
we = sorted(cache)
for k, i0 in enumerate(we):
    i1 = we[k + 1] if k + 1 < len(we) else len(dates) - 1
    for s in cache[i0]:
        j = tix[s.ticker]
        for i in range(i0 + 1, i1 + 1):
            if H[i, j] > s.trigger:
                ev.append(("breakout", s.ticker, i, s.trigger)); break
for i in range(dates.searchsorted(pd.Timestamp("2026-07-01")), len(dates)):
    for s in _ep_candidates(i, O, H, L, C, V, V50, in_univ, cols, cfg):
        j = tix[s.ticker]
        if H[i, j] > s.trigger:
            ev.append(("ep", s.ticker, i, s.trigger))
out = []
for kind, t, i, trig in ev:
    j = tix[t]; o, h, l, c = O[i, j], H[i, j], L[i, j], C[i, j]
    entry = max(o, trig); lim = min(p.max_risk_adr * ADR[i - 1, j], p.max_risk_pct); ms = entry * (1 - lim / 100)
    if c >= o:
        model = "skip (low first, too wide)" if l < ms else "fill, survive"
    else:
        lod = min(o, entry)
        model = "skip (too wide at fill)" if lod < ms else ("fill, stopped same day" if l <= (lod if lod < entry * 0.9999 else ms) else "fill, survive")
    out.append({"kind": kind, "ticker": t, "date": str(dates[i].date()), "open": round(o, 2), "trigger": round(trig, 2),
                "max_stop": round(ms, 2), "low": round(l, 2), "high": round(h, 2), "close": round(c, 2), "model": model})
df = pd.DataFrame(out).sort_values("date"); df.to_csv(DATA / "trigger_events.csv", index=False)
print(len(df)); print(df.groupby(["kind", "model"]).size()); print(df[df.date >= "2026-08-01"].groupby("date").ticker.apply(list).to_string())
