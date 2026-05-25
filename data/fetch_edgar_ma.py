#!/usr/bin/env python3
"""
fetch_edgar_ma.py

Systematically pulls biotech/pharma M&A acquisition records from SEC EDGAR.

Strategy:
  SC 14D9   — Solicitation/Recommendation Statement filed by the TARGET
              company in response to a tender offer.
  DEFM14A   — Definitive Merger Proxy filed by the TARGET for shareholder vote.

Both have the TARGET as the filer.  SIC code is available directly in EFTS
response (sics[] field) — no extra submissions API lookup needed.

For each qualifying target we extract from the filing document:
  - acquirer name
  - offer price per share
  - total transaction value (USD billions)

Output: data/edgar_ma_pull.json
"""

import requests
import time
import json
import re
from collections import defaultdict

# ── Config ─────────────────────────────────────────────────────────────────────

BIOTECH_SICS = {"2830", "2833", "2835", "2836", "8731"}

HEADERS = {
    "User-Agent": "biotech-tracker-research researcher@biotechtracker.io",
    "Accept-Encoding": "gzip, deflate",
}

EFTS_BASE   = "https://efts.sec.gov/LATEST/search-index"
ARCH_BASE   = "https://www.sec.gov/Archives/edgar/data"

# SC 14D9 = correct EDGAR form name (no hyphen after D)
# DEFM14A = definitive merger proxy
FORM_TYPES  = ["SC 14D9", "DEFM14A"]

START_YEAR  = 2021
END_YEAR    = 2026
END_DATE    = "2026-05-24"
DELAY       = 0.12       # ≤ 10 req/sec
MIN_VALUE_B = 0.5        # $500M threshold for "filtered" output

OUTPUT_PATH = "/Users/annhuiching/Library/CloudStorage/OneDrive-Personal/coding/pharma website/data/edgar_ma_pull.json"

# ── HTTP helpers ───────────────────────────────────────────────────────────────

def rget(url, params=None, raw=False):
    time.sleep(DELAY)
    r = requests.get(url, headers=HEADERS, params=params, timeout=30)
    if r.status_code == 429:
        print("  [rate-limited] sleeping 10s")
        time.sleep(10)
        r = requests.get(url, headers=HEADERS, params=params, timeout=30)
    r.raise_for_status()
    return r if raw else r.json()

# ── EDGAR collection ───────────────────────────────────────────────────────────

def collect_biotech_filers(form_type):
    """
    Paginate EDGAR EFTS for form_type (2021-END_DATE).
    Filter to biotech SIC codes using the sics[] field in the EFTS response.
    Skip amendments (file_type ending in /A).

    Returns dict: cik_str -> {"name": str, "sic": str, "filings": [{"acc", "date"}]}
    """
    print(f"\n=== {form_type}: collecting biotech filers ===")
    out = defaultdict(lambda: {"name": "", "sic": "", "filings": []})

    for year in range(START_YEAR, END_YEAR + 1):
        startdt = f"{year}-01-01"
        enddt   = END_DATE if year == END_YEAR else f"{year}-12-31"
        from_   = 0
        total   = None
        year_biotech = 0

        while total is None or from_ < total:
            params = {
                "forms":     form_type,
                "dateRange": "custom",
                "startdt":   startdt,
                "enddt":     enddt,
                "from":      from_,
            }
            data = rget(EFTS_BASE, params)
            hits = data.get("hits", {})

            if total is None:
                total = hits.get("total", {}).get("value", 0)
                print(f"  {year}: {total} {form_type} filings total")

            for hit in hits.get("hits", []):
                src = hit.get("_source", {})

                # Skip amendments
                file_type = src.get("file_type", "") or src.get("form", "")
                if file_type.endswith("/A"):
                    continue

                # SIC is available directly — filter here
                sics = src.get("sics", [])
                sic  = str(sics[0]) if sics else ""
                if sic not in BIOTECH_SICS:
                    continue

                # CIK — strip leading zeros for use as dict key and in URLs
                ciks = src.get("ciks", [])
                if not ciks:
                    continue
                cik = str(int(ciks[0]))  # "0001661460" -> "1661460"

                name = src.get("display_names", [""])[0]
                # Clean display_name: "Poseida Therapeutics, Inc.  (PSTX)  (CIK 0001661460)"
                name = re.sub(r"\s*\([^)]+\)\s*$", "", name).strip()
                name = re.sub(r"\s*\([^)]+\)\s*$", "", name).strip()

                acc  = src.get("adsh", "")
                date = src.get("file_date", "")

                out[cik]["name"] = out[cik]["name"] or name
                out[cik]["sic"]  = out[cik]["sic"]  or sic
                out[cik]["filings"].append({"form": form_type, "acc": acc, "date": date})
                year_biotech += 1

            from_ += 100

        print(f"  {year}: {year_biotech} biotech {form_type} filings")

    print(f"  Total unique biotech filers ({form_type}): {len(out)}")
    return dict(out)

