from datetime import datetime
from zoneinfo import ZoneInfo

from order_orchestration.calendar.location_calendar import (
    is_last_sunday,
    is_location_working_for_order_type,
    next_location_working_time,
    resolve_decision_datetime,
)
from order_orchestration.domain.enums import OrderType


def sample_calendar_rules():
    return {
        "timezone": "Asia/Kolkata",
        "execution_mode": {"mode": "CURRENT_PENDING"},
        "default_calendar": {
            "working_days": ["MON", "TUE", "WED", "THU", "FRI", "SAT"],
            "working_hours": {"start": "09:00", "end": "18:00"},
            "allowed_order_types": ["VOR", "ACC", "REPLENISHMENT", "PUSH"],
        },
        "locations": {
            "1110": {
                "location_name": "VEPDC",
                "working_days": ["MON", "TUE", "WED", "THU", "FRI", "SAT"],
                "working_hours": {"start": "09:00", "end": "18:00"},
                "sunday_rules": {
                    "enabled": True,
                    "regular_sunday": {
                        "is_working": True,
                        "working_hours": {"start": "09:00", "end": "14:00"},
                        "allowed_order_types": ["VOR", "ACC"],
                    },
                    "last_sunday": {
                        "is_working": True,
                        "working_hours": {"start": "09:00", "end": "18:00"},
                        "allowed_order_types": [
                            "VOR",
                            "ACC",
                            "REPLENISHMENT",
                            "PUSH",
                        ],
                    },
                },
            },
            "1158": {
                "location_name": "Lucknow RDC",
                "working_days": ["MON", "TUE", "WED", "THU", "FRI", "SAT"],
                "working_hours": {"start": "09:00", "end": "18:00"},
                "sunday_rules": {"enabled": False},
            },
        },
        "date_overrides": [
            {
                "date": "2026-08-15",
                "description": "Holiday",
                "locations": {
                    "1110": {
                        "is_working": True,
                        "working_hours": {"start": "09:00", "end": "13:00"},
                        "allowed_order_types": ["VOR", "ACC"],
                    },
                    "1158": {
                        "is_working": False,
                        "working_hours": None,
                        "allowed_order_types": [],
                    },
                },
            }
        ],
    }


def test_last_sunday_detection():
    assert is_last_sunday(datetime(2026, 7, 26).date()) is True
    assert is_last_sunday(datetime(2026, 7, 19).date()) is False


def test_rdc_not_working_on_sunday():
    rules = sample_calendar_rules()

    input_datetime = datetime(
        2026,
        7,
        19,
        10,
        0,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )

    assert (
        is_location_working_for_order_type(
            calendar_rules=rules,
            location="1158",
            order_type=OrderType.REPLENISHMENT,
            input_datetime=input_datetime,
        )
        is False
    )


def test_vepdc_regular_sunday_only_vor_acc():
    rules = sample_calendar_rules()

    input_datetime = datetime(
        2026,
        7,
        19,
        10,
        0,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )

    assert (
        is_location_working_for_order_type(
            calendar_rules=rules,
            location="1110",
            order_type=OrderType.VOR,
            input_datetime=input_datetime,
        )
        is True
    )

    assert (
        is_location_working_for_order_type(
            calendar_rules=rules,
            location="1110",
            order_type=OrderType.REPLENISHMENT,
            input_datetime=input_datetime,
        )
        is False
    )


def test_vepdc_last_sunday_allows_replenishment():
    rules = sample_calendar_rules()

    input_datetime = datetime(
        2026,
        7,
        26,
        10,
        0,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )

    assert (
        is_location_working_for_order_type(
            calendar_rules=rules,
            location="1110",
            order_type=OrderType.REPLENISHMENT,
            input_datetime=input_datetime,
        )
        is True
    )


def test_next_location_working_time_moves_replenishment_from_regular_sunday():
    rules = sample_calendar_rules()

    input_datetime = datetime(
        2026,
        7,
        19,
        10,
        0,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )

    result = next_location_working_time(
        calendar_rules=rules,
        location="1110",
        order_type=OrderType.REPLENISHMENT,
        input_datetime=input_datetime,
    )

    assert result == datetime(
        2026,
        7,
        20,
        9,
        0,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )


def test_date_override_closes_rdc():
    rules = sample_calendar_rules()

    input_datetime = datetime(
        2026,
        8,
        15,
        10,
        0,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )

    assert (
        is_location_working_for_order_type(
            calendar_rules=rules,
            location="1158",
            order_type=OrderType.VOR,
            input_datetime=input_datetime,
        )
        is False
    )


def test_current_pending_mode_uses_run_datetime():
    rules = sample_calendar_rules()

    order_created = datetime(
        2026,
        4,
        20,
        10,
        0,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )

    run_datetime = datetime(
        2026,
        7,
        28,
        11,
        46,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )

    result = resolve_decision_datetime(
        calendar_rules=rules,
        order_creation_datetime=order_created,
        run_datetime=run_datetime,
    )

    assert result == run_datetime