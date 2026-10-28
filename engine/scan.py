"""Weekly scan + ad-hoc ticker analysis.

  python -m engine.scan                    # full Sunday scan → data/scan_<date>.json and data/scan_latest.json
  python -m engine.scan --tickers NVDA,RKLB  # analyze specific tickers → prints JSON
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

from .data import FIELDS

from .data import DATA, load_prices, load_universe
from .framework import Params, atr_frame, indicators, rank_groups, regime_series, select_leaders, setup_for

REGIME_TXT = {2: "Risk-on: SPY & QQQ above 8/21/50 EMA, full size",
              1: "Caution: above 50 EMA but not all EMAs, half size",
              0: "Risk-off: below 50 EMA, no new longs"}


def _clean(o):
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if not math.isfinite(float(o)) else round(float(o), 4)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return o


def bars(px, ind, t: str, n: int = 160) -> list:
    df = pd.DataFrame({k: px[k][t] for k in ("Open", "High", "Low", "Close", "Volume")}).tail(n)
    e = pd.DataFrame({k: ind[k][t] for k in ("e1", "e2", "e3")}).reindex(df.index)
    return [[d.strftime("%Y-%m-%d"), *map(float, df.loc[d]), *map(float, e.loc[d])] for d in df.index]


def score_setup(s, row) -> float:
    """Ranking among ready setups: tighter + better RS + better group + sane extension."""
    return (row.get("rs_rating", 50) / 100) * 2 + (1 - min(s.tight_pct / max(s.adr * 2, 1e-9), 1)) \
        + (1 - min(s.dry, 1.5) / 1.5) + max(0, 1 - (row.get("industry_rank", 10) - 1) / 10)


def load_all(extra: list[str] = (), refresh: bool = False):
    u = load_universe(refresh=refresh)
    tickers = sorted(set(u.index) | {"SPY", "QQQ", "IWM"} | set(extra))
    px = load_prices(tickers)
    p = Params()
    ind = indicators(px, p)
    return u, px, ind, atr_frame(px), regime_series(px, p), p


def analyze(tickers: list[str], u, px, ind, atr, reg, p, ranks=None) -> list[dict]:
    date = px["Close"].index[-1]
    t_idx = len(px["Close"].index) - 1
    ranks = ranks or rank_groups(date, u, px, ind, p)
    st, inds, secs = ranks["stocks"], ranks["industries"], ranks["sectors"]
    out = []
    for t in tickers:
        if t not in px["Close"].columns:
            out.append({"ticker": t, "error": "no price data"})
            continue
        s = setup_for(t, t_idx, px, ind, atr, p)
        industry = u.industry.get(t, "n/a")
        sector = u.sector.get(t, "n/a")
        c = float(px["Close"][t].iloc[-1])
        rec = {
            "ticker": t, "name": u.name.get(t, ""), "sector": sector, "industry": industry,
            "close": c,
            "rs_rating": float(st.rs_rating.get(t, np.nan)) if t in st.index else None,
            "industry_rank": int(inds.index.get_loc(industry)) + 1 if industry in inds.index else None,
            "industry_count": len(inds),
            "sector_rank": int(secs.index.get_loc(sector)) + 1 if sector in secs.index else None,
            "adr": float(ind["adr"][t].iloc[-1]),
            "avg_vol10": float(ind["vol10"][t].iloc[-1]),
            "ema8": float(ind["e1"][t].iloc[-1]), "ema21": float(ind["e2"][t].iloc[-1]),
            "ema50": float(ind["e3"][t].iloc[-1]),
            "setup": s.to_dict(),
        }
        f = {
            "price>3": c >= p.min_price,
            "avg_vol10>500k": rec["avg_vol10"] >= p.min_avg_vol10,
            "adr>2%": rec["adr"] >= p.min_adr,
            "above_21_50": c > rec["ema21"] and c > rec["ema50"],
            "above_8": c > rec["ema8"],
            "near_52w_high": bool(np.isfinite(ind["pth"][t].iloc[-1]) and ind["pth"][t].iloc[-1] >= p.pth_min) if "pth" in ind else True,
        }
        rec["leader_filters"] = f
        out.append(rec)
    return _clean(out)


def analyze_light(tickers: list[str]) -> dict:
    """Ad-hoc analysis without the full-universe cache: fetch only these tickers (+SPY/QQQ) and use the
    group ranks saved by the last full scan (data/ranks_latest.json) for sector/industry/RS context."""
    p = Params()
    rk_path = DATA / "ranks_latest.json"
    rk = json.loads(rk_path.read_text()) if rk_path.exists() else None
    u = load_universe()
    need = sorted(set(tickers) | {"SPY", "QQQ"})
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        d = yf.download(need, period="2y", auto_adjust=True, progress=False, group_by="ticker", threads=True)
    px = {f: pd.DataFrame({t: d[t][f] for t in need if t in d.columns.get_level_values(0)}) for f in FIELDS}
    ind, atr, reg = indicators(px, p), atr_frame(px), regime_series(px, p)
    t_idx = len(px["Close"]) - 1
    inds = {r["industry"]: i + 1 for i, r in enumerate(rk["industries"])} if rk else {}
    secs = {r["sector"]: i + 1 for i, r in enumerate(rk["sectors"])} if rk else {}
    q = np.array(rk["rs_quantiles"]) if rk else None
    out = []
    for t in tickers:
        if t not in px["Close"].columns or px["Close"][t].dropna().empty:
            out.append({"ticker": t, "error": "no price data"})
            continue
        s = setup_for(t, t_idx, px, ind, atr, p)
        rs = float(ind["rs"][t].iloc[-1]) if np.isfinite(ind["rs"][t].iloc[-1]) else np.nan
        industry, sector = u.industry.get(t, "n/a"), u.sector.get(t, "n/a")
        c = float(px["Close"][t].iloc[-1])
        rec = {
            "ticker": t, "name": u.name.get(t, ""), "sector": sector, "industry": industry, "close": c,
            "rs_rating": float(np.clip(np.searchsorted(q, rs), 1, 99)) if q is not None and np.isfinite(rs) else None,
            "industry_rank": inds.get(industry), "industry_count": len(inds) or None, "sector_rank": secs.get(sector),
            "adr": float(ind["adr"][t].iloc[-1]), "avg_vol10": float(ind["vol10"][t].iloc[-1]),
            "ema8": float(ind["e1"][t].iloc[-1]), "ema21": float(ind["e2"][t].iloc[-1]), "ema50": float(ind["e3"][t].iloc[-1]),
            "setup": s.to_dict(), "bars": bars(px, ind, t, 160),
        }
        rec["leader_filters"] = {
            "price>3": c >= p.min_price, "avg_vol10>500k": rec["avg_vol10"] >= p.min_avg_vol10,
            "adr>2%": rec["adr"] >= p.min_adr, "above_21_50": c > rec["ema21"] and c > rec["ema50"],
            "above_8": c > rec["ema8"],
            "near_52w_high": bool(np.isfinite(ind["pth"][t].iloc[-1]) and ind["pth"][t].iloc[-1] >= p.pth_min) if "pth" in ind else True,
        }
        out.append(rec)
    r_now = int(reg.iloc[-1])
    return _clean({"as_of": str(px["Close"].index[-1].date()), "regime": r_now, "regime_text": REGIME_TXT[r_now],
                   "ranks_as_of": rk["as_of"] if rk else None, "tickers": out})


def full_scan(refresh: bool = True) -> dict:
    u, px, ind, atr, reg, p = load_all(refresh=refresh)
    date = px["Close"].index[-1]
    ranks = rank_groups(date, u, px, ind, p)
    lead = select_leaders(date, u, px, ind, p, ranks)
    recs = analyze(list(lead.index), u, px, ind, atr, reg, p, ranks)
    for r in recs:
        row = lead.loc[r["ticker"]]
        r["industry_rank_top"] = int(row.industry_rank)
        r["n_checks"] = sum(r["setup"]["checks"].values()) if r["setup"]["checks"] else 0
        s = setup_for(r["ticker"], len(px["Close"]) - 1, px, ind, atr, p)
        r["score"] = round(score_setup(s, {"rs_rating": row.rs_rating, "industry_rank": row.industry_rank}), 3)
        r["bars"] = bars(px, ind, r["ticker"])
    recs.sort(key=lambda r: (not r["setup"]["ready"], -r["n_checks"], -r["score"]))
    secs = ranks["sectors"].reset_index().rename(columns={"index": "sector"})
    inds = ranks["industries"].reset_index().rename(columns={"index": "industry"})
    r_now = int(reg.iloc[-1])
    out = {
        "as_of": str(date.date()),
        "regime": r_now, "regime_text": REGIME_TXT[r_now],
        "index": {k: {"close": float(px["Close"][k].iloc[-1]), "ema8": float(ind["e1"][k].iloc[-1]),
                      "ema21": float(ind["e2"][k].iloc[-1]), "ema50": float(ind["e3"][k].iloc[-1])}
                  for k in ("SPY", "QQQ")},
        "index_bars": {k: bars(px, ind, k, 120) for k in ("SPY", "QQQ")},
        "sectors": secs.head(12).to_dict("records"),
        "industries": inds.head(20).assign(sector=lambda d: d.industry.map(
            u.groupby("industry").sector.agg(lambda s: s.mode().iat[0]))).to_dict("records"),
        "top_sectors": list(ranks["sectors"].index[: p.top_sectors]),
        "candidates": recs,
        "params": p.__dict__,
    }
    out = _clean(out)
    st = ranks["stocks"]
    i2s = u.groupby("industry").sector.agg(lambda s: s.mode().iat[0])
    rank_export = _clean({
        "as_of": out["as_of"],
        "sectors": secs.to_dict("records"),
        "industries": inds.assign(sector=lambda d: d.industry.map(i2s)).to_dict("records"),
        "rs_quantiles": np.nanquantile(st.rs.to_numpy(), np.linspace(0, 1, 101)).tolist(),
        "stocks": {t: {"rs_rating": r.rs_rating, "industry": r.industry, "sector": r.sector} for t, r in st.iterrows()},
    })
    (DATA / "ranks_latest.json").write_text(json.dumps(rank_export))
    (DATA / f"scan_{out['as_of']}.json").write_text(json.dumps(out))
    (DATA / "scan_latest.json").write_text(json.dumps(out))
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", default="")
    ap.add_argument("--no-refresh", action="store_true")
    ap.add_argument("--charts", default="", help="with --tickers: write annotated PNG charts to this folder")
    a = ap.parse_args()
    if a.tickers:
        tk = [t.strip().upper() for t in a.tickers.split(",") if t.strip()]
        res = analyze_light(tk)
        if a.charts:
            from .charts import setup_chart
            out = Path(a.charts)
            out.mkdir(parents=True, exist_ok=True)
            for r in res["tickers"]:
                if "error" not in r and r["setup"].get("trigger") is not None and r.get("bars"):
                    (out / f"{r['ticker']}.png").write_bytes(setup_chart(r))
                    r["chart"] = str(out / f"{r['ticker']}.png")
        for r in res["tickers"]:
            r.pop("bars", None)
        print(json.dumps(res, indent=1))
    else:
        r = full_scan(refresh=not a.no_refresh)
        ready = [c["ticker"] for c in r["candidates"] if c["setup"]["ready"]]
        print(f"as of {r['as_of']} | {r['regime_text']} | leaders {len(r['candidates'])} | ready: {ready}")