# ── Filing document extraction ─────────────────────────────────────────────────

def fetch_filing_text(cik, accession, max_bytes=150_000):
    """Return up to max_bytes of stripped text from the main filing document.

    EDGAR archive layout:
      /Archives/edgar/data/{CIK}/{accession_no_dashes}/index.json
      response: { "directory": { "item": [ { "name": "...", "size": "..." }, ... ] } }

    Main document = the largest .htm/.html file that isn't an index header.
    """
    try:
        acc_nd  = accession.replace("-", "")
        idx_url = f"{ARCH_BASE}/{cik}/{acc_nd}/index.json"
        idx     = rget(idx_url)

        items = idx.get("directory", {}).get("item", [])

        # Find the main filing document: htm/html file, not an index, prefer largest
        candidates = []
        for it in items:
            name = it.get("name", "")
            nl   = name.lower()
            if not nl.endswith((".htm", ".html")):
                continue
            if "index" in nl:           # skip *-index.html, *-index-headers.html
                continue
            try:
                size = int(it.get("size", 0) or 0)
            except Exception:
                size = 0
            candidates.append((size, name))

        if not candidates:
            return ""

        # Largest non-index htm
        candidates.sort(reverse=True)
        main_filename = candidates[0][1]

        doc_url = f"{ARCH_BASE}/{cik}/{acc_nd}/{main_filename}"
        r       = rget(doc_url, raw=True)
        content = r.content[:max_bytes].decode("utf-8", errors="replace")

        # Strip HTML
        content = re.sub(r"<[^>]{1,500}>", " ", content)
        content = re.sub(r"&(?:[a-z]{2,8}|#[0-9]{2,5});", " ", content, flags=re.IGNORECASE)
        content = re.sub(r"\s+", " ", content)
        return content

    except Exception:
        return ""


# ── Text extraction patterns ───────────────────────────────────────────────────

def extract_price_per_share(text):
    patterns = [
        r"\$\s*(\d{1,4}(?:\.\d{2})?)\s+(?:in\s+cash\s+)?per\s+(?:share|Share|common\s+share)",
        r"consideration\s+of\s+\$\s*(\d{1,4}(?:\.\d{2})?)\s+per\s+(?:share|Share)",
        r"purchase\s+price\s+of\s+\$\s*(\d{1,4}(?:\.\d{2})?)\s+per\s+(?:share|Share)",
        r"Merger\s+Consideration[^$]{0,400}\$\s*(\d{1,4}(?:\.\d{2})?)",
        r"per\s+(?:share|Share)[^.]{0,60}\$\s*(\d{1,4}(?:\.\d{2})?)",
        r"(\d{1,4}(?:\.\d{1,2})?)\s+per\s+(?:share|Share)\s+in\s+cash",
    ]
    for pat in patterns:
        m = re.search(pat, text[:60_000], re.IGNORECASE)
        if m:
            try:
                v = float(m.group(1).replace(",", ""))
                if 1.0 < v < 2000.0:
                    return v
            except Exception:
                pass
    return None


