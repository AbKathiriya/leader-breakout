"""Annotated setup charts (PNG): base, entry trigger, max stop, undercut, first target, EMA trail exits.

Renders from the scan JSON record (bars = [date, O, H, L, C, V, ema8, ema21, ema50]) so it needs no price cache.
"""
from __future__ import annotations

import io
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

C = {
    "bg": "#ffffff", "ink": "#16201d", "muted": "#5d6b66", "grid": "#e6eae7",
    "up": "#0e9fb3", "down": "#c2307a", "ema8": "#0e9fb3", "ema21": "#c2307a", "ema50": "#7d8984",
    "trigger": "#d97a06", "stop": "#c0392b", "undercut": "#7a4fc4", "target": "#1d8a4e", "base": "#d97a06",
}


def _fmt(x):
    return f"{x:,.2f}" if x < 1000 else f"{x:,.0f}"


def setup_chart(rec: dict, days: int = 110, future: int = 18) -> bytes:
    b = pd.DataFrame(rec["bars"], columns=["d", "o", "h", "l", "c", "v", "e8", "e21", "e50"]).tail(days)
    b["d"] = pd.to_datetime(b["d"])
    s = {k: (np.nan if v is None else v) for k, v in rec["setup"].items()}
    x = np.arange(len(b))
    xf = len(b) + future
    trig, ustop, uc, t1 = s["trigger"], s["max_stop"], s["undercut"], s["t1"]

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9})
    fig = plt.figure(figsize=(10, 6.6), dpi=130, facecolor=C["bg"])
    gs = fig.add_gridspec(2, 1, height_ratios=[4, 1], hspace=0.04, left=0.07, right=0.80, top=0.88, bottom=0.27)
    ax = fig.add_subplot(gs[0])
    av = fig.add_subplot(gs[1], sharex=ax)
    for a in (ax, av):
        a.set_facecolor(C["bg"])
        a.grid(axis="y", color=C["grid"], lw=0.6)
        for sp in a.spines.values():
            sp.set_visible(False)
        a.tick_params(colors=C["muted"], length=0)

    # candles
    up = b.c >= b.o
    col = np.where(up, C["up"], C["down"])
    ax.vlines(x, b.l, b.h, color=col, lw=0.8)
    ax.bar(x, (b.c - b.o).abs().clip(lower=(b.h - b.l).mean() * 0.02), bottom=np.minimum(b.o, b.c), color=col, width=0.65)
    for k, w in (("e8", 1.0), ("e21", 1.0), ("e50", 1.8)):
        ax.plot(x, b[k], color=C["ema" + k[1:]], lw=w)

    # base box
    n = len(b)
    k = int(s.get("base_len") or 0)
    if k > 0 and np.isfinite(uc):
        x0 = n - 1 - k
        ax.add_patch(plt.Rectangle((x0 - 0.5, uc), k + 1, trig - uc, facecolor=C["base"], alpha=0.08, edgecolor=C["base"], lw=0.8))
        ax.text(x0, uc, f" base {k}d · {s.get('depth', 0):.0f}% deep", color=C["base"], va="top", ha="left", fontsize=8,
                bbox=dict(facecolor=C["bg"], edgecolor="none", pad=1))

    # levels extended into the future area; labels de-overlapped in a right-hand column
    levels = [(t1, C["target"], "-", "TRIM ¼"), (trig, C["trigger"], "-", "ENTRY"),
              (ustop, C["stop"], "--", "MAX STOP")]
    levels = [lv for lv in levels if lv[0] is not None and np.isfinite(lv[0])]
    lo_ = min([b.l.min()] + [lv[0] for lv in levels]); hi_ = max([b.h.max()] + [lv[0] for lv in levels])
    gap = (hi_ - lo_) * 0.075
    ys = []
    for y, *_ in sorted(levels, key=lambda t: -t[0]):
        ys.append(min(y, ys[-1] - gap) if ys else y)
    lab_y = dict(zip([lv[3] for lv in sorted(levels, key=lambda t: -t[0])], ys))
    for y, color, ls, name in levels:
        ax.hlines(y, n - 1 - max(k, 5), xf, color=color, ls=ls, lw=1.4, zorder=3)
        ax.annotate(f"{name}  {_fmt(y)}", xy=(xf, y), xytext=(xf + 1.2, lab_y[name]), textcoords="data",
                    color=color, va="center", ha="left", fontsize=9, fontweight="bold", annotation_clip=False,
                    arrowprops=dict(arrowstyle="-", color=color, lw=0.6, shrinkA=0, shrinkB=0) if abs(lab_y[name] - y) > gap * 0.2 else None)

    # entry marker and projected path
    xe = n + 1
    ax.annotate("", xy=(xe, trig), xytext=(xe, (trig + ustop) / 2), arrowprops=dict(arrowstyle="-|>", color=C["trigger"], lw=1.6))
    if np.isfinite(t1):
        ax.annotate("", xy=(xe + 9, t1), xytext=(xe + 1, trig), arrowprops=dict(arrowstyle="-|>", color=C["target"], lw=1.2, ls="--"))
    rr = s.get("rr_at_max_stop")
    if rr and np.isfinite(rr):
        ax.text(xe + 7, (trig + t1) / 2, f"{rr:.1f}R\nto target", color=C["target"], fontsize=8.5, fontweight="bold",
                ha="left", va="center", bbox=dict(facecolor=C["bg"], edgecolor="none", pad=1.5))

    last = b.iloc[-1]
    notes = [
        ("ENTRY", C["trigger"], "buy-stop above the base high; best on a 5-min break with ≥1.5× volume"),
        ("STOP", C["stop"], "low of the entry day; skip the trade if that low is below MAX STOP"),
        ("SIZE", C["ink"], "growth mode: the first fill may use the whole account; cash only, idle cash waits in SPY"),
        ("TRIM ¼", C["target"], "at first target, then move the stop to entry"),
        ("EXITS", C["muted"], f"¼ on close < 8 EMA ({_fmt(last.e8)}) · ¼ on close < 21 EMA ({_fmt(last.e21)}) · rest on close < 50 EMA ({_fmt(last.e50)})"),
    ]
    for i, (t, c, txt) in enumerate(notes):
        y = 0.205 - i * 0.04
        fig.text(0.06, y, t, color=c, fontsize=8.3, fontweight="bold")
        fig.text(0.155, y, txt, color=C["muted"], fontsize=8.3)

    lo = min(b.l.min(), ustop if np.isfinite(ustop) else b.l.min())
    hi = max(b.h.max(), t1 if np.isfinite(t1) else b.h.max())
    pad = (hi - lo) * 0.06
    ax.set_ylim(lo - pad * 2, hi + pad * 2.5)
    ax.set_xlim(-1, xf)

    # volume
    av.bar(x, b.v, color=col, width=0.65, alpha=0.6)
    av.plot(x, b.v.rolling(50, min_periods=10).mean(), color=C["muted"], lw=1)
    av.set_yticks([])
    ticks = list(range(0, n, max(1, n // 6)))
    av.set_xticks(ticks)
    av.set_xticklabels([b.d.iloc[i].strftime("%b %d") for i in ticks])
    plt.setp(ax.get_xticklabels(), visible=False)

    title = f"{rec['ticker']}  ·  {rec.get('industry', '')}"
    fig.text(0.07, 0.95, title, fontsize=13, fontweight="bold", color=C["ink"])
    if rec.get("kind") == "EP":
        sub = (f"EPISODIC PIVOT · gapped +{rec.get('gap_pct', 0):.0f}% on {rec.get('vol_x', 0):.0f}× average volume · "
               f"close {_fmt(rec['close'])}   ADR {rec.get('adr') or 0:.1f}%   entry = break of the gap-day high")
    else:
        sub = (f"close {_fmt(rec['close'])}   RS {rec.get('rs_rating') or '–'}   ADR {rec.get('adr') or 0:.1f}%   "
               f"prior run +{s.get('prior_move', float('nan')):.0f}%   leg vol {s.get('leg_vs_base', float('nan')):.1f}× · "
               f"up/down {s.get('ud_ratio', float('nan')):.1f}   last 5d range {s.get('tight_pct', float('nan')):.1f}% "
               f"on {s.get('dry', float('nan')):.2f}× avg vol")
    fig.text(0.07, 0.915, sub, fontsize=8.5, color=C["muted"])
    leg = [("8 EMA", C["ema8"]), ("21 EMA", C["ema21"]), ("50 EMA", C["ema50"])]
    for i, (t, c) in enumerate(leg):
        fig.text(0.07 + i * 0.075, 0.885 - 0.0, "", color=c)
    ax.legend(handles=[plt.Line2D([], [], color=c, lw=2, label=t) for t, c in leg], loc="upper left",
              frameon=False, fontsize=8, labelcolor=C["muted"], ncol=3)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=C["bg"])
    plt.close(fig)
    return buf.getvalue()


def write_charts(scan: dict, out_dir: Path, max_near: int = 4) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    picks = [c for c in scan["candidates"] if c["setup"]["ready"]]
    picks += [c for c in scan["candidates"] if not c["setup"]["ready"] and c.get("n_checks", 0) >= 5][:max_near]
    paths = {}
    for c in picks:
        if not c.get("bars") or c["setup"].get("trigger") is None:
            continue
        p = out_dir / f"{c['ticker']}.png"
        p.write_bytes(setup_chart(c))
        paths[c["ticker"]] = p
    return paths
