from datetime import datetime, timezone
from decimal import Decimal

import pandas as pd
import pytest

from order_orchestration.data.adapters import (
    inventory_dataframe_to_positions,
    normalize_order_type,
    orders_dataframe_to_order_lines,
    prepare_inventory_snapshot_from_master,
    safe_bool_from_flag,
    safe_datetime,
    safe_decimal,
    safe_string,
)
from order_orchestration.domain.enums import OrderType


def test_safe_decimal_valid_value():
    result = safe_decimal("10.5")

    assert result == Decimal("10.5")


def test_safe_decimal_invalid_value_returns_default():
    result = safe_decimal("abc")

    assert result == Decimal("0")


def test_safe_string_strips_spaces():
    result = safe_string("  MAT-001  ")

    assert result == "MAT-001"


def test_safe_bool_from_flag_true_values():
    assert safe_bool_from_flag(1) is True
    assert safe_bool_from_flag("1") is True
    assert safe_bool_from_flag("Y") is True
    assert safe_bool_from_flag("YES") is True
    assert safe_bool_from_flag("TRUE") is True
    assert safe_bool_from_flag("CB") is True


def test_safe_bool_from_flag_false_values():
    assert safe_bool_from_flag(0) is False
    assert safe_bool_from_flag("0") is False
    assert safe_bool_from_flag("NO") is False
    assert safe_bool_from_flag("") is False


def test_safe_datetime_converts_to_timezone_aware_datetime():
    result = safe_datetime("2026-07-24 10:00:00")

    assert result.tzinfo is not None
    assert result.year == 2026
    assert result.month == 7
    assert result.day == 24


def test_safe_datetime_raises_error_for_invalid_value():
    with pytest.raises(ValueError):
        safe_datetime("not-a-date")


def test_normalize_order_type_vor():
    assert normalize_order_type("VOR") == OrderType.VOR


def test_normalize_order_type_replenishment():
    assert normalize_order_type("Replenishment") == OrderType.REPLENISHMENT


def test_normalize_order_type_push():
    assert normalize_order_type("Push") == OrderType.PUSH


def test_normalize_order_type_unsupported_raises_error():
    with pytest.raises(ValueError):
        normalize_order_type("Export")


def test_orders_dataframe_to_order_lines_with_fallback_ids():
    orders_df = pd.DataFrame(
        {
            "order_category": ["Replenishment"],
            "plant": ["1158"],
            "material_code": ["MAT-001"],
            "customer_code": ["DEALER-001"],
            "order_create_datetime": ["2026-07-24 10:00:00+00:00"],
            "open_order_qty": [10],
            "is_credit_blocked": [0],
        }
    )

    order_lines = orders_dataframe_to_order_lines(orders_df)

    assert len(order_lines) == 1

    order_line = order_lines[0]

    assert order_line.order_id == "ROW_0"
    assert order_line.line_id == "1"
    assert order_line.order_type == OrderType.REPLENISHMENT
    assert order_line.material_code == "MAT-001"
    assert order_line.dealer_code == "DEALER-001"
    assert order_line.parent_rdc == "1158"
    assert order_line.requested_quantity == Decimal("10")
    assert order_line.remaining_quantity == Decimal("10")
    assert order_line.is_credit_blocked is False


def test_orders_dataframe_to_order_lines_with_sales_order_columns():
    orders_df = pd.DataFrame(
        {
            "sales_order": ["SO-001"],
            "sales_order_line": ["10"],
            "order_category": ["VOR"],
            "plant": ["1158"],
            "material_code": ["MAT-001"],
            "customer_code": ["DEALER-001"],
            "order_create_datetime": ["2026-07-24 10:00:00+00:00"],
            "open_order_qty": [5],
            "is_credit_blocked": ["CB"],
        }
    )

    order_lines = orders_dataframe_to_order_lines(orders_df)

    assert len(order_lines) == 1

    order_line = order_lines[0]

    assert order_line.order_id == "SO-001"
    assert order_line.line_id == "10"
    assert order_line.order_type == OrderType.VOR
    assert order_line.requested_quantity == Decimal("5")
    assert order_line.is_credit_blocked is True