def extract_total_value(text):
    patterns = [
        r"aggregate\s+(?:consideration|value|purchase\s+price|equity\s+value)[^$\d]{0,80}\$\s*([\d,]+(?:\.\d+)?)\s*(billion|million|B\b|M\b)",
        r"approximately\s+\$\s*([\d,]+(?:\.\d+)?)\s*(billion|million)\s+(?:in\s+)?(?:cash|aggregate|total)",
        r"valued?\s+at\s+approximately\s+\$\s*([\d,]+(?:\.\d+)?)\s*(billion|million)",
        r"transaction\s+(?:is\s+)?valued?\s+at[^$]{0,50}\$\s*([\d,]+(?:\.\d+)?)\s*(billion|million)",
        r"\$\s*([\d,]+(?:\.\d+)?)\s*(billion|million)\s+(?:all[\-\s]cash|cash)\s+(?:transaction|deal|acquisition|merger)",
        r"total\s+(?:consideration|value)[^$\d]{0,80}\$\s*([\d,]+(?:\.\d+)?)\s*(billion|million)",
        r"enterprise\s+value[^$\d]{0,80}\$\s*([\d,]+(?:\.\d+)?)\s*(billion|million)",
    ]
    for pat in patterns:
        m = re.search(pat, text[:100_000], re.IGNORECASE)
        if m:
            try:
                val  = float(m.group(1).replace(",", ""))
                unit = m.group(2).lower()
                if unit in ("billion", "b"):
                    if 0.05 < val < 300:
                        return round(val, 2)
                else:
                    if val > 50:
                        return round(val / 1000, 3)
            except Exception:
                pass
    return None


