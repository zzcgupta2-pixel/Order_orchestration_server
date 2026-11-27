from datetime import datetime, timezone
from decimal import Decimal

from order_orchestration.domain.enums import OrderType, ReasonCode, TransportMode
from order_orchestration.domain.route import Route
from order_orchestration.eligibility.transport_eligibility import (
    evaluate_transport_eligibility,
    get_allowed_transport_modes_for_order_type,
    is_transport_mode_allowed,
)


ALLOWED_TRANSPORT_MODES_CONFIG = {
    "VOR": ["AIR", "COURIER_EXPRESS", "SURFACE"],
    "REPLENISHMENT": ["MILK_RUN", "SURFACE", "PART_TRUCK_LOAD"],
    "PUSH": ["SURFACE", "PART_TRUCK_LOAD", "FULL_TRUCK_LOAD"],
}


def create_valid_route() -> Route:
    return Route(
        source_location="1158",
        destination_location="DEALER-001",
        transport_mode=TransportMode.SURFACE,
        standard_sla_days=3,
        pickup_buffer_hours=4,
        drop_buffer_hours=4,
        transport_cost=Decimal("1250.50"),
        connectivity_available=True,
        applicable_order_types=(
            OrderType.REPLENISHMENT,
            OrderType.PUSH,
        ),
        effective_start_datetime=datetime(2026, 7, 1, tzinfo=timezone.utc),
        effective_end_datetime=None,
        route_type="RDC_TO_DEALER",
    )


def test_get_allowed_transport_modes_for_order_type():
    allowed_modes = get_allowed_transport_modes_for_order_type(
        order_type=OrderType.REPLENISHMENT,
        allowed_transport_modes_config=ALLOWED_TRANSPORT_MODES_CONFIG,
    )

    assert TransportMode.MILK_RUN in allowed_modes
    assert TransportMode.SURFACE in allowed_modes
    assert TransportMode.PART_TRUCK_LOAD in allowed_modes
    assert TransportMode.AIR not in allowed_modes


def test_transport_mode_is_allowed():
    route = create_valid_route()

    result = is_transport_mode_allowed(
        route=route,
        order_type=OrderType.REPLENISHMENT,
        allowed_transport_modes_config=ALLOWED_TRANSPORT_MODES_CONFIG,
    )

    assert result is True


def test_transport_mode_is_not_allowed():
    route = Route(
        source_location="1158",
        destination_location="DEALER-001",
        transport_mode=TransportMode.AIR,
        standard_sla_days=1,
        pickup_buffer_hours=4,
        drop_buffer_hours=4,
        transport_cost=Decimal("2500"),
        connectivity_available=True,
        applicable_order_types=(OrderType.REPLENISHMENT,),
        effective_start_datetime=datetime(2026, 7, 1, tzinfo=timezone.utc),
        effective_end_datetime=None,
        route_type="RDC_TO_DEALER",
    )

    result = is_transport_mode_allowed(
        route=route,
        order_type=OrderType.REPLENISHMENT,
        allowed_transport_modes_config=ALLOWED_TRANSPORT_MODES_CONFIG,
    )

    assert result is False


def test_valid_route_is_eligible():
    route = create_valid_route()

    result = evaluate_transport_eligibility(
        route=route,
        order_type=OrderType.REPLENISHMENT,
        decision_datetime=datetime(2026, 7, 24, tzinfo=timezone.utc),
        allowed_transport_modes_config=ALLOWED_TRANSPORT_MODES_CONFIG,
    )

    assert result.eligible is True
    assert result.reason_codes == [ReasonCode.SLA_SATISFIED]


def test_missing_route_is_not_eligible():
    result = evaluate_transport_eligibility(
        route=None,
        order_type=OrderType.REPLENISHMENT,
        decision_datetime=datetime(2026, 7, 24, tzinfo=timezone.utc),
        allowed_transport_modes_config=ALLOWED_TRANSPORT_MODES_CONFIG,
    )

    assert result.eligible is False
    assert ReasonCode.MISSING_MASTER_DATA in result.reason_codes


def test_route_not_effective_is_not_eligible():
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
        effective_start_datetime=datetime(2026, 8, 1, tzinfo=timezone.utc),
        effective_end_datetime=None,
        route_type="RDC_TO_DEALER",
    )

    result = evaluate_transport_eligibility(
        route=route,
        order_type=OrderType.REPLENISHMENT,
        decision_datetime=datetime(2026, 7, 24, tzinfo=timezone.utc),
        allowed_transport_modes_config=ALLOWED_TRANSPORT_MODES_CONFIG,
    )

    assert result.eligible is False
    assert ReasonCode.ROUTE_NOT_EFFECTIVE in result.reason_codes


def test_no_transport_connectivity_is_not_eligible():
    route = Route(
        source_location="1158",
        destination_location="DEALER-001",
        transport_mode=TransportMode.SURFACE,
        standard_sla_days=3,
        pickup_buffer_hours=4,
        drop_buffer_hours=4,
        transport_cost=Decimal("1250.50"),
        connectivity_available=False,
        applicable_order_types=(OrderType.REPLENISHMENT,),
        effective_start_datetime=datetime(2026, 7, 1, tzinfo=timezone.utc),
        effective_end_datetime=None,
        route_type="RDC_TO_DEALER",
    )

    result = evaluate_transport_eligibility(
        route=route,
        order_type=OrderType.REPLENISHMENT,
        decision_datetime=datetime(2026, 7, 24, tzinfo=timezone.utc),
        allowed_transport_modes_config=ALLOWED_TRANSPORT_MODES_CONFIG,
    )

    assert result.eligible is False
    assert ReasonCode.NO_TRANSPORT_CONNECTIVITY in result.reason_codes


