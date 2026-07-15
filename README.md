# CH Cleaning Sector Scan

Find UK companies in a given SIC code (default: cleaning services — 81210,
81220, 81290) whose latest filed turnover falls inside a target band (default:
£10m–£30m), using **only official Companies House data**.

Every turnover/employee figure this tool outputs is sourced from a company's
actual filed accounts (iXBRL), so it can be labelled **Audited** — not
estimated, not scraped from a marketing site or a data vendor's model.

## How it works (two stages)

**Stage 1 — Discover companies in scope**
`src/discover_companies.py` lists every active company registered under the
chosen SIC code(s). Output: `data/companies.csv` (company number, name,
address, incorporation date, SIC codes). Two modes:

- `--mode bulk` (**recommended, and the workflow default**): downloads
  Companies House's free monthly **Free Company Data Product** snapshot (no
  API key needed — see https://download.companieshouse.gov.uk/en_output.html)
  and filters it locally. No pagination limit, so it reliably covers a whole
  SIC sector.
- `--mode api`: calls the **Advanced Search API** live. Always current, but
  the API has a confirmed ~10,000-match pagination ceiling — `start_index`
  only paginates within the first ~10k results of a query, not the true
  total. Common cleaning-sector codes (e.g. 81210) return more than that
  nationwide, so this mode **will fail partway through** for a full-sector
  sweep (see
  https://forum.companieshouse.gov.uk/t/advanced-search-companies-responds-with-500-after-10000-items/4813).
  Only use it for narrow searches you know return under ~10k matches.

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
  Because it makes no API calls, it can't look up **Persons with
  Significant Control** either, so `ownership_type` is left as a
  placeholder for every row it produces.

**Stage 3 — Fill in ownership for bulk-mode results (optional)**
`src/enrich_ownership.py` looks up PSC data and sets a real
`ownership_type` for every row still showing the bulk-mode placeholder.
This only needs the API for the small, already turnover-filtered
`output/results.csv` — typically a few dozen companies, not the whole
discovered sector — so it's cheap even though it needs
`COMPANIES_HOUSE_API_KEY`. The workflow runs this automatically after a
bulk-mode turnover scan; run it manually with
`python src/enrich_ownership.py` if you're working locally.

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
# Stage 1: discover companies in scope (bulk mode — recommended for a full sector sweep)
python src/discover_companies.py --mode bulk --sic 81210 81220 81290 --status active \
    --date 2026-07-01

# Stage 1 (alternative): API-driven discovery — only safe for narrow searches
# that return under ~10,000 matches
python src/discover_companies.py --mode api --sic 81210 81220 81290 --status active

# Stage 2a: API-driven turnover scan (good for a few hundred companies)
python src/scan_turnover.py --min-turnover 10000000 --max-turnover 30000000

# Stage 2b: bulk-driven turnover scan (good for a full sector sweep)
python src/bulk_scan.py --month 2026-06 --min-turnover 10000000 --max-turnover 30000000

# Stage 3 (only needed after bulk-driven turnover scans): fill in ownership
python src/enrich_ownership.py
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

## Running this as a hosted dashboard instead of on your machine

The repo also includes a GitHub Actions workflow and a static dashboard, so
the whole thing can run in GitHub's cloud rather than on your computer.

**How it works:** a manually-triggered Action (`.github/workflows/scan.yml`)
runs the discovery + turnover scan, converts the results to
`docs/results.json`, and commits that file back to the repo. GitHub Pages
serves `docs/index.html`, which reads that JSON and renders the register:
summary stats, a turnover-distribution chart, an ownership-type breakdown,
and a sortable/filterable table.

Nothing runs on a schedule — you trigger it by hand whenever you want fresh
numbers, from the Actions tab.

### One-time setup

1. **Add your API key as a secret** (this replaces the `.env` file you'd
   use locally — never commit the key itself):
   - Repo → **Settings → Secrets and variables → Actions → New repository
     secret**
   - Name: `COMPANIES_HOUSE_API_KEY`
   - Value: your key from developer.companieshouse.gov.uk

2. **Turn on GitHub Pages:**
   - Repo → **Settings → Pages**
   - Under "Build and deployment", set **Source: Deploy from a branch**
   - Branch: `main`, folder: **`/docs`**
   - Save. GitHub will give you a URL like
     `https://<you>.github.io/ch-cleaning-scan/` — that's your dashboard,
     live immediately (showing placeholder sample data until you run the
     scan at least once).

### Running a scan

- Repo → **Actions** tab → **"Run cleaning-sector turnover scan"** →
  **Run workflow**
- You'll be asked for: SIC codes, **discovery_mode** (stage 1), turnover
  band, and turnover-scan **mode** (stage 2):
  - `discovery_mode: bulk` (default) — Free Company Data Product snapshot,
    no per-company API calls, no match-count limit. Optionally set
    `discovery_snapshot_date` (YYYY-MM-DD) if the auto-guessed "1st of this
    month" doesn't match what's published at
    https://download.companieshouse.gov.uk/en_output.html.
  - `discovery_mode: api` — live Advanced Search. Only use for a narrow SIC
    sweep you know returns under ~10,000 companies; a full cleaning-sector
    sweep will fail partway through (see Stage 1 notes above).
  - turnover-scan `mode: api` — per-company, always current, but slower.
    There's an `api_company_limit` safety cap (default 500) so a first run
    doesn't accidentally try to process every matched company in one go and
    time out — raise it once you're happy with a small test run.
  - turnover-scan `mode: bulk` — uses Companies House's free monthly
    accounts archive (no extra API calls beyond discovery), and for a full
    sector sweep at scale this is the one to use: `bulk_month` is treated as
    an **anchor** month, and the workflow loops back over the **trailing 18
    months** ending there, `--append`-ing each one into `results.csv`. This
    matters because each monthly archive only contains accounts *filed*
    that month — since a company files once a year on its own schedule, a
    single month alone would only cover ~1/12 of your discovered companies;
    the extra 6 months beyond a full year gives headroom for late filers and
    companies whose accounting reference date has shifted.
    Leave `bulk_month` blank to anchor on today's month, or check
    https://download.companieshouse.gov.uk/en_accountsdata.html to confirm
    the filename pattern still matches `src/bulk_scan.py` if a month in the
    loop fails (the workflow logs a warning and skips that month rather
    than failing the whole run).
- When it finishes, it commits `docs/results.json`, and the dashboard
  updates automatically — refresh the Pages URL.

### Notes

- Because Pages is serving from a **public** repo, the dashboard (and the
  underlying `results.json`/`results.csv`) is publicly visible at that URL.
  That's fine here since everything in it is already public Companies
  House data — just worth knowing before you point this at anything else.
- The Action has `timeout-minutes: 300` (5 hours) as a hard ceiling — a
  full-sector `api` mode sweep of thousands of companies could still hit
  that; use the `api_company_limit` input or switch to `bulk` mode for
  large sweeps. Bulk mode's trailing-18-months loop downloads 18 monthly
  archives in one run (each is 1-4GB), which also takes real time — if this
  becomes a problem, split it across several workflow runs using different
  `bulk_month` anchors instead.
- If a run fails, check the Actions tab logs first — most likely causes are
  a missing/incorrect secret, a wrong bulk month/snapshot date/URL, or (if
  `discovery_mode` was set to `api` for a broad sector) the Advanced Search
  10,000-match ceiling described above.

## Known limitations

- The Companies House Advanced Search API (`--mode api` for stage 1) cannot
  paginate past roughly 10,000 matches for a given query — this is a
  confirmed platform limitation, not a bug in this tool. Use `--mode bulk`
  for any SIC sweep likely to return more than that (the default cleaning
  codes do, nationwide).
- Small and micro companies are legally allowed to file abbreviated/filleted
  accounts **without a P&L or turnover figure at all**. Those companies will
  show up in `companies.csv` but with no turnover in the results — this is
  not a bug, it's a disclosure exemption. Expect a real gap in coverage for
  the smaller end of any SIC code.
- `bulk_scan.py` skips a small fraction (~0.08% in a real monthly archive)
  of entries filed as `.zip`-wrapped alternate formats (UKSEF joint filings,
  CIC accounts) rather than plain iXBRL `.html` — `src/ixbrl_parser.py`
  doesn't unpack or parse those, so they're silently excluded rather than
  mis-parsed.
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
