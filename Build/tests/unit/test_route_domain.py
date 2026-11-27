from datetime import datetime, timezone
from decimal import Decimal

from order_orchestration.domain.enums import OrderType, TransportMode
from order_orchestration.domain.route import Route


def test_route_is_effective_when_decision_date_is_after_start_date():
    route = Route(
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

    decision_datetime = datetime(2026, 7, 24, tzinfo=timezone.utc)

    assert route.is_effective_on(decision_datetime) is True


def test_route_is_not_effective_before_start_date():
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
        effective_start_datetime=datetime(2026, 7, 10, tzinfo=timezone.utc),
        effective_end_datetime=None,
        route_type="RDC_TO_DEALER",
    )

    decision_datetime = datetime(2026, 7, 5, tzinfo=timezone.utc)

    assert route.is_effective_on(decision_datetime) is False


def test_route_is_not_effective_after_end_date():
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
        effective_start_datetime=datetime(2026, 7, 1, tzinfo=timezone.utc),
        effective_end_datetime=datetime(2026, 7, 20, tzinfo=timezone.utc),
        route_type="RDC_TO_DEALER",
    )

    decision_datetime = datetime(2026, 7, 24, tzinfo=timezone.utc)

    assert route.is_effective_on(decision_datetime) is False


def test_route_is_effective_on_end_date():
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
        effective_start_datetime=datetime(2026, 7, 1, tzinfo=timezone.utc),
        effective_end_datetime=datetime(2026, 7, 24, tzinfo=timezone.utc),
        route_type="RDC_TO_DEALER",
    )

    decision_datetime = datetime(2026, 7, 24, tzinfo=timezone.utc)

    assert route.is_effective_on(decision_datetime) is True


def test_route_is_applicable_for_order_type():
    route = Route(
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

    assert route.is_applicable_for_order_type(OrderType.REPLENISHMENT) is True
    assert route.is_applicable_for_order_type(OrderType.PUSH) is True


def test_route_is_not_applicable_for_order_type():
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
        effective_start_datetime=datetime(2026, 7, 1, tzinfo=timezone.utc),
        effective_end_datetime=None,
        route_type="RDC_TO_DEALER",
    )

    assert route.is_applicable_for_order_type(OrderType.VOR) is False


def test_route_has_valid_sla_when_sla_days_and_buffers_are_non_negative():
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
        effective_start_datetime=datetime(2026, 7, 1, tzinfo=timezone.utc),
        effective_end_datetime=None,
        route_type="RDC_TO_DEALER",
    )

    assert route.has_valid_sla() is True


def test_route_has_invalid_sla_when_standard_sla_days_is_negative():
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

    assert route.has_valid_sla() is False


def test_route_has_invalid_sla_when_pickup_buffer_is_negative():
    route = Route(
        source_location="1158",
        destination_location="DEALER-001",
        transport_mode=TransportMode.SURFACE,
        standard_sla_days=3,
        pickup_buffer_hours=-1,
        drop_buffer_hours=4,
        transport_cost=Decimal("1250.50"),
        connectivity_available=True,
        applicable_order_types=(OrderType.REPLENISHMENT,),
        effective_start_datetime=datetime(2026, 7, 1, tzinfo=timezone.utc),
        effective_end_datetime=None,
        route_type="RDC_TO_DEALER",
    )

    assert route.has_valid_sla() is False


def test_route_has_invalid_sla_when_drop_buffer_is_negative():
    route = Route(
        source_location="1158",
        destination_location="DEALER-001",
        transport_mode=TransportMode.SURFACE,
        standard_sla_days=3,
        pickup_buffer_hours=4,
        drop_buffer_hours=-1,
        transport_cost=Decimal("1250.50"),
        connectivity_available=True,
        applicable_order_types=(OrderType.REPLENISHMENT,),
        effective_start_datetime=datetime(2026, 7, 1, tzinfo=timezone.utc),
        effective_end_datetime=None,
        route_type="RDC_TO_DEALER",
    )

    assert route.has_valid_sla() is False


def test_route_has_valid_cost_when_cost_is_non_negative():
    route = Route(
        source_location="1158",
        destination_location="DEALER-001",
        transport_mode=TransportMode.SURFACE,
        standard_sla_days=3,
        pickup_buffer_hours=4,
        drop_buffer_hours=4,
        transport_cost=Decimal("0"),
        connectivity_available=True,
        applicable_order_types=(OrderType.REPLENISHMENT,),
        effective_start_datetime=datetime(2026, 7, 1, tzinfo=timezone.utc),
        effective_end_datetime=None,
        route_type="RDC_TO_DEALER",
    )

    assert route.has_valid_cost() is True


def test_route_has_invalid_cost_when_cost_is_negative():
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

    assert route.has_valid_cost() is False