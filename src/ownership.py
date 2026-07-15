"""
Best-effort ownership-type classification from Companies House
Persons-with-Significant-Control (PSC) data.

This is a heuristic, not a legal determination — always sanity-check
anything unusual (e.g. "Corporate parent" could still be a holding company
wholly owned by the same founder family).
"""

from __future__ import annotations


def classify_ownership(psc_items: list[dict]) -> str:
    if not psc_items:
        return "Unknown / no PSC registered"

    kinds = {item.get("kind", "") for item in psc_items}
    names = " ".join(item.get("name", "") for item in psc_items).lower()

    if "trustees" in names or "employee ownership trust" in names or "eot" in names:
        return "Employee Ownership Trust"

    if any(k == "corporate-entity-person-with-significant-control" for k in kinds):
        return "Corporate parent / group subsidiary"

    if any(k.startswith("individual-person-with-significant-control") for k in kinds):
        individuals = [i for i in psc_items if i.get("kind", "").startswith("individual")]
        if len(individuals) == 1:
            return "Sole individual owner"
        return f"Individual owners ({len(individuals)})"

    if any(k.startswith("legal-person-with-significant-control") for k in kinds):
        return "Legal entity (non-corporate) control"

    return "Unclassified — check PSC record manually"
