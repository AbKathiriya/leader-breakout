"""Earnings-date rules and EP priority, with historical earnings dates from Yahoo (cached in data/earnings.json).

Iterates: run → fetch dates for any traded ticker not cached → rerun, so every trade the rules could touch has dates.
"""
import json, sys, time, contextlib, io
sys.path.insert(0, ".")
from concurrent.futures import ThreadPoolExecutor
import numpy as np, pandas as pd, yfinance as yf
from engine.backtest import GROWTH_CASH, Config, metrics, run
from engine.data import DATA, load_prices, load_universe
from engine.framework import Params, atr_frame, indicators, regime_series

CACHE = DATA / "earnings.json"
cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}

def fetch(t):
    for a in range(3):
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                d = yf.Ticker(t).get_earnings_dates(limit=60)
            return t, [] if d is None else [x.isoformat() for x in d.index]
        except Exception:
            time.sleep(2 + 3 * a)
    return t, None

def ensure(tickers):
    need = [t for t in tickers if t not in cache]
    if not need:
        return 0
    with ThreadPoolExecutor(6) as ex:
        for t, v in ex.map(fetch, need):
            if v is not None:
                cache[t] = v
    CACHE.write_text(json.dumps(cache))
    return len(need)

u = load_universe(); px = load_prices(sorted(set(u.index) | {"SPY", "QQQ", "IWM"}))
p0 = Params(); ind, atr, reg = indicators(px, p0), atr_frame(px), regime_series(px, p0); spy = px["Close"]["SPY"]
dates = px["Close"].index

def gap_idx(stamps):
    out = set()
    for s_ in stamps:
        ts = pd.Timestamp(s_)
        day = pd.Timestamp(ts.date())
        k = dates.searchsorted(day)
        if k >= len(dates):
            continue
        same_day = dates[k] == day
        before_open = (ts.hour, ts.minute) < (9, 30)
        out.add(k if (not same_day or before_open) else k + 1)
    return np.array(sorted(x for x in out if x < len(dates)))

def earn_map():
    return {t: gap_idx(v) for t, v in cache.items()}

K = ["CAGR %", "Max drawdown %", "Sharpe", "Trades", "Avg R", "Profit factor"]
VARS = {
    "base": {},
    "ep_first": {"ep_first": True},
    "block2": {"earn_block": 2},
    "block5": {"earn_block": 5},
    "block10": {"earn_block": 10},
    "exit_half": {"earn_exit": "half"},
    "exit_all": {"earn_exit": "all"},
    "block2+exit_half": {"earn_block": 2, "earn_exit": "half"},
    "block5+exit_all": {"earn_block": 5, "earn_exit": "all"},
    "ep_first+block2+exit_half": {"ep_first": True, "earn_block": 2, "earn_exit": "half"},
}
seen = set(pd.read_csv(DATA / "bt_trades.csv").ticker) | set(cache)
for rnd in range(0 if "--no-rounds" in sys.argv else 4):
    n = ensure(sorted(seen))
    print(f"round {rnd}: fetched {n}, cached {len(cache)}", flush=True)
    em, new = earn_map(), set()
    for name, co in VARS.items():
        r = run(px, ind, atr, u, reg, p0, Config(**{**GROWTH_CASH, "earn": em, **co}))
        new |= set(r["trades"].ticker)
    if new <= seen:
        break
    seen |= new

em = earn_map()
missing = [t for t in seen if not len(em.get(t, []))]
print("tickers with no earnings dates:", len(missing), missing[:20], flush=True)
SKIP = set(a for a in sys.argv[1:] if not a.startswith("--"))
for name, co in VARS.items():
    if name in SKIP:
        continue
    for span, c2 in [("", {}), ("  15-20", {"end": "2020-12-31"}), ("  21-26", {"start": "2021-01-01"}),
                     ("  worst-entry", {"entry_mode": "touch_worst"})]:
        r = run(px, ind, atr, u, reg, p0, Config(**{**GROWTH_CASH, "earn": em, **co, **c2}))
        m = metrics(r, spy); tr = r["trades"]
        extra = {}
        if span == "":
            ex = tr.exits.astype(str)
            extra = {"stop_gap": int(ex.str.contains("stop_gap").sum()),
                     "gap_R": round(float(tr.R[ex.str.contains("stop_gap")].sum()), 1),
                     "pre_earn": int(ex.str.contains("pre_earnings").sum()), "worst_R": round(float(tr.R.min()), 2)}
        print(json.dumps({"name": name + span, **{k: m[k] for k in K}, **extra}), flush=True)
