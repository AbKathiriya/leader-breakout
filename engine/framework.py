"""The framework, as code: regime → leading sectors/industries → leaders → tight base → entries/stops/targets.

Everything here only uses data up to and including the evaluation bar (no look-ahead).
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field

import numpy as np
import pandas as pd


@dataclass
class Params:
    # trend
    ema_fast: int = 8
    ema_mid: int = 21
    ema_slow: int = 50
    # liquidity / leader filters (article's scanner)
    min_price: float = 3.0
    min_avg_vol10: float = 500_000
    min_dollar_vol20: float = 5e6
    min_adr: float = 2.0
    # ranking
    top_sectors: int = 0            # 0 = rank sectors for context but don't gate on them (gating hurt in the backtest)
    top_industries: int = 15
    stocks_per_industry: int = 5
    min_industry_members: int = 3
    # base / setup
    min_base: int = 5
    max_base: int = 40
    max_depth: float = 25.0          # allowed depth = min(cap, max(max_depth, depth_adr_mult × ADR%))
    max_depth_cap: float = 40.0
    depth_adr_mult: float = 3.0
    prior_look: int = 60
    prior_move: float = 25.0
    tight_len: int = 5
    tight_mult: float = 2.0
    dry_max: float = 1.0             # last tight_len days avg volume ≤ x × 50-day avg
    # entries
    vol_mult: float = 1.5
    max_risk_adr: float = 0.5        # skip if LOD stop is further than this × ADR …
    max_risk_pct: float = 3.0        # … or further than this % (the edge lives in tight-risk entries)
    # exits
    t1_mode: str = "resistance"   # or "r"
    t1_r: float = 3.0
    exit50_early: bool = True


# ───────────────────────── indicators (wide frames: dates × tickers) ─────────────────────────

def ema(df: pd.DataFrame, n: int) -> pd.DataFrame:
    return df.ewm(span=n, adjust=False, min_periods=n).mean()


def indicators(px: dict[str, pd.DataFrame], p: Params) -> dict[str, pd.DataFrame]:
    c, h, l, v = px["Close"], px["High"], px["Low"], px["Volume"]
    ind = {
        "e1": ema(c, p.ema_fast), "e2": ema(c, p.ema_mid), "e3": ema(c, p.ema_slow),
        "adr": 100 * ((h / l).rolling(20).mean() - 1),
        "vol10": v.rolling(10).mean(), "vol50": v.rolling(50).mean(),
        "dvol20": (c * v).rolling(20).mean(),
    }
    # IBD-style relative strength composite (weights recent quarter double)
    r = lambda n: c / c.shift(n) - 1
    ind["rs"] = 0.4 * r(63) + 0.2 * r(126) + 0.2 * r(189) + 0.2 * r(252)
    ind["rs"] = ind["rs"].where(c.notna().rolling(130).sum() >= 130)  # need ~6 months of history
    return ind


def regime_series(px: dict[str, pd.DataFrame], p: Params, idx=("SPY", "QQQ")) -> pd.Series:
    """2 = risk-on (both indexes above 8/21/50), 1 = caution (both above 50), 0 = risk-off."""
    c = px["Close"][list(idx)]
    above = [(c > ema(c, n)) for n in (p.ema_fast, p.ema_mid, p.ema_slow)]
    all_above = (above[0] & above[1] & above[2]).all(axis=1)
    above50 = above[2].all(axis=1)
    return pd.Series(np.where(all_above, 2, np.where(above50, 1, 0)), index=c.index)


# ───────────────────────── ranking ─────────────────────────

def rank_groups(date, universe: pd.DataFrame, px, ind, p: Params) -> dict:
    """Rank sectors and industries by median member RS (+ breadth) among liquid members at `date`."""
    c = px["Close"].loc[date]
    liquid = (c >= p.min_price) & (ind["dvol20"].loc[date] >= p.min_dollar_vol20) & ind["rs"].loc[date].notna()
    names = liquid[liquid].index.intersection(universe.index)
    df = pd.DataFrame({
        "rs": ind["rs"].loc[date, names],
        "above50": (c[names] > ind["e3"].loc[date, names]).astype(float),
        "sector": universe.loc[names, "sector"],
        "industry": universe.loc[names, "industry"],
    })
    # cross-sectional RS percentile 1..99 (like an RS rating)
    df["rs_rating"] = (df.rs.rank(pct=True) * 98 + 1).round()

    def agg(key):
        g = df.groupby(key).agg(n=("rs", "size"), rs_med=("rs_rating", "median"), breadth=("above50", "mean"))
        g = g[g.n >= p.min_industry_members]
        g["score"] = 0.7 * g.rs_med + 30 * g.breadth   # both on ~0-100 scale
        return g.sort_values("score", ascending=False)

    return {"stocks": df, "sectors": agg("sector"), "industries": agg("industry")}


_IND2SEC: dict = {}


def industry_sector_map(universe: pd.DataFrame) -> dict:
    key = id(universe)
    if key not in _IND2SEC:
        _IND2SEC[key] = universe.groupby("industry")["sector"].agg(lambda s: s.mode().iat[0]).to_dict()
    return _IND2SEC[key]


def select_leaders(date, universe, px, ind, p: Params, ranks: dict | None = None) -> pd.DataFrame:
    """Top sectors → top industries inside them → top N stocks per industry that pass the leader filters."""
    ranks = ranks or rank_groups(date, universe, px, ind, p)
    st, secs, inds = ranks["stocks"], ranks["sectors"], ranks["industries"]
    top_secs = list(secs.index[: p.top_sectors])
    ind2sec = industry_sector_map(universe)
    ind_in = inds[inds.index.map(lambda i: ind2sec.get(i) in top_secs).astype(bool)] if p.top_sectors else inds
    top_inds = list(ind_in.index[: p.top_industries])

    c = px["Close"].loc[date]
    ok = (
        (c >= p.min_price)
        & (ind["vol10"].loc[date] >= p.min_avg_vol10)
        & (ind["adr"].loc[date] >= p.min_adr)
        & (c > ind["e2"].loc[date]) & (c > ind["e3"].loc[date])
    )
    cand = st[st.industry.isin(top_inds) & ok.reindex(st.index).fillna(False)]
    cand = cand.sort_values("rs_rating", ascending=False).groupby("industry").head(p.stocks_per_industry)
    cand = cand.assign(industry_rank=cand.industry.map({k: i + 1 for i, k in enumerate(top_inds)}),
                       sector_rank=cand.sector.map({k: i + 1 for i, k in enumerate(top_secs)}))
    return cand.sort_values(["industry_rank", "rs_rating"], ascending=[True, False])


# ───────────────────────── setup detection (single ticker, arrays) ─────────────────────────

@dataclass
class Setup:
    ticker: str
    date: str
    ready: bool
    checks: dict = field(default_factory=dict)
    trigger: float = float("nan")      # base high → breakout buy-stop
    undercut: float = float("nan")     # base low → undercut & rally level
    base_len: int = 0
    depth: float = float("nan")
    prior_move: float = float("nan")
    tight_pct: float = float("nan")
    dry: float = float("nan")
    adr: float = float("nan")
    close: float = float("nan")
    max_stop: float = float("nan")     # trigger − max_risk_adr × ADR (LOD must be above this)
    t1: float = float("nan")
    rr_at_max_stop: float = float("nan")
    ext_atr: float = float("nan")

    def to_dict(self):
        return asdict(self)


def swing_highs(high: np.ndarray, upto: int, look: int = 252, w: int = 5) -> np.ndarray:
    """Confirmed pivot highs (w bars each side) whose confirmation bar ≤ upto."""
    lo = max(w, upto - look)
    out = []
    for i in range(lo, upto - w + 1):
        seg = high[i - w:i + w + 1]
        if np.isfinite(high[i]) and high[i] == np.nanmax(seg):
            out.append(high[i])
    return np.array(out)


def first_target(entry: float, stop: float, high: np.ndarray, upto: int, p: Params) -> float:
    r = entry - stop
    if p.t1_mode == "resistance" and r > 0:
        lv = swing_highs(high, upto)
        lv = lv[lv > entry + r]
        if len(lv):
            return float(lv.min())
    return entry + p.t1_r * r


def detect_setup(ticker: str, o, h, l, c, v, e2, e3, e1, adr, vol50, atr, t: int, p: Params, date="") -> Setup:
    """Evaluate the base at bar index t (inclusive). Arrays are numpy float."""
    s = Setup(ticker=ticker, date=str(date), ready=False)
    if t < p.max_base + p.prior_look + 5 or not np.isfinite(c[t]):
        return s
    win = h[t - p.max_base + 1: t + 1]
    if not np.isfinite(win).any():
        return s
    # k = bars since the highest high of the window (ties → most recent occurrence)
    mx = np.nanmax(win)
    k = int(np.where(win == mx)[0][-1])
    k = (p.max_base - 1) - k
    pivot = h[t - k]
    base_low = np.nanmin(l[t - k: t + 1])
    depth = 100 * (pivot - base_low) / pivot
    prior_low = np.nanmin(l[t - k - p.prior_look: t - k + 1])
    prior = 100 * (pivot / prior_low - 1)
    tight = 100 * (np.nanmax(h[t - p.tight_len + 1: t + 1]) - np.nanmin(l[t - p.tight_len + 1: t + 1])) / c[t]
    dry = np.nanmean(v[t - p.tight_len + 1: t + 1]) / vol50[t] if vol50[t] > 0 else np.nan
    a = adr[t]
    checks = {
        "trend": bool(c[t] > e2[t] and c[t] > e3[t] and e2[t] > e3[t]),
        "base_length": bool(k >= p.min_base),
        "depth": bool(depth <= min(p.max_depth_cap, max(p.max_depth, p.depth_adr_mult * a))),
        "prior_move": bool(prior >= p.prior_move),
        "tight": bool(tight <= p.tight_mult * a),
        "volume_dry": bool(np.isfinite(dry) and dry <= p.dry_max),
    }
    s.checks = checks
    s.ready = all(checks.values())
    s.trigger, s.undercut, s.base_len = float(pivot), float(base_low), int(k)
    s.depth, s.prior_move, s.tight_pct, s.dry, s.adr, s.close = map(float, (depth, prior, tight, dry, a, c[t]))
    s.max_stop = float(pivot * (1 - min(p.max_risk_adr * a, p.max_risk_pct) / 100))
    s.t1 = first_target(pivot, s.max_stop, h, t, p)
    s.rr_at_max_stop = float((s.t1 - pivot) / (pivot - s.max_stop)) if pivot > s.max_stop else float("nan")
    s.ext_atr = float((c[t] - e1[t]) / atr[t]) if atr[t] > 0 else float("nan")
    return s


def atr_frame(px, n=14) -> pd.DataFrame:
    h, l, c = px["High"], px["Low"], px["Close"]
    pc = c.shift(1)
    tr = np.maximum(h - l, np.maximum((h - pc).abs(), (l - pc).abs()))
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def setup_for(ticker: str, t: int, px, ind, atr, p: Params) -> Setup:
    g = lambda df: df[ticker].to_numpy(dtype=float)
    return detect_setup(
        ticker, g(px["Open"]), g(px["High"]), g(px["Low"]), g(px["Close"]), g(px["Volume"]),
        g(ind["e2"]), g(ind["e3"]), g(ind["e1"]), g(ind["adr"]), g(ind["vol50"]), g(atr),
        t, p, date=px["Close"].index[t].date(),
    )
