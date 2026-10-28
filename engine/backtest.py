"""Event-driven daily-bar backtest of the weekly leader/breakout strategy.

Timeline (no look-ahead):
  • Every week's last trading day (Friday close): regime, sector/industry ranking, leaders, setups → next week's watchlist.
  • Each day: manage open positions (stop → first target → close-based trims), then take new entries from the watchlist,
    using the previous close's regime for permission and size.

Entry models for the intraday "sniper" entry, which daily bars can't replay exactly:
  touch_path  (default) buy-stop at trigger; bar-path convention decides whether the day's low came before the fill
              (up bar: O→L→H→C) or after it (down bar: O→H→L→C → stopped at the low-of-day-at-fill that day).
  touch_worst every ambiguous day resolved against you (upper bound on damage).
  touch_opt   buy-stop at trigger (or open if gapped above); stop = day's low; no same-day stop-out.
  touch_pess  same, but if the entry day closes below the entry price, assume it was stopped out that day at the low.
  close_conf  enter at the close only if close > trigger and day volume ≥ vol_mult × 50-day avg; stop = day's low.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .framework import Params, first_target, rank_groups, select_leaders, setup_for


@dataclass
class Config:
    start: str = "2015-01-01"
    end: str | None = None
    capital: float = 100_000.0
    risk_pct: float = 0.02
    half_size_in_caution: bool = True
    regime_filter: bool = True
    max_positions: int = 8
    max_pos_pct: float = 0.25           # notional cap per position (tight LOD stops would otherwise size absurdly)
    entry_mode: str = "touch_path"      # touch_path | touch_opt | touch_pess | touch_worst | close_conf
    use_undercut: bool = True
    slippage: float = 0.0010            # per side
    selection: str = "groups"           # groups | rs_only
    rs_only_n: int = 24


@dataclass
class Pos:
    ticker: str
    kind: str
    entry_date: pd.Timestamp
    entry: float
    stop: float
    t1: float
    shares0: int
    shares: int
    risk_ps: float
    cost: float = 0.0
    proceeds: float = 0.0
    t1hit: bool = False
    did8: bool = False
    did21: bool = False
    exits: list = field(default_factory=list)


def week_ends(idx: pd.DatetimeIndex) -> np.ndarray:
    wk = idx.isocalendar()
    key = wk.year.astype(str) + "-" + wk.week.astype(str)
    return (key != key.shift(-1)).to_numpy()


def run(px, ind, atr, universe, regime: pd.Series, p: Params, cfg: Config, verbose: bool = False):
    dates = px["Close"].index
    i0 = dates.searchsorted(pd.Timestamp(cfg.start))
    i1 = len(dates) - 1 if cfg.end is None else dates.searchsorted(pd.Timestamp(cfg.end), side="right") - 1
    is_we = week_ends(dates)
    tick_ix = {t: j for j, t in enumerate(px["Close"].columns)}
    O, H, L, C, V = (px[f].to_numpy(dtype=float) for f in ("Open", "High", "Low", "Close", "Volume"))
    E1, E2, E3 = (ind[k].to_numpy(dtype=float) for k in ("e1", "e2", "e3"))
    ADR, V50 = ind["adr"].to_numpy(dtype=float), ind["vol50"].to_numpy(dtype=float)
    reg = regime.reindex(dates).fillna(0).to_numpy()
    slip = cfg.slippage

    cash, equity = cfg.capital, cfg.capital
    positions: list[Pos] = []
    trades, curve, watch_log = [], [], []
    watch: list = []          # Setups from last week end
    tried: set = set()

    def close_part(pos: Pos, n: int, price: float, why: str, d):
        nonlocal cash
        n = min(n, pos.shares)
        if n <= 0:
            return
        fill = price * (1 - slip)
        cash += n * fill
        pos.proceeds += n * fill
        pos.shares -= n
        pos.exits.append((str(d.date()), why, round(fill, 4), n))

    def finish(pos: Pos, d):
        pnl = pos.proceeds - pos.cost
        trades.append({
            "ticker": pos.ticker, "kind": pos.kind, "entry_date": pos.entry_date.date(), "exit_date": d.date(),
            "days": int((d - pos.entry_date).days), "entry": round(pos.entry, 4), "stop0": round(pos.entry - pos.risk_ps, 4),
            "t1": round(pos.t1, 4), "shares": pos.shares0, "pnl": round(pnl, 2),
            "R": round(pnl / (pos.risk_ps * pos.shares0), 3), "ret_pct": round(100 * pnl / pos.cost, 2),
            "t1_hit": pos.t1hit, "exits": pos.exits,
        })

    for i in range(max(i0, 260), i1 + 1):
        d = dates[i]
        # ── 1. manage open positions ──
        still = []
        for pos in positions:
            j = tick_ix[pos.ticker]
            o, h, l, c = O[i, j], H[i, j], L[i, j], C[i, j]
            if not np.isfinite(c):
                still.append(pos)
                continue
            if o <= pos.stop:
                close_part(pos, pos.shares, o, "stop_gap", d)
            elif l <= pos.stop:
                close_part(pos, pos.shares, pos.stop, "stop" if not pos.t1hit else "stop_be", d)
            else:
                if not pos.t1hit and h >= pos.t1:
                    close_part(pos, max(1, pos.shares0 // 4), max(o, pos.t1), "t1", d)
                    pos.t1hit, pos.stop = True, pos.entry
                if pos.shares and pos.t1hit and not pos.did8 and c < E1[i, j]:
                    pos.did8 = True
                    close_part(pos, max(1, pos.shares0 // 4), c, "close<ema8", d)
                if pos.shares and pos.t1hit and not pos.did21 and c < E2[i, j]:
                    pos.did21 = True
                    close_part(pos, max(1, pos.shares0 // 4), c, "close<ema21", d)
                if pos.shares and c < E3[i, j] and (pos.t1hit or p.exit50_early):
                    close_part(pos, pos.shares, c, "close<ema50", d)
            if pos.shares > 0:
                still.append(pos)
            else:
                finish(pos, d)
        positions = still

        # ── 2. entries from this week's watchlist ──
        r_prev = reg[i - 1]
        allowed = (r_prev >= 1) if cfg.regime_filter else True
        size_mult = 0.5 if (cfg.half_size_in_caution and cfg.regime_filter and r_prev == 1) else 1.0
        if allowed and watch:
            held = {q.ticker for q in positions}
            for s in watch:
                if len(positions) >= cfg.max_positions:
                    break
                if s.ticker in held or s.ticker in tried:
                    continue
                j = tick_ix[s.ticker]
                o, h, l, c, v = O[i, j], H[i, j], L[i, j], C[i, j], V[i, j]
                if not np.isfinite(c) or not np.isfinite(o):
                    continue
                adr_prev = ADR[i - 1, j]
                kind, entry, stop, same_day_stop = None, None, None, False
                limit_pct = min(p.max_risk_adr * adr_prev, p.max_risk_pct)
                touch = cfg.entry_mode in ("touch_opt", "touch_pess", "touch_path", "touch_worst")
                if touch and h > s.trigger:
                    kind, entry = "breakout", max(o, s.trigger) * (1 + slip)
                    max_stop = entry * (1 - limit_pct / 100)
                    if cfg.entry_mode == "touch_path":
                        # Bar-path convention: up bar O→L→H→C (low before the fill), down bar O→H→L→C (fill first).
                        if c >= o:
                            stop = l
                        else:
                            lod_at_fill = min(o, entry)
                            if lod_at_fill < max_stop:
                                stop = lod_at_fill          # too wide → skipped below
                            else:
                                stop = lod_at_fill if lod_at_fill < entry * (1 - 1e-4) else max_stop
                                same_day_stop = l <= stop
                    elif cfg.entry_mode == "touch_worst":
                        stop = l
                        if 100 * (entry - l) / entry > limit_pct and o < entry:
                            stop, same_day_stop = max_stop, True   # assume filled, then fell through the max stop
                        else:
                            same_day_stop = c < entry
                    else:
                        stop = l
                        same_day_stop = cfg.entry_mode == "touch_pess" and c < entry
                elif cfg.entry_mode == "close_conf" and c > s.trigger and v >= p.vol_mult * V50[i - 1, j]:
                    entry, stop, kind = c * (1 + slip), l, "breakout"
                elif cfg.use_undercut and l < s.undercut and c > s.undercut:
                    entry, stop, kind = c * (1 + slip), l, "undercut"
                if kind is None:
                    continue
                tried.add(s.ticker)  # one attempt per ticker per watchlist week
                risk_ps = entry - stop
                if risk_ps <= 0 or 100 * risk_ps / entry > limit_pct + 1e-9:
                    continue
                risk_amt = equity * cfg.risk_pct * size_mult
                sh = math.floor(min(risk_amt / risk_ps, cfg.max_pos_pct * equity / entry, cash / entry))
                if sh < 4:
                    continue
                cash -= sh * entry
                pos = Pos(s.ticker, kind, d, entry, stop, first_target(entry, stop, H[:, j], i - 1, p),
                          sh, sh, risk_ps, cost=sh * entry)
                pos.exits.append((str(d.date()), "entry", round(entry, 4), sh))
                if same_day_stop:
                    close_part(pos, pos.shares, stop, "stop_same_day", d)
                    finish(pos, d)
                else:
                    positions.append(pos)
                    held.add(s.ticker)

        # ── 3. mark to market ──
        mv = sum(q.shares * (C[i, tick_ix[q.ticker]] if np.isfinite(C[i, tick_ix[q.ticker]]) else q.entry)
                 for q in positions)
        equity = cash + mv
        curve.append((d, equity, len(positions), r_prev))

        # ── 4. weekly scan at week end ──
        if is_we[i]:
            if cfg.selection == "groups":
                lead = select_leaders(d, universe, px, ind, p)
            else:
                lead = rank_groups(d, universe, px, ind, p)["stocks"]
                c_ = px["Close"].loc[d]
                ok = (ind["vol10"].loc[d] >= p.min_avg_vol10) & (ind["adr"].loc[d] >= p.min_adr) & \
                     (c_ > ind["e2"].loc[d]) & (c_ > ind["e3"].loc[d])
                lead = lead[ok.reindex(lead.index).fillna(False)].nlargest(cfg.rs_only_n, "rs_rating")
            setups = [setup_for(t, i, px, ind, atr, p) for t in lead.index]
            watch = [s for s in setups if s.ready]
            tried = set()
            watch_log.append({"date": d.date(), "leaders": len(lead), "setups": [s.ticker for s in watch],
                              "regime": int(reg[i])})
            if verbose and len(watch_log) % 26 == 0:
                print(f"{d.date()} equity {equity:,.0f} open {len(positions)} setups {len(watch)}")

    # close remaining at last close (mark only)
    for pos in positions:
        j = tick_ix[pos.ticker]
        close_part(pos, pos.shares, C[i1, j], "open_at_end", dates[i1])
        finish(pos, dates[i1])

    curve = pd.DataFrame(curve, columns=["date", "equity", "open", "regime"]).set_index("date")
    return {"curve": curve, "trades": pd.DataFrame(trades), "watch": watch_log}


def metrics(res, bench: pd.Series | None = None) -> dict:
    eq = res["curve"]["equity"]
    tr = res["trades"]
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    rets = eq.pct_change().dropna()
    dd = eq / eq.cummax() - 1
    out = {
        "CAGR %": 100 * ((eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1),
        "Total return %": 100 * (eq.iloc[-1] / eq.iloc[0] - 1),
        "Max drawdown %": 100 * dd.min(),
        "Sharpe": rets.mean() / rets.std() * np.sqrt(252) if rets.std() > 0 else np.nan,
        "Trades": len(tr),
        "Win rate %": 100 * (tr.pnl > 0).mean() if len(tr) else np.nan,
        "Avg R": tr.R.mean() if len(tr) else np.nan,
        "Avg win R": tr.R[tr.R > 0].mean() if len(tr) else np.nan,
        "Avg loss R": tr.R[tr.R <= 0].mean() if len(tr) else np.nan,
        "Profit factor": tr.pnl[tr.pnl > 0].sum() / -tr.pnl[tr.pnl < 0].sum() if (tr.pnl < 0).any() else np.nan,
        "Best trade R": tr.R.max() if len(tr) else np.nan,
        "Avg hold days": tr.days.mean() if len(tr) else np.nan,
        "Exposure % (days with a position)": 100 * (res["curve"]["open"] > 0).mean(),
    }
    if bench is not None:
        b = bench.reindex(eq.index).ffill()
        out["Benchmark CAGR %"] = 100 * ((b.iloc[-1] / b.iloc[0]) ** (1 / yrs) - 1)
        out["Benchmark max DD %"] = 100 * (b / b.cummax() - 1).min()
    return {k: (round(float(v), 2) if isinstance(v, (float, np.floating)) else v) for k, v in out.items()}


def yearly(res, bench: pd.Series | None = None) -> pd.DataFrame:
    eq = res["curve"]["equity"]

    def by_year(s):
        last = s.groupby(s.index.year).last()
        prev = last.shift(1)
        prev.iloc[0] = s.iloc[0]
        return 100 * (last / prev - 1)

    out = pd.DataFrame({"strategy %": by_year(eq)})
    if bench is not None:
        out["SPY %"] = by_year(bench.reindex(eq.index).ffill())
    tr = res["trades"]
    if len(tr):
        tr = tr.assign(year=pd.to_datetime(tr.entry_date).dt.year)
        out["trades"] = tr.groupby("year").size()
        out["win %"] = 100 * tr.groupby("year").pnl.apply(lambda s: (s > 0).mean())
    return out.round(1)
