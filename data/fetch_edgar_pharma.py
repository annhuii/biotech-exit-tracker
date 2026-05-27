#!/usr/bin/env python3
"""
fetch_edgar_pharma.py

Systematically pulls pharma pipeline data from each company's latest 10-K
(US filers) or 20-F (foreign filers) on SEC EDGAR.

Strategy:
  Parse the 10-K/20-F HTML directly with BeautifulSoup, expanding rowspans
  so each row in a pipeline table becomes a fully-populated (Compound,
  Indication, Status, Developments) tuple. This captures the "drug N applies
  to indications X, Y, Z" structure that companies use in their pipeline
  disclosures.

  16 of 20 pharmas file with SEC; 4 (Roche, Bayer, Daiichi, Boehringer)
  do not and remain manually curated.

Output: data/pharma_auto.json
"""

import json, os, re, time, warnings
import urllib.request
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

# ── Config ─────────────────────────────────────────────────────────────────────

UA      = "biotech-tracker-research researcher@biotechtracker.io"
DELAY   = 0.12   # ≤10 req/sec EDGAR limit

# Output path: same directory as this script (/data/pharma_auto.json)
OUTPUT  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pharma_auto.json")

US_FILERS = {
    "Pfizer":                 "78003",
    "Johnson & Johnson":      "200406",
    "Merck & Co.":            "310158",
    "AbbVie":                 "1551152",
    "Eli Lilly":              "59478",
    "Bristol Myers Squibb":   "14272",
    "Amgen":                  "318154",
    "Vertex Pharmaceuticals": "875320",
    "Gilead Sciences":        "882095",
    "Regeneron":              "872589",
}

FOREIGN_FILERS = {
    "AstraZeneca":   "901832",
    "Novartis":      "1114448",
    "Sanofi":        "1121404",
    "GSK":           "1131399",
    "Novo Nordisk":  "353278",
    "Takeda":        "1395064",
}

NOT_IN_EDGAR = [
    "Roche",
    "Bayer (Pharma)",
    "Daiichi Sankyo",
    "Boehringer Ingelheim",
]


# ── HTTP helpers ───────────────────────────────────────────────────────────────

def rget(url, raw=False):
    time.sleep(DELAY)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        if raw:
            return r.read()
        return json.load(r)


def find_latest_filings(cik, form_types):
    padded = str(cik).zfill(10)
    d = rget(f"https://data.sec.gov/submissions/CIK{padded}.json")
    recent = d["filings"]["recent"]
    forms, dates, accs, docs = (
        recent["form"], recent["filingDate"],
        recent["accessionNumber"], recent["primaryDocument"],
    )
    result = {}
    for target in form_types:
        for i, f in enumerate(forms):
            if f == target:
                result[target] = (dates[i], accs[i], docs[i])
                break
    return result


def fetch_filing_html(cik, accession, primary_doc):
    acc_nd = accession.replace("-", "")
    url    = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nd}/{primary_doc}"
    raw    = rget(url, raw=True)
    return raw.decode("utf-8", errors="replace")


# ── HTML table parser ──────────────────────────────────────────────────────────

def parse_table_with_rowspan(table):
    """Parse a <table>, expanding rowspans. Ignores colspan (iXBRL uses it
    for visual padding; we collapse those duplicates afterwards)."""
    expanded = []
    sticky   = {}   # col_idx -> (text, rows_left)

    for tr in table.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        out = []
        col = 0

        def fill_sticky():
            nonlocal col
            while col in sticky and sticky[col][1] > 0:
                t, n = sticky[col]
                out.append(t)
                sticky[col] = (t, n - 1)
                if sticky[col][1] == 0:
                    del sticky[col]
                col += 1

        for c in cells:
            fill_sticky()
            text    = " ".join(c.stripped_strings).strip()
            rowspan = int(c.get("rowspan", "1") or "1")
            out.append(text)
            if rowspan > 1:
                sticky[col] = (text, rowspan - 1)
            col += 1

        fill_sticky()
        expanded.append(out)
    return expanded


def collapse_consecutive_dups(row):
    if not row:
        return row
    out = [row[0]]
    for v in row[1:]:
        if v != out[-1]:
            out.append(v)
    return out


# Heuristics for finding pipeline tables
PIPELINE_HEADER_RE = re.compile(
    r"(compound|product\s+candidate|candidate|asset|molecule|drug)\b.*?"
    r"\b(indication|target|disease|study|status|phase)",
    re.IGNORECASE,
)

