#!/usr/bin/env python3
"""
Fetch all US biotech/pharma IPOs from SEC EDGAR, 2021-01-01 through 2026-05-25.
"""

import json
import time
import re
import sys
from datetime import datetime, date
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

HEADERS = {"User-Agent": "biotrack/1.0 research@biotechtracker.io"}
SLEEP = 0.08

KEYWORDS = [
    "therapeutics", "biosciences", "biopharma", "biologics", "pharma",
    "oncology", "biotech", "genomics", "medicines", "biomed", "genetic",
    "immuno", "neuro", "cardio", "peptide", "molecular", "vaccine",
    "antibody", "radiopharmaceutical"
]

import os
OUTPUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "edgar_ipo_pull.json")


def sleep():
    time.sleep(SLEEP)


def fetch_json(url):
    sleep()
    req = Request(url, headers=HEADERS)
    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except HTTPError as e:
        print(f"  HTTP {e.code} for {url}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  Error fetching {url}: {e}", file=sys.stderr)
        return None


def fetch_text(url, nbytes=60000):
    sleep()
    req = Request(url, headers=HEADERS)
    try:
        with urlopen(req, timeout=30) as resp:
            return resp.read(nbytes).decode("utf-8", errors="replace")
    except HTTPError as e:
        print(f"  HTTP {e.code} for {url}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  Error fetching {url}: {e}", file=sys.stderr)
        return None


def name_matches_biotech(name):
    n = name.lower()
    return any(kw in n for kw in KEYWORDS)


def collect_candidates_for_year(year):
    """
    Use EDGAR EFTS to find all 424B4 filings in the given year.
    Return dict: {cik: {name, ticker, filings: [{accessionNumber, date, primaryDocument}]}}
    """
    start_dt = f"{year}-01-01"
    end_dt = "2026-05-25" if year == 2026 else f"{year}-12-31"

    base_url = (
        f"https://efts.sec.gov/LATEST/search-index?forms=424B4"
        f"&dateRange=custom&startdt={start_dt}&enddt={end_dt}"
    )

    candidates = {}
    offset = 0
    total_hits = None

    while True:
        url = base_url + f"&from={offset}"
        data = fetch_json(url)
        if not data:
            break

        hits = data.get("hits", {})
        if total_hits is None:
            total_hits = hits.get("total", {})
            if isinstance(total_hits, dict):
                total_hits = total_hits.get("value", 0)
            else:
                total_hits = int(total_hits) if total_hits else 0

        hit_list = hits.get("hits", [])
        if not hit_list:
            break

        for h in hit_list:
            src = h.get("_source", {})
            entity_name = src.get("entity_name", "") or src.get("display_names", [""])[0]
            cik = src.get("file_num", "") or ""
            # Try extracting CIK from _id or other fields
            cik = src.get("period_of_report", "")  # not right
            cik = h.get("_id", "").split(":")[-1] if ":" in h.get("_id", "") else ""

            # Better: use entity_id or ciks field
            ciks_field = src.get("ciks", [])
            if ciks_field:
                cik = str(ciks_field[0])
            else:
                # Try to parse from _id
                raw_id = h.get("_id", "")
                # format like "0001234567-21-000001" — first 10 digits is CIK embedded in accession
                # Actually CIK is in entity_id
                cik = src.get("entity_id", "")

            if not cik:
                continue

            # Normalize CIK
            cik_str = str(cik).lstrip("0") or "0"
            cik_padded = str(cik).zfill(10)

            if not name_matches_biotech(entity_name):
                continue

            accession = src.get("file_date", "")  # wrong field name
            accession = h.get("_id", "")  # accession number is the _id
            filing_date = src.get("file_date", "") or src.get("period_of_report", "")
            primary_doc = src.get("file_num", "")  # wrong

            # Actually the correct fields:
            accession = src.get("accession_no", "") or h.get("_id", "")
            filing_date = src.get("file_date", "")
            primary_doc = src.get("file_num", "")  # still wrong

            if cik_padded not in candidates:
                candidates[cik_padded] = {
                    "name": entity_name,
                    "ticker": src.get("period_of_report", ""),  # placeholder
                    "filings_424b4": []
                }
            candidates[cik_padded]["filings_424b4"].append({
                "accessionNumber": accession,
                "date": filing_date,
                "primaryDocument": primary_doc
            })

        offset += len(hit_list)
        if offset >= total_hits:
            break
        if len(hit_list) == 0:
            break

    return candidates, total_hits


