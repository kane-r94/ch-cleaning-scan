#!/usr/bin/env python3
"""
Fills in ownership_type for rows produced by bulk_scan.py, which can't look
up Persons with Significant Control (PSC) without hitting the API and is
deliberately designed to avoid per-company API calls during the turnover
sweep itself.

This script runs against the already turnover-filtered output/results.csv
instead — typically a few dozen companies, not thousands — so it's cheap
even though it needs the API and a company key.

Usage:
    python src/enrich_ownership.py --in output/results.csv
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
from ownership import classify_ownership

log = logging.getLogger(__name__)

BULK_PLACEHOLDER = (
    "Not looked up in bulk mode — cross-reference via ownership.py + PSC API if needed"
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--in", dest="infile", default="output/results.csv")
    parser.add_argument("--out", dest="outfile", default=None,
                         help="defaults to overwriting --in in place")
    parser.add_argument("--force", action="store_true",
                         help="re-look-up ownership for every row, not just rows still "
                              "showing the bulk-mode placeholder")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                         format="%(asctime)s %(levelname)s %(message)s")

    outfile = args.outfile or args.infile

    if not os.path.exists(args.infile):
        sys.exit(f"Input not found: {args.infile}")

    with open(args.infile, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    if not rows:
        print(f"No rows in {args.infile} — nothing to enrich.")
        return

    client = CompaniesHouseClient()

    updated = 0
    for row in tqdm(rows, desc="Looking up PSC ownership"):
        if not args.force and row.get("ownership_type", "") != BULK_PLACEHOLDER:
            continue
        number = row.get("company_number", "")
        if not number:
            continue
        try:
            psc_items = client.persons_with_significant_control(number)
            row["ownership_type"] = classify_ownership(psc_items)
            updated += 1
        except Exception as exc:  # noqa: BLE001 - keep going across the rest of the list
            log.warning("PSC lookup failed for %s (%s): %s", number, row.get("company_name"), exc)
            row["ownership_type"] = "PSC lookup failed — retry or check manually"
        time.sleep(0.1)

    with open(outfile, "w", newline="", encoding="utf-8") as out_f:
        writer = csv.DictWriter(out_f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Updated ownership for {updated} companies in {outfile}")


if __name__ == "__main__":
    main()
