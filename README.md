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

See `output/example_results.csv` for a sample of what this looks like
(illustrative data, not real companies).

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

## Getting this onto GitHub

**Option A — no command line, using the GitHub website (easiest)**

1. Unzip the folder you downloaded, so you have a plain `ch-cleaning-scan`
   folder on your computer.
2. Go to https://github.com/new (log in first if needed).
3. Give it a name (e.g. `ch-cleaning-scan`), leave it **Public** or
   **Private** as you prefer, and click **Create repository** — don't tick
   any of the "initialize with README" boxes.
4. On the next page, click the link that says **"uploading an existing
   file"**.
5. Open your unzipped folder, select all the files and sub-folders
   (`README.md`, `requirements.txt`, `src/`, `tests/`, etc. — everything
   except the hidden `.git` folder, which the web uploader ignores anyway),
   and drag them into the browser window.
6. Scroll down, add a short commit message (e.g. "Initial upload"), and
   click **Commit changes**.

Done — the repo is live. (One thing this method skips: the git commit
history I created locally. That doesn't affect anything functionally, it
just means GitHub will show one upload rather than the original commit.)

**Option B — command line (keeps the original commit history)**

1. Unzip the folder, then open a terminal and move into it:
   ```bash
   unzip ch-cleaning-scan.zip
   cd ch-cleaning-scan
   ```
2. Create an empty repository at https://github.com/new — same as step 3
   above, same rule about not initializing it with a README.
3. GitHub will show you a repo URL like
   `https://github.com/<your-username>/ch-cleaning-scan.git`. Copy it, then
   run:
   ```bash
   git remote add origin https://github.com/<your-username>/ch-cleaning-scan.git
   git branch -M main
   git push -u origin main
   ```
4. If it asks for a password, GitHub no longer accepts your account
   password for this — you'll need a Personal Access Token instead
   (GitHub → Settings → Developer settings → Personal access tokens →
   generate one with "repo" scope, and paste that in when prompted for a
   password), or set up GitHub Desktop/SSH keys if you'd rather avoid
   tokens entirely.

Either way, remember `.env` (your actual API key) is excluded by
`.gitignore` and won't be uploaded — good, since that key shouldn't go on
GitHub, private or public.

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
