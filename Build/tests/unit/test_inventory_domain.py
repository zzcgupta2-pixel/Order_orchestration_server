from datetime import datetime, timezone
from decimal import Decimal

from order_orchestration.domain.inventory import InventoryPosition


def test_inventory_position_creation_with_current_fields():
    position = InventoryPosition(
        snapshot_timestamp=datetime(2026, 7, 24, tzinfo=timezone.utc),
        location="1158",
        material_code="MAT-001",
        actual_stock=Decimal("100"),
        allocated_quantity=Decimal("10"),
        pending_so_quantity=Decimal("5"),
        safety_stock=Decimal("20"),
        ageing_quantity=Decimal("30"),
        ageing_quantity_gt_1yr=Decimal("15"),
    )

    assert position.location == "1158"
    assert position.material_code == "MAT-001"
    assert position.actual_stock == Decimal("100")
    assert position.allocated_quantity == Decimal("10")
    assert position.pending_so_quantity == Decimal("5")
    assert position.safety_stock == Decimal("20")
    assert position.ageing_quantity == Decimal("30")
    assert position.ageing_quantity_gt_1yr == Decimal("15")


def test_inventory_position_default_ageing_values_are_zero():
    position = InventoryPosition(
        snapshot_timestamp=datetime(2026, 7, 24, tzinfo=timezone.utc),
        location="1158",
        material_code="MAT-002",
        actual_stock=Decimal("50"),
        allocated_quantity=Decimal("0"),
        pending_so_quantity=Decimal("0"),
        safety_stock=Decimal("10"),
    )

    assert position.ageing_quantity == Decimal("0")
    assert position.ageing_quantity_gt_1yr == Decimal("0")