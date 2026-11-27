from datetime import datetime
from typing import Iterable

import pandas as pd

from order_orchestration.domain.enums import OrderType


DEFAULT_ORDER_PRIORITY = {
    OrderType.VOR.value: 1,
    OrderType.REPLENISHMENT.value: 2,
    OrderType.PUSH.value: 3,
}


def normalize_order_type(order_type: str) -> str:
    """
    Normalizes order type/category values into engine-standard values.

    Input examples:
        VOR -> VOR
        Replenishment -> REPLENISHMENT
        Push -> PUSH
    """

    value = str(order_type).strip().upper()

    if value == "REPLENISHMENT":
        return OrderType.REPLENISHMENT.value

    if value == "VOR":
        return OrderType.VOR.value

    if value == "PUSH":
        return OrderType.PUSH.value

    return value


def prepare_orders_for_queue(
    orders_df: pd.DataFrame,
    order_priority: dict[str, int] | None = None,
) -> pd.DataFrame:
    """
    Prepares order dataframe for deterministic queue processing.

    Required columns:
        - order_category
        - order_create_datetime

    Optional deterministic tie-breaker columns:
        - sales_order
        - sales_order_line

    If optional tie-breaker columns are missing, generated fallback values
    are created using dataframe index.
    """

    if order_priority is None:
        order_priority = DEFAULT_ORDER_PRIORITY

    required_columns = [
        "order_category",
        "order_create_datetime",
    ]

    missing_columns = [
        column for column in required_columns if column not in orders_df.columns
    ]

    if missing_columns:
        raise ValueError(f"Orders dataframe missing columns: {missing_columns}")

    df = orders_df.copy()

    df["order_type_normalized"] = df["order_category"].apply(normalize_order_type)

    df["queue_priority"] = df["order_type_normalized"].map(order_priority)

    if df["queue_priority"].isna().any():
        unsupported_types = (
            df.loc[df["queue_priority"].isna(), "order_category"]
            .astype(str)
            .unique()
            .tolist()
        )
        raise ValueError(f"Unsupported order categories found: {unsupported_types}")

    df["queue_priority"] = df["queue_priority"].astype(int)

    df["order_create_datetime"] = pd.to_datetime(
        df["order_create_datetime"],
        errors="coerce",
        utc=True,
    )

    if df["order_create_datetime"].isna().any():
        raise ValueError("Some order_create_datetime values could not be parsed.")

    if "sales_order" not in df.columns:
        df["sales_order"] = df.index.astype(str)

    if "sales_order_line" not in df.columns:
        df["sales_order_line"] = df.index.astype(str)

    df["sales_order"] = df["sales_order"].astype(str).str.strip()
    df["sales_order_line"] = df["sales_order_line"].astype(str).str.strip()

    return df


def build_order_execution_key(
    row: pd.Series,
) -> tuple[str, str]:
    """
    Builds unique execution key for an order line.

    This key is used to prevent duplicate execution.
    """

    return str(row["sales_order"]), str(row["sales_order_line"])


def get_available_orders(
    orders_df: pd.DataFrame,
    current_timestamp: datetime | pd.Timestamp,
    processed_order_keys: Iterable[tuple[str, str]] | None = None,
) -> pd.DataFrame:
    """
    Returns orders that have arrived on or before current_timestamp and
    have not been processed yet.
    """

    if processed_order_keys is None:
        processed_order_keys = set()
    else:
        processed_order_keys = set(processed_order_keys)

    df = orders_df.copy()

    current_timestamp = pd.to_datetime(
        current_timestamp,
        errors="coerce",
        utc=True,
    )

    if pd.isna(current_timestamp):
        raise ValueError("current_timestamp could not be parsed.")

    available_df = df[df["order_create_datetime"] <= current_timestamp].copy()

    if available_df.empty:
        return available_df

    available_df["execution_key"] = available_df.apply(
        build_order_execution_key,
        axis=1,
    )

    available_df = available_df[
        ~available_df["execution_key"].isin(processed_order_keys)
    ].copy()

    return available_df


def sort_orders_deterministically(
    orders_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Sorts available orders deterministically by:
        1. queue_priority
        2. order_create_datetime
        3. sales_order
        4. sales_order_line
    """

    if orders_df.empty:
        return orders_df.copy()

    sorted_df = orders_df.sort_values(
        by=[
            "queue_priority",
            "order_create_datetime",
            "sales_order",
            "sales_order_line",
        ],
        ascending=[True, True, True, True],
    ).reset_index(drop=True)

    return sorted_df


def select_next_order(
    orders_df: pd.DataFrame,
    current_timestamp: datetime | pd.Timestamp,
    processed_order_keys: Iterable[tuple[str, str]] | None = None,
) -> pd.Series | None:
    """
    Selects the next order to process at current simulation timestamp.

    Logic:
        - Only orders with order_create_datetime <= current_timestamp are visible.
        - Already processed order lines are excluded.
        - Highest priority available order is selected.
        - FIFO is applied within the same order type.
        - Sales order and sales order line are deterministic tie-breakers.
    """

    available_orders = get_available_orders(
        orders_df=orders_df,
        current_timestamp=current_timestamp,
        processed_order_keys=processed_order_keys,
    )

    if available_orders.empty:
        return None

    sorted_orders = sort_orders_deterministically(available_orders)

    return sorted_orders.iloc[0]


def get_next_event_timestamp(
    orders_df: pd.DataFrame,
    processed_order_keys: Iterable[tuple[str, str]] | None = None,
) -> pd.Timestamp | None:
    """
    Returns the next unprocessed order creation timestamp.

    This is useful for event-driven simulation when no order is currently
    available at the current timestamp.
    """

    if processed_order_keys is None:
        processed_order_keys = set()
    else:
        processed_order_keys = set(processed_order_keys)

    df = orders_df.copy()

    df["execution_key"] = df.apply(
        build_order_execution_key,
        axis=1,
    )

    unprocessed_df = df[
        ~df["execution_key"].isin(processed_order_keys)
    ].copy()

    if unprocessed_df.empty:
        return None

    return unprocessed_df["order_create_datetime"].min()