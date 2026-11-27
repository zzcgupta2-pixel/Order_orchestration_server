from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from order_orchestration.domain.enums import OrderType


WEEKDAY_NAME_TO_NUMBER = {
    "MON": 0,
    "TUE": 1,
    "WED": 2,
    "THU": 3,
    "FRI": 4,
    "SAT": 5,
    "SUN": 6,
}


@dataclass(frozen=True)
class LocationWorkingRule:
    """
    Working rule resolved for a specific location, date, and order type.
    """

    is_working: bool
    work_start_time: time | None
    work_end_time: time | None
    allowed_order_types: list[str]


def parse_time_value(value: str) -> time:
    """
    Converts HH:MM string into time object.
    """

    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def is_last_sunday(input_date: date) -> bool:
    """
    Returns True if input_date is the last Sunday of its month.
    """

    if input_date.weekday() != 6:
        return False

    next_week = input_date + timedelta(days=7)
    return next_week.month != input_date.month


def get_date_override_rule(
    calendar_rules: dict,
    location: str,
    input_date: date,
) -> dict | None:
    """
    Returns configured date override for a location and date, if available.
    """

    date_overrides = calendar_rules.get("date_overrides", [])

    for override in date_overrides:
        override_date = datetime.strptime(override["date"], "%Y-%m-%d").date()

        if override_date != input_date:
            continue

        location_rules = override.get("locations", {})
        location_rule = location_rules.get(str(location).strip())

        if location_rule is not None:
            return location_rule

    return None


def get_location_config(
    calendar_rules: dict,
    location: str,
) -> dict:
    """
    Returns location-specific calendar config, falling back to default calendar.
    """

    location = str(location).strip()
    locations = calendar_rules.get("locations", {})

    if location in locations:
        return locations[location]

    default_calendar = calendar_rules.get("default_calendar", {})

    return {
        "working_days": default_calendar.get("working_days", []),
        "working_hours": default_calendar.get(
            "working_hours",
            {"start": "09:00", "end": "18:00"},
        ),
        "sunday_rules": {"enabled": False},
        "allowed_order_types": default_calendar.get(
            "allowed_order_types",
            ["VOR", "ACC", "REPLENISHMENT", "PUSH"],
        ),
    }


def build_rule_from_override(
    override_rule: dict,
) -> LocationWorkingRule:
    """
    Builds LocationWorkingRule from a date override section.
    """

    if not override_rule.get("is_working", False):
        return LocationWorkingRule(
            is_working=False,
            work_start_time=None,
            work_end_time=None,
            allowed_order_types=[],
        )

    working_hours = override_rule.get("working_hours") or {}

    return LocationWorkingRule(
        is_working=True,
        work_start_time=parse_time_value(working_hours["start"]),
        work_end_time=parse_time_value(working_hours["end"]),
        allowed_order_types=override_rule.get("allowed_order_types", []),
    )


def resolve_location_working_rule(
    calendar_rules: dict,
    location: str,
    input_date: date,
) -> LocationWorkingRule:
    """
    Resolves working rule for a location and date.

    Priority:
    1. Specific date override
    2. Sunday special rule
    3. Regular location calendar
    4. Default calendar
    """

    location = str(location).strip()

    override_rule = get_date_override_rule(
        calendar_rules=calendar_rules,
        location=location,
        input_date=input_date,
    )

    if override_rule is not None:
        return build_rule_from_override(override_rule)

    location_config = get_location_config(
        calendar_rules=calendar_rules,
        location=location,
    )

    timezone = calendar_rules.get("timezone", "Asia/Kolkata")

    if input_date.weekday() == 6:
        sunday_rules = location_config.get("sunday_rules", {})

        if not sunday_rules.get("enabled", False):
            return LocationWorkingRule(
                is_working=False,
                work_start_time=None,
                work_end_time=None,
                allowed_order_types=[],
            )

        if is_last_sunday(input_date):
            sunday_rule = sunday_rules.get("last_sunday", {})
        else:
            sunday_rule = sunday_rules.get("regular_sunday", {})

        if not sunday_rule.get("is_working", False):
            return LocationWorkingRule(
                is_working=False,
                work_start_time=None,
                work_end_time=None,
                allowed_order_types=[],
            )

        working_hours = sunday_rule.get("working_hours", {})

        return LocationWorkingRule(
            is_working=True,
            work_start_time=parse_time_value(working_hours["start"]),
            work_end_time=parse_time_value(working_hours["end"]),
            allowed_order_types=sunday_rule.get("allowed_order_types", []),
        )

    working_days = {
        WEEKDAY_NAME_TO_NUMBER[day]
        for day in location_config.get("working_days", [])
    }

    if input_date.weekday() not in working_days:
        return LocationWorkingRule(
            is_working=False,
            work_start_time=None,
            work_end_time=None,
            allowed_order_types=[],
        )

    working_hours = location_config.get("working_hours", {})

    allowed_order_types = location_config.get(
        "allowed_order_types",
        calendar_rules.get("default_calendar", {}).get(
            "allowed_order_types",
            ["VOR", "ACC", "REPLENISHMENT", "PUSH"],
        ),
    )

    return LocationWorkingRule(
        is_working=True,
        work_start_time=parse_time_value(working_hours["start"]),
        work_end_time=parse_time_value(working_hours["end"]),
        allowed_order_types=allowed_order_types,
    )


