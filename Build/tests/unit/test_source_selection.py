from decimal import Decimal

from order_orchestration.domain.candidate import CandidateSource
from order_orchestration.domain.enums import (
    DecisionType,
    ReasonCode,
    SourceType,
    TransportMode,
)
from order_orchestration.selection.source_selection import (
    filter_selectable_candidates,
    get_full_fill_candidates,
    get_maximum_quantity_candidates,
    select_best_source,
)


def create_candidate(
    location: str,
    source_type: SourceType,
    eligible_quantity: str,
    requested_quantity: str = "10",
    eligible: bool = True,
    full_fill_capable: bool | None = None,
    configured_sla_days: int | None = None,
    transport_cost: str | None = None,
    ageing_quantity: str = "0",
) -> CandidateSource:
    eligible_qty = Decimal(eligible_quantity)
    requested_qty = Decimal(requested_quantity)

    if full_fill_capable is None:
        full_fill_capable = eligible_qty >= requested_qty

    return CandidateSource(
        location=location,
        source_type=source_type,
        material_code="MAT-001",
        requested_quantity=requested_qty,
        available_quantity=eligible_qty,
        safety_stock=Decimal("0"),
        eligible_quantity=eligible_qty,
        full_fill_capable=full_fill_capable,
        ageing_quantity=Decimal(ageing_quantity),
        cluster=None,
        region=None,
        route_available=True,
        allowed_transport_modes=[],
        selected_transport_mode=TransportMode.SURFACE,
        configured_sla_days=configured_sla_days,
        transport_cost=Decimal(transport_cost) if transport_cost is not None else None,
        expected_dispatch=None,
        expected_delivery=None,
        eligible=eligible,
        rejection_reason_codes=[],
    )


def test_filter_selectable_candidates_removes_ineligible_candidates():
    candidates = [
        create_candidate("1158", SourceType.PARENT_RDC, "10", eligible=True),
        create_candidate("1141", SourceType.PAN_INDIA_RDC, "10", eligible=False),
        create_candidate("1157", SourceType.CLUSTER_RDC, "0", eligible=True),
    ]

    selectable = filter_selectable_candidates(candidates)

    assert len(selectable) == 1
    assert selectable[0].location == "1158"


def test_get_full_fill_candidates():
    candidates = [
        create_candidate("1158", SourceType.PARENT_RDC, "10"),
        create_candidate("1141", SourceType.PAN_INDIA_RDC, "7"),
    ]

    full_fill = get_full_fill_candidates(candidates)

    assert len(full_fill) == 1
    assert full_fill[0].location == "1158"


def test_get_maximum_quantity_candidates():
    candidates = [
        create_candidate("1158", SourceType.PARENT_RDC, "4"),
        create_candidate("1141", SourceType.PAN_INDIA_RDC, "7"),
        create_candidate("1157", SourceType.CLUSTER_RDC, "7"),
    ]

    maximum_candidates = get_maximum_quantity_candidates(candidates)

    assert len(maximum_candidates) == 2
    assert {candidate.location for candidate in maximum_candidates} == {
        "1141",
        "1157",
    }


def test_select_full_fill_over_partial():
    candidates = [
        create_candidate("1158", SourceType.PARENT_RDC, "4"),
        create_candidate("1157", SourceType.CLUSTER_RDC, "10"),
    ]

    result = select_best_source(
        candidates=candidates,
        requested_quantity=Decimal("10"),
    )

    assert result.decision == DecisionType.ALLOCATE
    assert result.selected_candidate is not None
    assert result.selected_candidate.location == "1157"
    assert result.allocated_quantity == Decimal("10")
    assert result.remaining_quantity == Decimal("0")
    assert ReasonCode.CLUSTER_FULL_FILL in result.reason_codes


def test_select_maximum_partial_when_no_full_fill():
    candidates = [
        create_candidate("1158", SourceType.PARENT_RDC, "4"),
        create_candidate("1157", SourceType.CLUSTER_RDC, "7"),
        create_candidate("1141", SourceType.PAN_INDIA_RDC, "6"),
    ]

    result = select_best_source(
        candidates=candidates,
        requested_quantity=Decimal("10"),
    )

    assert result.decision == DecisionType.ALLOCATE
    assert result.selected_candidate is not None
    assert result.selected_candidate.location == "1157"
    assert result.allocated_quantity == Decimal("7")
    assert result.remaining_quantity == Decimal("3")
    assert ReasonCode.MAXIMUM_PARTIAL_FILL in result.reason_codes


