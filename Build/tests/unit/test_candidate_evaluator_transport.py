from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from order_orchestration.calendar.working_calendar import WorkingCalendarConfig
from order_orchestration.candidates.evaluator import (
    build_route_lookup,
    evaluate_candidates_transport,
    get_route_for_candidate,
)
from order_orchestration.domain.candidate import CandidateSource
from order_orchestration.domain.enums import OrderType, ReasonCode, SourceType, TransportMode
from order_orchestration.domain.route import Route


ALLOWED_TRANSPORT_MODES_CONFIG = {
    "VOR": ["AIR", "COURIER_EXPRESS", "SURFACE"],
    "REPLENISHMENT": ["MILK_RUN", "SURFACE", "PART_TRUCK_LOAD"],
    "PUSH": ["SURFACE", "PART_TRUCK_LOAD", "FULL_TRUCK_LOAD"],
}


def create_candidate(
    location: str = "1158",
    source_type: SourceType = SourceType.PARENT_RDC,
    eligible: bool = True,
) -> CandidateSource:
    return CandidateSource(
        location=location,
        source_type=source_type,
        material_code="MAT-001",
        requested_quantity=Decimal("10"),
        available_quantity=Decimal("100"),
        safety_stock=Decimal("20"),
        eligible_quantity=Decimal("80"),
        full_fill_capable=True,
        ageing_quantity=Decimal("0"),
        cluster=None,
        region=None,
        route_available=False,
        selected_transport_mode=None,
        configured_sla_days=None,
        transport_cost=None,
        expected_dispatch=None,
        expected_delivery=None,
        eligible=eligible,
        rejection_reason_codes=[],
    )


def create_valid_route(
    source_location: str = "1158",
    destination_location: str = "DEALER-001",
    transport_mode: TransportMode = TransportMode.SURFACE,
) -> Route:
    return Route(
        source_location=source_location,
        destination_location=destination_location,
        transport_mode=transport_mode,
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


def test_build_route_lookup_creates_source_destination_key():
    route = create_valid_route()

    route_lookup = build_route_lookup([route])

    assert ("1158", "DEALER-001") in route_lookup
    assert route_lookup[("1158", "DEALER-001")] == route


def test_get_route_for_candidate_returns_matching_route():
    candidate = create_candidate(location="1158")
    route = create_valid_route(source_location="1158", destination_location="DEALER-001")

    route_lookup = build_route_lookup([route])

    matched_route = get_route_for_candidate(
        candidate=candidate,
        destination_location="DEALER-001",
        route_lookup=route_lookup,
    )

    assert matched_route == route


def test_get_route_for_candidate_returns_none_when_missing():
    candidate = create_candidate(location="9999")
    route = create_valid_route(source_location="1158", destination_location="DEALER-001")

    route_lookup = build_route_lookup([route])

    matched_route = get_route_for_candidate(
        candidate=candidate,
        destination_location="DEALER-001",
        route_lookup=route_lookup,
    )

    assert matched_route is None


def test_candidate_transport_evaluation_adds_delivery_details():
    candidate = create_candidate(location="1158", eligible=True)
    route = create_valid_route(source_location="1158", destination_location="DEALER-001")

    calendar_config = WorkingCalendarConfig()

    decision_datetime = datetime(
        2026,
        7,
        20,
        10,
        0,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )

    evaluated_candidates = evaluate_candidates_transport(
        candidates=[candidate],
        routes=[route],
        order_type=OrderType.REPLENISHMENT,
        decision_datetime=decision_datetime,
        destination_location="DEALER-001",
        allowed_transport_modes_config=ALLOWED_TRANSPORT_MODES_CONFIG,
        calendar_config=calendar_config,
        adjust_final_delivery_to_working_time=True,
    )

    evaluated = evaluated_candidates[0]

    assert evaluated.route_available is True
    assert evaluated.selected_transport_mode == TransportMode.SURFACE
    assert evaluated.configured_sla_days == 3
    assert evaluated.transport_cost == Decimal("1250.50")
    assert evaluated.expected_dispatch == datetime(
        2026,
        7,
        20,
        10,
        0,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )
    assert evaluated.expected_delivery == datetime(
        2026,
        7,
        24,
        9,
        0,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )
    assert evaluated.eligible is True
    assert ReasonCode.SLA_SATISFIED in evaluated.rejection_reason_codes


def test_candidate_transport_evaluation_rejects_missing_route():
    candidate = create_candidate(location="9999", eligible=True)

    calendar_config = WorkingCalendarConfig()

    decision_datetime = datetime(
        2026,
        7,
        20,
        10,
        0,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )

    evaluated_candidates = evaluate_candidates_transport(
        candidates=[candidate],
        routes=[],
        order_type=OrderType.REPLENISHMENT,
        decision_datetime=decision_datetime,
        destination_location="DEALER-001",
        allowed_transport_modes_config=ALLOWED_TRANSPORT_MODES_CONFIG,
        calendar_config=calendar_config,
    )

    evaluated = evaluated_candidates[0]

    assert evaluated.route_available is False
    assert evaluated.eligible is False
    assert ReasonCode.MISSING_MASTER_DATA in evaluated.rejection_reason_codes


def test_candidate_transport_evaluation_rejects_no_connectivity():
    candidate = create_candidate(location="1158", eligible=True)

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
        effective_start_datetime=datetime(
            2026,
            7,
            1,
            tzinfo=ZoneInfo("Asia/Kolkata"),
        ),
        effective_end_datetime=None,
        route_type="RDC_TO_DEALER",
    )

    calendar_config = WorkingCalendarConfig()

    decision_datetime = datetime(
        2026,
        7,
        20,
        10,
        0,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )

    evaluated_candidates = evaluate_candidates_transport(
        candidates=[candidate],
        routes=[route],
        order_type=OrderType.REPLENISHMENT,
        decision_datetime=decision_datetime,
        destination_location="DEALER-001",
        allowed_transport_modes_config=ALLOWED_TRANSPORT_MODES_CONFIG,
        calendar_config=calendar_config,
    )

    evaluated = evaluated_candidates[0]

    assert evaluated.route_available is True
    assert evaluated.eligible is False
    assert ReasonCode.NO_TRANSPORT_CONNECTIVITY in evaluated.rejection_reason_codes


