from datetime import datetime, timezone
from decimal import Decimal

import pandas as pd

from order_orchestration.data.state_reconstruction import (
    build_inventory_positions_as_of,
    get_inventory_position_as_of,
    get_latest_inventory_snapshot_as_of,
)


def test_latest_snapshot_before_order_time_is_selected():
    inventory_df = pd.DataFrame(
        {
            "snapshot_timestamp": [
                "2026-07-20 09:00:00+00:00",
                "2026-07-20 14:00:00+00:00",
            ],
            "location": ["1158", "1158"],
            "material_code": ["MAT-001", "MAT-001"],
            "actual_stock": [100, 200],
            "allocated_quantity": [0, 0],
            "pending_so_quantity": [0, 0],
            "safety_stock": [10, 10],
        }
    )

    order_time = datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc)

    result = get_latest_inventory_snapshot_as_of(
        inventory_df=inventory_df,
        as_of_timestamp=order_time,
    )

    assert len(result) == 1
    assert result.iloc[0]["actual_stock"] == 100


def test_future_snapshot_is_not_selected():
    inventory_df = pd.DataFrame(
        {
            "snapshot_timestamp": [
                "2026-07-20 14:00:00+00:00",
            ],
            "location": ["1158"],
            "material_code": ["MAT-001"],
            "actual_stock": [200],
            "allocated_quantity": [0],
            "pending_so_quantity": [0],
            "safety_stock": [10],
        }
    )

    order_time = datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc)

    result = get_latest_inventory_snapshot_as_of(
        inventory_df=inventory_df,
        as_of_timestamp=order_time,
    )

    assert result.empty


def test_exact_timestamp_match_is_allowed():
    inventory_df = pd.DataFrame(
        {
            "snapshot_timestamp": [
                "2026-07-20 10:00:00+00:00",
            ],
            "location": ["1158"],
            "material_code": ["MAT-001"],
            "actual_stock": [150],
            "allocated_quantity": [0],
            "pending_so_quantity": [0],
            "safety_stock": [10],
        }
    )

    order_time = datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc)

    result = get_latest_inventory_snapshot_as_of(
        inventory_df=inventory_df,
        as_of_timestamp=order_time,
    )

    assert len(result) == 1
    assert result.iloc[0]["actual_stock"] == 150


def test_multiple_location_material_pairs_are_handled():
    inventory_df = pd.DataFrame(
        {
            "snapshot_timestamp": [
                "2026-07-20 09:00:00+00:00",
                "2026-07-20 08:00:00+00:00",
                "2026-07-20 14:00:00+00:00",
            ],
            "location": ["1158", "1141", "1158"],
            "material_code": ["MAT-001", "MAT-002", "MAT-001"],
            "actual_stock": [100, 50, 999],
            "allocated_quantity": [0, 0, 0],
            "pending_so_quantity": [0, 0, 0],
            "safety_stock": [10, 5, 10],
        }
    )

    order_time = datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc)

    result = get_latest_inventory_snapshot_as_of(
        inventory_df=inventory_df,
        as_of_timestamp=order_time,
    )

    assert len(result) == 2

    result_key_values = {
        (row["location"], row["material_code"]): row["actual_stock"]
        for _, row in result.iterrows()
    }

    assert result_key_values[("1158", "MAT-001")] == 100
    assert result_key_values[("1141", "MAT-002")] == 50


def test_get_inventory_position_as_of_returns_domain_object():
    inventory_df = pd.DataFrame(
        {
            "snapshot_timestamp": [
                "2026-07-20 09:00:00+00:00",
            ],
            "location": ["1158"],
            "material_code": ["MAT-001"],
            "actual_stock": [100],
            "allocated_quantity": [5],
            "pending_so_quantity": [10],
            "safety_stock": [20],
            "ageing_quantity": [30],
            "ageing_quantity_gt_1yr": [15],
        }
    )

    order_time = datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc)

    position = get_inventory_position_as_of(
        inventory_df=inventory_df,
        location="1158",
        material_code="MAT-001",
        as_of_timestamp=order_time,
    )

    assert position is not None
    assert position.location == "1158"
    assert position.material_code == "MAT-001"
    assert position.actual_stock == Decimal("100")
    assert position.allocated_quantity == Decimal("5")
    assert position.pending_so_quantity == Decimal("10")
    assert position.safety_stock == Decimal("20")
    assert position.ageing_quantity == Decimal("30")
    assert position.ageing_quantity_gt_1yr == Decimal("15")


def test_get_inventory_position_as_of_returns_none_when_not_found():
    inventory_df = pd.DataFrame(
        {
            "snapshot_timestamp": [
                "2026-07-20 09:00:00+00:00",
            ],
            "location": ["1158"],
            "material_code": ["MAT-001"],
            "actual_stock": [100],
            "allocated_quantity": [0],
            "pending_so_quantity": [0],
            "safety_stock": [10],
        }
    )

    order_time = datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc)

    position = get_inventory_position_as_of(
        inventory_df=inventory_df,
        location="1141",
        material_code="MAT-999",
        as_of_timestamp=order_time,
    )

    assert position is None


def test_build_inventory_positions_as_of_returns_positions():
    inventory_df = pd.DataFrame(
        {
            "snapshot_timestamp": [
                "2026-07-20 09:00:00+00:00",
                "2026-07-20 08:00:00+00:00",
            ],
            "location": ["1158", "1141"],
            "material_code": ["MAT-001", "MAT-002"],
            "actual_stock": [100, 50],
            "allocated_quantity": [0, 0],
            "pending_so_quantity": [0, 0],
            "safety_stock": [10, 5],
        }
    )

    order_time = datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc)

    positions = build_inventory_positions_as_of(
        inventory_df=inventory_df,
        as_of_timestamp=order_time,
    )

    assert len(positions) == 2
    assert positions[0].material_code in {"MAT-001", "MAT-002"}
    assert positions[1].material_code in {"MAT-001", "MAT-002"}