"""
Extracts turnover and average employee figures from a Companies House
iXBRL accounts document.

iXBRL embeds XBRL facts inside human-readable HTML using <ix:nonFraction>
(numeric) tags. Each fact has a `name` attribute like
"core:TurnoverGrossOperatingRevenue" or "core:Turnover" — the prefix and
exact element name vary by taxonomy version (old UK GAAP, FRS 101, FRS 102,
full IFRS), so this parser matches on a list of known local names rather
than a single exact tag.

This is inherently a best-effort exercise: Companies House does not enforce
one taxonomy, and smaller filers' software sometimes tags things
inconsistently. Treat "not found" as "not disclosed or not detected" — see
README "Known limitations".
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from bs4 import BeautifulSoup

# Local element names (case-insensitive, namespace prefix ignored) that
# represent turnover/revenue across taxonomy versions in common use.
TURNOVER_TAGS = {
    "turnover",
    "turnovergrossoperatingrevenue",
    "turnoverrevenue",
    "revenue",
    "grossrevenue",
    "totalturnoverrevenue",
}

EMPLOYEE_TAGS = {
    "averagenumberemployeesduringperiod",
    "employeenumbersstaff",
    "averagenumberofemployeesduringtheperiod",
}


@dataclass
class Fact:
    tag: str
    raw_value: Decimal
    scale: int
    sign: str
    context_ref: str
    unit_ref: str | None

    @property
    def value(self) -> Decimal:
        v = self.raw_value * (Decimal(10) ** self.scale)
        return -v if self.sign == "-" else v


def _clean_number(text: str) -> Decimal:
    cleaned = text.strip().replace(",", "").replace("\u2013", "-").replace("\xa0", "")
    if cleaned in ("", "-", "\u2014"):
        return Decimal(0)
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        raise ValueError(f"Could not parse numeric iXBRL fact text: {text!r}")


def _local_name(name_attr: str) -> str:
    """Strip a namespace prefix like 'core:Turnover' -> 'turnover'."""
    return name_attr.split(":")[-1].lower() if name_attr else ""


def parse_ixbrl(document_bytes: bytes) -> dict:
    """
    Parses an iXBRL document and returns the best-guess turnover and
    employee figures, plus the raw facts found (for manual sanity-checking)
    and the reporting period end-date context, where determinable.

    Returns:
        {
          "turnover": Decimal | None,
          "turnover_tag": str | None,
          "employees": Decimal | None,
          "employees_tag": str | None,
          "period_end": str | None,          # best-effort, from context
          "all_turnover_candidates": [Fact, ...],
          "all_employee_candidates": [Fact, ...],
        }
    """
    soup = BeautifulSoup(document_bytes, "lxml-xml")

    # ix:nonFraction elements carry the numeric facts we care about.
    non_fractions = soup.find_all(lambda t: t.name and t.name.split(":")[-1] == "nonFraction")

    turnover_candidates: list[Fact] = []
    employee_candidates: list[Fact] = []

    for el in non_fractions:
        name_attr = el.get("name", "")
        local = _local_name(name_attr)
        if local not in TURNOVER_TAGS and local not in EMPLOYEE_TAGS:
            continue
        try:
            raw = _clean_number(el.get_text())
        except ValueError:
            continue
        scale = int(el.get("scale", 0) or 0)
        sign = el.get("sign", "") or ""
        context_ref = el.get("contextref", "") or el.get("contextRef", "")
        unit_ref = el.get("unitref") or el.get("unitRef")
        fact = Fact(tag=local, raw_value=raw, scale=scale, sign=sign,
                    context_ref=context_ref, unit_ref=unit_ref)
        if local in TURNOVER_TAGS:
            turnover_candidates.append(fact)
        else:
            employee_candidates.append(fact)

    period_end = _best_effort_period_end(soup)

    turnover_fact = _pick_best_candidate(turnover_candidates, soup, period_end)
    employee_fact = _pick_best_candidate(employee_candidates, soup, period_end)

    return {
        "turnover": turnover_fact.value if turnover_fact else None,
        "turnover_tag": turnover_fact.tag if turnover_fact else None,
        "employees": employee_fact.value if employee_fact else None,
        "employees_tag": employee_fact.tag if employee_fact else None,
        "period_end": period_end,
        "all_turnover_candidates": turnover_candidates,
        "all_employee_candidates": employee_candidates,
    }


def _best_effort_period_end(soup: BeautifulSoup) -> str | None:
    """
    Looks for the latest <xbrli:instant> or period end-date in the
    document's contexts, to help identify which candidate fact belongs to
    the current (vs. prior) reporting period.
    """
    end_dates = []
    for el in soup.find_all(lambda t: t.name and t.name.split(":")[-1] in ("endDate", "instant")):
        text = el.get_text(strip=True)
        if text:
            end_dates.append(text)
    return max(end_dates) if end_dates else None


def _pick_best_candidate(
    candidates: list[Fact], soup: BeautifulSoup, period_end: str | None
) -> Fact | None:
    """
    A document typically tags both the current and prior year's figures.
    Prefer the fact whose context maps to the latest period end-date; fall
    back to the largest context_ref (usually the current period in
    Companies House's context-id convention) or simply the first found.
    """
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    if period_end:
        context_ids_for_latest_period = set()
        for ctx in soup.find_all(lambda t: t.name and t.name.split(":")[-1] == "context"):
            ctx_id = ctx.get("id")
            if not ctx_id:
                continue
            dates = [
                e.get_text(strip=True)
                for e in ctx.find_all(lambda t: t.name and t.name.split(":")[-1] in ("endDate", "instant"))
            ]
            if period_end in dates:
                context_ids_for_latest_period.add(ctx_id)
        matching = [f for f in candidates if f.context_ref in context_ids_for_latest_period]
        if matching:
            # Among matches for the latest period, prefer the one with the
            # largest magnitude (guards against a stray segment/dimension
            # fact for a sub-total rather than the headline figure).
            return max(matching, key=lambda f: abs(f.value))

    return max(candidates, key=lambda f: abs(f.value))