def extract_acquirer(text, target_name):
    chunk = text[:30_000]

    sub_re = re.compile(
        r"acquisition\s+(?:sub(?:sidiary)?|corp(?:oration)?|co(?:mpany)?)|merger\s+sub",
        re.IGNORECASE
    )
    bad = {
        target_name.lower(), "the company", "company", "our", "we", "us", "you",
        "merger sub", "acquisition corp", "acquisition co", "shareholders",
        "stockholders", "board of directors",
    }

    # Name-capturing patterns — ordered most-specific to least
    patterns = [
        r"[Oo]ffer\s+(?:by|from|made\s+by)\s+([A-Z][A-Za-z0-9&\s,\.\-\']+?(?:Inc\.?|Corp\.?|Ltd\.?|LLC|Co\.?|plc|SE|AG|NV|SA|GmbH|B\.V\.|L\.P\.))",
        r"\bParent[\":\s\']+([A-Z][A-Za-z0-9&\s,\.\-\']+?(?:Inc\.?|Corp\.?|Ltd\.?|LLC|Co\.?|plc|SE|AG|NV|SA|GmbH|B\.V\.|L\.P\.))",
        r"([A-Z][A-Za-z0-9&\s,\.\-\']+?(?:Inc\.?|Corp\.?|Ltd\.?|LLC|Co\.?|plc|SE|AG|NV|SA|GmbH|B\.V\.|L\.P\.))\s+has\s+commenced",
        r"to\s+be\s+acquired\s+by\s+([A-Z][A-Za-z0-9&\s,\.\-\']+?(?:Inc\.?|Corp\.?|Ltd\.?|LLC|Co\.?|plc|SE|AG|NV|SA|GmbH|B\.V\.|L\.P\.))",
        r"[Mm]erger\s+with\s+([A-Z][A-Za-z0-9&\s,\.\-\']+?(?:Inc\.?|Corp\.?|Ltd\.?|LLC|Co\.?|plc|SE|AG|NV|SA|GmbH|B\.V\.|L\.P\.))",
        r"[Mm]erger\s+[Aa]greement\s+with\s+([A-Z][A-Za-z0-9&\s,\.\-\']+?(?:Inc\.?|Corp\.?|Ltd\.?|LLC|Co\.?|plc|SE|AG|NV|SA|GmbH|B\.V\.|L\.P\.))",
        r"([A-Z][A-Za-z0-9&\s,\.\-\']+?(?:Inc\.?|Corp\.?|Ltd\.?|LLC|Co\.?|plc|SE|AG|NV|SA|GmbH|B\.V\.|L\.P\.))\s+(?:has\s+)?agreed\s+to\s+acquire",
    ]

    for pat in patterns:
        for m in re.finditer(pat, chunk):
            c = m.group(1).strip().rstrip(".,;:")
            c = re.sub(r"\s+and\s+.*$", "", c, flags=re.IGNORECASE).strip()
            cl = c.lower()
            if (len(c) > 4
                    and cl not in bad
                    and not sub_re.search(c)
                    and not cl.startswith("the ")):
                return c

    return None


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    # Step 1 — collect all biotech filers for both form types
    all_filers = {}
    for form_type in FORM_TYPES:
        filers = collect_biotech_filers(form_type)
        for cik, info in filers.items():
            if cik not in all_filers:
                all_filers[cik] = info
            else:
                all_filers[cik]["filings"].extend(info["filings"])

    print(f"\n=== Total unique biotech acquisition targets: {len(all_filers)} ===")

    # Step 2 — fetch filing document and extract deal terms
    print("\n=== Extracting deal info from filings ===")
    results = []
    errors  = 0

    for i, (cik, info) in enumerate(all_filers.items()):
        if i % 20 == 0:
            print(f"  {i}/{len(all_filers)} processed, {len(results)} records so far")

        # Sort filings chronologically; use earliest (= announcement proxy)
        filings = sorted(info["filings"], key=lambda x: x["date"] or "")
        if not filings:
            continue

        best = filings[0]
        acc  = best["acc"]
        date = best["date"]
        form = best["form"]

        text = fetch_filing_text(cik, acc)
        if not text:
            errors += 1
            continue

        name     = info["name"]
        acquirer  = extract_acquirer(text, name)
        price     = extract_price_per_share(text)
        total_val = extract_total_value(text)

        results.append({
            "cik":               cik,
            "target":            name,
            "announce_date":     date,
            "year":              int(date[:4]) if date else None,
            "form_type":         form,
            "acquirer":          acquirer,
            "offer_price_usd":   price,
            "total_value_usd_b": total_val,
            "sic":               info.get("sic", ""),
        })

    # Step 3 — sort and output
    results_sorted   = sorted(results,
                               key=lambda x: x.get("announce_date") or "",
                               reverse=True)
    results_filtered = [r for r in results_sorted
                        if r["total_value_usd_b"] and r["total_value_usd_b"] >= MIN_VALUE_B]

    print(f"\n=== DONE ===")
    print(f"Total biotech targets found:          {len(results)}")
    print(f"Deals with extracted value >= $500M:  {len(results_filtered)}")
    print(f"Errors (no filing text):              {errors}")

    from collections import Counter
    year_counts = Counter(r["year"] for r in results if r["year"])
    print("\nYear breakdown (all targets):")
    for yr in sorted(year_counts):
        print(f"  {yr}: {year_counts[yr]}")

    out = {
        "generated":        "2026-05-25",
        "total_targets":    len(results),
        "deals_above_500m": len(results_filtered),
        "all_targets":      results_sorted,
        "deals_filtered":   results_filtered,
    }

    with open(OUTPUT_PATH, "w") as f:
        json.dump(out, f, indent=2)

    print(f"\nOutput: {OUTPUT_PATH}")
    print("\nDeals found with extracted value >= $500M:")
    for d in results_filtered:
        yr  = (d["announce_date"] or "????")[:7]
        acq = d["acquirer"] or "?"
        tgt = d["target"]
        val = d["total_value_usd_b"]
        print(f"  {yr} | {acq:<35} / {tgt:<40} | ${val}B")


if __name__ == "__main__":
    main()