def test_candidate_transport_evaluation_rejects_transport_mode_not_allowed():
    candidate = create_candidate(location="1158", eligible=True)

    route = create_valid_route(
        source_location="1158",
        destination_location="DEALER-001",
        transport_mode=TransportMode.AIR,
    )

    calendar_config = WorkingCalendarConfig()

    decision_datetime = datetime(
        2026,
        7,
        20,
        10,
        0,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )

    evaluated_candidates = evaluate_candidates_transport(
        candidates=[candidate],
        routes=[route],
        order_type=OrderType.REPLENISHMENT,
        decision_datetime=decision_datetime,
        destination_location="DEALER-001",
        allowed_transport_modes_config=ALLOWED_TRANSPORT_MODES_CONFIG,
        calendar_config=calendar_config,
    )

    evaluated = evaluated_candidates[0]

    assert evaluated.route_available is True
    assert evaluated.selected_transport_mode == TransportMode.AIR
    assert evaluated.eligible is False
    assert ReasonCode.TRANSPORT_MODE_NOT_ALLOWED in evaluated.rejection_reason_codes


def test_candidate_with_inventory_rejection_remains_ineligible_even_if_route_valid():
    candidate = create_candidate(location="1158", eligible=False)
    candidate.rejection_reason_codes.append(ReasonCode.NO_ELIGIBLE_STOCK)

    route = create_valid_route(source_location="1158", destination_location="DEALER-001")

    calendar_config = WorkingCalendarConfig()

    decision_datetime = datetime(
        2026,
        7,
        20,
        10,
        0,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )

    evaluated_candidates = evaluate_candidates_transport(
        candidates=[candidate],
        routes=[route],
        order_type=OrderType.REPLENISHMENT,
        decision_datetime=decision_datetime,
        destination_location="DEALER-001",
        allowed_transport_modes_config=ALLOWED_TRANSPORT_MODES_CONFIG,
        calendar_config=calendar_config,
    )

    evaluated = evaluated_candidates[0]

    assert evaluated.route_available is True
    assert evaluated.eligible is False
    assert ReasonCode.NO_ELIGIBLE_STOCK in evaluated.rejection_reason_codes
    assert ReasonCode.SLA_SATISFIED in evaluated.rejection_reason_codes