def collect_candidates_for_year_v2(year):
    """
    Better version using correct EFTS field names.
    """
    start_dt = f"{year}-01-01"
    end_dt = "2026-05-25" if year == 2026 else f"{year}-12-31"

    # Use the full-text search API with correct pagination
    base_url = (
        f"https://efts.sec.gov/LATEST/search-index?forms=424B4"
        f"&dateRange=custom&startdt={start_dt}&enddt={end_dt}&hits.hits._source=entity_name,file_date,period_of_report,accession_no,display_names"
    )

    candidates = {}
    offset = 0
    page_size = 10

    # First probe to get total
    probe_url = base_url + f"&from=0&hits.hits.total.value=true"
    data = fetch_json(probe_url)
    if not data:
        return candidates, 0

    total_hits = 0
    hits_obj = data.get("hits", {})
    total_obj = hits_obj.get("total", {})
    if isinstance(total_obj, dict):
        total_hits = total_obj.get("value", 0)
    else:
        total_hits = int(total_obj) if total_obj else 0

    print(f"  Year {year}: total 424B4 filings = {total_hits}")

    # Process first page
    hit_list = hits_obj.get("hits", [])
    for h in hit_list:
        _parse_hit(h, candidates)

    offset = len(hit_list)

    while offset < total_hits:
        url = base_url + f"&from={offset}"
        data = fetch_json(url)
        if not data:
            break
        hit_list = data.get("hits", {}).get("hits", [])
        if not hit_list:
            break
        for h in hit_list:
            _parse_hit(h, candidates)
        offset += len(hit_list)
        if offset % 100 == 0:
            print(f"  ... processed {offset}/{total_hits}")

    return candidates, total_hits


def _parse_hit(h, candidates):
    src = h.get("_source", {})

    # Entity name
    entity_name = ""
    dn = src.get("display_names", [])
    if dn:
        # display_names can be list of strings like "COMPANY NAME (TICK) (CIK XXXX)"
        entity_name = dn[0] if isinstance(dn[0], str) else str(dn[0])
    if not entity_name:
        entity_name = src.get("entity_name", "")

    if not name_matches_biotech(entity_name):
        return

    # CIK: extract from display_names or from accession
    cik_padded = ""
    # Try to extract CIK from display_names "(CIK XXXXXXXXXX)"
    m = re.search(r"\(CIK\s+(\d+)\)", entity_name)
    if m:
        cik_padded = m.group(1).zfill(10)

    if not cik_padded:
        # Try from _id which is typically the accession number
        raw_id = h.get("_id", "")
        # accession format: XXXXXXXXXX-YY-ZZZZZZ where first 10 digits = CIK
        acc_clean = raw_id.replace("-", "")
        if len(acc_clean) >= 10:
            cik_padded = acc_clean[:10].zfill(10)

    if not cik_padded:
        return

    # Clean name (remove "(TICK) (CIK XXX)" suffix)
    clean_name = re.sub(r"\s*\([A-Z0-9/]+\)\s*\(CIK\s+\d+\)", "", entity_name).strip()
    clean_name = re.sub(r"\s*\(CIK\s+\d+\)", "", clean_name).strip()

    # Extract ticker from display_names "(TICK)"
    ticker = ""
    m2 = re.search(r"\(([A-Z]{1,5})\)\s*\(CIK", entity_name)
    if m2:
        ticker = m2.group(1)

    accession = h.get("_id", "")
    filing_date = src.get("file_date", "")

    if cik_padded not in candidates:
        candidates[cik_padded] = {
            "name": clean_name,
            "ticker": ticker,
            "filings_424b4": []
        }
    else:
        if ticker and not candidates[cik_padded]["ticker"]:
            candidates[cik_padded]["ticker"] = ticker

    candidates[cik_padded]["filings_424b4"].append({
        "accessionNumber": accession,
        "date": filing_date,
    })


