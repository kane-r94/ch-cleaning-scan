#!/usr/bin/env python3
"""
Stage 4 (optional): narrows the full discovered company list down to
"candidates worth a manual/agent check" — companies matching the target SIC
codes and status whose Accounts.AccountCategory implies they should have a
disclosed turnover figure (not dormant/micro/exempt), but who don't appear
in the turnover-matched results.csv from this run.

This can't tell you WHY a candidate is missing — genuinely outside the
turnover band, filing fell outside the scanned window, or (as confirmed for
THE FLOORBRITE GROUP LIMITED, company no. 01219526) a scanned/image-only
accounts filing with no iXBRL rendering at all — only that it's worth a
human or agent looking at the actual filed document. Only meaningful when
data/companies.csv came from --mode bulk (API-mode discovery doesn't carry
an accounts_category, so every row would show up as "gap").

Usage:
    python src/find_gap_companies.py
"""

from __future__ import annotations

import argparse
import csv
import os
import sys

from discover_companies import EXEMPT_ACCOUNTS_CATEGORIES


def load_csv(path: str) -> list[dict]:
    # utf-8-sig strips a BOM if present (e.g. if the file was re-saved in
    # Excel) — a plain "utf-8" read would silently fold it into the first
    # header name and break every row's company_number lookup.
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--companies", dest="companies_csv", default="data/companies.csv")
    parser.add_argument("--results", dest="results_csv", default="output/results.csv")
    parser.add_argument("--out", dest="outfile", default="output/gap_companies.csv")
    args = parser.parse_args()

    if not os.path.exists(args.companies_csv):
        sys.exit(f"Not found: {args.companies_csv}. Run discover_companies.py first.")
    if not os.path.exists(args.results_csv):
        sys.exit(f"Not found: {args.results_csv}. Run bulk_scan.py / scan_turnover.py first.")

    companies = load_csv(args.companies_csv)
    matched_numbers = {row["company_number"] for row in load_csv(args.results_csv)}

    total = len(companies)
    matched = 0
    exempt = 0
    gap: list[dict] = []

    for row in companies:
        number = row.get("company_number", "")
        if number in matched_numbers:
            matched += 1
            continue
        category = (row.get("accounts_category") or "").strip().upper()
        if category in EXEMPT_ACCOUNTS_CATEGORIES:
            exempt += 1
            continue
        gap.append(row)

    os.makedirs(os.path.dirname(args.outfile) or ".", exist_ok=True)
    fieldnames = list(companies[0].keys()) if companies else []
    with open(args.outfile, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(gap)

    print(f"Discovered companies: {total}")
    print(f"Already matched in {args.results_csv}: {matched}")
    print(f"Exempt accounts category (dormant/micro/abridged — known no-turnover-disclosed gap): {exempt}")
    print(f"Remaining gap — non-exempt, unmatched, worth a manual/agent check: {len(gap)}")
    print(f"Gap list written to {args.outfile}")


if __name__ == "__main__":
    main()