def test_orders_dataframe_to_order_lines_missing_required_column_raises_error():
    orders_df = pd.DataFrame(
        {
            "order_category": ["Replenishment"],
            "plant": ["1158"],
        }
    )

    with pytest.raises(ValueError):
        orders_dataframe_to_order_lines(orders_df)


def test_inventory_dataframe_to_positions_creates_inventory_positions():
    inventory_df = pd.DataFrame(
        {
            "snapshot_timestamp": ["2026-07-24 00:00:00+00:00"],
            "location": ["1158"],
            "material_code": ["MAT-001"],
            "actual_stock": [100],
            "allocated_quantity": [10],
            "pending_so_quantity": [5],
            "safety_stock": [20],
            "ageing_quantity": [30],
            "ageing_quantity_gt_1yr": [15],
        }
    )

    positions = inventory_dataframe_to_positions(inventory_df)

    assert len(positions) == 1

    position = positions[0]

    assert position.location == "1158"
    assert position.material_code == "MAT-001"
    assert position.actual_stock == Decimal("100")
    assert position.allocated_quantity == Decimal("10")
    assert position.pending_so_quantity == Decimal("5")
    assert position.safety_stock == Decimal("20")
    assert position.ageing_quantity == Decimal("30")
    assert position.ageing_quantity_gt_1yr == Decimal("15")


def test_inventory_dataframe_to_positions_defaults_ageing_columns_to_zero():
    inventory_df = pd.DataFrame(
        {
            "snapshot_timestamp": ["2026-07-24 00:00:00+00:00"],
            "location": ["1158"],
            "material_code": ["MAT-001"],
            "actual_stock": [100],
            "allocated_quantity": [0],
            "pending_so_quantity": [0],
            "safety_stock": [20],
        }
    )

    positions = inventory_dataframe_to_positions(inventory_df)

    assert len(positions) == 1
    assert positions[0].ageing_quantity == Decimal("0")
    assert positions[0].ageing_quantity_gt_1yr == Decimal("0")


def test_inventory_dataframe_to_positions_missing_required_column_raises_error():
    inventory_df = pd.DataFrame(
        {
            "location": ["1158"],
            "material_code": ["MAT-001"],
        }
    )

    with pytest.raises(ValueError):
        inventory_dataframe_to_positions(inventory_df)


def test_inventory_dataframe_to_positions_missing_snapshot_timestamp_raises_error():
    inventory_df = pd.DataFrame(
        {
            "location": ["1158"],
            "material_code": ["MAT-001"],
            "actual_stock": [100],
            "allocated_quantity": [0],
            "pending_so_quantity": [0],
            "safety_stock": [20],
        }
    )

    with pytest.raises(ValueError):
        inventory_dataframe_to_positions(inventory_df)


def test_prepare_inventory_snapshot_from_master():
    master_df = pd.DataFrame(
        {
            "plant": ["1158"],
            "material_code": ["MAT-001"],
            "total_saleable_inventory_qty": [100],
            "safety_stock": [20],
            "ageing_stock_qty": [30],
            "ageing_stock_gt_1yr": [15],
        }
    )

    snapshot_timestamp = datetime(2026, 7, 24, tzinfo=timezone.utc)

    inventory_snapshot_df = prepare_inventory_snapshot_from_master(
        master_df=master_df,
        snapshot_timestamp=snapshot_timestamp,
    )

    assert len(inventory_snapshot_df) == 1

    row = inventory_snapshot_df.iloc[0]

    assert row["location"] == "1158"
    assert row["material_code"] == "MAT-001"
    assert row["actual_stock"] == 100
    assert row["allocated_quantity"] == 0
    assert row["pending_so_quantity"] == 0
    assert row["safety_stock"] == 20
    assert row["ageing_quantity"] == 30
    assert row["ageing_quantity_gt_1yr"] == 15
    assert pd.notna(row["snapshot_timestamp"])


def test_prepare_inventory_snapshot_from_master_missing_required_column_raises_error():
    master_df = pd.DataFrame(
        {
            "plant": ["1158"],
            "material_code": ["MAT-001"],
        }
    )

    with pytest.raises(ValueError):
        prepare_inventory_snapshot_from_master(
            master_df=master_df,
            snapshot_timestamp=datetime(2026, 7, 24, tzinfo=timezone.utc),
        )