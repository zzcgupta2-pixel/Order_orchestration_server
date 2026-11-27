from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from order_orchestration.calendar.working_calendar import (
    WorkingCalendarConfig,
    add_working_duration,
    is_working_day,
    is_working_time,
    next_working_time,
)


def test_monday_is_working_day():
    config = WorkingCalendarConfig()

    monday = date(2026, 7, 20)

    assert is_working_day(monday, config) is True


def test_sunday_is_non_working_day():
    config = WorkingCalendarConfig()

    sunday = date(2026, 7, 19)

    assert is_working_day(sunday, config) is False


def test_configured_holiday_is_non_working_day():
    holiday = date(2026, 7, 20)

    config = WorkingCalendarConfig(
        holidays={holiday},
    )

    assert is_working_day(holiday, config) is False


def test_time_inside_working_hours_is_working_time():
    config = WorkingCalendarConfig()

    input_datetime = datetime(
        2026,
        7,
        20,
        10,
        0,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )

    assert is_working_time(input_datetime, config) is True


def test_time_before_work_start_is_not_working_time():
    config = WorkingCalendarConfig()

    input_datetime = datetime(
        2026,
        7,
        20,
        8,
        59,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )

    assert is_working_time(input_datetime, config) is False


def test_time_at_work_end_is_not_working_time():
    config = WorkingCalendarConfig()

    input_datetime = datetime(
        2026,
        7,
        20,
        18,
        0,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )

    assert is_working_time(input_datetime, config) is False


def test_next_working_time_before_start_moves_to_same_day_start():
    config = WorkingCalendarConfig()

    input_datetime = datetime(
        2026,
        7,
        20,
        8,
        0,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )

    result = next_working_time(input_datetime, config)

    assert result == datetime(
        2026,
        7,
        20,
        9,
        0,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )


def test_next_working_time_after_end_moves_to_next_day_start():
    config = WorkingCalendarConfig()

    input_datetime = datetime(
        2026,
        7,
        20,
        19,
        0,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )

    result = next_working_time(input_datetime, config)

    assert result == datetime(
        2026,
        7,
        21,
        9,
        0,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )


def test_next_working_time_on_sunday_moves_to_monday_start():
    config = WorkingCalendarConfig()

    input_datetime = datetime(
        2026,
        7,
        19,
        11,
        0,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )

    result = next_working_time(input_datetime, config)

    assert result == datetime(
        2026,
        7,
        20,
        9,
        0,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )


def test_next_working_time_on_holiday_moves_to_next_working_day():
    holiday = date(2026, 7, 20)

    config = WorkingCalendarConfig(
        holidays={holiday},
    )

    input_datetime = datetime(
        2026,
        7,
        20,
        11,
        0,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )

    result = next_working_time(input_datetime, config)

    assert result == datetime(
        2026,
        7,
        21,
        9,
        0,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )


def test_add_working_duration_within_same_day():
    config = WorkingCalendarConfig()

    start_datetime = datetime(
        2026,
        7,
        20,
        10,
        0,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )

    result = add_working_duration(
        start_datetime=start_datetime,
        duration_hours=4,
        calendar_config=config,
    )

    assert result == datetime(
        2026,
        7,
        20,
        14,
        0,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )


def test_add_working_duration_across_days():
    config = WorkingCalendarConfig()

    start_datetime = datetime(
        2026,
        7,
        20,
        16,
        0,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )

    result = add_working_duration(
        start_datetime=start_datetime,
        duration_hours=4,
        calendar_config=config,
    )

    assert result == datetime(
        2026,
        7,
        21,
        11,
        0,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )


def test_add_working_duration_skips_sunday():
    config = WorkingCalendarConfig()

    start_datetime = datetime(
        2026,
        7,
        18,
        16,
        0,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )

    result = add_working_duration(
        start_datetime=start_datetime,
        duration_hours=4,
        calendar_config=config,
    )

    assert result == datetime(
        2026,
        7,
        20,
        11,
        0,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )


def test_add_working_duration_rejects_negative_duration():
    config = WorkingCalendarConfig()

    start_datetime = datetime(
        2026,
        7,
        20,
        10,
        0,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )

    with pytest.raises(ValueError):
        add_working_duration(
            start_datetime=start_datetime,
            duration_hours=-1,
            calendar_config=config,
        )


def test_custom_working_hours_are_supported():
    config = WorkingCalendarConfig(
        work_start_time=time(8, 0),
        work_end_time=time(17, 0),
    )

    input_datetime = datetime(
        2026,
        7,
        20,
        8,
        30,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )

    assert is_working_time(input_datetime, config) is True