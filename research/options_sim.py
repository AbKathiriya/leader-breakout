"""Approximate the same trades done with calls instead of shares (no historical option data → Black-Scholes repricing).

Per trade: buy a call with ~0.70 delta and `dte` days to expiry at the entry price; IV = iv_mult × 20-day realized vol
(floored); pay `spread` (fraction of mid) on every buy and sell; roll to a fresh contract when < `roll_dte` days remain.
Each exit leg of the share trade (stop / T1 / EMA trims / final exit, same dates and prices) sells the same fraction of
contracts. Size so that a fill at the stop loses `risk_pct` of equity. Equity is marked to model daily.

Caveats: no IV crush/expansion, no skew, no early-exercise, fills at modelled mid ± spread. Breakout days often see IV
rise slightly, then fall; gaps through the stop are captured through the reprice at the gap price.
"""
from __future__ import annotations

import ast
import math
import sys
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
from engine.data import DATA  # noqa: E402

SQ2 = math.sqrt(2.0)


def ncdf(x):
    return 0.5 * (1 + math.erf(x / SQ2))


def bs_call(S, K, T, sig, r=0.04):
    if T <= 0:
        return max(S - K, 0.0)
    v = sig * math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sig * sig) * T) / v
    return S * ncdf(d1) - K * math.exp(-r * T) * ncdf(d1 - v)


def strike_for_delta(S, T, sig, delta=0.70, r=0.04):
    from statistics import NormalDist
    d1 = NormalDist().inv_cdf(delta)
    return S * math.exp(-(d1 * sig * math.sqrt(T) - (r + 0.5 * sig * sig) * T))


@dataclass
class OptPos:
    ticker: str
    legs: list           # [(date, why, price, frac)]
    K: float
    expiry: pd.Timestamp
    sig: float
    contracts: float     # in "per original contract" units after rolls → multiplier
    cost: float
    risk: float
    prem_pct: float = 0.0
    proceeds: float = 0.0
    frac_left: float = 1.0
    log: list = field(default_factory=list)


def simulate(trades: pd.DataFrame, closes: pd.DataFrame, capital=10_000.0, risk_pct=0.05, dte=90, roll_dte=30,
             iv_mult=1.2, iv_floor=0.30, spread=0.03, max_premium_frac=1.0, delta=0.70):
    rets = np.log(closes).diff()
    rv20 = rets.rolling(20).std() * math.sqrt(252)
    dates = closes.index
    evs = {}
    for _, t in trades.iterrows():
        legs = ast.literal_eval(t.exits.replace("np.float64(", "(")) if isinstance(t.exits, str) else t.exits
        evs.setdefault(pd.Timestamp(t.entry_date), []).append(t.to_dict() | {"legs": legs})
    cash, eq_curve, out = capital, [], []
    open_: list[OptPos] = []
    for d in dates[dates >= pd.Timestamp(trades.entry_date.min())]:
        # exits / rolls on existing positions
        keep = []
        for p in open_:
            S = closes.at[d, p.ticker]
            for (ld, why, price, frac) in [l for l in p.legs if pd.Timestamp(l[0]) == d]:
                T = max((p.expiry - d).days, 1) / 365
                val = bs_call(price, p.K, T, p.sig) * (1 - spread) * 100 * p.contracts * frac
                cash += val
                p.proceeds += val
                p.frac_left -= frac
                p.log.append((str(d.date()), why, round(price, 2), round(val, 0)))
            if p.frac_left > 1e-6 and np.isfinite(S) and (p.expiry - d).days < roll_dte:
                T = max((p.expiry - d).days, 1) / 365
                old = bs_call(S, p.K, T, p.sig) * (1 - spread)
                sig = max(iv_mult * float(rv20.at[d, p.ticker]), iv_floor) if np.isfinite(rv20.at[d, p.ticker]) else p.sig
                T2 = dte / 365
                K2 = strike_for_delta(S, T2, sig, delta)
                new = bs_call(S, K2, T2, sig) * (1 + spread)
                p.contracts *= old / new
                p.K, p.expiry, p.sig = K2, d + pd.Timedelta(days=dte), sig
                p.log.append((str(d.date()), "roll", round(S, 2), None))
            if p.frac_left > 1e-6:
                keep.append(p)
            else:
                pnl = p.proceeds - p.cost
                out.append({"ticker": p.ticker, "entry_date": p.legs[0][0], "pnl": pnl, "R": pnl / p.risk,
                            "premium_pct_equity": p.prem_pct, "log": p.log})
        open_ = keep
        # mark-to-model equity
        mv = 0.0
        for p in open_:
            S = closes.at[d, p.ticker]
            T = max((p.expiry - d).days, 1) / 365
            if np.isfinite(S):
                mv += bs_call(S, p.K, T, p.sig) * (1 - spread) * 100 * p.contracts * p.frac_left
        equity = cash + mv
        # new entries today
        for t in evs.get(d, []):
            S0, stop = float(t["entry"]), float(t["stop0"])
            rv = rv20.at[d, t["ticker"]]
            sig = max(iv_mult * float(rv), iv_floor) if np.isfinite(rv) else iv_floor
            T = dte / 365
            K = strike_for_delta(S0, T, sig, delta)
            prem = bs_call(S0, K, T, sig) * (1 + spread) * 100
            at_stop = bs_call(stop, K, T - 1 / 365, sig) * (1 - spread) * 100
            loss_per = max(prem - at_stop, 1e-6)
            n = equity * risk_pct / loss_per
            n = math.floor(min(n, max_premium_frac * equity / prem, cash / prem))
            if n * prem < 50 or n < 1:
                continue
            cost = n * prem
            cash -= cost
            legs = [(l[0], l[1], float(l[2]), l[3] / float(t["shares"])) for l in t["legs"][1:]]
            same_day = [l for l in legs if pd.Timestamp(l[0]) == d]
            p = OptPos(t["ticker"], legs, K, d + pd.Timedelta(days=dte), sig, n, cost, n * loss_per,
                       prem_pct=cost / equity)
            for (ld, why, price, frac) in same_day:
                val = bs_call(price, K, T, sig) * (1 - spread) * 100 * p.contracts * frac
                cash += val
                p.proceeds += val
                p.frac_left -= frac
            if p.frac_left > 1e-6:
                open_.append(p)
            else:
                out.append({"ticker": p.ticker, "entry_date": str(d.date()), "pnl": p.proceeds - p.cost,
                            "R": (p.proceeds - p.cost) / p.risk, "premium_pct_equity": cost / equity, "log": []})
        eq_curve.append((d, equity))
    curve = pd.Series(dict(eq_curve)).sort_index()
    return curve, pd.DataFrame(out)
