#!/usr/bin/env python3
"""
Stage 2a (API-driven): for each company in data/companies.csv, fetch its
latest full-accounts filing, download the iXBRL, parse turnover/employees,
and write everything (filtered to the target turnover band) to
output/results.csv.

This makes ~3-4 API calls per company (filing history, document metadata,
document content, PSC), so it's best suited to a few hundred companies at a
time rather than a full-sector sweep — use bulk_scan.py for that instead.

Usage:
    python src/scan_turnover.py --min-turnover 10000000 --max-turnover 30000000
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
import time

from tqdm import tqdm

from ch_api import CompaniesHouseClient
from ixbrl_parser import parse_ixbrl
from ownership import classify_ownership

log = logging.getLogger(__name__)

OUTPUT_FIELDS = [
    "company_name", "entity_type", "company_number", "hq_address",
    "latest_turnover", "turnover_year", "employees", "ownership_type",
    "sic_codes", "confidence", "source",
]


def format_address(profile: dict) -> str:
    addr = profile.get("registered_office_address", {}) or {}
    return ", ".join(filter(None, [
        addr.get("address_line_1"), addr.get("address_line_2"),
        addr.get("locality"), addr.get("region"), addr.get("postal_code"),
    ]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="infile", default="data/companies.csv")
    parser.add_argument("--out", dest="outfile", default="output/results.csv")
    parser.add_argument("--min-turnover", type=float, default=5_000_000)
    parser.add_argument("--max-turnover", type=float, default=35_000_000)
    parser.add_argument("--limit", type=int, default=None,
                         help="cap the number of companies processed (useful for a test run)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                         format="%(asctime)s %(levelname)s %(message)s")

    if not os.path.exists(args.infile):
        sys.exit(f"Input file not found: {args.infile}. Run discover_companies.py first.")

    os.makedirs(os.path.dirname(args.outfile) or ".", exist_ok=True)

    client = CompaniesHouseClient()

    with open(args.infile, newline="", encoding="utf-8") as f:
        companies = list(csv.DictReader(f))
    if args.limit:
        companies = companies[: args.limit]

    matched = 0
    with open(args.outfile, "w", newline="", encoding="utf-8") as out_f:
        writer = csv.DictWriter(out_f, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()

        for row in tqdm(companies, desc="Scanning companies"):
            number = row["company_number"]
            try:
                filing = client.latest_accounts_filing(number)
                if not filing:
                    continue  # no full-accounts filing on record (micro/abridged filer)

                doc_meta = filing.get("links", {}).get("document_metadata")
                if not doc_meta:
                    continue
                document_id = doc_meta.rstrip("/").split("/")[-1]

                doc_bytes = client.download_document(document_id, content_type="application/xhtml+xml")
                parsed = parse_ixbrl(doc_bytes)

                turnover = parsed["turnover"]
                if turnover is None:
                    continue
                turnover_f = float(turnover)
                if not (args.min_turnover <= turnover_f <= args.max_turnover):
                    continue

                profile = client.company_profile(number) or {}
                psc_items = client.persons_with_significant_control(number)

                writer.writerow({
                    "company_name": row["company_name"],
                    "entity_type": profile.get("type", row.get("company_type", "")),
                    "company_number": number,
                    "hq_address": format_address(profile) or row.get("address_snippet", ""),
                    "latest_turnover": f"{turnover_f:,.0f}",
                    "turnover_year": parsed.get("period_end", filing.get("date", "")),
                    "employees": (f"{float(parsed['employees']):,.0f}"
                                  if parsed.get("employees") is not None else ""),
                    "ownership_type": classify_ownership(psc_items),
                    "sic_codes": row.get("sic_codes", ""),
                    "confidence": "Audited",
                    "source": f"Companies House filed accounts, document {document_id}",
                })
                matched += 1
                out_f.flush()
                time.sleep(0.1)

            except Exception as exc:  # noqa: BLE001 - log and keep going across a big scan
                log.warning("Skipping %s (%s) due to error: %s", number, row.get("company_name"), exc)
                continue

    print(f"Done. {matched} companies matched the turnover band, written to {args.outfile}")


if __name__ == "__main__":
    main()
