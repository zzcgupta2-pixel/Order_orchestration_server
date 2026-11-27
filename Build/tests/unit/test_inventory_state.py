from datetime import datetime, timezone
from decimal import Decimal

import pytest

from order_orchestration.domain.enums import ReasonCode
from order_orchestration.domain.inventory import InventoryPosition
from order_orchestration.exceptions import DuplicateExecutionError, InventoryStateError
from order_orchestration.state.inventory_state import InventoryStateManager


def create_inventory_position(
    location: str = "1158",
    material_code: str = "MAT-001",
    actual_stock: str = "100",
    allocated_quantity: str = "0",
    pending_so_quantity: str = "0",
    safety_stock: str = "20",
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


def test_inventory_state_initializes_available_quantity():
    position = create_inventory_position(
        actual_stock="100",
        allocated_quantity="10",
        pending_so_quantity="5",
        safety_stock="20",
    )

    manager = InventoryStateManager([position])

    available_qty = manager.get_available_quantity(
        location="1158",
        material_code="MAT-001",
    )

    assert available_qty == Decimal("65")


def test_inventory_state_clips_negative_available_quantity_to_zero():
    position = create_inventory_position(
        actual_stock="10",
        allocated_quantity="5",
        pending_so_quantity="5",
        safety_stock="10",
    )

    manager = InventoryStateManager([position])

    available_qty = manager.get_available_quantity(
        location="1158",
        material_code="MAT-001",
    )

    assert available_qty == Decimal("0")


def test_has_inventory_position_returns_true_when_position_exists():
    position = create_inventory_position()

    manager = InventoryStateManager([position])

    assert manager.has_inventory_position(
        location="1158",
        material_code="MAT-001",
    ) is True


def test_has_inventory_position_returns_false_when_position_missing():
    position = create_inventory_position()

    manager = InventoryStateManager([position])

    assert manager.has_inventory_position(
        location="9999",
        material_code="MAT-999",
    ) is False


def test_get_available_quantity_returns_zero_for_missing_position():
    position = create_inventory_position()

    manager = InventoryStateManager([position])

    available_qty = manager.get_available_quantity(
        location="9999",
        material_code="MAT-999",
    )

    assert available_qty == Decimal("0")


def test_allocation_reduces_inventory_balance():
    position = create_inventory_position(
        actual_stock="100",
        allocated_quantity="0",
        pending_so_quantity="0",
        safety_stock="20",
    )

    manager = InventoryStateManager([position])

    movement = manager.allocate(
        order_id="SO-001",
        line_id="10",
        location="1158",
        material_code="MAT-001",
        quantity=Decimal("30"),
        movement_timestamp=datetime(2026, 7, 24, 10, 0, tzinfo=timezone.utc),
        reason_code=ReasonCode.SINGLE_SOURCE_REROUTE,
    )

    assert movement.order_id == "SO-001"
    assert movement.line_id == "10"
    assert movement.material_code == "MAT-001"
    assert movement.location == "1158"
    assert movement.allocated_quantity == Decimal("30")
    assert movement.inventory_before == Decimal("80")
    assert movement.inventory_after == Decimal("50")

    available_qty_after = manager.get_available_quantity(
        location="1158",
        material_code="MAT-001",
    )

    assert available_qty_after == Decimal("50")


def test_allocation_records_inventory_movement():
    position = create_inventory_position(
        actual_stock="100",
        safety_stock="20",
    )

    manager = InventoryStateManager([position])

    manager.allocate(
        order_id="SO-001",
        line_id="10",
        location="1158",
        material_code="MAT-001",
        quantity=Decimal("25"),
        movement_timestamp=datetime(2026, 7, 24, 10, 0, tzinfo=timezone.utc),
        reason_code=ReasonCode.SINGLE_SOURCE_REROUTE,
        remarks="Allocated from parent RDC.",
    )

    movements = manager.get_movements()

    assert len(movements) == 1
    assert movements[0].order_id == "SO-001"
    assert movements[0].line_id == "10"
    assert movements[0].allocated_quantity == Decimal("25")
    assert movements[0].inventory_before == Decimal("80")
    assert movements[0].inventory_after == Decimal("55")
    assert movements[0].reason_code == ReasonCode.SINGLE_SOURCE_REROUTE
    assert movements[0].remarks == "Allocated from parent RDC."


def test_negative_inventory_is_prevented():
    position = create_inventory_position(
        actual_stock="100",
        safety_stock="20",
    )

    manager = InventoryStateManager([position])

    with pytest.raises(InventoryStateError):
        manager.allocate(
            order_id="SO-001",
            line_id="10",
            location="1158",
            material_code="MAT-001",
            quantity=Decimal("100"),
            movement_timestamp=datetime(2026, 7, 24, 10, 0, tzinfo=timezone.utc),
            reason_code=ReasonCode.SINGLE_SOURCE_REROUTE,
        )


def test_duplicate_order_execution_is_blocked():
    position = create_inventory_position(
        actual_stock="100",
        safety_stock="20",
    )

    manager = InventoryStateManager([position])

    manager.allocate(
        order_id="SO-001",
        line_id="10",
        location="1158",
        material_code="MAT-001",
        quantity=Decimal("20"),
        movement_timestamp=datetime(2026, 7, 24, 10, 0, tzinfo=timezone.utc),
        reason_code=ReasonCode.SINGLE_SOURCE_REROUTE,
    )

    with pytest.raises(DuplicateExecutionError):
        manager.allocate(
            order_id="SO-001",
            line_id="10",
            location="1158",
            material_code="MAT-001",
            quantity=Decimal("10"),
            movement_timestamp=datetime(2026, 7, 24, 11, 0, tzinfo=timezone.utc),
            reason_code=ReasonCode.SINGLE_SOURCE_REROUTE,
        )


def test_missing_inventory_position_raises_error():
    position = create_inventory_position()

    manager = InventoryStateManager([position])

    with pytest.raises(InventoryStateError):
        manager.allocate(
            order_id="SO-001",
            line_id="10",
            location="9999",
            material_code="MAT-999",
            quantity=Decimal("10"),
            movement_timestamp=datetime(2026, 7, 24, 10, 0, tzinfo=timezone.utc),
            reason_code=ReasonCode.SINGLE_SOURCE_REROUTE,
        )


def test_zero_allocation_quantity_is_rejected():
    position = create_inventory_position()

    manager = InventoryStateManager([position])

    with pytest.raises(InventoryStateError):
        manager.allocate(
            order_id="SO-001",
            line_id="10",
            location="1158",
            material_code="MAT-001",
            quantity=Decimal("0"),
            movement_timestamp=datetime(2026, 7, 24, 10, 0, tzinfo=timezone.utc),
            reason_code=ReasonCode.SINGLE_SOURCE_REROUTE,
        )


def test_negative_allocation_quantity_is_rejected():
    position = create_inventory_position()

    manager = InventoryStateManager([position])

    with pytest.raises(InventoryStateError):
        manager.allocate(
            order_id="SO-001",
            line_id="10",
            location="1158",
            material_code="MAT-001",
            quantity=Decimal("-5"),
            movement_timestamp=datetime(2026, 7, 24, 10, 0, tzinfo=timezone.utc),
            reason_code=ReasonCode.SINGLE_SOURCE_REROUTE,
        )


def test_has_processed_order_after_allocation():
    position = create_inventory_position()

    manager = InventoryStateManager([position])

    assert manager.has_processed_order("SO-001", "10") is False

    manager.allocate(
        order_id="SO-001",
        line_id="10",
        location="1158",
        material_code="MAT-001",
        quantity=Decimal("10"),
        movement_timestamp=datetime(2026, 7, 24, 10, 0, tzinfo=timezone.utc),
        reason_code=ReasonCode.SINGLE_SOURCE_REROUTE,
    )

    assert manager.has_processed_order("SO-001", "10") is True


def test_get_inventory_balance_snapshot_returns_copy():
    position = create_inventory_position(
        actual_stock="100",
        safety_stock="20",
    )

    manager = InventoryStateManager([position])

    snapshot = manager.get_inventory_balance_snapshot()

    assert snapshot[("1158", "MAT-001")] == Decimal("80")

    snapshot[("1158", "MAT-001")] = Decimal("999")

    actual_available_qty = manager.get_available_quantity(
        location="1158",
        material_code="MAT-001",
    )

    assert actual_available_qty == Decimal("80")