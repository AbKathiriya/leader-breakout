"""Daily episodic-pivot scan (run after the close): today's ≥15% gap-ups on ≥5× average volume that closed in the upper
half of their range, with a day range ≥ 2× ADR (filters out buyout announcements, which gap and then pin). Tomorrow's entry is a buy-stop at today's high, stopped at tomorrow's low (same max-stop rule).

  python -m engine.ep_scan              → data/ep_latest.json
"""
from __future__ import annotations

import contextlib
import io
import json

import numpy as np
import pandas as pd
import yfinance as yf

from .data import DATA, FIELDS, load_universe
from .framework import Params, first_target
from .scan import REGIME_TXT, _clean


def fetch(tickers: list[str], period: str = "1y", batch: int = 200) -> dict[str, pd.DataFrame]:
    frames = {}
    for k in range(0, len(tickers), batch):
        chunk = tickers[k:k + batch]
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            d = yf.download(chunk, period=period, auto_adjust=True, progress=False, group_by="ticker", threads=True)
        for t in chunk:
            try:
                frames[t] = d[t][FIELDS].dropna(subset=["Close"])
            except KeyError:
                pass
    return {f: pd.DataFrame({t: df[f] for t, df in frames.items()}) for f in FIELDS}


def daily_ep(gap_min: float = 0.15, vol_min: float = 5.0, min_range_adr: float = 2.0, min_mcap: float = 3e8) -> dict:
    p = Params()
    u = load_universe()
    names = sorted(set(u[u.mcap >= min_mcap].index) | {"SPY", "QQQ"})
    px = fetch(names)
    C, O, H, L, V = (px[f] for f in ("Close", "Open", "High", "Low", "Volume"))
    ema = lambda df, n: df.ewm(span=n, adjust=False, min_periods=n).mean()
    e8, e21, e50 = ema(C, 8), ema(C, 21), ema(C, 50)
    vol50 = V.rolling(50).mean()
    adr = 100 * ((H / L).rolling(20).mean() - 1)
    t = len(C) - 1
    now_et = pd.Timestamp.now(tz="America/New_York")
    if C.index[t].date() == now_et.date() and now_et.hour * 60 + now_et.minute < 16 * 60 + 15:
        t -= 1                                   # today's bar is still forming; use the last completed session
    idx = ["SPY", "QQQ"]
    above = [(C[idx].iloc[t] > e.iloc[t][idx]).all() for e in (e8, e21, e50)]
    regime = 2 if all(above) else (1 if above[2] else 0)
    gap = O.iloc[t] / C.iloc[t - 1] - 1
    volx = V.iloc[t] / vol50.iloc[t - 1]
    strong = C.iloc[t] >= L.iloc[t] + 0.5 * (H.iloc[t] - L.iloc[t])
    liquid = (C.iloc[t] >= 3) & (vol50.iloc[t - 1] * C.iloc[t] >= 5e6)
    rng = 100 * (H.iloc[t] - L.iloc[t]) / C.iloc[t]
    not_buyout = rng >= min_range_adr * adr.iloc[t - 1]     # buyouts gap and pin: range ≈ 0.1–0.2× ADR
    hit = gap.index[(gap >= gap_min) & (volx >= vol_min) & strong & liquid & not_buyout & gap.index.isin(u.index)]
    out = []
    for tk in sorted(hit, key=lambda x: -volx[x]):
        hi = float(H[tk].iloc[t])
        a = float(adr[tk].iloc[t])
        lim = min(p.max_risk_adr * a, p.max_risk_pct)
        trig = hi
        max_stop = trig * (1 - lim / 100)
        t1 = first_target(trig, max_stop, H[tk].to_numpy(dtype=float), t, p)
        out.append({
            "ticker": tk, "name": u.name.get(tk, ""), "sector": u.sector.get(tk, ""), "industry": u.industry.get(tk, ""),
            "close": float(C[tk].iloc[t]), "gap_pct": round(100 * float(gap[tk]), 1), "vol_x": round(float(volx[tk]), 1),
            "adr": a, "ema8": float(e8[tk].iloc[t]), "ema21": float(e21[tk].iloc[t]), "ema50": float(e50[tk].iloc[t]),
            "setup": {"ready": True, "trigger": trig, "max_stop": max_stop, "undercut": float(L[tk].iloc[t]), "t1": t1,
                      "rr_at_max_stop": (t1 - trig) / (trig - max_stop) if trig > max_stop else None},
            "score": float(volx[tk]) / 100,
            "kind": "EP",
            "bars": [[d.strftime("%Y-%m-%d"), float(O[tk][d]), float(H[tk][d]), float(L[tk][d]), float(C[tk][d]),
                      float(V[tk][d]), float(e8[tk][d]), float(e21[tk][d]), float(e50[tk][d])] for d in C.index[max(0, t - 159): t + 1]],
        })
    res = _clean({"as_of": str(C.index[t].date()), "regime": regime, "regime_text": REGIME_TXT[regime], "candidates": out})
    (DATA / "ep_latest.json").write_text(json.dumps(res))
    return res


if __name__ == "__main__":
    r = daily_ep()
    print(f"{r['as_of']} | {r['regime_text']} | EP candidates: {[c['ticker'] for c in r['candidates']]}")
