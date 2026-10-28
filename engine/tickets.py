"""Turn ready setups into sized trade tickets for the user's account (data/account.json)."""
from __future__ import annotations

import json
import math
from pathlib import Path

from .data import DATA

DEFAULT_ACCOUNT = {
    "equity": 10_000,            # update as the account grows
    "monthly_deposit": 1_500,
    "mode": "growth_cash",       # growth_cash below 100k; switch to "standard" above
    "max_positions": 2,
    "max_position_pct": 1.0,     # share of equity one position may use (cash only, no margin)
    "risk_pct": 0.05,            # rarely binds with ≤3% stops; cash is the limit
    "chase_limit_pct": 1.0,      # buy-stop-limit: don't pay more than trigger + this %
    "exit_mode": "ladder",
    "use_undercut": False,       # undercut entries lost money in growth-mode testing
    "idle": "SPY",               # park idle cash here; hold cash instead on days a ticket is live
}


def load_account(path: Path | None = None) -> dict:
    p = path or DATA / "account.json"
    acct = dict(DEFAULT_ACCOUNT)
    if p.exists():
        acct.update(json.loads(p.read_text()))
    return acct


def ticket(c: dict, acct: dict, regime: int) -> dict:
    s = c["setup"]
    trig, max_stop, t1 = s["trigger"], s["max_stop"], s["t1"]
    rf = {2: 1.0, 1: 0.5, 0: 0.0}[regime]
    eq = acct["equity"]
    buy_stop = round(trig + 0.01, 2)
    limit = round(trig * (1 + acct["chase_limit_pct"] / 100), 2)
    risk_ps = max(buy_stop - max_stop, 0.01)
    by_risk = eq * acct["risk_pct"] * (rf if rf > 0 else 1.0) / risk_ps
    by_cash = eq * acct["max_position_pct"] * (rf if rf > 0 else 1.0) / limit
    shares = max(int(math.floor(min(by_risk, by_cash))), 0)
    q = shares // 4
    trims = ([{"when": f"price hits {t1:.2f} (first target)", "sell": q, "then": f"move stop to {buy_stop:.2f} (breakeven)"},
              {"when": f"daily close below 8 EMA (now {c['ema8']:.2f})", "sell": q},
              {"when": f"daily close below 21 EMA (now {c['ema21']:.2f})", "sell": q},
              {"when": f"daily close below 50 EMA (now {c['ema50']:.2f})", "sell": shares - 3 * q}]
             if acct.get("exit_mode", "ladder") == "ladder" else
             [{"when": "after 4 trading days, if above entry", "sell": shares // 2, "then": "move stop to breakeven"},
              {"when": f"daily close below the {acct.get('trail_sma', 10)}-day SMA", "sell": shares - shares // 2}])
    return {
        "ticker": c["ticker"], "allowed": regime >= 1,
        "size_note": {2: "full size", 1: "half size (caution regime)", 0: "risk-off: wait (sized for when it turns risk-on)"}[regime],
        "buy_stop": buy_stop, "limit": limit, "shares": shares, "cost": round(shares * buy_stop, 2),
        "pct_of_account": round(100 * shares * buy_stop / eq, 1),
        "max_stop": round(max_stop, 2), "risk_at_max_stop": round(shares * risk_ps, 2),
        "risk_pct_of_account": round(100 * shares * risk_ps / eq, 2),
        "stop_rule": f"stop = entry-day low; if that low is below {max_stop:.2f} at the time of the fill, sell / don't take it",
        "undercut_entry": (f"alternative: if it dips below {s['undercut']:.2f} and reclaims it, buy the reclaim, stop at the day's low"
                           if acct.get("use_undercut") and c.get("kind") != "EP" else ""),
        "kind": c.get("kind", "Breakout"),
        "t1": round(t1, 2), "reward_risk": round((t1 - buy_stop) / risk_ps, 1),
        "exits": trims,
    }


def tickets_for(scan: dict, acct: dict | None = None, top: int | None = None, ep: dict | None = None) -> dict:
    acct = acct or load_account()
    ready = [c for c in scan["candidates"] if c["setup"]["ready"]]
    ready.sort(key=lambda c: -(c.get("score") or 0))
    if ep:
        ready += ep.get("candidates", [])          # breakouts keep priority, as in the backtest
    regime = ep["regime"] if ep and ep.get("as_of", "") >= scan["as_of"] else scan["regime"]
    tix = [ticket(c, acct, regime) for c in ready[: top or len(ready)]]
    live = [t for t in tix if t["allowed"]][: acct["max_positions"]]
    idle = acct.get("idle", "cash")
    if live:
        need = sum(t["cost"] for t in live[:1])          # the first fill can use the whole account
        plan = (f"Sell enough {idle} at the open to hold about ${need:,.0f} in cash, then place buy-stop-limit orders on "
                f"the top {len(live)}. Whichever fills first uses the cash; cancel or shrink the other. "
                f"Move unused cash back into {idle} once the tickets expire (end of week for breakouts, end of day for EPs).") \
            if idle != "cash" else (f"Place buy-stop-limit orders on the top {len(live)}. Whichever fills first uses the cash; "
                                    f"cancel or shrink the other.")
    else:
        plan = (f"No live tickets: keep idle cash in {idle}." if idle != "cash" else "No live tickets: stay in cash.")
    return {"account": acct, "tickets": tix, "plan": plan + " Cash account, no margin."}
