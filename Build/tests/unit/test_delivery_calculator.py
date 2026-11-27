from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from order_orchestration.calendar.delivery_calculator import (
    calculate_expected_delivery,
    calculate_expected_dispatch,
    calculate_route_delivery_result,
)
from order_orchestration.calendar.working_calendar import WorkingCalendarConfig
from order_orchestration.domain.enums import OrderType, TransportMode
from order_orchestration.domain.route import Route


def test_expected_dispatch_during_working_time_stays_same():
    config = WorkingCalendarConfig()

    decision_datetime = datetime(
        2026,
        7,
        20,
        10,
        0,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )

    result = calculate_expected_dispatch(
        decision_datetime=decision_datetime,
        calendar_config=config,
    )

    assert result == decision_datetime


def test_expected_dispatch_before_work_start_moves_to_start_time():
    config = WorkingCalendarConfig()

    decision_datetime = datetime(
        2026,
        7,
        20,
        8,
        0,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )

    result = calculate_expected_dispatch(
        decision_datetime=decision_datetime,
        calendar_config=config,
    )

    assert result == datetime(
        2026,
        7,
        20,
        9,
        0,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )


def test_expected_dispatch_after_work_end_moves_to_next_day_start():
    config = WorkingCalendarConfig()

    decision_datetime = datetime(
        2026,
        7,
        20,
        19,
        0,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )

    result = calculate_expected_dispatch(
        decision_datetime=decision_datetime,
        calendar_config=config,
    )

    assert result == datetime(
        2026,
        7,
        21,
        9,
        0,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )


def test_expected_delivery_adds_pickup_sla_days_and_drop_buffer():
    config = WorkingCalendarConfig()

    decision_datetime = datetime(
        2026,
        7,
        20,
        10,
        0,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )

    expected_dispatch, expected_delivery = calculate_expected_delivery(
        decision_datetime=decision_datetime,
        standard_sla_days=3,
        pickup_buffer_hours=4,
        drop_buffer_hours=4,
        calendar_config=config,
        adjust_final_delivery_to_working_time=True,
    )

    assert expected_dispatch == datetime(
        2026,
        7,
        20,
        10,
        0,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )

    assert expected_delivery == datetime(
        2026,
        7,
        24,
        9,
        0,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )



def test_expected_delivery_adjusts_if_final_time_after_work_end():
    config = WorkingCalendarConfig()

    decision_datetime = datetime(
        2026,
        7,
        20,
        16,
        0,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )

    expected_dispatch, expected_delivery = calculate_expected_delivery(
        decision_datetime=decision_datetime,
        standard_sla_days=1,
        pickup_buffer_hours=4,
        drop_buffer_hours=4,
        calendar_config=config,
        adjust_final_delivery_to_working_time=True,
    )

    # Dispatch = 20-Jul 16:00
    # Tentative delivery = 20-Jul 16:00 + 4h + 1 day + 4h
    #                    = 21-Jul 00:00
    # Since 00:00 is outside working time, adjusted to 21-Jul 09:00.
    assert expected_dispatch == datetime(
        2026,
        7,
        20,
        16,
        0,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )

    assert expected_delivery == datetime(
        2026,
        7,
        22,
        9,
        0,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )


def test_expected_delivery_without_final_working_time_adjustment():
    config = WorkingCalendarConfig()

    decision_datetime = datetime(
        2026,
        7,
        20,
        16,
        0,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )

    expected_dispatch, expected_delivery = calculate_expected_delivery(
        decision_datetime=decision_datetime,
        standard_sla_days=1,
        pickup_buffer_hours=4,
        drop_buffer_hours=4,
        calendar_config=config,
        adjust_final_delivery_to_working_time=False,
    )

    assert expected_dispatch == datetime(
        2026,
        7,
        20,
        16,
        0,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )

    assert expected_delivery == datetime(
        2026,
        7,
        22,
        0,
        0,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )


def test_expected_delivery_on_sunday_adjusts_to_monday():
    config = WorkingCalendarConfig()

    decision_datetime = datetime(
        2026,
        7,
        18,
        10,
        0,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )

    expected_dispatch, expected_delivery = calculate_expected_delivery(
        decision_datetime=decision_datetime,
        standard_sla_days=1,
        pickup_buffer_hours=0,
        drop_buffer_hours=0,
        calendar_config=config,
        adjust_final_delivery_to_working_time=True,
    )

    # 18-Jul-2026 is Saturday.
    # +1 SLA day = Sunday 19-Jul-2026.
    # Sunday is non-working, so delivery adjusts to Monday 20-Jul 09:00.
    assert expected_dispatch == datetime(
        2026,
        7,
        18,
        10,
        0,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )

    assert expected_delivery == datetime(
        2026,
        7,
        20,
        9,
        0,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )


def test_route_delivery_result_returns_structured_output():
    config = WorkingCalendarConfig()

    route = Route(
        source_location="1158",
        destination_location="DEALER-001",
        transport_mode=TransportMode.SURFACE,
        standard_sla_days=3,
        pickup_buffer_hours=4,
        drop_buffer_hours=4,
        transport_cost=Decimal("1250.50"),
        connectivity_available=True,
        applicable_order_types=(OrderType.REPLENISHMENT,),
        effective_start_datetime=datetime(
            2026,
            7,
            1,
            tzinfo=ZoneInfo("Asia/Kolkata"),
        ),
        effective_end_datetime=None,
        route_type="RDC_TO_DEALER",
    )

    decision_datetime = datetime(
        2026,
        7,
        20,
        10,
        0,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )

    result = calculate_route_delivery_result(
        route=route,
        decision_datetime=decision_datetime,
        calendar_config=config,
        adjust_final_delivery_to_working_time=True,
    )

    assert result.expected_dispatch == datetime(
        2026,
        7,
        20,
        10,
        0,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )

    assert result.expected_delivery == datetime(
        2026,
        7,
        24,
        9,
        0,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )

    assert result.standard_sla_days == 3
    assert result.pickup_buffer_hours == 4
    assert result.drop_buffer_hours == 4
    assert result.transport_cost == Decimal("1250.50")


def test_negative_sla_days_raises_error():
    config = WorkingCalendarConfig()

    decision_datetime = datetime(
        2026,
        7,
        20,
        10,
        0,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )

    with pytest.raises(ValueError):
        calculate_expected_delivery(
            decision_datetime=decision_datetime,
            standard_sla_days=-1,
            pickup_buffer_hours=4,
            drop_buffer_hours=4,
            calendar_config=config,
        )


def test_negative_pickup_buffer_raises_error():
    config = WorkingCalendarConfig()

    decision_datetime = datetime(
        2026,
        7,
        20,
        10,
        0,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )

    with pytest.raises(ValueError):
        calculate_expected_delivery(
            decision_datetime=decision_datetime,
            standard_sla_days=1,
            pickup_buffer_hours=-1,
            drop_buffer_hours=4,
            calendar_config=config,
        )


def test_negative_drop_buffer_raises_error():
    config = WorkingCalendarConfig()

    decision_datetime = datetime(
        2026,
        7,
        20,
        10,
        0,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )

    with pytest.raises(ValueError):
        calculate_expected_delivery(
            decision_datetime=decision_datetime,
            standard_sla_days=1,
            pickup_buffer_hours=4,
            drop_buffer_hours=-1,
            calendar_config=config,
        )