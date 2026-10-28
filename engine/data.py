"""Universe + price data (Yahoo via yfinance), cached to parquet."""
from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)

LISTING_URL = "https://raw.githubusercontent.com/rreichel3/US-Stock-Symbols/main/{ex}/{ex}_full_tickers.json"
FIELDS = ["Open", "High", "Low", "Close", "Volume"]


def _num(x) -> float:
    try:
        return float(str(x).replace("$", "").replace(",", ""))
    except ValueError:
        return 0.0


def load_universe(refresh: bool = False, min_mcap: float = 1e8, min_price: float = 2.0) -> pd.DataFrame:
    """US common stocks with Nasdaq-classified sector/industry.

    Today's listing is used for the whole history → survivorship bias (delisted names are missing).
    """
    rows = []
    for ex in ("nasdaq", "nyse", "amex"):
        f = DATA / f"{ex}_full.json"
        if refresh or not f.exists():
            urllib.request.urlretrieve(LISTING_URL.format(ex=ex), f)
        for r in json.loads(f.read_text()):
            rows.append({
                "symbol": r["symbol"].strip(),
                "name": r.get("name", ""),
                "sector": (r.get("sector") or "").strip(),
                "industry": (r.get("industry") or "").strip(),
                "mcap": _num(r.get("marketCap")),
                "price": _num(r.get("lastsale")),
                "exchange": ex.upper(),
            })
    u = pd.DataFrame(rows).drop_duplicates("symbol")
    u = u[u.symbol.str.fullmatch(r"[A-Z]{1,5}") & (u.sector != "") & (u.industry != "")]
    # crude filters against preferreds/SPAC units/warrants that slip through
    bad = u.name.str.contains(r"Warrant|Units?\b|Preferred|Depositary Shares Each|Notes due|Rights", case=False, regex=True)
    u = u[~bad & (u.mcap >= min_mcap) & (u.price >= min_price)]
    return u.set_index("symbol").sort_index()


def _download_batch(tickers: list[str], start: str) -> dict[str, pd.DataFrame]:
    for attempt in range(4):
        try:
            d = yf.download(tickers, start=start, auto_adjust=True, progress=False, threads=True,
                            group_by="ticker", timeout=30)
            out = {}
            for t in tickers:
                try:
                    df = d[t][FIELDS] if len(tickers) > 1 else d[FIELDS]
                except KeyError:
                    continue
                df = df.dropna(subset=["Close"])
                if len(df):
                    out[t] = df
            return out
        except Exception as e:  # rate limit / transient
            wait = 10 * (attempt + 1)
            print(f"  batch failed ({e}); retry in {wait}s")
            time.sleep(wait)
    return {}


def load_prices(tickers: list[str], start: str = "2013-01-01", cache: str = "prices.parquet",
                refresh: bool = False, batch: int = 150) -> dict[str, pd.DataFrame]:
    """Wide parquet cache: columns MultiIndex (field, ticker). Returns dict of field → DataFrame (dates × tickers)."""
    path = DATA / cache
    have = None
    if path.exists() and not refresh:
        have = pd.read_parquet(path)
        missing = [t for t in tickers if t not in have["Close"].columns]
        last = have.index.max()
        stale = (pd.Timestamp.today().normalize() - last).days > 3
    else:
        missing, stale = list(tickers), False

    frames = {}
    if stale and have is not None:
        # top up all cached tickers from a little before the last date
        cached = list(have["Close"].columns)
        top_start = (have.index.max() - pd.Timedelta(days=10)).strftime("%Y-%m-%d")
        print(f"Refreshing {len(cached)} cached tickers from {top_start}")
        for i in range(0, len(cached), batch):
            frames.update(_download_batch(cached[i:i + batch], top_start))
    if missing:
        print(f"Downloading {len(missing)} tickers from {start}")
        for i in range(0, len(missing), batch):
            frames.update(_download_batch(missing[i:i + batch], start))
            print(f"  {min(i + batch, len(missing))}/{len(missing)}")

    if frames:
        new = pd.concat({t: df for t, df in frames.items()}, axis=1)  # (ticker, field)
        new = new.swaplevel(axis=1).sort_index(axis=1)
        if have is not None:
            combined = have.combine_first(new) if not stale else new.combine_first(have)
        else:
            combined = new
        combined = combined.astype("float32")
        combined.to_parquet(path)
        have = combined
    wide = {f: have[f] for f in FIELDS}
    cols = [t for t in tickers if t in wide["Close"].columns]
    return {f: wide[f][cols] for f in FIELDS}
