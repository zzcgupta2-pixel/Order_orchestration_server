from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from order_orchestration.calendar.location_calendar import (
    next_location_working_time,
)
from order_orchestration.calendar.working_calendar import (
    WorkingCalendarConfig,
    next_working_time,
)
from order_orchestration.domain.enums import OrderType
from order_orchestration.domain.route import Route


@dataclass(frozen=True)
class DeliveryCalculationResult:
    """
    Structured output of deterministic dispatch and delivery calculation.

    standard_sla_days is interpreted as fixed configured transit days
    from the logistics master.

    pickup_buffer_hours and drop_buffer_hours are separate operational buffers.
    """

    expected_dispatch: datetime
    expected_delivery: datetime
    standard_sla_days: int
    pickup_buffer_hours: int
    drop_buffer_hours: int
    transport_cost: Decimal


def validate_delivery_inputs(
    standard_sla_days: int,
    pickup_buffer_hours: int,
    drop_buffer_hours: int,
) -> None:
    """
    Validates delivery calculation inputs.

    SLA days and buffers must not be negative.
    """

    if standard_sla_days < 0:
        raise ValueError("standard_sla_days cannot be negative.")

    if pickup_buffer_hours < 0:
        raise ValueError("pickup_buffer_hours cannot be negative.")

    if drop_buffer_hours < 0:
        raise ValueError("drop_buffer_hours cannot be negative.")


# =============================================================================
# Legacy/simple calendar functions
# These are kept so existing tests and older logic do not break.
# =============================================================================

def calculate_expected_dispatch(
    decision_datetime: datetime,
    calendar_config: WorkingCalendarConfig,
) -> datetime:
    """
    Calculates the next feasible dispatch datetime using simple calendar rules.

    Current deterministic rule:
    - Dispatch can happen at the next valid working time.
    - If decision_datetime is already within working time, dispatch is same.
    - If decision_datetime is outside working time, dispatch moves to next
      working time.
    """

    return next_working_time(
        input_datetime=decision_datetime,
        calendar_config=calendar_config,
    )


def calculate_expected_delivery(
    decision_datetime: datetime,
    standard_sla_days: int,
    pickup_buffer_hours: int,
    drop_buffer_hours: int,
    calendar_config: WorkingCalendarConfig,
    adjust_final_delivery_to_working_time: bool = True,
) -> tuple[datetime, datetime]:
    """
    Calculates expected dispatch and delivery datetime using simple calendar rules.

    Business interpretation:
        expected_dispatch =
            next feasible working dispatch time

        expected_delivery =
            expected_dispatch
            + pickup_buffer_hours
            + fixed SLA transit days
            + drop_buffer_hours

    Important:
        standard_sla_days is a fixed transit duration from logistics master.
        It is not converted into working hours.
    """

    validate_delivery_inputs(
        standard_sla_days=standard_sla_days,
        pickup_buffer_hours=pickup_buffer_hours,
        drop_buffer_hours=drop_buffer_hours,
    )

    expected_dispatch = calculate_expected_dispatch(
        decision_datetime=decision_datetime,
        calendar_config=calendar_config,
    )

    tentative_delivery = (
        expected_dispatch
        + timedelta(hours=pickup_buffer_hours)
        + timedelta(days=standard_sla_days)
        + timedelta(hours=drop_buffer_hours)
    )

    if adjust_final_delivery_to_working_time:
        expected_delivery = next_working_time(
            input_datetime=tentative_delivery,
            calendar_config=calendar_config,
        )
    else:
        expected_delivery = tentative_delivery

    return expected_dispatch, expected_delivery


def calculate_route_delivery_result(
    route: Route,
    decision_datetime: datetime,
    calendar_config: WorkingCalendarConfig,
    adjust_final_delivery_to_working_time: bool = True,
) -> DeliveryCalculationResult:
    """
    Calculates dispatch and delivery details for a configured route using
    simple calendar rules.

    This function is retained for backward compatibility.
    New location-wise logic should use calculate_route_delivery_result_for_location().
    """

    expected_dispatch, expected_delivery = calculate_expected_delivery(
        decision_datetime=decision_datetime,
        standard_sla_days=route.standard_sla_days,
        pickup_buffer_hours=route.pickup_buffer_hours,
        drop_buffer_hours=route.drop_buffer_hours,
        calendar_config=calendar_config,
        adjust_final_delivery_to_working_time=adjust_final_delivery_to_working_time,
    )

    return DeliveryCalculationResult(
        expected_dispatch=expected_dispatch,
        expected_delivery=expected_delivery,
        standard_sla_days=route.standard_sla_days,
        pickup_buffer_hours=route.pickup_buffer_hours,
        drop_buffer_hours=route.drop_buffer_hours,
        transport_cost=route.transport_cost,
    )