def test_shortest_sla_tie_break_is_used_for_full_fill_candidates():
    candidates = [
        create_candidate(
            "1157",
            SourceType.CLUSTER_RDC,
            "10",
            configured_sla_days=5,
        ),
        create_candidate(
            "1141",
            SourceType.PAN_INDIA_RDC,
            "10",
            configured_sla_days=2,
        ),
    ]

    result = select_best_source(
        candidates=candidates,
        requested_quantity=Decimal("10"),
        tie_break_order=["shortest_sla"],
    )

    assert result.selected_candidate is not None
    assert result.selected_candidate.location == "1141"
    assert ReasonCode.SHORTEST_SLA_SELECTED in result.reason_codes


def test_source_priority_tie_break_is_used():
    candidates = [
        create_candidate(
            "1110",
            SourceType.VEPDC,
            "10",
            configured_sla_days=3,
        ),
        create_candidate(
            "1157",
            SourceType.CLUSTER_RDC,
            "10",
            configured_sla_days=3,
        ),
    ]

    source_priority = {
        SourceType.CLUSTER_RDC.value: 1,
        SourceType.VEPDC.value: 2,
    }

    result = select_best_source(
        candidates=candidates,
        requested_quantity=Decimal("10"),
        tie_break_order=["source_priority"],
        source_priority=source_priority,
    )

    assert result.selected_candidate is not None
    assert result.selected_candidate.location == "1157"


def test_lowest_cost_tie_break_is_used():
    candidates = [
        create_candidate(
            "1157",
            SourceType.CLUSTER_RDC,
            "10",
            transport_cost="500",
        ),
        create_candidate(
            "1141",
            SourceType.PAN_INDIA_RDC,
            "10",
            transport_cost="300",
        ),
    ]

    result = select_best_source(
        candidates=candidates,
        requested_quantity=Decimal("10"),
        tie_break_order=["lowest_cost"],
    )

    assert result.selected_candidate is not None
    assert result.selected_candidate.location == "1141"
    assert ReasonCode.LOWEST_COST_SELECTED in result.reason_codes


def test_ageing_quantity_tie_break_is_used():
    candidates = [
        create_candidate(
            "1157",
            SourceType.CLUSTER_RDC,
            "10",
            ageing_quantity="20",
        ),
        create_candidate(
            "1141",
            SourceType.PAN_INDIA_RDC,
            "10",
            ageing_quantity="5",
        ),
    ]

    result = select_best_source(
        candidates=candidates,
        requested_quantity=Decimal("10"),
        tie_break_order=["ageing_quantity"],
    )

    assert result.selected_candidate is not None
    assert result.selected_candidate.location == "1157"
    assert ReasonCode.AGEING_STOCK_PREFERRED in result.reason_codes


def test_no_eligible_candidates_returns_no_eligible_stock():
    candidates = [
        create_candidate("1158", SourceType.PARENT_RDC, "0", eligible=False),
        create_candidate("1157", SourceType.CLUSTER_RDC, "0", eligible=False),
    ]

    result = select_best_source(
        candidates=candidates,
        requested_quantity=Decimal("10"),
    )

    assert result.decision == DecisionType.NO_ELIGIBLE_STOCK
    assert result.selected_candidate is None
    assert result.allocated_quantity == Decimal("0")
    assert result.remaining_quantity == Decimal("10")
    assert ReasonCode.NO_ELIGIBLE_STOCK in result.reason_codes


def test_deterministic_location_tie_break_is_used():
    candidates = [
        create_candidate(
            "B_LOCATION",
            SourceType.PAN_INDIA_RDC,
            "10",
        ),
        create_candidate(
            "A_LOCATION",
            SourceType.PAN_INDIA_RDC,
            "10",
        ),
    ]

    result = select_best_source(
        candidates=candidates,
        requested_quantity=Decimal("10"),
        tie_break_order=[],
    )

    assert result.selected_candidate is not None
    assert result.selected_candidate.location == "A_LOCATION"


def test_single_source_rule_no_split_across_locations():
    candidates = [
        create_candidate("1158", SourceType.PARENT_RDC, "4"),
        create_candidate("1157", SourceType.CLUSTER_RDC, "6"),
    ]

    result = select_best_source(
        candidates=candidates,
        requested_quantity=Decimal("10"),
    )

    assert result.selected_candidate is not None
    assert result.allocated_quantity == Decimal("6")
    assert result.remaining_quantity == Decimal("4")
    assert result.selected_candidate.location == "1157"
    assert ReasonCode.MAXIMUM_PARTIAL_FILL in result.reason_codes