from datetime import datetime, timezone
from decimal import Decimal

from order_orchestration.candidates.evaluator import (
    build_inventory_position_lookup,
    evaluate_candidates_inventory,
)
from order_orchestration.domain.candidate import CandidateSource
from order_orchestration.domain.enums import OrderType, ReasonCode, SourceType
from order_orchestration.domain.inventory import InventoryPosition


SAFETY_STOCK_CONFIG = {
    "VOR": True,
    "REPLENISHMENT": True,
    "PUSH": True,
}


def create_inventory_position(
    location: str,
    material_code: str,
    actual_stock: str,
    allocated_quantity: str = "0",
    pending_so_quantity: str = "0",
    safety_stock: str = "0",
) -> InventoryPosition:
    return InventoryPosition(
        snapshot_timestamp=datetime(2026, 7, 24, tzinfo=timezone.utc),
        location=location,
        material_code=material_code,
        actual_stock=Decimal(actual_stock),
        allocated_quantity=Decimal(allocated_quantity),
        pending_so_quantity=Decimal(pending_so_quantity),
        safety_stock=Decimal(safety_stock),
        ageing_quantity=Decimal("0"),
        ageing_quantity_gt_1yr=Decimal("0"),
    )


def create_candidate(
    location: str,
    source_type: SourceType,
    requested_quantity: str = "10",
) -> CandidateSource:
    return CandidateSource(
        location=location,
        source_type=source_type,
        material_code="MAT-001",
        requested_quantity=Decimal(requested_quantity),
        available_quantity=Decimal("0"),
        safety_stock=Decimal("0"),
        eligible_quantity=Decimal("0"),
        full_fill_capable=False,
        ageing_quantity=Decimal("0"),
        cluster=None,
        region=None,
        route_available=False,
        eligible=False,
        rejection_reason_codes=[],
    )


def test_build_inventory_position_lookup():
    positions = [
        create_inventory_position(
            location="1158",
            material_code="MAT-001",
            actual_stock="100",
        )
    ]

    lookup = build_inventory_position_lookup(positions)

    assert ("1158", "MAT-001") in lookup
    assert lookup[("1158", "MAT-001")].actual_stock == Decimal("100")


def test_parent_candidate_full_fill():
    candidate = create_candidate(
        location="1158",
        source_type=SourceType.PARENT_RDC,
        requested_quantity="10",
    )

    positions = [
        create_inventory_position(
            location="1158",
            material_code="MAT-001",
            actual_stock="100",
            allocated_quantity="0",
            pending_so_quantity="0",
            safety_stock="20",
        )
    ]

    evaluated = evaluate_candidates_inventory(
        candidates=[candidate],
        inventory_positions=positions,
        order_type=OrderType.REPLENISHMENT,
        safety_stock_config=SAFETY_STOCK_CONFIG,
    )[0]

    assert evaluated.eligible_quantity == Decimal("80")
    assert evaluated.full_fill_capable is True
    assert evaluated.eligible is True
    assert ReasonCode.PARENT_INSUFFICIENT_QUANTITY not in evaluated.rejection_reason_codes
    assert ReasonCode.SAFETY_STOCK_PROTECTED in evaluated.rejection_reason_codes


def test_parent_candidate_insufficient_quantity():
    candidate = create_candidate(
        location="1158",
        source_type=SourceType.PARENT_RDC,
        requested_quantity="10",
    )

    positions = [
        create_inventory_position(
            location="1158",
            material_code="MAT-001",
            actual_stock="12",
            allocated_quantity="0",
            pending_so_quantity="0",
            safety_stock="5",
        )
    ]

    evaluated = evaluate_candidates_inventory(
        candidates=[candidate],
        inventory_positions=positions,
        order_type=OrderType.REPLENISHMENT,
        safety_stock_config=SAFETY_STOCK_CONFIG,
    )[0]

    assert evaluated.eligible_quantity == Decimal("7")
    assert evaluated.full_fill_capable is False
    assert evaluated.eligible is True
    assert ReasonCode.PARENT_INSUFFICIENT_QUANTITY in evaluated.rejection_reason_codes


