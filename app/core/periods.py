import calendar
from datetime import date

from app.models.enums import RecurrenceFrequency

MONTHS_PER_PERIOD = {
    RecurrenceFrequency.MONTHLY: 1,
    RecurrenceFrequency.QUARTERLY: 3,
    RecurrenceFrequency.ANNUAL: 12,
}


def _last_day_of_month(year: int, month: int) -> int:
    """Computed rather than assumed, so February and leap years are correct."""
    return calendar.monthrange(year, month)[1]


def _add_months(any_date: date, months_to_add: int) -> date:
    total_months = any_date.month - 1 + months_to_add
    year = any_date.year + total_months // 12
    month = total_months % 12 + 1
    day = min(any_date.day, _last_day_of_month(year, month))
    return date(year, month, day)


def period_bounds(
    frequency: RecurrenceFrequency, any_date: date
) -> tuple[date, date]:
    """Return the calendar-aligned period containing any_date, inclusive."""
    months_per_period = MONTHS_PER_PERIOD[frequency]
    start_month = ((any_date.month - 1) // months_per_period) * months_per_period + 1
    start = date(any_date.year, start_month, 1)

    end_month_start = _add_months(start, months_per_period - 1)
    end = date(
        end_month_start.year,
        end_month_start.month,
        _last_day_of_month(end_month_start.year, end_month_start.month),
    )
    return start, end


def next_period(
    frequency: RecurrenceFrequency, period_start: date
) -> tuple[date, date]:
    """Return the period immediately following the one starting at period_start."""
    following_start = _add_months(period_start, MONTHS_PER_PERIOD[frequency])
    return period_bounds(frequency, following_start)
