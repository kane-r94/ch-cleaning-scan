#!/usr/bin/env python3
"""
Stage 5 (optional, human-in-the-loop): for every company in
output/gap_companies.csv, downloads their latest full-accounts document as a
human-readable PDF into output/gap_documents/, and writes a companion review
spreadsheet (output/gap_review.csv) with the known company details already
filled in and blank columns for you to fill in after reading each PDF.

Once you've read a company's PDF and confirmed its turnover falls in the
target band, copy that row (with the blanks filled in) into
manual_review/manual_additions.csv — export_dashboard_json.py picks that
file up automatically and folds confirmed entries into the dashboard,
labelled "Manually verified" so they stay visually distinct from the
"Audited" auto-parsed rows. Rows with no numeric latest_turnover are ignored,
so a half-filled-in working copy of this spreadsheet is safe to keep around.

Usage:
    python src/fetch_gap_documents.py
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import re
import sys
import time

from tqdm import tqdm

from ch_api import CompaniesHouseClient

log = logging.getLogger(__name__)

REVIEW_FIELDS = [
    "company_number", "company_name", "entity_type", "hq_address",
    "sic_codes", "accounts_category", "filing_date", "pdf_filename",
    "latest_turnover", "turnover_year", "employees", "meets_band", "notes",
]


def _safe_filename(company_number: str, company_name: str) -> str:
    name = re.sub(r"[^A-Za-z0-9]+", "_", company_name).strip("_")[:60]
    return f"{company_number}_{name}.pdf"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--in", dest="infile", default="output/gap_companies.csv")
    parser.add_argument("--docs-dir", default="output/gap_documents")
    parser.add_argument("--out", dest="outfile", default="output/gap_review.csv")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                         format="%(asctime)s %(levelname)s %(message)s")

    if not os.path.exists(args.infile):
        sys.exit(f"Not found: {args.infile}. Run find_gap_companies.py first.")

    with open(args.infile, newline="", encoding="utf-8-sig") as f:
        companies = list(csv.DictReader(f))

    os.makedirs(args.docs_dir, exist_ok=True)
    os.makedirs(os.path.dirname(args.outfile) or ".", exist_ok=True)

    client = CompaniesHouseClient()

    rows = []
    for row in tqdm(companies, desc="Fetching gap-company accounts"):
        number = row.get("company_number", "")
        name = row.get("company_name", "")
        pdf_filename = ""
        filing_date = ""
        try:
            filing = client.latest_accounts_filing(number)
            if filing:
                filing_date = filing.get("date", "")
                doc_meta = filing.get("links", {}).get("document_metadata")
                if doc_meta:
                    document_id = doc_meta.rstrip("/").split("/")[-1]
                    pdf_bytes = client.download_document(document_id, content_type="application/pdf")
                    pdf_filename = _safe_filename(number, name)
                    with open(os.path.join(args.docs_dir, pdf_filename), "wb") as pdf_f:
                        pdf_f.write(pdf_bytes)
        except Exception as exc:  # noqa: BLE001 - keep going across the rest of the list
            log.warning("Failed to fetch document for %s (%s): %s", number, name, exc)
        time.sleep(0.1)

        rows.append({
            "company_number": number,
            "company_name": name,
            "entity_type": row.get("company_type", ""),
            "hq_address": row.get("address_snippet", ""),
            "sic_codes": row.get("sic_codes", ""),
            "accounts_category": row.get("accounts_category", ""),
            "filing_date": filing_date,
            "pdf_filename": pdf_filename,
            "latest_turnover": "",
            "turnover_year": "",
            "employees": "",
            "meets_band": "",
            "notes": "" if pdf_filename else "Could not fetch a document — check manually",
        })

    with open(args.outfile, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=REVIEW_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    fetched = sum(1 for r in rows if r["pdf_filename"])
    print(f"Fetched {fetched}/{len(rows)} documents into {args.docs_dir}")
    print(f"Review spreadsheet written to {args.outfile}")


if __name__ == "__main__":
    main()