STATUS_RE = re.compile(r"\b(Phase\s*[1-3]|Phase\s*[IVX]+|Approved|Submitted|Filed|Registration|NDA|BLA|MAA)\b", re.I)

TA_HEADER_KEYWORDS = {
    # If a row has just ONE of these as its only content, it's a TA section header
    "cardiometabolic","oncology","immunology","neuroscience","cardiovascular",
    "respiratory","rare","vaccines","hematology","ophthalmology","infectious",
    "metabolic","endocrinology","dermatology","obesity","weight","diabetes",
    "neurology","autoimmune","virology","hepatology","gastroenterology",
    "transplant","general medicines","specialty care","specialty",
    "pharmaceuticals","oncology and hematology","rare disease",
    "cardiometabolic health","cancer","other","cell therapy","gene therapy",
    "biopharma","biopharmaceuticals",
}


# Drug codename patterns — used to detect "patent expiry table" style
DRUG_CODE_RE = re.compile(
    r"\b("
    r"MK-?\d{3,5}[A-Z]?"        # Merck (MK-1234)
    r"|V\d{2,4}"                # Merck vaccine (V940)
    r"|BMS-?\d{3,7}"            # BMS (BMS-986482)
    r"|AZD\d{3,5}"              # AstraZeneca (AZD0240)
    r"|RG\d{3,5}"               # Roche (RG7937)
    r"|GS-?\d{3,5}"             # Gilead (GS-1720)
    r"|GSK\d{3,7}"              # GSK (GSK4532990)
    r"|REGN-?\d{3,5}"           # Regeneron
    r"|PF-?\d{6,8}"             # Pfizer (PF-07799933)
    r"|VX-?\d{3,5}"             # Vertex (VX-993)
    r"|AMG-?\d{3,5}"            # Amgen
    r"|JNJ-?\d{3,8}"            # JNJ
    r"|SAR-?\d{6,8}"            # Sanofi
    r"|LY-?\d{6,9}"             # Lilly
    r"|TAK-?\d{3,5}"            # Takeda
    r"|NN-?\d{3,5}"             # Novo Nordisk
    r")\b",
    re.IGNORECASE,
)


def find_pipeline_tables(soup):
    """
    Return list of (table, rows, header_idx, table_type) for pipeline tables.

    Detects two table types:
      - "phase":  ≥5 rows containing a Phase/Approved/Submitted status keyword
                  (Lilly/Sanofi/GSK/Pfizer/AZ style)
      - "patent": ≥5 rows of (drug-code-or-name, year YYYY) pairs
                  (Merck style)
    """
    out = []
    for t in soup.find_all("table"):
        raw_rows = parse_table_with_rowspan(t)
        rows     = [collapse_consecutive_dups(r) for r in raw_rows]

        # --- Detection 1: status-bearing rows
        status_rows = [
            j for j, r in enumerate(rows)
            if any(c and STATUS_RE.search(c) and len(c) < 60 for c in r)
        ]

        if len(status_rows) >= 5:
            first = status_rows[0]
            header_idx = max(0, first - 1)
            if any(c and STATUS_RE.search(c) for c in rows[header_idx]):
                header_idx = 0
            out.append((t, rows, header_idx, "phase"))
            continue

        # --- Detection 2: patent expiry table (drug code + year)
        # Look for rows where one cell has a drug code AND another has a year 20XX
        year_re = re.compile(r"\b20[2-4]\d\b")
        patent_rows = 0
        for r in rows:
            has_drug = any(c and DRUG_CODE_RE.search(c) for c in r)
            has_year = any(c and year_re.search(c) and len(c) < 20 for c in r)
            if has_drug and has_year:
                patent_rows += 1

        if patent_rows >= 5:
            # Find header — row before the first drug-code-bearing row
            first_drug_row = None
            for j, r in enumerate(rows):
                if any(c and DRUG_CODE_RE.search(c) for c in r):
                    first_drug_row = j
                    break
            header_idx = max(0, (first_drug_row or 1) - 1)
            out.append((t, rows, header_idx, "patent"))

    return out


