"""Compare a call (or call debit spread) with shares for a setup, from live Robinhood option quotes.

Input JSON (stdin or file), one object per ticker:
{
  "ticker": "ELF", "spot": 113.17, "trigger": 118.29, "stop": 116.28, "t1": 132.37, "adr": 3.4,
  "account": 100000, "risk_pct": 0.02, "regime_factor": 1.0, "dte": 80,
  "calls": [{"strike": 110, "mark": 14.48, "bid": 13.75, "ask": 15.2, "delta": 0.61, "gamma": 0.0122,
             "theta": -0.082, "iv": 0.596, "oi": 396, "expiration": "2027-01-15"}, ...]
}
Output: the chosen structure with per-contract risk at the stop, value at T1, contracts for the risk budget,
R:R versus shares, liquidity flags, and a one-line summary for the report.

Valuation is a delta-gamma Taylor expansion from today's spot (theta over the expected hold is subtracted),
so it is an estimate. It ignores IV changes, which usually fall after a breakout.
"""
from __future__ import annotations

import json
import math
import sys


def _val(c: dict, s0: float, s: float, days: float) -> float:
    ds = s - s0
    delta = min(max(c["delta"] + c["gamma"] * ds, 0.0), 1.0)
    # integrate delta linearly: V = mark + Δ·ds + ½Γ·ds², clamp so delta stays in [0,1]
    v = c["mark"] + c["delta"] * ds + 0.5 * c["gamma"] * ds * ds
    if delta in (0.0, 1.0):  # beyond the convex region, fall back to intrinsic-ish bounds
        v = max(v, max(s - c["strike"], 0.0))
    v += c.get("theta", 0.0) * days
    return max(v, 0.0)


def evaluate(x: dict, hold_days_to_t1: float = 10, max_spread: float = 0.06, min_oi: int = 500) -> dict:
    s0, trig, stop, t1 = x["spot"], x["trigger"], x["stop"], x["t1"]
    budget = x.get("account", 100_000) * x.get("risk_pct", 0.02) * x.get("regime_factor", 1.0)
    stock_rr = (t1 - trig) / (trig - stop) if trig > stop else float("nan")
    best = None
    for c in x["calls"]:
        mid = c["mark"]
        spread = (c["ask"] - c["bid"]) / mid if mid > 0 else 1.0
        # delta at the entry (trigger) price
        d_entry = c["delta"] + c["gamma"] * (trig - s0)
        entry_cost = _val(c, s0, trig, 0) + (c["ask"] - c["bid"]) / 2       # pay half the spread
        at_stop = _val(c, s0, stop, 1) - (c["ask"] - c["bid"]) / 2           # sell at bid side
        at_t1 = _val(c, s0, t1, hold_days_to_t1) - (c["ask"] - c["bid"]) / 2
        loss = max(min(entry_cost - at_stop, entry_cost), 1e-9) * 100
        gain = (at_t1 - entry_cost) * 100
        rec = {
            **c, "spread_pct": round(100 * spread, 1), "delta_at_entry": round(d_entry, 2),
            "est_entry_price": round(entry_cost, 2), "loss_per_contract_at_stop": round(loss, 0),
            "gain_per_contract_at_t1": round(gain, 0), "rr": round(gain / loss, 2),
            "contracts": int(budget // loss), "liquid": spread <= max_spread and c.get("oi", 0) >= min_oi,
        }
        in_band = 0.5 <= d_entry <= 0.75
        key = (rec["liquid"], in_band, rec["rr"])
        if best is None or key > best[0]:
            best = (key, rec)
    if best is None:
        return {"ticker": x["ticker"], "choice": "shares", "summary": "No option quotes supplied; trade shares."}
    o = best[1]
    realized = x.get("adr", 3) / 100 * math.sqrt(252) * 0.8
    iv_rich = o.get("iv", 0) > 1.3 * realized
    weekly_theta = abs(o.get("theta", 0)) * 5 * 100
    prefer_option = o["liquid"] and o["rr"] > stock_rr
    exp = o.get("expiration", "")
    if not o["liquid"]:
        summary = (f"Options too thin ({o['spread_pct']}% wide, OI {o.get('oi', 0)}); trade shares. "
                   f"Stock R:R {stock_rr:.1f}R.")
        choice = "shares"
    else:
        summary = (f"{exp} {o['strike']:g}C ≈ {o['est_entry_price']:.2f} at the trigger (Δ {o['delta_at_entry']}); "
                   f"risk ≈ ${o['loss_per_contract_at_stop']:.0f}/contract at the stop, ≈ ${o['gain_per_contract_at_t1']:.0f} at target "
                   f"→ {o['rr']}R vs {stock_rr:.1f}R for shares; {o['contracts']} contracts for a ${budget:,.0f} risk budget; "
                   f"theta ≈ ${weekly_theta:.0f}/week.")
        if iv_rich:
            summary += f" IV {o['iv']:.0%} is rich vs ~{realized:.0%} realized: consider a debit spread up to the target strike."
        choice = "call" if prefer_option else "shares"
        summary = ("Calls favored: " if prefer_option else "Shares favored: ") + summary
    return {"ticker": x["ticker"], "choice": choice, "stock_rr": round(stock_rr, 2), "best_call": o,
            "iv_rich": iv_rich, "summary": summary}


if __name__ == "__main__":
    data = json.load(open(sys.argv[1]) if len(sys.argv) > 1 else sys.stdin)
    items = data if isinstance(data, list) else [data]
    out = {r["ticker"]: r for r in (evaluate(x) for x in items)}
    print(json.dumps(out, indent=1))
