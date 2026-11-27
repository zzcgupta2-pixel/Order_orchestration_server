from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class WorkingCalendarConfig:
    """
    Configuration for a working calendar.

    Default assumptions:
    - Monday to Saturday are working days.
    - Sunday is non-working.
    - Working hours are 09:00 to 18:00.
    - Holidays are configurable.
    - Timezone is configurable.
    """

    working_days: set[int] = field(default_factory=lambda: {0, 1, 2, 3, 4, 5})
    work_start_time: time = time(9, 0)
    work_end_time: time = time(18, 0)
    holidays: set[date] = field(default_factory=set)
    timezone_name: str = "Asia/Kolkata"


def ensure_timezone_aware(
    input_datetime: datetime,
    timezone_name: str,
) -> datetime:
    """
    Ensures datetime is timezone-aware.

    If the input datetime is naive, the configured timezone is attached.
    If the input datetime is already timezone-aware, it is converted to
    the configured timezone.
    """

    target_timezone = ZoneInfo(timezone_name)

    if input_datetime.tzinfo is None:
        return input_datetime.replace(tzinfo=target_timezone)

    return input_datetime.astimezone(target_timezone)


def is_working_day(
    input_date: date,
    calendar_config: WorkingCalendarConfig,
) -> bool:
    """
    Returns True if the given date is a working day.

    A working day must:
    - belong to configured working weekdays
    - not be present in configured holidays
    """

    if input_date in calendar_config.holidays:
        return False

    return input_date.weekday() in calendar_config.working_days


def is_working_time(
    input_datetime: datetime,
    calendar_config: WorkingCalendarConfig,
) -> bool:
    """
    Returns True if the given datetime falls within configured working time.

    The datetime must:
    - be on a working day
    - be greater than or equal to work_start_time
    - be strictly before work_end_time
    """

    local_datetime = ensure_timezone_aware(
        input_datetime=input_datetime,
        timezone_name=calendar_config.timezone_name,
    )

    if not is_working_day(local_datetime.date(), calendar_config):
        return False

    current_time = local_datetime.time()

    return (
        calendar_config.work_start_time
        <= current_time
        < calendar_config.work_end_time
    )


def start_of_working_day(
    input_date: date,
    calendar_config: WorkingCalendarConfig,
) -> datetime:
    """
    Returns the configured start datetime for a working day.
    """

    timezone = ZoneInfo(calendar_config.timezone_name)

    return datetime.combine(
        input_date,
        calendar_config.work_start_time,
        tzinfo=timezone,
    )


def next_working_day(
    input_date: date,
    calendar_config: WorkingCalendarConfig,
) -> date:
    """
    Returns the next date that is a working day.

    The search starts from the day after input_date.
    """

    candidate_date = input_date + timedelta(days=1)

    while not is_working_day(candidate_date, calendar_config):
        candidate_date += timedelta(days=1)

    return candidate_date


def next_working_time(
    input_datetime: datetime,
    calendar_config: WorkingCalendarConfig,
) -> datetime:
    """
    Moves input datetime to the next valid working datetime.

    Rules:
    - If input falls within working time, return it as-is.
    - If input date is non-working, move to next working day start.
    - If input time is before work start, move to same day work start.
    - If input time is at or after work end, move to next working day start.
    """

    local_datetime = ensure_timezone_aware(
        input_datetime=input_datetime,
        timezone_name=calendar_config.timezone_name,
    )

    current_date = local_datetime.date()
    current_time = local_datetime.time()

    if is_working_time(local_datetime, calendar_config):
        return local_datetime

    if not is_working_day(current_date, calendar_config):
        next_day = current_date

        while not is_working_day(next_day, calendar_config):
            next_day += timedelta(days=1)

        return start_of_working_day(next_day, calendar_config)

    if current_time < calendar_config.work_start_time:
        return start_of_working_day(current_date, calendar_config)

    next_day = next_working_day(current_date, calendar_config)
    return start_of_working_day(next_day, calendar_config)


def add_working_duration(
    start_datetime: datetime,
    duration_hours: int | float,
    calendar_config: WorkingCalendarConfig,
) -> datetime:
    """
    Adds working duration in hours while respecting working days and working hours.

    Example:
        Start = Monday 16:00
        Duration = 4 working hours
        Workday = 09:00 to 18:00

        Result = Tuesday 11:00
    """

    if duration_hours < 0:
        raise ValueError("duration_hours cannot be negative.")

    current_datetime = next_working_time(
        input_datetime=start_datetime,
        calendar_config=calendar_config,
    )

    remaining_duration = timedelta(hours=duration_hours)

    while remaining_duration > timedelta(0):
        work_end_datetime = datetime.combine(
            current_datetime.date(),
            calendar_config.work_end_time,
            tzinfo=ZoneInfo(calendar_config.timezone_name),
        )

        available_today = work_end_datetime - current_datetime

        if remaining_duration <= available_today:
            return current_datetime + remaining_duration

        remaining_duration -= available_today

        next_day = next_working_day(
            input_date=current_datetime.date(),
            calendar_config=calendar_config,
        )

        current_datetime = start_of_working_day(
            input_date=next_day,
            calendar_config=calendar_config,
        )

    return current_datetime