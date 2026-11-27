from datetime import datetime, timezone
from decimal import Decimal

from order_orchestration.domain.enums import OrderType
from order_orchestration.domain.inventory import InventoryPosition
from order_orchestration.eligibility.inventory_eligibility import (
    calculate_eligible_quantity,
    is_full_fill_capable,
    is_partial_fill_possible,
    should_protect_safety_stock,
)


def test_eligible_quantity_with_safety_stock_protected():
    safety_stock_config = {
        "VOR": True,
        "REPLENISHMENT": True,
        "PUSH": True,
    }

    position = InventoryPosition(
        snapshot_timestamp=datetime(2026, 7, 24, tzinfo=timezone.utc),
        location="1158",
        material_code="MAT-001",
        actual_stock=Decimal("100"),
        allocated_quantity=Decimal("10"),
        pending_so_quantity=Decimal("20"),
        safety_stock=Decimal("15"),
    )

    eligible_qty = calculate_eligible_quantity(
        inventory_position=position,
        order_type=OrderType.REPLENISHMENT,
        safety_stock_config=safety_stock_config,
    )

    assert eligible_qty == Decimal("55")


def test_eligible_quantity_without_safety_stock_protection():
    safety_stock_config = {
        "VOR": False,
        "REPLENISHMENT": True,
        "PUSH": True,
    }

    position = InventoryPosition(
        snapshot_timestamp=datetime(2026, 7, 24, tzinfo=timezone.utc),
        location="1158",
        material_code="MAT-002",
        actual_stock=Decimal("100"),
        allocated_quantity=Decimal("10"),
        pending_so_quantity=Decimal("20"),
        safety_stock=Decimal("15"),
    )

    eligible_qty = calculate_eligible_quantity(
        inventory_position=position,
        order_type=OrderType.VOR,
        safety_stock_config=safety_stock_config,
    )

    assert eligible_qty == Decimal("70")


def test_eligible_quantity_never_negative():
    safety_stock_config = {
        "VOR": True,
        "REPLENISHMENT": True,
        "PUSH": True,
    }

    position = InventoryPosition(
        snapshot_timestamp=datetime(2026, 7, 24, tzinfo=timezone.utc),
        location="1158",
        material_code="MAT-003",
        actual_stock=Decimal("10"),
        allocated_quantity=Decimal("8"),
        pending_so_quantity=Decimal("7"),
        safety_stock=Decimal("5"),
    )

    eligible_qty = calculate_eligible_quantity(
        inventory_position=position,
        order_type=OrderType.REPLENISHMENT,
        safety_stock_config=safety_stock_config,
    )

    assert eligible_qty == Decimal("0")


def test_full_fill_capable_true():
    assert is_full_fill_capable(
        eligible_quantity=Decimal("10"),
        requested_quantity=Decimal("10"),
    ) is True


def test_full_fill_capable_false_when_insufficient():
    assert is_full_fill_capable(
        eligible_quantity=Decimal("7"),
        requested_quantity=Decimal("10"),
    ) is False


def test_partial_fill_possible_true():
    assert is_partial_fill_possible(
        eligible_quantity=Decimal("7"),
        requested_quantity=Decimal("10"),
    ) is True


def test_partial_fill_possible_false_when_full_fill_possible():
    assert is_partial_fill_possible(
        eligible_quantity=Decimal("10"),
        requested_quantity=Decimal("10"),
    ) is False


def test_safety_stock_config_by_order_type():
    safety_stock_config = {
        "VOR": False,
        "REPLENISHMENT": True,
        "PUSH": True,
    }

    assert should_protect_safety_stock(OrderType.VOR, safety_stock_config) is False
    assert should_protect_safety_stock(OrderType.REPLENISHMENT, safety_stock_config) is True
    assert should_protect_safety_stock(OrderType.PUSH, safety_stock_config) is True