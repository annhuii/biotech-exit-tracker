# Biotech Exit Tracker

A 3-page static dashboard for thinking about biotech exits on a 4–7 year horizon.

- **Pipelines** — top 20 pharma by Rx revenue, with a TA-emphasis heatmap, modality mix, late-stage assets and patent-cliff exposure.
- **M&A** — biotech deals ≥ $500M since 2021, including major China-out platform licensing.
- **IPOs** — selected NASDAQ/NYSE + HKEX 18A biotech listings 2021–2026 with lead asset, clinical phase, and current market cap.

## Run locally

It's a static site with no build step — open `index.html` in any browser, or serve the folder:

```bash
python3 -m http.server 8080
# then open http://localhost:8080
```

## Deploy to GitHub Pages

1. Create a public GitHub repo (e.g. `biotech-exit-tracker`).
2. From this directory:
   ```bash
   git init
   git add .
   git commit -m "initial dashboard"
   git branch -M main
   git remote add origin https://github.com/<your-username>/biotech-exit-tracker.git
   git push -u origin main
   ```
3. In the repo settings → Pages → set source to `main` branch, `/ (root)`. Pages will publish to `https://<your-username>.github.io/biotech-exit-tracker/`.
4. The included GitHub Actions workflow (`.github/workflows/refresh.yml`) runs **weekly on Monday at 06:00 UTC** to refresh market caps and re-stamp the data. You can trigger it manually from the Actions tab.

## Data layout

```
data/
  pharma.json   # top 20 pharma — pipeline data, hand-curated
  ma.json       # M&A + licensing deals since 2021
  ipos.json     # biotech IPOs 2021–2026
```

All three files have an `as_of` field. The HTML pages render directly off these — to edit content, edit the JSON and refresh.

## What's automated and what's not

| Component        | Source                       | Refresh |
|------------------|------------------------------|---------|
| Pharma pipelines | Hand-curated from 10-K, R&D days, analyst notes | Manual — review quarterly |
| Market caps (IPOs) | Yahoo Finance via `yfinance` | Weekly (GitHub Actions) |
| New M&A deals    | SEC EDGAR 8-K (stub)         | Weekly — currently logging only; full ingest is a follow-up |
| `as_of` dates    | `scripts/stamp_date.py`      | Weekly |

The M&A ingest is intentionally a stub — silent auto-parsing of 8-Ks is too easy to get wrong. The recommended pattern is to skim Endpoints / Fierce Biotech weekly and append entries to `data/ma.json` by hand.

## Methodology notes (for interviews)

- **"Top 20 by Rx revenue"** uses FY2024 prescription drug sales. Boehringer Ingelheim is private and the figure is estimated.
- **TA-emphasis scores** are 0–4 and subjective — they reflect *forward-looking pipeline weight*, not historical revenue mix. A company with strong oncology revenue but a thin oncology pipeline gets a lower score.
- **Patent cliff exposure** is qualitative; verify specific LOE dates in 10-Ks before citing.
- **China-origin** flag covers (a) assets in-licensed from Chinese biotechs to global pharma and (b) HKEX 18A listings of China-domiciled biotechs.
- **IPO market caps** are approximate and will drift; the weekly refresh job is the source of truth.

## Limits

This is a v1 demo, not a production data product. Treat all figures as starting points for diligence, not endpoints. The fact lookups most likely to be stale: market caps (refresh weekly), late-stage asset readouts (fast-moving), recent BD activity (week-by-week).