def test_candidate_no_eligible_stock():
    candidate = create_candidate(
        location="1158",
        source_type=SourceType.PARENT_RDC,
        requested_quantity="10",
    )

    positions = [
        create_inventory_position(
            location="1158",
            material_code="MAT-001",
            actual_stock="5",
            allocated_quantity="0",
            pending_so_quantity="0",
            safety_stock="5",
        )
    ]

    evaluated = evaluate_candidates_inventory(
        candidates=[candidate],
        inventory_positions=positions,
        order_type=OrderType.REPLENISHMENT,
        safety_stock_config=SAFETY_STOCK_CONFIG,
    )[0]

    assert evaluated.eligible_quantity == Decimal("0")
    assert evaluated.full_fill_capable is False
    assert evaluated.eligible is False
    assert ReasonCode.NO_ELIGIBLE_STOCK in evaluated.rejection_reason_codes


def test_non_parent_candidate_insufficient_quantity_gets_generic_reason():
    candidate = create_candidate(
        location="1141",
        source_type=SourceType.PAN_INDIA_RDC,
        requested_quantity="10",
    )

    positions = [
        create_inventory_position(
            location="1141",
            material_code="MAT-001",
            actual_stock="8",
            allocated_quantity="0",
            pending_so_quantity="0",
            safety_stock="2",
        )
    ]

    evaluated = evaluate_candidates_inventory(
        candidates=[candidate],
        inventory_positions=positions,
        order_type=OrderType.REPLENISHMENT,
        safety_stock_config=SAFETY_STOCK_CONFIG,
    )[0]

    assert evaluated.eligible_quantity == Decimal("6")
    assert evaluated.full_fill_capable is False
    assert evaluated.eligible is True
    assert ReasonCode.INSUFFICIENT_QUANTITY in evaluated.rejection_reason_codes


def test_missing_inventory_position_returns_missing_master_data():
    candidate = create_candidate(
        location="9999",
        source_type=SourceType.PAN_INDIA_RDC,
        requested_quantity="10",
    )

    positions = [
        create_inventory_position(
            location="1158",
            material_code="MAT-001",
            actual_stock="100",
        )
    ]

    evaluated = evaluate_candidates_inventory(
        candidates=[candidate],
        inventory_positions=positions,
        order_type=OrderType.REPLENISHMENT,
        safety_stock_config=SAFETY_STOCK_CONFIG,
    )[0]

    assert evaluated.eligible is False
    assert evaluated.eligible_quantity == Decimal("0")
    assert ReasonCode.MISSING_MASTER_DATA in evaluated.rejection_reason_codes


def test_safety_stock_can_be_disabled_by_order_type():
    candidate = create_candidate(
        location="1158",
        source_type=SourceType.PARENT_RDC,
        requested_quantity="10",
    )

    positions = [
        create_inventory_position(
            location="1158",
            material_code="MAT-001",
            actual_stock="10",
            allocated_quantity="0",
            pending_so_quantity="0",
            safety_stock="5",
        )
    ]

    safety_stock_config = {
        "VOR": False,
        "REPLENISHMENT": True,
        "PUSH": True,
    }

    evaluated = evaluate_candidates_inventory(
        candidates=[candidate],
        inventory_positions=positions,
        order_type=OrderType.VOR,
        safety_stock_config=safety_stock_config,
    )[0]

    assert evaluated.eligible_quantity == Decimal("10")
    assert evaluated.full_fill_capable is True
    assert ReasonCode.SAFETY_STOCK_PROTECTED not in evaluated.rejection_reason_codes


def test_git_candidate_quantity_is_evaluated():
    candidate = CandidateSource(
        location="1158",
        source_type=SourceType.PARENT_GIT,
        material_code="MAT-001",
        requested_quantity=Decimal("10"),
        available_quantity=Decimal("8"),
        safety_stock=Decimal("0"),
        eligible_quantity=Decimal("8"),
        full_fill_capable=False,
        ageing_quantity=Decimal("0"),
        cluster=None,
        region=None,
        route_available=True,
        eligible=True,
        rejection_reason_codes=[],
    )

    evaluated = evaluate_candidates_inventory(
        candidates=[candidate],
        inventory_positions=[],
        order_type=OrderType.REPLENISHMENT,
        safety_stock_config=SAFETY_STOCK_CONFIG,
    )[0]

    assert evaluated.eligible is True
    assert evaluated.full_fill_capable is False
    assert ReasonCode.INSUFFICIENT_QUANTITY in evaluated.rejection_reason_codes