from datetime import datetime, timezone
from decimal import Decimal

from order_orchestration.candidates.generator import (
    generate_all_source_candidates,
    generate_parent_git_candidates,
    generate_physical_source_candidates,
)
from order_orchestration.domain.enums import OrderType, SourceType
from order_orchestration.domain.git import GitShipment
from order_orchestration.domain.inventory import InventoryPosition
from order_orchestration.domain.order import OrderLine


def create_order_line() -> OrderLine:
    return OrderLine(
        order_id="SO-001",
        line_id="10",
        order_creation_timestamp=datetime(2026, 7, 24, tzinfo=timezone.utc),
        order_type=OrderType.REPLENISHMENT,
        material_code="MAT-001",
        dealer_code="DEALER-001",
        parent_rdc="1158",
        requested_quantity=Decimal("10"),
        remaining_quantity=Decimal("10"),
        is_credit_blocked=False,
    )

def create_inventory_positions() -> list:
    return [
        InventoryPosition(
            snapshot_timestamp=datetime(2026, 7, 24, tzinfo=timezone.utc),
            location="1158",
            material_code="MAT-001",
            actual_stock=Decimal("100"),
            allocated_quantity=Decimal("0"),
            pending_so_quantity=Decimal("0"),
            safety_stock=Decimal("10"),
            ageing_quantity=Decimal("0"),
            ageing_quantity_gt_1yr=Decimal("0"),
        ),
        InventoryPosition(
            snapshot_timestamp=datetime(2026, 7, 24, tzinfo=timezone.utc),
            location="1157",
            material_code="MAT-001",
            actual_stock=Decimal("50"),
            allocated_quantity=Decimal("0"),
            pending_so_quantity=Decimal("0"),
            safety_stock=Decimal("5"),
            ageing_quantity=Decimal("20"),
            ageing_quantity_gt_1yr=Decimal("20"),
        ),
        InventoryPosition(
            snapshot_timestamp=datetime(2026, 7, 24, tzinfo=timezone.utc),
            location="1141",
            material_code="MAT-001",
            actual_stock=Decimal("30"),
            allocated_quantity=Decimal("0"),
            pending_so_quantity=Decimal("0"),
            safety_stock=Decimal("5"),
            ageing_quantity=Decimal("0"),
            ageing_quantity_gt_1yr=Decimal("0"),
        ),
        InventoryPosition(
            snapshot_timestamp=datetime(2026, 7, 24, tzinfo=timezone.utc),
            location="1110",
            material_code="MAT-001",
            actual_stock=Decimal("500"),
            allocated_quantity=Decimal("0"),
            pending_so_quantity=Decimal("0"),
            safety_stock=Decimal("50"),
            ageing_quantity=Decimal("0"),
            ageing_quantity_gt_1yr=Decimal("0"),
        ),
        InventoryPosition(
            snapshot_timestamp=datetime(2026, 7, 24, tzinfo=timezone.utc),
            location="1158",
            material_code="MAT-999",
            actual_stock=Decimal("999"),
            allocated_quantity=Decimal("0"),
            pending_so_quantity=Decimal("0"),
            safety_stock=Decimal("0"),
            ageing_quantity=Decimal("0"),
            ageing_quantity_gt_1yr=Decimal("0"),
        ),
    ]


def test_generate_physical_source_candidates_creates_expected_source_types():
    order_line = create_order_line()
    inventory_positions = create_inventory_positions()

    location_cluster_map = {
        "1158": "NORTH",
        "1157": "NORTH",
        "1141": "SOUTH",
        "1110": "VEPDC",
    }

    candidates = generate_physical_source_candidates(
        order_line=order_line,
        inventory_positions=inventory_positions,
        location_cluster_map=location_cluster_map,
        vepdc_location_code="1110",
    )

    source_types = {candidate.source_type for candidate in candidates}

    assert len(candidates) == 4
    assert SourceType.PARENT_RDC in source_types
    assert SourceType.CLUSTER_RDC in source_types
    assert SourceType.PAN_INDIA_RDC in source_types
    assert SourceType.VEPDC in source_types


def test_generate_physical_source_candidates_filters_material():
    order_line = create_order_line()
    inventory_positions = create_inventory_positions()

    location_cluster_map = {
        "1158": "NORTH",
        "1157": "NORTH",
        "1141": "SOUTH",
        "1110": "VEPDC",
    }

    candidates = generate_physical_source_candidates(
        order_line=order_line,
        inventory_positions=inventory_positions,
        location_cluster_map=location_cluster_map,
        vepdc_location_code="1110",
    )

    assert all(candidate.material_code == "MAT-001" for candidate in candidates)