def ensure_timezone_aware(
    input_datetime: datetime,
    timezone_name: str,
) -> datetime:
    """
    Ensures datetime is timezone-aware and converted to configured timezone.
    """

    timezone = ZoneInfo(timezone_name)

    if input_datetime.tzinfo is None:
        return input_datetime.replace(tzinfo=timezone)

    return input_datetime.astimezone(timezone)


def is_location_working_for_order_type(
    calendar_rules: dict,
    location: str,
    order_type: OrderType,
    input_datetime: datetime,
) -> bool:
    """
    Returns True if location can execute the order type at input datetime.
    """

    timezone_name = calendar_rules.get("timezone", "Asia/Kolkata")

    local_datetime = ensure_timezone_aware(
        input_datetime=input_datetime,
        timezone_name=timezone_name,
    )

    rule = resolve_location_working_rule(
        calendar_rules=calendar_rules,
        location=location,
        input_date=local_datetime.date(),
    )

    if not rule.is_working:
        return False

    if order_type.value not in rule.allowed_order_types:
        return False

    current_time = local_datetime.time()

    return (
        rule.work_start_time is not None
        and rule.work_end_time is not None
        and rule.work_start_time <= current_time < rule.work_end_time
    )


def start_of_location_working_day(
    calendar_rules: dict,
    location: str,
    input_date: date,
) -> datetime | None:
    """
    Returns start datetime for location if working rule exists.
    """

    timezone_name = calendar_rules.get("timezone", "Asia/Kolkata")
    timezone = ZoneInfo(timezone_name)

    rule = resolve_location_working_rule(
        calendar_rules=calendar_rules,
        location=location,
        input_date=input_date,
    )

    if not rule.is_working or rule.work_start_time is None:
        return None

    return datetime.combine(
        input_date,
        rule.work_start_time,
        tzinfo=timezone,
    )


def next_location_working_time(
    calendar_rules: dict,
    location: str,
    order_type: OrderType,
    input_datetime: datetime,
) -> datetime:
    """
    Moves input datetime to the next valid working time for:

    - source location
    - order type
    - date-specific overrides
    - Sunday rules
    - configured working hours
    """

    timezone_name = calendar_rules.get("timezone", "Asia/Kolkata")

    current_datetime = ensure_timezone_aware(
        input_datetime=input_datetime,
        timezone_name=timezone_name,
    )

    for _ in range(370):
        current_date = current_datetime.date()

        rule = resolve_location_working_rule(
            calendar_rules=calendar_rules,
            location=location,
            input_date=current_date,
        )

        if (
            rule.is_working
            and order_type.value in rule.allowed_order_types
            and rule.work_start_time is not None
            and rule.work_end_time is not None
        ):
            current_time = current_datetime.time()

            if current_time < rule.work_start_time:
                return datetime.combine(
                    current_date,
                    rule.work_start_time,
                    tzinfo=ZoneInfo(timezone_name),
                )

            if rule.work_start_time <= current_time < rule.work_end_time:
                return current_datetime

        current_datetime = datetime.combine(
            current_date + timedelta(days=1),
            time(0, 0),
            tzinfo=ZoneInfo(timezone_name),
        )

    raise ValueError(
        f"No working time found within 370 days for location={location}, "
        f"order_type={order_type.value}."
    )


def resolve_decision_datetime(
    calendar_rules: dict,
    order_creation_datetime: datetime,
    run_datetime: datetime,
) -> datetime:
    """
    Resolves decision datetime based on execution mode.

    HISTORICAL_REPLAY:
        use order creation timestamp

    CURRENT_PENDING:
        use current run timestamp
    """

    mode = (
        calendar_rules
        .get("execution_mode", {})
        .get("mode", "HISTORICAL_REPLAY")
    )

    if mode == "CURRENT_PENDING":
        return ensure_timezone_aware(
            input_datetime=run_datetime,
            timezone_name=calendar_rules.get("timezone", "Asia/Kolkata"),
        )

    return ensure_timezone_aware(
        input_datetime=order_creation_datetime,
        timezone_name=calendar_rules.get("timezone", "Asia/Kolkata"),
    )