def test_route_not_applicable_for_order_type_is_not_eligible():
    route = Route(
        source_location="1158",
        destination_location="DEALER-001",
        transport_mode=TransportMode.SURFACE,
        standard_sla_days=3,
        pickup_buffer_hours=4,
        drop_buffer_hours=4,
        transport_cost=Decimal("1250.50"),
        connectivity_available=True,
        applicable_order_types=(OrderType.PUSH,),
        effective_start_datetime=datetime(2026, 7, 1, tzinfo=timezone.utc),
        effective_end_datetime=None,
        route_type="RDC_TO_DEALER",
    )

    result = evaluate_transport_eligibility(
        route=route,
        order_type=OrderType.REPLENISHMENT,
        decision_datetime=datetime(2026, 7, 24, tzinfo=timezone.utc),
        allowed_transport_modes_config=ALLOWED_TRANSPORT_MODES_CONFIG,
    )

    assert result.eligible is False
    assert ReasonCode.INVALID_ORDER_TYPE in result.reason_codes


def test_transport_mode_not_allowed_is_not_eligible():
    route = Route(
        source_location="1158",
        destination_location="DEALER-001",
        transport_mode=TransportMode.AIR,
        standard_sla_days=1,
        pickup_buffer_hours=4,
        drop_buffer_hours=4,
        transport_cost=Decimal("2500"),
        connectivity_available=True,
        applicable_order_types=(OrderType.REPLENISHMENT,),
        effective_start_datetime=datetime(2026, 7, 1, tzinfo=timezone.utc),
        effective_end_datetime=None,
        route_type="RDC_TO_DEALER",
    )

    result = evaluate_transport_eligibility(
        route=route,
        order_type=OrderType.REPLENISHMENT,
        decision_datetime=datetime(2026, 7, 24, tzinfo=timezone.utc),
        allowed_transport_modes_config=ALLOWED_TRANSPORT_MODES_CONFIG,
    )

    assert result.eligible is False
    assert ReasonCode.TRANSPORT_MODE_NOT_ALLOWED in result.reason_codes


def test_invalid_route_sla_is_not_eligible():
    route = Route(
        source_location="1158",
        destination_location="DEALER-001",
        transport_mode=TransportMode.SURFACE,
        standard_sla_days=-1,
        pickup_buffer_hours=4,
        drop_buffer_hours=4,
        transport_cost=Decimal("1250.50"),
        connectivity_available=True,
        applicable_order_types=(OrderType.REPLENISHMENT,),
        effective_start_datetime=datetime(2026, 7, 1, tzinfo=timezone.utc),
        effective_end_datetime=None,
        route_type="RDC_TO_DEALER",
    )

    result = evaluate_transport_eligibility(
        route=route,
        order_type=OrderType.REPLENISHMENT,
        decision_datetime=datetime(2026, 7, 24, tzinfo=timezone.utc),
        allowed_transport_modes_config=ALLOWED_TRANSPORT_MODES_CONFIG,
    )

    assert result.eligible is False
    assert ReasonCode.INVALID_ROUTE_SLA in result.reason_codes


def test_invalid_transport_cost_is_not_eligible():
    route = Route(
        source_location="1158",
        destination_location="DEALER-001",
        transport_mode=TransportMode.SURFACE,
        standard_sla_days=3,
        pickup_buffer_hours=4,
        drop_buffer_hours=4,
        transport_cost=Decimal("-10"),
        connectivity_available=True,
        applicable_order_types=(OrderType.REPLENISHMENT,),
        effective_start_datetime=datetime(2026, 7, 1, tzinfo=timezone.utc),
        effective_end_datetime=None,
        route_type="RDC_TO_DEALER",
    )

    result = evaluate_transport_eligibility(
        route=route,
        order_type=OrderType.REPLENISHMENT,
        decision_datetime=datetime(2026, 7, 24, tzinfo=timezone.utc),
        allowed_transport_modes_config=ALLOWED_TRANSPORT_MODES_CONFIG,
    )

    assert result.eligible is False
    assert ReasonCode.INVALID_TRANSPORT_COST in result.reason_codes


def test_multiple_rejection_reasons_are_retained():
    route = Route(
        source_location="1158",
        destination_location="DEALER-001",
        transport_mode=TransportMode.AIR,
        standard_sla_days=-1,
        pickup_buffer_hours=4,
        drop_buffer_hours=4,
        transport_cost=Decimal("-10"),
        connectivity_available=False,
        applicable_order_types=(OrderType.PUSH,),
        effective_start_datetime=datetime(2026, 8, 1, tzinfo=timezone.utc),
        effective_end_datetime=None,
        route_type="RDC_TO_DEALER", 
    )

    result = evaluate_transport_eligibility(
        route=route,
        order_type=OrderType.REPLENISHMENT,
        decision_datetime=datetime(2026, 7, 24, tzinfo=timezone.utc),
        allowed_transport_modes_config=ALLOWED_TRANSPORT_MODES_CONFIG,
    )

    assert result.eligible is False
    assert ReasonCode.ROUTE_NOT_EFFECTIVE in result.reason_codes
    assert ReasonCode.NO_TRANSPORT_CONNECTIVITY in result.reason_codes
    assert ReasonCode.INVALID_ORDER_TYPE in result.reason_codes
    assert ReasonCode.TRANSPORT_MODE_NOT_ALLOWED in result.reason_codes
    assert ReasonCode.INVALID_ROUTE_SLA in result.reason_codes
    assert ReasonCode.INVALID_TRANSPORT_COST in result.reason_codes