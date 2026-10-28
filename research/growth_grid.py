"""10k → 100k research: sizing / concentration / leverage grid on the same weekly watchlists.

For each config: full-period CAGR and max drawdown, then for every monthly start date the time to reach 10× and
whether the account first fell below 50% / 25% of its start ("ruin"). Rolling starts reuse one equity path, which is
valid because sizing is a fixed fraction of equity (scale-invariant apart from share rounding).
"""
from __future__ import annotations

import itertools
import json
import sys
import time
from dataclasses import replace

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
from engine.backtest import Config, metrics, run  # noqa: E402
from engine.data import DATA, load_prices, load_universe  # noqa: E402
from engine.framework import Params, atr_frame, indicators, regime_series  # noqa: E402


def rolling_stats(eq: pd.Series, target: float = 10.0, horizon_years: float = 5.0) -> dict:
    eq = eq[eq.index >= "2015-06-01"]
    starts = eq.resample("MS").first().dropna().index
    days, hit, ruin50, ruin25, mult3 = [], 0, 0, 0, []
    v = eq.to_numpy()
    idx = eq.index
    for st in starts:
        a = idx.searchsorted(st)
        if (idx[-1] - idx[a]).days < 365 * 3:
            continue
        end = idx.searchsorted(idx[a] + pd.Timedelta(days=365 * horizon_years))
        path = v[a:end] / v[a]
        reach = np.argmax(path >= target) if (path >= target).any() else None
        upto = path[: reach + 1] if reach is not None else path
        if upto.min() <= 0.5:
            ruin50 += 1
        if upto.min() <= 0.25:
            ruin25 += 1
        if reach is not None:
            hit += 1
            days.append((idx[a + reach] - idx[a]).days / 365.25)
        k3 = idx.searchsorted(idx[a] + pd.Timedelta(days=365 * 3))
        mult3.append(v[min(k3, len(v) - 1)] / v[a])
    n = len(mult3)
    return {
        "starts": n,
        f"hit {target:g}x within {horizon_years:g}y %": round(100 * hit / n, 1),
        "median years to 10x (when hit)": round(float(np.median(days)), 2) if days else None,
        "fell to 50% first %": round(100 * ruin50 / n, 1),
        "fell to 25% first %": round(100 * ruin25 / n, 1),
        "3y multiple p10/p50/p90": [round(float(np.percentile(mult3, q)), 2) for q in (10, 50, 90)],
    }


def main():
    u = load_universe()
    px = load_prices(sorted(set(u.index) | {"SPY", "QQQ", "IWM"}))
    p = Params()
    ind, atr, reg = indicators(px, p), atr_frame(px), regime_series(px, p)
    spy = px["Close"]["SPY"]
    cache: dict = {}
    t0 = time.time()
    run(px, ind, atr, u, reg, p, Config(capital=10_000), watch_cache=cache)
    print(f"watchlists cached in {time.time() - t0:.0f}s ({len(cache)} weeks)", flush=True)

    grid = []
    for risk, maxpos, cap, lev in itertools.product((0.02, 0.05, 0.10), (1, 2, 3, 5, 8), (0.25, 1.0, 2.0), (1.0, 2.0)):
        if cap > lev:          # a position can't exceed buying power
            continue
        grid.append(dict(risk_pct=risk, max_positions=maxpos, max_pos_pct=cap, leverage=lev))
    out = []
    for g in grid:
        cfg = Config(capital=10_000, **g)
        res = run(px, ind, atr, u, reg, p, cfg, watch_cache=cache)
        m = metrics(res, spy)
        rs = rolling_stats(res["curve"]["equity"])
        row = {**g, **{k: m[k] for k in ("CAGR %", "Max drawdown %", "Sharpe", "Trades", "Win rate %", "Avg R")}, **rs}
        out.append(row)
        print(json.dumps(row), flush=True)
    pd.DataFrame(out).to_csv(DATA / "growth_grid.csv", index=False)


if __name__ == "__main__":
    main()