def check_is_ipo(cik_padded, candidates_entry, target_years):
    """
    Fetch submissions JSON for CIK, apply IPO criteria.
    Returns (is_ipo, ipo_info_dict) or (False, None).
    """
    url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
    data = fetch_json(url)
    if not data:
        return False, None

    filings = data.get("filings", {}).get("recent", {})
    forms = filings.get("form", [])
    dates_filed = filings.get("filingDate", [])
    accessions = filings.get("accessionNumber", [])
    primary_docs = filings.get("primaryDocument", [])
    tickers_list = data.get("tickers", [])

    if not forms:
        return False, None

    # Group by form type
    s1_dates = []
    s3_dates = []
    tenk_dates = []
    tenq_dates = []
    filings_424b4 = []  # list of (date, accession, primary_doc)

    for i, form in enumerate(forms):
        fd = dates_filed[i] if i < len(dates_filed) else ""
        acc = accessions[i] if i < len(accessions) else ""
        pdoc = primary_docs[i] if i < len(primary_docs) else ""

        if form == "S-1" or form == "S-1/A":
            s1_dates.append(fd)
        elif form == "S-3" or form == "S-3/A":
            s3_dates.append(fd)
        elif form == "10-K" or form == "10-K/A":
            tenk_dates.append(fd)
        elif form == "10-Q":
            tenq_dates.append(fd)
        elif form == "424B4":
            filings_424b4.append((fd, acc, pdoc))

    if not filings_424b4:
        return False, None

    # Must have S-1
    if not s1_dates:
        return False, None

    # Filter 424B4 filings to target years
    target_year_filings = [
        (fd, acc, pdoc) for fd, acc, pdoc in filings_424b4
        if fd and int(fd[:4]) in target_years
    ]
    if not target_year_filings:
        return False, None

    # Sort by date ascending
    target_year_filings.sort(key=lambda x: x[0])
    earliest_424b4 = target_year_filings[0]
    ipo_date = earliest_424b4[0]

    # S-3 anomaly check: skip if S-3 exists more than 12 months before earliest S-1
    if s3_dates:
        earliest_s3 = min(s3_dates)
        earliest_s1 = min(s1_dates)
        try:
            d_s3 = date.fromisoformat(earliest_s3)
            d_s1 = date.fromisoformat(earliest_s1)
            if (d_s1 - d_s3).days > 365:
                return False, None
        except Exception:
            pass

    # Check 10-K timing
    if tenk_dates:
        earliest_10k = min(tenk_dates)
        try:
            d_ipo = date.fromisoformat(ipo_date)
            d_10k = date.fromisoformat(earliest_10k)
            # 10-K must be AFTER or within 6 months of IPO date
            if (d_ipo - d_10k).days > 180:
                return False, None
        except Exception:
            pass

    # Use ticker from submissions if not already found
    ticker = candidates_entry.get("ticker", "")
    if not ticker and tickers_list:
        ticker = tickers_list[0]

    # Get exchange
    exchanges = data.get("exchanges", [])
    exchange = ""
    if exchanges:
        ex = exchanges[0].upper()
        if "NYSE" in ex:
            exchange = "NYSE"
        elif "NASDAQ" in ex or "NAS" in ex:
            exchange = "NASDAQ"
        else:
            exchange = ex

    return True, {
        "ipo_date": ipo_date,
        "ipo_year": int(ipo_date[:4]),
        "ticker": ticker,
        "exchange": exchange,
        "accession": earliest_424b4[1],
        "primary_doc": earliest_424b4[2],
        "cik_padded": cik_padded,
    }


def extract_prospectus_info(cik_padded, accession_number, primary_doc):
    """
    Fetch the 424B4 primary document and extract price, shares, exchange, description.
    """
    # Build URL
    acc_nodash = accession_number.replace("-", "")
    cik_nodash = str(int(cik_padded))  # remove leading zeros for path

    if not primary_doc:
        # Try to get index page
        index_url = (
            f"https://www.sec.gov/Archives/edgar/data/{cik_nodash}/{acc_nodash}/{accession_number}-index.htm"
        )
        text = fetch_text(index_url, nbytes=10000)
        if text:
            m = re.search(r'href="([^"]+\.htm[l]?)"', text, re.IGNORECASE)
            if m:
                primary_doc = m.group(1).split("/")[-1]
        if not primary_doc:
            return None

    doc_url = (
        f"https://www.sec.gov/Archives/edgar/data/{cik_nodash}/{acc_nodash}/{primary_doc}"
    )

    text = fetch_text(doc_url, nbytes=60000)
    if not text:
        return None

    result = {
        "ipo_price_usd": None,
        "ipo_raise_usd_m": None,
        "exchange": None,
        "lead_asset": "",
    }

    # Extract price per share
    price_match = re.search(
        r'\$\s*([\d,]+\.?\d*)\s*per\s+(?:share|ADS|American Depositary Share)',
        text, re.IGNORECASE
    )
    if price_match:
        try:
            price = float(price_match.group(1).replace(",", ""))
            result["ipo_price_usd"] = price
        except Exception:
            pass

    # Extract shares offered
    shares_match = re.search(
        r'([\d,]+)\s+(?:shares|American Depositary Shares|ADS)',
        text, re.IGNORECASE
    )
    if shares_match:
        try:
            shares = int(shares_match.group(1).replace(",", ""))
            if result["ipo_price_usd"] and shares > 0:
                raise_m = round(result["ipo_price_usd"] * shares / 1e6, 1)
                result["ipo_raise_usd_m"] = raise_m
        except Exception:
            pass

    # Extract exchange
    if re.search(r'Nasdaq\s+Global\s+Select\s+Market|Nasdaq\s+Capital\s+Market|Nasdaq\s+Global\s+Market', text, re.IGNORECASE):
        result["exchange"] = "NASDAQ"
    elif re.search(r'New\s+York\s+Stock\s+Exchange|NYSE', text, re.IGNORECASE):
        result["exchange"] = "NYSE"
    elif re.search(r'Nasdaq', text, re.IGNORECASE):
        result["exchange"] = "NASDAQ"

    # Extract business description ("We are" or "We are a")
    we_are_match = re.search(r'(We are\s+[^.]{10,300}\.)', text, re.IGNORECASE)
    if we_are_match:
        desc = we_are_match.group(1).strip()
        result["lead_asset"] = desc[:300]

    return result


