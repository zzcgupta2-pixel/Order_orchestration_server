from datetime import datetime
from decimal import Decimal
from typing import Optional

import pandas as pd

from order_orchestration.domain.inventory import InventoryPosition


REQUIRED_INVENTORY_COLUMNS = [
    "snapshot_timestamp",
    "location",
    "material_code",
    "actual_stock",
    "allocated_quantity",
    "pending_so_quantity",
    "safety_stock",
]


def _ensure_datetime_column(
    df: pd.DataFrame,
    column_name: str,
) -> pd.DataFrame:
    """
    Ensures that a dataframe column is converted to timezone-aware datetime.

    The function returns a copy of the dataframe and does not modify
    the original dataframe.
    """

    output_df = df.copy()
    output_df[column_name] = pd.to_datetime(
        output_df[column_name],
        errors="coerce",
        utc=True,
    )

    return output_df


def validate_inventory_snapshot_columns(
    inventory_df: pd.DataFrame,
) -> None:
    """
    Validates that the inventory dataframe has the minimum required columns.

    Required columns:
    - snapshot_timestamp
    - location
    - material_code
    - actual_stock
    - allocated_quantity
    - pending_so_quantity
    - safety_stock
    """

    missing_columns = [
        column
        for column in REQUIRED_INVENTORY_COLUMNS
        if column not in inventory_df.columns
    ]

    if missing_columns:
        raise ValueError(
            f"Inventory dataframe is missing required columns: {missing_columns}"
        )


def get_latest_inventory_snapshot_as_of(
    inventory_df: pd.DataFrame,
    as_of_timestamp: datetime | pd.Timestamp,
) -> pd.DataFrame:
    """
    Returns the latest inventory snapshot for every location-material pair
    available on or before the given timestamp.

    This prevents future-data leakage during historical simulation.

    Example:
        If order timestamp is 2026-07-20 10:00,
        and snapshots exist at 09:00 and 14:00,
        only the 09:00 snapshot is eligible.

    Args:
        inventory_df: Inventory snapshot dataframe.
        as_of_timestamp: Decision/order timestamp.

    Returns:
        DataFrame containing one latest row per location-material pair.
    """

    validate_inventory_snapshot_columns(inventory_df)

    df = _ensure_datetime_column(inventory_df, "snapshot_timestamp")

    as_of_timestamp = pd.to_datetime(
        as_of_timestamp,
        errors="coerce",
        utc=True,
    )

    if pd.isna(as_of_timestamp):
        raise ValueError("as_of_timestamp could not be converted to datetime.")

    eligible_snapshots = df[df["snapshot_timestamp"] <= as_of_timestamp].copy()

    if eligible_snapshots.empty:
        return eligible_snapshots

    eligible_snapshots = eligible_snapshots.sort_values(
        by=["location", "material_code", "snapshot_timestamp"],
        ascending=[True, True, True],
    )

    latest_snapshot = (
        eligible_snapshots.groupby(["location", "material_code"], as_index=False)
        .tail(1)
        .reset_index(drop=True)
    )

    return latest_snapshot


def inventory_row_to_position(row: pd.Series) -> InventoryPosition:
    """
    Converts a pandas inventory row into an InventoryPosition domain object.
    """

    ageing_quantity = (
        row["ageing_quantity"]
        if "ageing_quantity" in row.index
        else Decimal("0")
    )

    ageing_quantity_gt_1yr = (
        row["ageing_quantity_gt_1yr"]
        if "ageing_quantity_gt_1yr" in row.index
        else Decimal("0")
    )

    return InventoryPosition(
        snapshot_timestamp=pd.to_datetime(
            row["snapshot_timestamp"],
            utc=True,
        ).to_pydatetime(),
        location=str(row["location"]).strip(),
        material_code=str(row["material_code"]).strip(),
        actual_stock=Decimal(str(row["actual_stock"])),
        allocated_quantity=Decimal(str(row["allocated_quantity"])),
        pending_so_quantity=Decimal(str(row["pending_so_quantity"])),
        safety_stock=Decimal(str(row["safety_stock"])),
        ageing_quantity=Decimal(str(ageing_quantity)),
        ageing_quantity_gt_1yr=Decimal(str(ageing_quantity_gt_1yr)),
    )


def get_inventory_position_as_of(
    inventory_df: pd.DataFrame,
    location: str,
    material_code: str,
    as_of_timestamp: datetime | pd.Timestamp,
) -> Optional[InventoryPosition]:
    """
    Returns one InventoryPosition for a specific location-material pair
    as of the given timestamp.

    If no valid snapshot exists on or before the timestamp, returns None.
    """

    latest_snapshot_df = get_latest_inventory_snapshot_as_of(
        inventory_df=inventory_df,
        as_of_timestamp=as_of_timestamp,
    )

    if latest_snapshot_df.empty:
        return None

    location = str(location).strip()
    material_code = str(material_code).strip()

    matched_rows = latest_snapshot_df[
        (latest_snapshot_df["location"].astype(str).str.strip() == location)
        & (
            latest_snapshot_df["material_code"].astype(str).str.strip()
            == material_code
        )
    ]

    if matched_rows.empty:
        return None

    row = matched_rows.iloc[0]

    return inventory_row_to_position(row)


def build_inventory_positions_as_of(
    inventory_df: pd.DataFrame,
    as_of_timestamp: datetime | pd.Timestamp,
) -> list[InventoryPosition]:
    """
    Builds InventoryPosition domain objects for all latest inventory
    snapshots available on or before the given timestamp.

    This is useful for generating candidate sources during orchestration.
    """

    latest_snapshot_df = get_latest_inventory_snapshot_as_of(
        inventory_df=inventory_df,
        as_of_timestamp=as_of_timestamp,
    )

    if latest_snapshot_df.empty:
        return []

    positions = [
        inventory_row_to_position(row)
        for _, row in latest_snapshot_df.iterrows()
    ]

    return positions