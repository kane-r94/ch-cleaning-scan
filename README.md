# CH Cleaning Sector Scan

Find UK companies in a given SIC code (default: cleaning services — 81210,
81220, 81290) whose latest filed turnover falls inside a target band (default:
£10m–£30m), using **only official Companies House data**.

Every turnover/employee figure this tool outputs is sourced from a company's
actual filed accounts (iXBRL), so it can be labelled **Audited** — not
estimated, not scraped from a marketing site or a data vendor's model.

## How it works (two stages)

**Stage 1 — Discover companies in scope**
`src/discover_companies.py` calls the Companies House **Advanced Search API**
to list every active company registered under the chosen SIC code(s). Output:
`data/companies.csv` (company number, name, address, incorporation date,
SIC codes).

**Stage 2 — Pull turnover from filed accounts**
Two ways to do this, pick whichever suits your access:

- `src/scan_turnover.py` (API-driven): for each company, fetches its filing
  history, finds the latest "Full accounts" (AA) filing, downloads the
  iXBRL document via the Document API, and parses out turnover + average
  employees. Slower, but always current and only touches companies you care
  about.

- `src/bulk_scan.py` (bulk-driven, recommended for a full sector sweep):
  downloads Companies House's free monthly **Accounts Data Product** ZIP
  (no API key needed — see
  https://download.companieshouse.gov.uk/en_accountsdata.html), and parses
  every iXBRL file inside it, matching against `data/companies.csv`. Much
  faster for scanning thousands of companies since it avoids one API call
  per company, but only covers whichever monthly archives you download.

Both stages write into `data/`, and the final filtered result — companies
whose turnover falls in the target band — goes to `output/results.csv`.

## Setup

1. Get a free API key: register at
   https://developer.companieshouse.gov.uk/ → "Create an application" →
   choose **REST API key** (read-only, no OAuth needed for this use case).
2. Clone this repo and install dependencies:

   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

3. Copy `.env.example` to `.env` and paste in your key:

   ```bash
   cp .env.example .env
   ```

## Usage

```bash
# Stage 1: discover companies in scope
python src/discover_companies.py --sic 81210 81220 81290 --status active

# Stage 2a: API-driven turnover scan (good for a few hundred companies)
python src/scan_turnover.py --min-turnover 10000000 --max-turnover 30000000

# Stage 2b: bulk-driven turnover scan (good for a full sector sweep)
python src/bulk_scan.py --month 2026-06 --min-turnover 10000000 --max-turnover 30000000
```

Results land in `output/results.csv` with columns matching the table format:

```
company_name, entity_type, company_number, hq_address, latest_turnover,
turnover_year, employees, ownership_type, sic_codes, confidence, source
```

`confidence` will be `Audited` for anything successfully parsed from a filed
account. `ownership_type` is a best-effort label derived from the PSC
(persons with significant control) register — e.g. "Employee Ownership
Trust", "Individual person(s) with significant control", "Corporate
parent" — and should be sanity-checked for anything unusual.

## Rate limits & good practice

- The REST API allows 600 requests per 5-minute rolling window per key.
  `ch_api.py` throttles automatically and retries on HTTP 429.
- Advanced Search and Document API endpoints are billed against the same
  key/quota as the main API.
- Companies House's data is Crown copyright; free to reuse, but don't
  represent scraped/derived figures as more precise than the source (e.g.
  accounts are often rounded to the nearest £1,000 or £'000s — check the
  `units` note the parser attaches to each figure).

## Known limitations

- Small and micro companies are legally allowed to file abbreviated/filleted
  accounts **without a P&L or turnover figure at all**. Those companies will
  show up in `companies.csv` but with no turnover in the results — this is
  not a bug, it's a disclosure exemption. Expect a real gap in coverage for
  the smaller end of any SIC code.
- iXBRL tagging isn't perfectly standardised across accounting software and
  taxonomy versions (old UK GAAP vs FRS 101 vs FRS 102 vs full IFRS). The
  parser matches on several known tag name variants (see
  `src/ixbrl_parser.py::TURNOVER_TAGS`) but a small number of filings may
  use non-standard tagging and be missed. Treat a "no turnover found" result
  as "not disclosed or not detected," not "zero."
- Group accounts: a company's own standalone turnover may differ from its
  consolidated group turnover if it's a subsidiary — check
  `persons-with-significant-control` / parent company links if this matters
  for your use case.