def main():
    target_years = list(range(2021, 2027))
    all_ipos = []
    global_errors = 0

    # Step 1 & 2: Collect candidates per year
    all_candidates = {}  # cik_padded -> entry

    for year in target_years:
        print(f"\n=== Year {year}: Collecting 424B4 candidates ===")
        candidates, total = collect_candidates_for_year_v2(year)
        print(f"  Year {year}: {len(candidates)} biotech/pharma candidates out of total 424B4 filings")

        # Merge into global
        for cik, entry in candidates.items():
            if cik not in all_candidates:
                all_candidates[cik] = entry
            else:
                # Merge filings
                existing_accessions = {
                    f["accessionNumber"] for f in all_candidates[cik]["filings_424b4"]
                }
                for f in entry["filings_424b4"]:
                    if f["accessionNumber"] not in existing_accessions:
                        all_candidates[cik]["filings_424b4"].append(f)

    print(f"\n=== Total unique biotech/pharma CIKs with 424B4 filings: {len(all_candidates)} ===")

    # Step 2: For each CIK, verify IPO criteria
    print("\n=== Checking IPO criteria for each candidate ===")
    confirmed_ipos = []

    for i, (cik_padded, entry) in enumerate(all_candidates.items()):
        if i % 50 == 0:
            print(f"  Progress: {i}/{len(all_candidates)} checked, {len(confirmed_ipos)} confirmed IPOs so far")

        is_ipo, ipo_info = check_is_ipo(cik_padded, entry, set(target_years))
        if is_ipo:
            confirmed_ipos.append((cik_padded, entry, ipo_info))

    print(f"\n=== Confirmed IPOs: {len(confirmed_ipos)} ===")

    # Step 3: Fetch prospectus details
    print("\n=== Fetching prospectus details ===")
    results = []

    for i, (cik_padded, entry, ipo_info) in enumerate(confirmed_ipos):
        if i % 20 == 0:
            print(f"  Progress: {i}/{len(confirmed_ipos)} processed")

        accession = ipo_info["accession"]
        primary_doc = ipo_info["primary_doc"]

        prosp_info = None
        try:
            prosp_info = extract_prospectus_info(cik_padded, accession, primary_doc)
        except Exception as e:
            print(f"  Error fetching prospectus for {entry['name']} ({cik_padded}): {e}", file=sys.stderr)
            global_errors += 1

        # Determine exchange
        exchange = ipo_info.get("exchange", "")
        if prosp_info and prosp_info.get("exchange"):
            exchange = prosp_info["exchange"]

        record = {
            "year": ipo_info["ipo_year"],
            "ticker": ipo_info.get("ticker", entry.get("ticker", "")),
            "name": entry["name"],
            "exchange": exchange,
            "ipo_price_usd": prosp_info["ipo_price_usd"] if prosp_info else None,
            "ipo_raise_usd_m": prosp_info["ipo_raise_usd_m"] if prosp_info else None,
            "latest_close_usd": None,
            "market_cap_now_usd_m": None,
            "lead_asset": prosp_info["lead_asset"] if prosp_info else "",
            "moa": "",
            "phase": "",
            "status": "",
            "thesis": "",
            "edgar_424b4_date": ipo_info["ipo_date"],
            "edgar_cik": cik_padded,
        }
        results.append(record)

    # Sort by year, then date
    results.sort(key=lambda x: (x["year"], x["edgar_424b4_date"]))

    # Write output
    output = {
        "ipos": results,
        "pulled_at": "2026-05-25",
        "total": len(results)
    }

    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n=== DONE ===")
    print(f"Total confirmed IPOs written: {len(results)}")
    print(f"Total errors encountered: {global_errors}")
    print(f"Output: {OUTPUT_PATH}")

    # Summary by year
    by_year = {}
    for r in results:
        y = r["year"]
        by_year[y] = by_year.get(y, 0) + 1
    for y in sorted(by_year):
        print(f"  Year {y}: {by_year[y]} IPOs")


if __name__ == "__main__":
    main()
