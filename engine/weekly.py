"""Helpers for the Sunday run.

  python -m engine.weekly options-plan       # what to quote on Robinhood for each ready setup
  python -m engine.weekly options-input F    # merge quotes JSON (from the agent) with levels → options input file
  python -m engine.weekly backtest-card      # bt_summary.json → data/bt_report.json (report block)
"""
from __future__ import annotations

import datetime as dt
import json
import sys

from .data import DATA


def options_plan(regime_factor: float | None = None) -> list[dict]:
    s = json.loads((DATA / "scan_latest.json").read_text())
    rf = regime_factor if regime_factor is not None else {2: 1.0, 1: 0.5, 0: 0.0}[s["regime"]]
    asof = dt.date.fromisoformat(s["as_of"])
    plan = []
    for c in s["candidates"]:
        if not c["setup"]["ready"]:
            continue
        st = c["setup"]
        plan.append({
            "ticker": c["ticker"], "spot": c["close"], "trigger": st["trigger"], "stop": st["max_stop"],
            "t1": st["t1"], "adr": c["adr"], "regime_factor": rf or 1.0,
            "expiry_window": [str(asof + dt.timedelta(days=45)), str(asof + dt.timedelta(days=90))],
            "strike_band": [round(st["trigger"] * 0.90, 2), round(st["trigger"] * 1.01, 2)],
            "note": "quote 3-4 listed call strikes inside strike_band for the first monthly expiry in expiry_window "
                    "(after earnings if possible); pass strike_price to get_option_instruments, one call per strike",
        })
    return plan


def options_input(quotes_path: str) -> None:
    """quotes file: {ticker: [{strike, mark, bid, ask, delta, gamma, theta, iv, oi, expiration}, ...]}"""
    quotes = json.loads(open(quotes_path).read())
    items = []
    for p in options_plan():
        if p["ticker"] in quotes:
            items.append({**{k: p[k] for k in ("ticker", "spot", "trigger", "stop", "t1", "adr", "regime_factor")},
                          "calls": quotes[p["ticker"]]})
    (DATA / "options_input.json").write_text(json.dumps(items, indent=1))
    print(f"wrote {DATA / 'options_input.json'} ({len(items)} tickers)")


def backtest_card() -> None:
    bt = json.loads((DATA / "bt_summary.json").read_text())
    b, o, w = bt["base"], bt.get("optimistic_entry", {}), bt.get("worst_case_entry", {})
    keep = ["CAGR %", "Max drawdown %", "Sharpe", "Trades", "Win rate %", "Avg R", "Profit factor",
            "Benchmark CAGR %", "Benchmark max DD %"]
    card = {
        "note": "2015 to now, daily bars, bar-path model of the intraday entry"
                + (f"; optimistic {o['CAGR %']}% and worst-case {w['CAGR %']}% CAGR" if o and w else "")
                + "; today's listings only (survivorship bias)",
        "metrics": {k.replace("Benchmark", "SPY"): b[k] for k in keep if k in b},
    }
    card["variants"] = {k: {m: v.get(m) for m in ("CAGR %", "Max drawdown %", "Sharpe", "Trades", "Profit factor")}
                        for k, v in bt.items()}
    card["equity_png"] = _equity_png()
    (DATA / "bt_report.json").write_text(json.dumps(card))
    print(json.dumps({k: v for k, v in card.items() if k != "equity_png"}, indent=1))


def _equity_png() -> str | None:
    import base64
    import io

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import pandas as pd
    p = DATA / "bt_curve.csv"
    if not p.exists():
        return None
    eq = pd.read_csv(p, index_col=0, parse_dates=True)["equity"]
    spy = pd.read_parquet(DATA / "prices.parquet")["Close"]["SPY"].reindex(eq.index).ffill()
    fig, ax = plt.subplots(figsize=(10, 3.4), dpi=130)
    ax.plot(eq.index, eq / eq.iloc[0] * 100, color="#d97a06", lw=1.8, label="Strategy (pessimistic entries)")
    ax.plot(spy.index, spy / spy.iloc[0] * 100, color="#7d8984", lw=1.2, label="SPY buy & hold")
    ax.set_yscale("log")
    ax.grid(axis="y", color="#e6eae7", lw=0.6)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.tick_params(colors="#5d6b66", length=0)
    ax.legend(frameon=False, fontsize=9, labelcolor="#5d6b66", loc="upper left")
    ax.set_ylabel("Growth of 100 (log)", color="#5d6b66", fontsize=9)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor="white")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "options-plan"
    if cmd == "options-plan":
        print(json.dumps(options_plan(), indent=1))
    elif cmd == "options-input":
        options_input(sys.argv[2])
    elif cmd == "backtest-card":
        backtest_card()
