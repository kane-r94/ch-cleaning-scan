#!/usr/bin/env python3
"""
Stage 1: discover every company registered under given SIC code(s), and
write them to data/companies.csv. Two modes:

--mode api  (default): live Companies House Advanced Search API. Always
    current, but the API has an undocumented-but-confirmed ~10,000-match
    pagination ceiling (start_index only paginates within the first ~10k
    results of a query, not the full match count) — see
    https://forum.companieshouse.gov.uk/t/advanced-search-companies-responds-with-500-after-10000-items/4813
    Fine for narrow SIC sweeps, but common cleaning-sector codes (e.g.
    81210) return more than 10k active companies nationwide and this mode
    WILL fail partway through. Use --mode bulk for those.

--mode bulk: downloads Companies House's free monthly "Free Company Data
    Product" (a full snapshot of every UK company, no API key needed, no
    pagination limit — see https://download.companieshouse.gov.uk/en_output.html)
    and filters it locally by SIC code + status. Slower to download (a few
    hundred MB) but the only mode that reliably covers a whole SIC sector.

Usage:
    python src/discover_companies.py --sic 81210 81220 81290 --status active

    python src/discover_companies.py --mode bulk --sic 81210 81220 81290 \\
        --date 2026-07-01
"""

from __future__ import annotations

import argparse
import csv
import io
import logging
import os
import sys
import zipfile

import requests
from tqdm import tqdm

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
    "accounts_category",
]

# Accounts.AccountCategory values that mean "this company is legally allowed
# to file without disclosing a P&L/turnover figure at all" — used downstream
# by find_gap_companies.py to tell "genuinely has no turnover to find" apart
# from "should have a turnover figure but our pipeline couldn't find one".
EXEMPT_ACCOUNTS_CATEGORIES = {
    "DORMANT",
    "MICRO ENTITY",
    "TOTAL EXEMPTION SMALL",
    "TOTAL EXEMPTION FULL",
    "AUDIT EXEMPTION SUBSIDIARY",
    "UNAUDITED ABRIDGED",
    "AUDITED ABRIDGED",
    "NO ACCOUNTS FILED",
    "ACCOUNTS TYPE NOT AVAILABLE",
    "",
}

# Companies House publishes this dated by the 1st of the month; the actual
# file is usually uploaded a few working days after month-end for the
# *previous* month's snapshot. Check download.companieshouse.gov.uk/en_output.html
# for the current filename and pass it explicitly with --url if this guess
# (today's month, 1st) is wrong.
DEFAULT_URL_TEMPLATE = (
    "https://download.companieshouse.gov.uk/BasicCompanyDataAsOneFile-{date}.zip"
)


def discover_via_api(args) -> int:
    from ch_api import CompaniesHouseClient

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
                "accounts_category": "",  # not available from Advanced Search results
            })
            count += 1
            if count % 200 == 0:
                print(f"  ...{count} companies written so far", file=sys.stderr)
    return count


def download_zip(url: str) -> bytes:
    print(f"Downloading {url} ...", file=sys.stderr)
    resp = requests.get(url, stream=True, timeout=300)
    resp.raise_for_status()
    total = int(resp.headers.get("content-length", 0))
    buf = io.BytesIO()
    with tqdm(total=total, unit="B", unit_scale=True, desc="download") as bar:
        for chunk in resp.iter_content(chunk_size=1024 * 256):
            buf.write(chunk)
            bar.update(len(chunk))
    return buf.getvalue()


def _to_iso_date(value: str) -> str:
    """Free Company Data Product dates are DD/MM/YYYY; convert to ISO for
    consistency with the API mode's date_of_creation. Falls back to the raw
    value if it doesn't parse (e.g. already blank)."""
    value = (value or "").strip()
    if not value:
        return ""
    parts = value.split("/")
    if len(parts) == 3:
        day, month, year = parts
        return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
    return value


def _extract_sic_codes(row: dict) -> list[str]:
    """Pulls the up-to-4 SICCode.SicText_N columns (format "81210 - General
    cleaning of buildings") and returns just the leading numeric codes."""
    codes = []
    for key, value in row.items():
        if not key.startswith("SICCode.SicText"):
            continue
        value = (value or "").strip()
        if not value:
            continue
        code = value.split("-", 1)[0].strip()
        if code:
            codes.append(code)
    return codes


def discover_via_bulk(args) -> int:
    if args.zip_path:
        with open(args.zip_path, "rb") as f:
            zip_bytes = f.read()
    else:
        url = args.url or DEFAULT_URL_TEMPLATE.format(date=args.date)
        zip_bytes = download_zip(url)

    wanted_sic = set(args.sic)
    wanted_status = args.status.strip().lower()

    count = 0
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if not csv_names:
            sys.exit(f"No CSV file found inside {args.zip_path or url}")

        with zf.open(csv_names[0]) as raw, \
                io.TextIOWrapper(raw, encoding="utf-8-sig") as text_f, \
                open(args.out, "w", newline="", encoding="utf-8") as out_f:

            reader = csv.DictReader(text_f)
            reader.fieldnames = [(h or "").strip() for h in reader.fieldnames]

            writer = csv.DictWriter(out_f, fieldnames=FIELDNAMES)
            writer.writeheader()

            for row in tqdm(reader, desc="Scanning company snapshot"):
                row = {(k or "").strip(): v for k, v in row.items()}
                status = (row.get("CompanyStatus") or "").strip().lower()
                if status != wanted_status:
                    continue
                sic_codes = _extract_sic_codes(row)
                if not (wanted_sic & set(sic_codes)):
                    continue

                address_snippet = ", ".join(filter(None, [
                    (row.get("RegAddress.AddressLine1") or "").strip(),
                    (row.get("RegAddress.PostTown") or "").strip(),
                    (row.get("RegAddress.PostCode") or "").strip(),
                ]))

                writer.writerow({
                    "company_number": (row.get("CompanyNumber") or "").strip(),
                    "company_name": (row.get("CompanyName") or "").strip(),
                    "company_status": (row.get("CompanyStatus") or "").strip(),
                    "company_type": (row.get("CompanyCategory") or "").strip(),
                    "date_of_creation": _to_iso_date(row.get("IncorporationDate", "")),
                    "sic_codes": ";".join(sic_codes),
                    "address_snippet": address_snippet,
                    "accounts_category": (row.get("Accounts.AccountCategory") or "").strip().upper(),
                })
                count += 1
                if count % 200 == 0:
                    print(f"  ...{count} companies written so far", file=sys.stderr)
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sic", nargs="+", default=DEFAULT_SIC_CODES,
                         help=f"SIC codes to search (default: {DEFAULT_SIC_CODES})")
    parser.add_argument("--status", default="active",
                         help="company status filter (default: active)")
    parser.add_argument("--out", default="data/companies.csv")
    parser.add_argument("--mode", choices=["api", "bulk"], default="api",
                         help="api = live Advanced Search (fails past ~10k matches); "
                              "bulk = Free Company Data Product snapshot (default: api)")
    parser.add_argument("--date", help="YYYY-MM-DD snapshot date, used with the default bulk URL template")
    parser.add_argument("--url", help="explicit URL to a Free Company Data Product zip (bulk mode)")
    parser.add_argument("--zip-path", help="path to an already-downloaded zip file (bulk mode)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                         format="%(asctime)s %(levelname)s %(message)s")

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)

    if args.mode == "bulk":
        count = discover_via_bulk(args)
    else:
        count = discover_via_api(args)

    print(f"Done. {count} companies written to {args.out}")


if __name__ == "__main__":
    main()
