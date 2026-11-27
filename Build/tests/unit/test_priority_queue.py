from datetime import datetime, timezone

import pandas as pd

from order_orchestration.queue.priority_queue import (
    get_available_orders,
    prepare_orders_for_queue,
    select_next_order,
    sort_orders_deterministically,
)


def test_fifo_within_same_order_type():
    orders_df = pd.DataFrame(
        {
            "sales_order": ["SO2", "SO1"],
            "sales_order_line": ["10", "10"],
            "order_category": ["Replenishment", "Replenishment"],
            "order_create_datetime": [
                "2026-07-20 11:00:00+00:00",
                "2026-07-20 10:00:00+00:00",
            ],
        }
    )

    prepared_df = prepare_orders_for_queue(orders_df)
    sorted_df = sort_orders_deterministically(prepared_df)

    assert sorted_df.iloc[0]["sales_order"] == "SO1"
    assert sorted_df.iloc[1]["sales_order"] == "SO2"


def test_vor_priority_over_replenishment_when_both_available():
    orders_df = pd.DataFrame(
        {
            "sales_order": ["SO1", "SO2"],
            "sales_order_line": ["10", "10"],
            "order_category": ["Replenishment", "VOR"],
            "order_create_datetime": [
                "2026-07-20 10:00:00+00:00",
                "2026-07-20 10:05:00+00:00",
            ],
        }
    )

    prepared_df = prepare_orders_for_queue(orders_df)

    selected = select_next_order(
        orders_df=prepared_df,
        current_timestamp=datetime(2026, 7, 20, 10, 10, tzinfo=timezone.utc),
        processed_order_keys=set(),
    )

    assert selected is not None
    assert selected["order_category"] == "VOR"


def test_future_vor_does_not_affect_earlier_push():
    orders_df = pd.DataFrame(
        {
            "sales_order": ["SO_PUSH", "SO_VOR"],
            "sales_order_line": ["10", "10"],
            "order_category": ["Push", "VOR"],
            "order_create_datetime": [
                "2026-07-20 10:00:00+00:00",
                "2026-07-20 11:00:00+00:00",
            ],
        }
    )

    prepared_df = prepare_orders_for_queue(orders_df)

    selected = select_next_order(
        orders_df=prepared_df,
        current_timestamp=datetime(2026, 7, 20, 10, 30, tzinfo=timezone.utc),
        processed_order_keys=set(),
    )

    assert selected is not None
    assert selected["sales_order"] == "SO_PUSH"


def test_equal_timestamps_use_sales_order_tie_breaker():
    orders_df = pd.DataFrame(
        {
            "sales_order": ["SO2", "SO1"],
            "sales_order_line": ["10", "10"],
            "order_category": ["Replenishment", "Replenishment"],
            "order_create_datetime": [
                "2026-07-20 10:00:00+00:00",
                "2026-07-20 10:00:00+00:00",
            ],
        }
    )

    prepared_df = prepare_orders_for_queue(orders_df)

    selected = select_next_order(
        orders_df=prepared_df,
        current_timestamp=datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc),
        processed_order_keys=set(),
    )

    assert selected is not None
    assert selected["sales_order"] == "SO1"


def test_equal_sales_order_uses_sales_order_line_tie_breaker():
    orders_df = pd.DataFrame(
        {
            "sales_order": ["SO1", "SO1"],
            "sales_order_line": ["20", "10"],
            "order_category": ["Replenishment", "Replenishment"],
            "order_create_datetime": [
                "2026-07-20 10:00:00+00:00",
                "2026-07-20 10:00:00+00:00",
            ],
        }
    )

    prepared_df = prepare_orders_for_queue(orders_df)

    selected = select_next_order(
        orders_df=prepared_df,
        current_timestamp=datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc),
        processed_order_keys=set(),
    )

    assert selected is not None
    assert selected["sales_order_line"] == "10"


def test_processed_orders_are_excluded():
    orders_df = pd.DataFrame(
        {
            "sales_order": ["SO1", "SO2"],
            "sales_order_line": ["10", "10"],
            "order_category": ["VOR", "Replenishment"],
            "order_create_datetime": [
                "2026-07-20 10:00:00+00:00",
                "2026-07-20 10:00:00+00:00",
            ],
        }
    )

    prepared_df = prepare_orders_for_queue(orders_df)

    selected = select_next_order(
        orders_df=prepared_df,
        current_timestamp=datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc),
        processed_order_keys={("SO1", "10")},
    )

    assert selected is not None
    assert selected["sales_order"] == "SO2"


def test_get_available_orders_only_returns_arrived_orders():
    orders_df = pd.DataFrame(
        {
            "sales_order": ["SO1", "SO2"],
            "sales_order_line": ["10", "10"],
            "order_category": ["Push", "VOR"],
            "order_create_datetime": [
                "2026-07-20 10:00:00+00:00",
                "2026-07-20 11:00:00+00:00",
            ],
        }
    )

    prepared_df = prepare_orders_for_queue(orders_df)

    available_df = get_available_orders(
        orders_df=prepared_df,
        current_timestamp=datetime(2026, 7, 20, 10, 30, tzinfo=timezone.utc),
        processed_order_keys=set(),
    )

    assert len(available_df) == 1
    assert available_df.iloc[0]["sales_order"] == "SO1"