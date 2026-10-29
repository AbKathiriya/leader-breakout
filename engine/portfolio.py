"""Daily position tracking and order tickets (buy and sell) for the growth-mode account.

The agent reads Robinhood (positions, recent filled orders, portfolio value) with the MCP and writes them to JSON; this
module reconciles them with data/positions.json (the strategy's memory of each trade), applies the exit rules to the
latest daily bars, and prints the orders for the next session.

  python -m engine.portfolio sync  rh_positions.json rh_fills.json [rh_equity]
  python -m engine.portfolio orders                 → data/orders_latest.json + a plain-text message on stdout

rh_positions.json: [{"symbol", "quantity", "average_buy_price"}]
rh_fills.json:     [{"symbol", "side", "quantity", "price", "date"}]   (filled orders, last ~10 days)
"""
from __future__ import annotations

import contextlib
import io
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

from .data import DATA
from .framework import Params, first_target
from .tickets import load_account, tickets_for

POS = DATA / "positions.json"
IDLE_ETFS = {"SPY", "QQQ"}


def _bars(tickers: list[str], period: str = "1y") -> dict[str, pd.DataFrame]:
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        d = yf.download(sorted(set(tickers) | {"SPY", "QQQ"}), period=period, auto_adjust=False, progress=False,
                        group_by="ticker", threads=True)
    out = {}
    for t in set(tickers) | {"SPY", "QQQ"}:
        try:
            df = d[t][["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
        except KeyError:
            continue
        now_et = pd.Timestamp.now(tz="America/New_York")
        if len(df) and df.index[-1].date() == now_et.date() and now_et.hour * 60 + now_et.minute < 16 * 60 + 15:
            df = df.iloc[:-1]                         # drop today's still-forming bar
        for n in (8, 21, 50):
            df[f"e{n}"] = df.Close.ewm(span=n, adjust=False, min_periods=n).mean()
        df["adr"] = 100 * ((df.High / df.Low).rolling(20).mean() - 1)
        out[t] = df
    return out


def _regime(b) -> int:
    above = [all(b[k].Close.iloc[-1] > b[k][f"e{n}"].iloc[-1] for k in ("SPY", "QQQ")) for n in (8, 21, 50)]
    return 2 if all(above) else (1 if above[2] else 0)


def load_positions() -> dict:
    return json.loads(POS.read_text()) if POS.exists() else {}


def sync(rh_positions: list, rh_fills: list, rh_equity: float | None = None) -> dict:
    """Reconcile Robinhood holdings with the strategy's trade records."""
    p = Params()
    book = load_positions()
    held = {r["symbol"]: float(r["quantity"]) for r in rh_positions if float(r["quantity"]) > 0}
    avg = {r["symbol"]: float(r["average_buy_price"]) for r in rh_positions}
    strat = [t for t in held if t not in IDLE_ETFS]
    b = _bars(strat) if strat else {}
    for t in strat:
        if t not in book:                              # new position → open a record from its buy fills
            buys = sorted([f for f in rh_fills if f["symbol"] == t and f["side"] == "buy"], key=lambda f: f["date"])
            d0 = buys[0]["date"][:10] if buys else str(pd.Timestamp.today().date())
            entry = avg[t]
            df = b.get(t)
            adr = float(df.adr.loc[:d0].iloc[-1]) if df is not None and len(df.loc[:d0]) else 4.0
            max_stop = entry * (1 - min(p.max_risk_adr * adr, p.max_risk_pct) / 100)
            day = df.loc[d0] if df is not None and pd.Timestamp(d0) in df.index else None
            stop = max(float(day.Low), max_stop) if day is not None else max_stop
            if stop >= entry:                          # fill price doesn't match the day's bar (bad data): use max stop
                stop = max_stop
            hi = df.High.to_numpy(float) if df is not None else np.array([entry])
            upto = len(df.loc[:d0]) - 1 if df is not None else 0
            book[t] = {"entry_date": d0, "entry": round(entry, 4), "shares0": held[t], "max_stop": round(max_stop, 4),
                       "stop": round(stop, 4), "t1": round(first_target(entry, stop, hi, upto, p), 4),
                       "t1_hit": False, "did8": False, "did21": False, "stop_from_day_low": day is not None}
        else:
            rec = book[t]
            if not rec.get("stop_from_day_low") and t in b and pd.Timestamp(rec["entry_date"]) in b[t].index:
                low = float(b[t].loc[rec["entry_date"]].Low)  # entry day has closed → tighten to its low
                rec["stop"] = round(max(low, rec["max_stop"]), 4) if low < rec["entry"] else rec["max_stop"]
                rec["stop_from_day_low"] = True
        book[t]["shares"] = held[t]
    for t in list(book):
        if t not in held:
            book.pop(t)                                # closed out
    POS.write_text(json.dumps(book, indent=1))
    if rh_equity:
        acct_path = DATA / "account.json"
        acct = json.loads(acct_path.read_text()) if acct_path.exists() else {}
        acct["equity"] = round(float(rh_equity), 2)
        acct_path.write_text(json.dumps(acct, indent=1))
    return book


def orders() -> dict:
    acct = load_account()
    book = load_positions()
    b = _bars(list(book)) if book else _bars([])
    regime = _regime(b)
    asof = str(b["SPY"].index[-1].date())
    sells, notes = [], []
    for t, r in book.items():
        df = b.get(t)
        if df is None or not len(df):
            notes.append(f"{t}: no price data")
            continue
        last = df.iloc[-1]
        sh, q = r["shares"], max(1, int(r["shares0"] // 4))
        c, h, l = float(last.Close), float(last.High), float(last.Low)
        entry_day = str(df.index[-1].date()) == str(r["entry_date"])[:10]   # day's low includes pre-entry trading
        if l <= r["stop"] and not entry_day:
            sells.append({"ticker": t, "action": "SELL ALL", "shares": sh, "type": "market at open",
                          "why": f"stop {r['stop']:.2f} was hit (low {l:.2f}); exit if the stop order didn't already fill"})
            continue
        if not r["t1_hit"] and h >= r["t1"]:
            r["t1_hit"], r["stop"] = True, r["entry"]
            sells.append({"ticker": t, "action": "SELL", "shares": min(q, sh), "type": "market at open (or it filled at your T1 limit)",
                          "why": f"first target {r['t1']:.2f} reached", "then": f"move stop on the rest to breakeven {r['entry']:.2f}"})
            sh -= min(q, sh)
        if sh and r["t1_hit"] and not r["did8"] and c < last.e8:
            r["did8"] = True
            sells.append({"ticker": t, "action": "SELL", "shares": min(q, sh), "type": "market at open",
                          "why": f"closed {c:.2f} below the 8 EMA {last.e8:.2f}"})
            sh -= min(q, sh)
        if sh and r["t1_hit"] and not r["did21"] and c < last.e21:
            r["did21"] = True
            sells.append({"ticker": t, "action": "SELL", "shares": min(q, sh), "type": "market at open",
                          "why": f"closed {c:.2f} below the 21 EMA {last.e21:.2f}"})
            sh -= min(q, sh)
        if sh and c < last.e50:
            sells.append({"ticker": t, "action": "SELL ALL", "shares": sh, "type": "market at open",
                          "why": f"closed {c:.2f} below the 50 EMA {last.e50:.2f}"})
            sh = 0
        if sh:
            notes.append(f"{t}: hold {sh:g} sh · stop {r['stop']:.2f} · "
                         + (f"T1 {r['t1']:.2f} (sell {q} there)" if not r["t1_hit"] else "T1 done") +
                         f" · close {c:.2f} vs 8/21/50 EMA {last.e8:.2f}/{last.e21:.2f}/{last.e50:.2f}")
    POS.write_text(json.dumps(book, indent=1))

    slots = acct["max_positions"] - len(book)
    buys = []
    if slots > 0:
        scan = json.loads((DATA / "scan_latest.json").read_text())
        ep_path = DATA / "ep_latest.json"
        ep = json.loads(ep_path.read_text()) if ep_path.exists() else None
        if ep and ep.get("as_of") != asof:
            ep = None                                    # EP tickets are only valid the session after the gap day
        tk = tickets_for(scan, acct, ep=ep)
        for t in tk["tickets"]:
            if t["ticker"] in book or len(buys) >= slots:
                continue
            if not t["allowed"]:
                continue
            buys.append(t)
    res = {"as_of": asof, "regime": regime, "account": acct, "sells": sells, "buys": buys, "holding": notes}
    (DATA / "orders_latest.json").write_text(json.dumps(res, indent=1, default=float))
    return res


def message(res: dict) -> str:
    rtxt = {2: "Risk-on", 1: "Caution (half size)", 0: "Risk-off (no new buys)"}[res["regime"]]
    lines = [f"Leader Breakout — orders for the session after {res['as_of']} · {rtxt} · account ${res['account']['equity']:,.0f}"]
    if res["sells"]:
        lines.append("SELL")
        for s in res["sells"]:
            lines.append(f"• {s['action']} {s['ticker']} {s['shares']:g} sh, {s['type']} — {s['why']}"
                         + (f"; then {s['then']}" if s.get("then") else ""))
    if res["buys"]:
        need = sum(t["cost"] for t in res["buys"][:1])
        lines.append(f"BUY (sell ~${need:,.0f} of SPY at the open first)")
        for t in res["buys"]:
            valid = "tomorrow only" if t.get("kind") == "EP" else "good through Friday"
            lines.append(f"• {t['kind']} {t['ticker']}: buy {t['shares']} sh, stop {t['buy_stop']:.2f} limit {t['limit']:.2f} ({valid}). "
                         f"Once filled: sell-stop {t['shares']} at {t['max_stop']:.2f}, limit-sell {t['shares'] // 4} at {t['t1']:.2f}. "
                         f"Worst case ${t['risk_at_max_stop']:,.0f}")
    if not res["sells"] and not res["buys"]:
        lines.append("No orders. " + ("Market is risk-off." if res["regime"] == 0 else "No new setups triggered."))
    if res["holding"]:
        lines.append("HOLDING")
        lines += [f"• {n}" for n in res["holding"]]
    return "\n".join(lines)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "orders"
    if cmd == "sync":
        pos = json.loads(Path(sys.argv[2]).read_text())
        fills = json.loads(Path(sys.argv[3]).read_text()) if len(sys.argv) > 3 else []
        eq = float(sys.argv[4]) if len(sys.argv) > 4 else None
        print(json.dumps(sync(pos, fills, eq), indent=1))
    else:
        print(message(orders()))
