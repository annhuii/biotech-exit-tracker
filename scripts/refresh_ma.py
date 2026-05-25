"""Refresh M&A deal list from SEC EDGAR full-text search.

v1 implementation is a STUB — it lists planned queries and writes a
status note but doesn't yet mutate data/ma.json. The reason: high-quality
deal parsing requires care (filtering 8-K Item 1.01 + 7.01 for biotech
SIC codes, deduping announcement/close, parsing values), and getting it
wrong silently corrupts the dataset.

When ready to extend:
  1. Hit EDGAR full-text search API for biotech SIC codes (2834, 2836).
  2. For each new 8-K, extract acquirer/target, deal value, announce date.
  3. Cross-reference against existing data/ma.json by (acquirer, target).
  4. Append new deals; do NOT modify existing curated rows automatically.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data" / "ma.json"

PLANNED_QUERIES = [
    # EDGAR full-text endpoint:
    # https://efts.sec.gov/LATEST/search-index?q=...&forms=8-K
    "merger agreement biotech pharmaceutical",
    "definitive agreement to acquire",
    "asset purchase agreement clinical-stage",
]


def main() -> int:
    data = json.loads(DATA.read_text())
    data.setdefault("_refresh_log", []).append({
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "status": "stub_run",
        "planned_queries": PLANNED_QUERIES,
        "note": "Auto-ingest not yet enabled; curated entries unchanged.",
    })
    # Keep log bounded.
    data["_refresh_log"] = data["_refresh_log"][-12:]
    DATA.write_text(json.dumps(data, indent=2))
    print("Stub run recorded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
