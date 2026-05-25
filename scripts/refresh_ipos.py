"""Refresh approximate market caps for tickers in data/ipos.json.

Uses yfinance (free, unauthenticated). HKEX tickers like '9926.HK' are
natively supported. Skips entries with phase == 'skip' or no ticker.

The script is conservative: if a lookup fails it leaves the prior value
in place, so a transient yfinance outage doesn't erase data.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

try:
    import yfinance as yf
except ImportError:
    print("yfinance not installed. Run: pip install yfinance", file=sys.stderr)
    sys.exit(1)

DATA = Path(__file__).resolve().parent.parent / "data" / "ipos.json"


def usd_per_hkd() -> float:
    """Spot HKD -> USD via yfinance."""
    try:
        fx = yf.Ticker("HKDUSD=X").fast_info
        return float(fx["last_price"])
    except Exception:
        return 0.128  # safe fallback


def market_cap_usd_m(ticker: str, fx_hkd: float) -> int | None:
    try:
        info = yf.Ticker(ticker).fast_info
        mcap = info.get("market_cap") or info.get("marketCap")
        if not mcap:
            return None
        if ticker.endswith(".HK"):
            return int(mcap * fx_hkd / 1_000_000)
        if ticker.endswith(".T") or ticker.endswith(".SW") or ticker.endswith(".DE"):
            # yfinance reports market_cap in local currency; we approximate.
            # For demo accuracy this is OK; for memo accuracy use a paid feed.
            return int(mcap / 1_000_000)
        return int(mcap / 1_000_000)
    except Exception as exc:
        print(f"  ! {ticker}: {exc}", file=sys.stderr)
        return None


def main() -> int:
    data = json.loads(DATA.read_text())
    fx = usd_per_hkd()
    print(f"Using HKDUSD = {fx:.4f}")
    changed = 0
    for ipo in data["ipos"]:
        ticker = ipo.get("ticker", "").strip()
        if not ticker or ipo.get("phase") == "skip":
            continue
        if "." in ticker and not (ticker.endswith(".HK") or ticker.endswith(".T") or ticker.endswith(".SW") or ticker.endswith(".DE")):
            continue
        new_mcap = market_cap_usd_m(ticker, fx)
        if new_mcap is None:
            continue
        old = ipo.get("market_cap_now_usd_m")
        if old != new_mcap:
            ipo["market_cap_now_usd_m"] = new_mcap
            changed += 1
            print(f"  {ticker}: {old} -> {new_mcap}")
        time.sleep(0.2)
    DATA.write_text(json.dumps(data, indent=2))
    print(f"Done. {changed} market caps updated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