# =============================================================================
# New location-aware calendar functions
# These use config/calendar_rules.yaml through calendar_rules dict.
# =============================================================================

def calculate_expected_dispatch_for_location(
    calendar_rules: dict,
    source_location: str,
    order_type: OrderType,
    decision_datetime: datetime,
) -> datetime:
    """
    Calculates expected dispatch datetime using location-wise calendar rules.

    This considers:
    - source location
    - order type
    - location working days
    - location working hours
    - special Sundays
    - date-specific holiday overrides
    """

    return next_location_working_time(
        calendar_rules=calendar_rules,
        location=source_location,
        order_type=order_type,
        input_datetime=decision_datetime,
    )


def calculate_expected_delivery_for_location(
    calendar_rules: dict,
    source_location: str,
    order_type: OrderType,
    decision_datetime: datetime,
    standard_sla_days: int,
    pickup_buffer_hours: int,
    drop_buffer_hours: int,
    adjust_final_delivery_to_working_time: bool = True,
) -> tuple[datetime, datetime]:
    """
    Calculates expected dispatch and expected delivery using location-wise
    calendar rules.

    Business interpretation:
        expected_dispatch =
            next valid working time at source location for the given order type

        tentative_delivery =
            expected_dispatch
            + pickup_buffer_hours
            + fixed SLA transit days
            + drop_buffer_hours

        expected_delivery =
            tentative_delivery adjusted to next source working time if configured

    Note:
        For now, only source dispatch calendar is used for final delivery adjustment.
        Dealer/destination receiving calendar is not applied yet.
    """

    validate_delivery_inputs(
        standard_sla_days=standard_sla_days,
        pickup_buffer_hours=pickup_buffer_hours,
        drop_buffer_hours=drop_buffer_hours,
    )

    expected_dispatch = calculate_expected_dispatch_for_location(
        calendar_rules=calendar_rules,
        source_location=source_location,
        order_type=order_type,
        decision_datetime=decision_datetime,
    )

    tentative_delivery = (
        expected_dispatch
        + timedelta(hours=pickup_buffer_hours)
        + timedelta(days=standard_sla_days)
        + timedelta(hours=drop_buffer_hours)
    )

    if adjust_final_delivery_to_working_time:
        expected_delivery = next_location_working_time(
            calendar_rules=calendar_rules,
            location=source_location,
            order_type=order_type,
            input_datetime=tentative_delivery,
        )
    else:
        expected_delivery = tentative_delivery

    return expected_dispatch, expected_delivery


def calculate_route_delivery_result_for_location(
    route: Route,
    order_type: OrderType,
    decision_datetime: datetime,
    calendar_rules: dict,
    adjust_final_delivery_to_working_time: bool = True,
) -> DeliveryCalculationResult:
    """
    Calculates route dispatch and delivery using location-aware calendar rules.

    This is the preferred function for the orchestration engine going forward.

    It uses:
    - route.source_location
    - order_type
    - route.standard_sla_days
    - route.pickup_buffer_hours
    - route.drop_buffer_hours
    - route.transport_cost
    - calendar_rules.yaml-loaded dict
    """

    expected_dispatch, expected_delivery = calculate_expected_delivery_for_location(
        calendar_rules=calendar_rules,
        source_location=route.source_location,
        order_type=order_type,
        decision_datetime=decision_datetime,
        standard_sla_days=route.standard_sla_days,
        pickup_buffer_hours=route.pickup_buffer_hours,
        drop_buffer_hours=route.drop_buffer_hours,
        adjust_final_delivery_to_working_time=adjust_final_delivery_to_working_time,
    )

    return DeliveryCalculationResult(
        expected_dispatch=expected_dispatch,
        expected_delivery=expected_delivery,
        standard_sla_days=route.standard_sla_days,
        pickup_buffer_hours=route.pickup_buffer_hours,
        drop_buffer_hours=route.drop_buffer_hours,
        transport_cost=route.transport_cost,
    )