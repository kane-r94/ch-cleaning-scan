#!/usr/bin/env python3
"""
Reads output/results.csv and writes docs/results.json — the file the static
dashboard (docs/index.html) loads. Adds run metadata and summary stats so
the dashboard doesn't need to recompute anything client-side from a raw CSV.

Usage:
    python src/export_dashboard_json.py \\
        --in output/results.csv --out docs/results.json \\
        --min-turnover 10000000 --max-turnover 30000000 --mode api
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone


def to_number(value: str) -> float | None:
    if not value:
        return None
    try:
        return float(value.replace(",", ""))
    except ValueError:
        return None


RESULT_FIELDS = [
    "company_name", "entity_type", "company_number", "hq_address",
    "latest_turnover", "turnover_year", "employees", "ownership_type",
    "sic_codes", "confidence", "source",
]


def load_manual_additions(path: str, min_turnover: float, max_turnover: float,
                           already_matched: set) -> list[dict]:
    """
    Confirmed rows from manual_review/manual_additions.csv (human-verified
    against the actual filed document — see src/fetch_gap_documents.py) get
    folded into the dashboard alongside the auto-parsed results, labelled
    "Manually verified" so they stay visually distinct. A row only counts
    once it has a numeric latest_turnover inside the current band — a
    half-filled-in working copy, or one left over from a previous, wider
    band, is safely ignored rather than silently included.
    """
    if not os.path.exists(path):
        return []

    with open(path, newline="", encoding="utf-8-sig") as f:
        raw_rows = list(csv.DictReader(f))

    by_company: dict[str, dict] = {}
    for row in raw_rows:
        number = (row.get("company_number") or "").strip()
        if not number:
            continue
        turnover = to_number(row.get("latest_turnover", ""))
        if turnover is None or not (min_turnover <= turnover <= max_turnover):
            continue
        if number in already_matched:
            continue
        by_company[number] = {
            "company_name": row.get("company_name", ""),
            "entity_type": row.get("entity_type", ""),
            "company_number": number,
            "hq_address": row.get("hq_address", ""),
            "latest_turnover": f"{turnover:,.0f}",
            "turnover_year": row.get("turnover_year", ""),
            "employees": row.get("employees", ""),
            "ownership_type": row.get("ownership_type", ""),
            "sic_codes": row.get("sic_codes", ""),
            "confidence": "Manually verified",
            "source": (
                f"Manually confirmed from filed accounts, Companies House "
                f"company no. {number} (see manual_review/manual_additions.csv)"
            ),
        }
    return list(by_company.values())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="infile", default="output/results.csv")
    parser.add_argument("--out", dest="outfile", default="docs/results.json")
    parser.add_argument("--min-turnover", type=float, default=5_000_000)
    parser.add_argument("--max-turnover", type=float, default=35_000_000)
    parser.add_argument("--mode", default="api", choices=["api", "bulk"])
    parser.add_argument("--manual-additions", default="manual_review/manual_additions.csv",
                         help="confirmed manual entries to fold in alongside the auto-parsed results")
    args = parser.parse_args()

    if not os.path.exists(args.infile):
        sys.exit(f"Input not found: {args.infile}")

    with open(args.infile, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    already_matched = {r.get("company_number", "") for r in rows}
    manual_rows = load_manual_additions(args.manual_additions, args.min_turnover,
                                         args.max_turnover, already_matched)
    if manual_rows:
        print(f"Folding in {len(manual_rows)} confirmed manual addition(s) from {args.manual_additions}")
        rows.extend(manual_rows)

    turnovers = [to_number(r.get("latest_turnover", "")) for r in rows]
    turnovers = [t for t in turnovers if t is not None]

    ownership_counts = Counter(r.get("ownership_type", "Unknown") for r in rows)
    confidence_counts = Counter(r.get("confidence", "Unknown") for r in rows)

    # Simple histogram of turnover in £2.5m bins across the scanned band,
    # for the dashboard's distribution chart.
    bin_size = 2_500_000
    bins: dict[str, int] = {}
    if turnovers:
        lo = int(args.min_turnover // bin_size) * bin_size
        hi = int(args.max_turnover // bin_size + 1) * bin_size
        edges = list(range(lo, hi, bin_size))
        for edge in edges:
            label = f"£{edge/1_000_000:.1f}m\u2013£{(edge+bin_size)/1_000_000:.1f}m"
            bins[label] = 0
        for t in turnovers:
            for edge in edges:
                if edge <= t < edge + bin_size:
                    label = f"£{edge/1_000_000:.1f}m\u2013£{(edge+bin_size)/1_000_000:.1f}m"
                    bins[label] += 1
                    break

    output = {
        "is_sample": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scan_mode": args.mode,
        "turnover_band": {"min": args.min_turnover, "max": args.max_turnover},
        "summary": {
            "company_count": len(rows),
            "average_turnover": (sum(turnovers) / len(turnovers)) if turnovers else None,
            "median_turnover": (sorted(turnovers)[len(turnovers) // 2] if turnovers else None),
            "total_employees": sum(
                int(to_number(r.get("employees", "")) or 0) for r in rows
            ),
        },
        "ownership_breakdown": dict(ownership_counts),
        "confidence_breakdown": dict(confidence_counts),
        "turnover_histogram": bins,
        "companies": rows,
    }

    os.makedirs(os.path.dirname(args.outfile) or ".", exist_ok=True)
    with open(args.outfile, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    print(f"Wrote {args.outfile}: {len(rows)} companies")


if __name__ == "__main__":
    main()