def extract_compounds_from_table(rows, header_idx):
    """
    From a parsed table, yield rows of {compound, indication, status, developments}.
    Carries forward the compound name on continuation rows (where it doesn't repeat
    because the table cell was rowspan'd in HTML).
    """
    compounds = []
    current   = None

    for r in rows[header_idx + 1:]:
        non_empty = [c for c in r if c]
        if not non_empty:
            continue

        # TA section header (single cell)
        if len(non_empty) == 1:
            if non_empty[0].lower().strip() in TA_HEADER_KEYWORDS:
                continue
            # If it's a single cell that's not a TA header, skip — probably a heading
            continue

        # Strip empty trailing cells
        while r and not r[-1]:
            r = r[:-1]

        # Find status column — the cell containing Phase/Approved/etc.
        status_col = None
        for ci, cell in enumerate(r):
            if cell and STATUS_RE.search(cell) and len(cell) < 40:
                status_col = ci
                break
        if status_col is None:
            continue

        # Compound = first cell; indication = cell(s) before status
        # Typical layout: [Compound, Indication, Status, Developments]
        compound = r[0] if r else None
        indication = r[status_col - 1] if status_col >= 1 else ""
        status     = r[status_col]
        developments = r[status_col + 1] if len(r) > status_col + 1 else ""

        # Detect continuation row (compound is same as indication, or compound cell is short/empty)
        # In a continuation row, the compound column was rowspan'd above so we read from current
        if compound and compound == indication:
            compound = current
        elif not compound or compound.lower() in {"compound", "candidate", "product candidate", "molecule"}:
            compound = current
        else:
            # If the first cell starts with the same text as the previous compound, treat as continuation
            if current and compound.startswith(current.split("(")[0].strip()):
                pass  # keep new value as it's a re-declaration
            current = compound

        if not compound or not indication or not status:
            continue
        if compound == indication:
            continue

        # Filter junk
        if len(compound) > 70 or len(indication) > 200:
            continue
        # Compound shouldn't be a sentence
        if compound.endswith('.') or compound.count(' ') > 6:
            continue

        compounds.append({
            "compound":     compound.strip(),
            "indication":   indication.strip(),
            "status":       status.strip(),
            "developments": developments.strip()[:200],
        })

    # Dedupe (compound, indication)
    seen = set()
    out = []
    for c in compounds:
        key = (c["compound"].lower(), c["indication"].lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


# ── Per-company orchestration ──────────────────────────────────────────────────

def process_company(name, cik, is_foreign=False):
    if is_foreign:
        form_types = ["20-F", "6-K"]
    else:
        form_types = ["10-K", "10-Q"]

    print(f"\n=== {name} (CIK {cik}) ===")

    result = {
        "name":         name,
        "cik":          cik,
        "filer_type":   "foreign-20F" if is_foreign else "us-10K",
        "filings":      {},
        "pipeline":     [],
        "extraction_notes": [],
    }

    try:
        filings = find_latest_filings(cik, form_types)
    except Exception as e:
        result["extraction_notes"].append(f"EDGAR submissions error: {e}")
        return result

    annual_form = "10-K" if not is_foreign else "20-F"

    if annual_form not in filings:
        result["extraction_notes"].append(f"No recent {annual_form} found")
        return result

    date, acc, doc = filings[annual_form]
    result["filings"][annual_form] = {
        "filing_date": date,
        "accession":   acc,
        "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-','')}/{doc}",
    }
    print(f"  Fetching {annual_form} ({date}) — {doc} ...")

    try:
        html = fetch_filing_html(cik, acc, doc)
        soup = BeautifulSoup(html, "html.parser")

        pipeline_tables = find_pipeline_tables(soup)
        phase_tables = [pt for pt in pipeline_tables if pt[3] == "phase"]
        patent_tables = [pt for pt in pipeline_tables if pt[3] == "patent"]
        print(f"    Pipeline tables found: {len(phase_tables)} phase + {len(patent_tables)} patent")

        all_compounds = []
        # Phase tables (Lilly-style)
        for table, rows, header_idx, _ in phase_tables:
            all_compounds.extend(extract_compounds_from_table(rows, header_idx))

        # Patent expiry tables (Merck-style) — extract drug + year
        year_re = re.compile(r"\b(20[2-4]\d)\b")
        for table, rows, header_idx, _ in patent_tables:
            # Try to infer phase from the table caption/header
            header_text = " ".join(rows[header_idx]).lower() if header_idx < len(rows) else ""
            phase_label = "Phase 3" if "phase 3" in header_text or "phase iii" in header_text else "Patent table"

            for r in rows[header_idx + 1:]:
                if len(r) < 2:
                    continue
                drug_cell = None
                year_cell = None
                for c in r:
                    if c and DRUG_CODE_RE.search(c) and not drug_cell:
                        drug_cell = c
                    if c and year_re.match(c.strip()) and not year_cell:
                        year_cell = c
                if drug_cell and year_cell:
                    yr = int(year_re.search(year_cell).group(1))
                    if 2025 <= yr <= 2049:
                        all_compounds.append({
                            "compound":     drug_cell,
                            "indication":   f"(patent table — see {phase_label})",
                            "status":       phase_label,
                            "developments": f"Patent expiry {yr}",
                        })

        # Dedupe across tables
        seen = set()
        dedup = []
        for c in all_compounds:
            k = (c["compound"].lower(), c["indication"].lower())
            if k not in seen:
                seen.add(k)
                dedup.append(c)

        result["pipeline"] = dedup

        # Quick phase counts
        from collections import Counter
        phase_count = Counter()
        for c in dedup:
            s = c["status"].lower()
            if "approved" in s:
                phase_count["approved"] += 1
            elif "submit" in s or "filed" in s or "registration" in s:
                phase_count["submitted"] += 1
            elif "phase 3" in s or "phase iii" in s:
                phase_count["phase3"] += 1
            elif "phase 2" in s or "phase ii" in s:
                phase_count["phase2"] += 1
            elif "phase 1" in s or "phase i" in s:
                phase_count["phase1"] += 1

        result["phase_counts"] = dict(phase_count)
        print(f"    Total compound rows: {len(dedup)}")
        print(f"    Phase counts: {dict(phase_count)}")

        if not dedup:
            result["extraction_notes"].append(
                f"No pipeline table found in {annual_form}; "
                "company may disclose in narrative format only"
            )

    except Exception as e:
        result["extraction_notes"].append(f"Error parsing {annual_form}: {e}")
        import traceback; traceback.print_exc()

    # Interim filing reference
    interim = "10-Q" if not is_foreign else "6-K"
    if interim in filings:
        d, a, doc2 = filings[interim]
        result["filings"][interim] = {
            "filing_date": d,
            "accession":   a,
            "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{a.replace('-','')}/{doc2}",
        }

    return result


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    results = []

    for name, cik in US_FILERS.items():
        try:
            results.append(process_company(name, cik, is_foreign=False))
        except Exception as e:
            print(f"  FATAL {name}: {e}")
            results.append({
                "name": name, "cik": cik, "filer_type": "us-10K",
                "extraction_notes": [f"Fatal: {e}"], "pipeline": [],
            })

    for name, cik in FOREIGN_FILERS.items():
        try:
            results.append(process_company(name, cik, is_foreign=True))
        except Exception as e:
            print(f"  FATAL {name}: {e}")
            results.append({
                "name": name, "cik": cik, "filer_type": "foreign-20F",
                "extraction_notes": [f"Fatal: {e}"], "pipeline": [],
            })

    for name in NOT_IN_EDGAR:
        results.append({
            "name":             name,
            "cik":              None,
            "filer_type":       "not-in-edgar",
            "extraction_notes": ["Does not file with SEC; stays manually curated"],
            "pipeline":         [],
        })

    # Summary
    print("\n\n=== Summary ===")
    print(f"{'Company':<27} | {'Filer':<13} | {'Pipeline rows':<13} | Filing date")
    print("-" * 90)
    for r in results:
        n_pipe = len(r.get("pipeline", []))
        date = ""
        if r.get("filings"):
            for f in r["filings"].values():
                date = f.get("filing_date", "")
                break
        marker = "✓" if n_pipe > 0 else " "
        print(f"[{marker}] {r['name']:<23} | {r.get('filer_type','?'):<13} | {n_pipe:<13} | {date}")

    output = {
        "as_of": time.strftime("%Y-%m-%d"),
        "source": "SEC EDGAR — 10-K (US filers) and 20-F (foreign filers)",
        "methodology": (
            "For each pharma, pull the latest 10-K (US) or 20-F (foreign) from SEC EDGAR. "
            "Parse the HTML with BeautifulSoup, expanding <td rowspan='N'> attributes so each "
            "row of the pipeline table becomes a fully-populated (Compound, Indication, Status, "
            "Developments) tuple. This captures the 'one drug → multiple indications' structure "
            "that companies use in 10-K pipeline disclosures. "
            "4 of 20 pharmas (Roche, Bayer, Daiichi, Boehringer) do not file with SEC — they "
            "remain manually curated. Latest interim filing (10-Q or 6-K) is referenced."
        ),
        "companies": results,
    }

    with open(OUTPUT, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nWritten to: {OUTPUT}")


if __name__ == "__main__":
    main()
