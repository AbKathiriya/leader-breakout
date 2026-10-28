"""Does adding ETFs to the breakout candidate list help growth mode?

ETFs have no Nasdaq industry, so they never enter the stock ranking. Here they get their own lane: each week the ETFs
that pass the same leader filters (price, volume, ADR, above 21/50 EMA, ≥85% of 52w high) are ranked by RS and the
top N are appended to (or put ahead of) the stock leaders, then go through the same base/entry/exit rules.
"""
import json
import sys

sys.path.insert(0, ".")
import numpy as np
import pandas as pd

import engine.backtest as bt
from engine.backtest import GROWTH_CASH, Config, metrics, run
from engine.data import load_prices, load_universe
from engine.framework import Params, atr_frame, indicators, regime_series

UNLEV = ("XLK XLF XLE XLV XLI XLY XLP XLU XLB XLRE XLC SMH SOXX IGV XBI IBB KRE KBE ITB XHB XRT XME XOP OIH GDX GDXJ "
         "SIL SLV GLD COPX URA TAN ICLN LIT ARKK ARKG KWEB FXI EWZ EWJ EWW INDA EEM EFA IWM DIA MDY IYT JETS HACK CIBR "
         "SKYY BOTZ FDN PBW PAVE ITA XAR BITO REMX SLX MOO").split()
LEV = "TQQQ SOXL TECL LABU TNA FAS NUGT JNUG UPRO SPXL GUSH ERX URTY CURE RETL DRN DFEN".split()

u = load_universe()
px = load_prices(sorted(set(u.index) | {"SPY", "QQQ", "IWM"}))
etf = load_prices(UNLEV + LEV, cache="prices_etf.parquet")
for f in px:
    add = etf[f].reindex(px[f].index)
    px[f] = pd.concat([px[f], add[[c for c in add.columns if c not in px[f].columns]]], axis=1)
p0 = Params()
ind, atr, reg = indicators(px, p0), atr_frame(px), regime_series(px, p0)
spy = px["Close"]["SPY"]
orig = bt.select_leaders


def lane(etfs, n, where, stocks=True, adr_min=None):
    def sel(d, universe, px_, ind_, p, ranks=None):
        lead = orig(d, universe, px_, ind_, p, ranks) if stocks else orig(d, universe, px_, ind_, p, ranks).iloc[:0]
        c = px_["Close"].loc[d, etfs]
        ok = ((c >= p.min_price) & (ind_["vol10"].loc[d, etfs] >= p.min_avg_vol10)
              & (ind_["adr"].loc[d, etfs] >= (p.min_adr if adr_min is None else adr_min))
              & (c > ind_["e2"].loc[d, etfs]) & (c > ind_["e3"].loc[d, etfs])
              & (ind_["pth"].loc[d, etfs] >= p.pth_min))
        rs_all = ind_["rs"].loc[d].dropna()
        e = ind_["rs"].loc[d, etfs][ok.fillna(False)].dropna().nlargest(n)
        if not len(e):
            return lead
        rat = (rs_all.rank(pct=True) * 98 + 1).round()[e.index]
        rank = 0 if where == "front" else 99
        add = pd.DataFrame({"rs": e, "rs_rating": rat, "sector": "ETF", "industry": "ETF", "industry_rank": rank,
                            "sector_rank": np.nan}, index=e.index)
        out = pd.concat([lead, add])
        return out.sort_values(["industry_rank", "rs_rating"], ascending=[True, False])
    return sel


K = ["CAGR %", "Max drawdown %", "Sharpe", "Trades", "Avg R", "Profit factor"]
VARS = [
    ("base (stocks only)", None),
    ("+ ETFs (plain), after stocks", lane(UNLEV, 5, "back")),
    ("+ ETFs (plain, ADR>=1%), after", lane(UNLEV, 5, "back", adr_min=1.0)),
    ("+ ETFs (plain+lev), after", lane(UNLEV + LEV, 5, "back")),
    ("+ ETFs (plain+lev), before", lane(UNLEV + LEV, 5, "front")),
    ("ETFs only (plain+lev)", lane(UNLEV + LEV, 10, "back", stocks=False)),
    ("ETFs only (plain, ADR>=1%)", lane(UNLEV, 10, "back", stocks=False, adr_min=1.0)),
]
for name, sel in VARS:
    for span, co in [("", {}), ("  15-20", {"end": "2020-12-31"}), ("  21-26", {"start": "2021-01-01"})]:
        bt.select_leaders = sel or orig
        r = run(px, ind, atr, u, reg, p0, Config(**{**GROWTH_CASH, **co}))
        m = metrics(r, spy)
        tr = r["trades"]
        is_etf = tr.ticker.isin(UNLEV + LEV) if len(tr) else pd.Series(dtype=bool)
        extra = {"etf_trades": int(is_etf.sum()), "etf_avgR": round(float(tr.R[is_etf].mean()), 2) if is_etf.any() else None,
                 "etf_tickers": sorted(set(tr.ticker[is_etf]))[:12]} if span == "" else {}
        print(json.dumps({"name": name + span, **{k: m[k] for k in K}, **extra}), flush=True)
bt.select_leaders = orig