def test_generate_physical_source_candidates_can_filter_allowed_source_types():
    order_line = create_order_line()
    inventory_positions = create_inventory_positions()

    location_cluster_map = {
        "1158": "NORTH",
        "1157": "NORTH",
        "1141": "SOUTH",
        "1110": "VEPDC",
    }

    candidates = generate_physical_source_candidates(
        order_line=order_line,
        inventory_positions=inventory_positions,
        location_cluster_map=location_cluster_map,
        vepdc_location_code="1110",
        allowed_source_types={SourceType.PARENT_RDC},
    )

    assert len(candidates) == 1
    assert candidates[0].source_type == SourceType.PARENT_RDC
    assert candidates[0].location == "1158"


def test_parent_git_candidate_is_generated_for_parent_bound_git():
    order_line = create_order_line()

    git_shipments = [
        GitShipment(
            material_code="MAT-001",
            source_location="1110",
            destination_location="1158",
            git_quantity=Decimal("20"),
            expected_arrival_datetime=datetime(2026, 7, 25, tzinfo=timezone.utc),
            status="IN_TRANSIT",
        )
    ]

    candidates = generate_parent_git_candidates(
        order_line=order_line,
        git_shipments=git_shipments,
    )

    assert len(candidates) == 1
    assert candidates[0].source_type == SourceType.PARENT_GIT
    assert candidates[0].location == "1158"
    assert candidates[0].available_quantity == Decimal("20")
    assert candidates[0].full_fill_capable is True


def test_parent_git_candidate_not_generated_for_wrong_destination():
    order_line = create_order_line()

    git_shipments = [
        GitShipment(
            material_code="MAT-001",
            source_location="1110",
            destination_location="1141",
            git_quantity=Decimal("20"),
            expected_arrival_datetime=datetime(2026, 7, 25, tzinfo=timezone.utc),
            status="IN_TRANSIT",
        )
    ]

    candidates = generate_parent_git_candidates(
        order_line=order_line,
        git_shipments=git_shipments,
    )

    assert len(candidates) == 0


def test_generate_all_source_candidates_includes_physical_and_git():
    order_line = create_order_line()
    inventory_positions = create_inventory_positions()

    git_shipments = [
        GitShipment(
            material_code="MAT-001",
            source_location="1110",
            destination_location="1158",
            git_quantity=Decimal("20"),
            expected_arrival_datetime=datetime(2026, 7, 25, tzinfo=timezone.utc),
            status="IN_TRANSIT",
        )
    ]

    location_cluster_map = {
        "1158": "NORTH",
        "1157": "NORTH",
        "1141": "SOUTH",
        "1110": "VEPDC",
    }

    candidates = generate_all_source_candidates(
        order_line=order_line,
        inventory_positions=inventory_positions,
        git_shipments=git_shipments,
        location_cluster_map=location_cluster_map,
        vepdc_location_code="1110",
        include_parent_git=True,
    )

    assert len(candidates) == 5

    source_types = [candidate.source_type for candidate in candidates]

    assert SourceType.PARENT_RDC in source_types
    assert SourceType.CLUSTER_RDC in source_types
    assert SourceType.PAN_INDIA_RDC in source_types
    assert SourceType.VEPDC in source_types
    assert SourceType.PARENT_GIT in source_types


def test_generate_all_source_candidates_can_exclude_git():
    order_line = create_order_line()
    inventory_positions = create_inventory_positions()

    git_shipments = [
        GitShipment(
            material_code="MAT-001",
            source_location="1110",
            destination_location="1158",
            git_quantity=Decimal("20"),
            expected_arrival_datetime=datetime(2026, 7, 25, tzinfo=timezone.utc),
            status="IN_TRANSIT",
        )
    ]

    location_cluster_map = {
        "1158": "NORTH",
        "1157": "NORTH",
        "1141": "SOUTH",
        "1110": "VEPDC",
    }

    candidates = generate_all_source_candidates(
        order_line=order_line,
        inventory_positions=inventory_positions,
        git_shipments=git_shipments,
        location_cluster_map=location_cluster_map,
        vepdc_location_code="1110",
        include_parent_git=False,
    )

    assert len(candidates) == 4
    assert SourceType.PARENT_GIT not in {
        candidate.source_type for candidate in candidates
    }