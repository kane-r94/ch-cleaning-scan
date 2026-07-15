#!/usr/bin/env python3
"""
Stage 2b (bulk-driven): scans one or more months of Companies House's free
"Accounts Data Product" bulk download against data/companies.csv, and
writes matches within the target turnover band to output/results.csv.

This needs NO API key and makes NO per-company API calls — it's the
efficient way to sweep a whole SIC code sector, at the cost of only
covering whichever months you download (each monthly file contains every
account *filed* that month, which is not the same as "every company's
current accounts" — a company only appears in the month it happened to
file).

Data source (Crown copyright, free to reuse):
    https://download.companieshouse.gov.uk/en_accountsdata.html

The exact monthly filenames on that page change over time — check the page
for the current pattern and pass it explicitly with --url if the default
guess below is wrong.

Usage:
    # Download and scan a single month
    python src/bulk_scan.py --month 2026-06 \\
        --min-turnover 10000000 --max-turnover 30000000

    # Scan a ZIP you already downloaded manually
    python src/bulk_scan.py --zip-path ./Accounts_Monthly_Data-June2026.zip \\
        --min-turnover 10000000 --max-turnover 30000000
"""

from __future__ import annotations

import argparse
import csv
import datetime
import io
import logging
import os
import re
import sys
import zipfile

import requests
from tqdm import tqdm

from ixbrl_parser import parse_ixbrl

log = logging.getLogger(__name__)

OUTPUT_FIELDS = [
    "company_name", "entity_type", "company_number", "hq_address",
    "latest_turnover", "turnover_year", "employees", "ownership_type",
    "sic_codes", "confidence", "source",
]

# Companies House has used a couple of naming conventions over the years;
# adjust here (or pass --url) if download.companieshouse.gov.uk's current
# page shows something different. Confirmed current pattern (verified
# against a real download): Accounts_Monthly_Data-{MonthName}{Year}.zip,
# e.g. Accounts_Monthly_Data-June2026.zip.
DEFAULT_URL_TEMPLATE = (
    "https://download.companieshouse.gov.uk/Accounts_Monthly_Data-{month_name}{year}.zip"
)

# Filenames inside the zip carry a batch-code prefix before the actual
# company number, e.g. Prod224_2606_00009604_20250930.html — the prefix
# segments vary by batch, so match on the number+date immediately before
# ".html" rather than assuming the filename starts with the company number.
COMPANY_NUMBER_RE = re.compile(
    r"^.*_(?P<number>[A-Z0-9]{6,8})_(?P<date>\d{8})\.html$", re.IGNORECASE
)


def _month_to_filename_parts(month: str) -> tuple[str, str]:
    """Converts a 'YYYY-MM' CLI argument into the (MonthName, Year) pair
    the download filename actually uses, e.g. ('2026-06') -> ('June', '2026')."""
    dt = datetime.datetime.strptime(month, "%Y-%m")
    return dt.strftime("%B"), dt.strftime("%Y")


def load_companies_of_interest(path: str) -> dict[str, dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return {row["company_number"]: row for row in csv.DictReader(f)}


def download_zip(url: str) -> bytes:
    print(f"Downloading {url} ...", file=sys.stderr)
    resp = requests.get(url, stream=True, timeout=120)
    resp.raise_for_status()
    total = int(resp.headers.get("content-length", 0))
    buf = io.BytesIO()
    with tqdm(total=total, unit="B", unit_scale=True, desc="download") as bar:
        for chunk in resp.iter_content(chunk_size=1024 * 256):
            buf.write(chunk)
            bar.update(len(chunk))
    return buf.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--month", help="YYYY-MM, used with the default URL template")
    parser.add_argument("--url", help="explicit URL to a monthly Accounts Data Product zip")
    parser.add_argument("--zip-path", help="path to an already-downloaded zip file")
    parser.add_argument("--companies", dest="companies_csv", default="data/companies.csv")
    parser.add_argument("--out", dest="outfile", default="output/results.csv")
    parser.add_argument("--min-turnover", type=float, default=10_000_000)
    parser.add_argument("--max-turnover", type=float, default=30_000_000)
    parser.add_argument("--append", action="store_true",
                         help="append to an existing results.csv instead of overwriting "
                              "(use this when scanning multiple months in turn)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                         format="%(asctime)s %(levelname)s %(message)s")

    if not os.path.exists(args.companies_csv):
        sys.exit(f"Company list not found: {args.companies_csv}. Run discover_companies.py first.")
    companies = load_companies_of_interest(args.companies_csv)
    print(f"Matching against {len(companies)} companies of interest")

    if args.zip_path:
        with open(args.zip_path, "rb") as f:
            zip_bytes = f.read()
    else:
        if args.url:
            url = args.url
        else:
            month_name, year = _month_to_filename_parts(args.month)
            url = DEFAULT_URL_TEMPLATE.format(month_name=month_name, year=year)
        zip_bytes = download_zip(url)

    os.makedirs(os.path.dirname(args.outfile) or ".", exist_ok=True)
    mode = "a" if args.append and os.path.exists(args.outfile) else "w"
    write_header = mode == "w"

    matched = 0
    scanned = 0
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf, \
            open(args.outfile, mode, newline="", encoding="utf-8") as out_f:

        writer = csv.DictWriter(out_f, fieldnames=OUTPUT_FIELDS)
        if write_header:
            writer.writeheader()

        names = zf.namelist()
        for name in tqdm(names, desc="Scanning filed accounts"):
            m = COMPANY_NUMBER_RE.match(os.path.basename(name))
            if not m:
                continue
            number = m.group("number").lstrip("0").rjust(len(m.group("number")), "0")
            # Companies House numbers are zero-padded 8 chars in some
            # contexts and unpadded in others — try both.
            row = companies.get(number) or companies.get(number.lstrip("0")) or companies.get(number.zfill(8))
            if not row:
                continue

            scanned += 1
            try:
                doc_bytes = zf.read(name)
                parsed = parse_ixbrl(doc_bytes)
            except Exception as exc:  # noqa: BLE001
                log.warning("Failed to parse %s: %s", name, exc)
                continue

            turnover = parsed["turnover"]
            if turnover is None:
                continue
            turnover_f = float(turnover)
            if not (args.min_turnover <= turnover_f <= args.max_turnover):
                continue

            writer.writerow({
                "company_name": row.get("company_name", ""),
                "entity_type": row.get("company_type", ""),
                "company_number": row.get("company_number", number),
                "hq_address": row.get("address_snippet", ""),
                "latest_turnover": f"{turnover_f:,.0f}",
                "turnover_year": parsed.get("period_end", ""),
                "employees": (f"{float(parsed['employees']):,.0f}"
                              if parsed.get("employees") is not None else ""),
                "ownership_type": "Not looked up in bulk mode — cross-reference via "
                                  "ownership.py + PSC API if needed",
                "sic_codes": row.get("sic_codes", ""),
                "confidence": "Audited",
                "source": f"Companies House Accounts Data Product, file {name}",
            })
            matched += 1

    print(f"Scanned {scanned} filings for companies of interest; "
          f"{matched} matched the turnover band. Written to {args.outfile}")


if __name__ == "__main__":
    main()
