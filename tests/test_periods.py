from datetime import date

import pytest

from app.core.periods import next_period, period_bounds
from app.models.enums import RecurrenceFrequency

MONTHLY = RecurrenceFrequency.MONTHLY
QUARTERLY = RecurrenceFrequency.QUARTERLY
ANNUAL = RecurrenceFrequency.ANNUAL


@pytest.mark.parametrize(
    "frequency,any_date,expected",
    [
        (MONTHLY, date(2026, 8, 17), (date(2026, 8, 1), date(2026, 8, 31))),
        (MONTHLY, date(2026, 2, 3), (date(2026, 2, 1), date(2026, 2, 28))),
        (MONTHLY, date(2028, 2, 3), (date(2028, 2, 1), date(2028, 2, 29))),
        (QUARTERLY, date(2026, 8, 17), (date(2026, 7, 1), date(2026, 9, 30))),
        (QUARTERLY, date(2026, 1, 1), (date(2026, 1, 1), date(2026, 3, 31))),
        (ANNUAL, date(2026, 8, 17), (date(2026, 1, 1), date(2026, 12, 31))),
    ],
)
def test_period_bounds(frequency, any_date, expected):
    assert period_bounds(frequency, any_date) == expected


@pytest.mark.parametrize(
    "frequency,period_start,expected",
    [
        (MONTHLY, date(2026, 8, 1), (date(2026, 9, 1), date(2026, 9, 30))),
        (MONTHLY, date(2026, 12, 1), (date(2027, 1, 1), date(2027, 1, 31))),
        (MONTHLY, date(2026, 1, 1), (date(2026, 2, 1), date(2026, 2, 28))),
        (MONTHLY, date(2028, 1, 1), (date(2028, 2, 1), date(2028, 2, 29))),
        (QUARTERLY, date(2026, 7, 1), (date(2026, 10, 1), date(2026, 12, 31))),
        (QUARTERLY, date(2026, 10, 1), (date(2027, 1, 1), date(2027, 3, 31))),
        (ANNUAL, date(2026, 1, 1), (date(2027, 1, 1), date(2027, 12, 31))),
    ],
)
def test_next_period(frequency, period_start, expected):
    assert next_period(frequency, period_start) == expected
