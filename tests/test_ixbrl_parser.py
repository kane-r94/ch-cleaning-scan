import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ixbrl_parser import parse_ixbrl  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(__file__), "fixture_accounts.xhtml")


def test_parses_current_year_turnover_and_employees():
    with open(FIXTURE, "rb") as f:
        result = parse_ixbrl(f.read())

    assert result["turnover"] == Decimal("18450000")
    assert result["turnover_tag"] == "turnover"
    assert result["employees"] == Decimal("412")
    assert result["employees_tag"] == "averagenumberemployeesduringperiod"
    assert result["period_end"] == "2024-05-31"

    # both years should have been detected as candidates even though only
    # the current-year one is picked as the headline figure
    assert len(result["all_turnover_candidates"]) == 2
    assert len(result["all_employee_candidates"]) == 2


if __name__ == "__main__":
    test_parses_current_year_turnover_and_employees()
    print("OK")
