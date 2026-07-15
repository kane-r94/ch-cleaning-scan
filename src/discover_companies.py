#!/usr/bin/env python3
"""
Stage 1: discover every company registered under given SIC code(s) via the
Companies House Advanced Search API, and write them to data/companies.csv.

Usage:
    python src/discover_companies.py --sic 81210 81220 81290 --status active
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import sys

from ch_api import CompaniesHouseClient

log = logging.getLogger(__name__)

# Common cleaning-sector SIC codes (2007 UK SIC):
#   81210 - General cleaning of buildings
#   81220 - Other building and industrial cleaning activities
#   81221 - Window cleaning services
#   81222 - Specialised cleaning services
#   81223 - Furnace and chimney cleaning
#   81229 - Other building and industrial cleaning activities n.e.c.
#   81290 - Other cleaning services
DEFAULT_SIC_CODES = ["81210", "81220", "81221", "81222", "81223", "81229", "81290"]

FIELDNAMES = [
    "company_number",
    "company_name",
    "company_status",
    "company_type",
    "date_of_creation",
    "sic_codes",
    "address_snippet",
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sic", nargs="+", default=DEFAULT_SIC_CODES,
                         help=f"SIC codes to search (default: {DEFAULT_SIC_CODES})")
    parser.add_argument("--status", default="active",
                         help="company_status filter (default: active)")
    parser.add_argument("--out", default="data/companies.csv")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                         format="%(asctime)s %(levelname)s %(message)s")

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)

    client = CompaniesHouseClient()

    count = 0
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for item in client.advanced_search_companies(sic_codes=args.sic, company_status=args.status):
            address = item.get("registered_office_address", {}) or {}
            address_snippet = ", ".join(
                filter(None, [
                    address.get("address_line_1"),
                    address.get("locality"),
                    address.get("postal_code"),
                ])
            )
            writer.writerow({
                "company_number": item.get("company_number"),
                "company_name": item.get("company_name") or item.get("title"),
                "company_status": item.get("company_status"),
                "company_type": item.get("company_type"),
                "date_of_creation": item.get("date_of_creation"),
                "sic_codes": ";".join(item.get("sic_codes", []) or []),
                "address_snippet": address_snippet,
            })
            count += 1
            if count % 200 == 0:
                print(f"  ...{count} companies written so far", file=sys.stderr)

    print(f"Done. {count} companies written to {args.out}")


if __name__ == "__main__":
    main()
