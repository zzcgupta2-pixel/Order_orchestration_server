from __future__ import annotations
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import pandas as pd
from order_orchestration.domain.git import GitShipment
from order_orchestration.domain.route import Route
from order_orchestration.domain.enums import OrderType, TransportMode
# from order_orchestration.domain.enums import OrderType
from order_orchestration.domain.inventory import InventoryPosition
from order_orchestration.domain.order import OrderLine

def safe_optional_int(value) -> int | None:
    """
    Converts values such as 11, 11.0, or '11' into an integer.

    Returns None for blank or invalid values.
    """

    if value is None:
        return None

    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass

    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None
    
def safe_decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    """
    Safely converts a value into Decimal.

    If conversion fails or value is missing, returns default.
    """

    if value is None:
        return default

    if pd.isna(value):
        return default

    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return default


def safe_string(value: Any, default: str = "") -> str:
    """
    Safely converts a value into stripped string.
    """

    if value is None:
        return default

    if pd.isna(value):
        return default

    return str(value).strip()


def safe_bool_from_flag(value: Any) -> bool:
    """
    Converts common numeric/string flags into boolean.

    Supported true values:
    - 1
    - "1"
    - "Y"
    - "YES"
    - "TRUE"
    - "CB"
    """

    normalized_value = safe_string(value).upper()

    return normalized_value in {"1", "Y", "YES", "TRUE", "CB"}


def safe_datetime(value: Any) -> datetime:
    """
    Converts value into timezone-aware datetime.

    Raises ValueError if conversion fails.
    """

    parsed_datetime = pd.to_datetime(
        value,
        errors="coerce",
        utc=True,
    )

    if pd.isna(parsed_datetime):
        raise ValueError(f"Could not parse datetime value: {value}")

    return parsed_datetime.to_pydatetime()


def normalize_order_type(order_category: Any) -> OrderType:
    """
    Converts cleaned order category into OrderType enum.

    Supported values:
    - VOR
    - Replenishment
    - REPLENISHMENT
    - Push
    - PUSH
    """

    normalized_value = safe_string(order_category).upper()

    if normalized_value == "VOR":
        return OrderType.VOR

    if normalized_value == "ACC":
        return OrderType.ACC

    if normalized_value == "REPLENISHMENT":
        return OrderType.REPLENISHMENT

    if normalized_value == "PUSH":
        return OrderType.PUSH

    raise ValueError(f"Unsupported order category: {order_category}")


def orders_dataframe_to_order_lines(
    orders_df: pd.DataFrame,
    order_id_column: str | None = None,
    line_id_column: str | None = None,
) -> list:
    """
    Converts cleaned open-order/master dataframe into OrderLine domain objects.

    Expected dataframe columns:
    - order_category
    - plant
    - material_code
    - customer_code
    - order_create_datetime
    - open_order_qty
    - is_credit_blocked

    Optional:
    - sales_order
    - sales_order_line

    If order_id_column or line_id_column are not supplied or not present,
    deterministic fallback IDs are generated using dataframe index.
    """

    required_columns = [
        "order_category",
        "plant",
        "material_code",
        "customer_code",
        "order_create_datetime",
        "open_order_qty",
        "is_credit_blocked",
    ]

    missing_columns = [
        column for column in required_columns if column not in orders_df.columns
    ]

    if missing_columns:
        raise ValueError(f"Orders dataframe missing columns: {missing_columns}")

    order_lines: list[OrderLine] = []

    for row_index, row in orders_df.iterrows():
        if order_id_column and order_id_column in orders_df.columns:
            order_id = safe_string(row[order_id_column])
        elif "sales_order" in orders_df.columns:
            order_id = safe_string(row["sales_order"])
        else:
            order_id = f"ROW_{row_index}"

        if line_id_column and line_id_column in orders_df.columns:
            line_id = safe_string(row[line_id_column])
        elif "sales_order_line" in orders_df.columns:
            line_id = safe_string(row["sales_order_line"])
        else:
            line_id = "1"

        requested_quantity = safe_decimal(row["open_order_qty"])

        raw_dealer_norms = (row.get("dealer_norms",None,))

        dealer_norms = None

        if (
            raw_dealer_norms is not None
            and pd.notna(raw_dealer_norms)
        ):
            try:
                dealer_norms = Decimal(
                    str(raw_dealer_norms).strip()
                )
            except (
                ValueError,
                TypeError,
                ArithmeticError,
            ):
                dealer_norms = None
                
        order_line = OrderLine(
            order_id=order_id,
            line_id=line_id,
            order_creation_timestamp=safe_datetime(row["order_create_datetime"]),
            order_type=normalize_order_type(row["order_category"]),
            material_code=safe_string(row["material_code"]),
            dealer_code=safe_string(row["customer_code"]),
            parent_rdc=safe_string(row["parent_plant"]),
            requested_quantity=requested_quantity,
            remaining_quantity=requested_quantity,
            is_credit_blocked=safe_bool_from_flag(row["is_credit_blocked"]),
            colour_code=safe_optional_int(
                row["ean_upc"]
                if "ean_upc" in orders_df.columns
                else row.get("colour_code")
            ),
            raw_order_type=(
                str(row["raw_order_type"]).strip()
                if (
                    "raw_order_type" in row.index
                    and pd.notna(row["raw_order_type"])
                    and str(row["raw_order_type"]).strip()
                )
                else None
            ),
            dealer_norms=dealer_norms,

        )

        order_lines.append(order_line)

    return order_lines


def inventory_dataframe_to_positions(
    inventory_df: pd.DataFrame,
    snapshot_timestamp_column: str | None = None,
) -> list:
    """
    Converts cleaned inventory dataframe into InventoryPosition domain objects.

    Expected normalized columns:
    - location
    - material_code
    - actual_stock
    - allocated_quantity
    - pending_so_quantity
    - safety_stock

    Optional:
    - snapshot_timestamp
    - ageing_quantity
    - ageing_quantity_gt_1yr

    If snapshot_timestamp_column is not available, a ValueError is raised.
    This prevents accidental use of inventory without time context.
    """

    required_columns = [
        "location",
        "material_code",
        "actual_stock",
        "allocated_quantity",
        "pending_so_quantity",
        "safety_stock",
    ]

    missing_columns = [
        column for column in required_columns if column not in inventory_df.columns
    ]

    if missing_columns:
        raise ValueError(f"Inventory dataframe missing columns: {missing_columns}")

    if snapshot_timestamp_column is None:
        snapshot_timestamp_column = "snapshot_timestamp"

    if snapshot_timestamp_column not in inventory_df.columns:
        raise ValueError(
            f"Inventory dataframe missing snapshot timestamp column: "
            f"{snapshot_timestamp_column}"
        )

    positions: list[InventoryPosition] = []

    for _, row in inventory_df.iterrows():
        position = InventoryPosition(
            snapshot_timestamp=safe_datetime(row[snapshot_timestamp_column]),
            location=safe_string(row["location"]),
            material_code=safe_string(row["material_code"]),
            actual_stock=safe_decimal(row["actual_stock"]),
            allocated_quantity=safe_decimal(row["allocated_quantity"]),
            pending_so_quantity=safe_decimal(row["pending_so_quantity"]),
            safety_stock=safe_decimal(row["safety_stock"]),
            ageing_quantity=safe_decimal(row.get("ageing_quantity", Decimal("0"))),
            ageing_quantity_gt_1yr=safe_decimal(
                row.get("ageing_quantity_gt_1yr", Decimal("0"))
            ),
        )

        positions.append(position)

    return positions


def prepare_inventory_snapshot_from_master(
    master_df: pd.DataFrame,
    snapshot_timestamp: datetime | pd.Timestamp,
) -> pd.DataFrame:
    """
    Prepares inventory snapshot dataframe from your current final master dataframe.

    This is useful because your current master has columns such as:
    - plant
    - material_code
    - total_saleable_inventory_qty
    - safety_stock
    - ageing_stock_qty
    - ageing_stock_gt_1yr

    Output columns are normalized for inventory_dataframe_to_positions().
    """

    required_columns = [
        "plant",
        "material_code",
        "total_saleable_inventory_qty",
        "safety_stock",
    ]

    missing_columns = [
        column for column in required_columns if column not in master_df.columns
    ]

    if missing_columns:
        raise ValueError(f"Master dataframe missing columns: {missing_columns}")

    inventory_snapshot_df = master_df.copy()

    inventory_snapshot_df = inventory_snapshot_df.rename(
        columns={
            "plant": "location",
            "total_saleable_inventory_qty": "actual_stock",
            "ageing_stock_qty": "ageing_quantity",
            "ageing_stock_gt_1yr": "ageing_quantity_gt_1yr",
        }
    )

    inventory_snapshot_df["snapshot_timestamp"] = pd.to_datetime(
        snapshot_timestamp,
        utc=True,
    )

    if "allocated_quantity" not in inventory_snapshot_df.columns:
        inventory_snapshot_df["allocated_quantity"] = 0

    if "pending_so_quantity" not in inventory_snapshot_df.columns:
        inventory_snapshot_df["pending_so_quantity"] = 0

    if "ageing_quantity" not in inventory_snapshot_df.columns:
        inventory_snapshot_df["ageing_quantity"] = 0

    if "ageing_quantity_gt_1yr" not in inventory_snapshot_df.columns:
        inventory_snapshot_df["ageing_quantity_gt_1yr"] = 0

    final_columns = [
        "snapshot_timestamp",
        "location",
        "material_code",
        "actual_stock",
        "allocated_quantity",
        "pending_so_quantity",
        "safety_stock",
        "ageing_quantity",
        "ageing_quantity_gt_1yr",
    ]

    inventory_snapshot_df = inventory_snapshot_df[final_columns]

    inventory_snapshot_df = inventory_snapshot_df.drop_duplicates(
        subset=["snapshot_timestamp", "location", "material_code"],
        keep="first",
    )

    return inventory_snapshot_df

def git_dataframe_to_shipments(
    git_df: pd.DataFrame,
    expected_arrival_column: str | None = None,
    default_expected_arrival_datetime: datetime | pd.Timestamp | None = None,
    status_column: str | None = None,
    default_status: str = "IN_TRANSIT",
) -> list:
    """
    Converts cleaned GIT dataframe into GitShipment domain objects.

    Expected columns:
    - material_code
    - from_location
    - to_plant
    - git_qty

    Optional:
    - expected arrival column
    - status column

    Important:
    For VOR GIT threshold logic, expected arrival datetime is required.
    Therefore, either expected_arrival_column must be supplied or
    default_expected_arrival_datetime must be supplied.
    """

    required_columns = [
        "material_code",
        "from_location",
        "to_plant",
        "git_qty",
    ]

    missing_columns = [
        column for column in required_columns if column not in git_df.columns
    ]

    if missing_columns:
        raise ValueError(f"GIT dataframe missing columns: {missing_columns}")

    if expected_arrival_column is None and default_expected_arrival_datetime is None:
        raise ValueError(
            "GIT expected arrival datetime is required. "
            "Provide expected_arrival_column or default_expected_arrival_datetime."
        )

    if expected_arrival_column is not None and expected_arrival_column not in git_df.columns:
        raise ValueError(
            f"GIT dataframe missing expected arrival column: "
            f"{expected_arrival_column}"
        )

    if status_column is not None and status_column not in git_df.columns:
        raise ValueError(f"GIT dataframe missing status column: {status_column}")

    shipments: list[GitShipment] = []

    for _, row in git_df.iterrows():
        if expected_arrival_column is not None:
            expected_arrival_datetime = safe_datetime(row[expected_arrival_column])
        else:
            expected_arrival_datetime = safe_datetime(default_expected_arrival_datetime)

        if status_column is not None:
            status = safe_string(row[status_column], default=default_status)
        else:
            status = default_status

        shipment = GitShipment(
            material_code=safe_string(row["material_code"]),
            source_location=safe_string(row["from_location"]),
            destination_location=safe_string(row["to_plant"]),
            git_quantity=safe_decimal(row["git_qty"]),
            expected_arrival_datetime=expected_arrival_datetime,
            status=status,
        )

        shipments.append(shipment)

    return shipments


def _transport_mode_from_text(mode_text: str) -> TransportMode:
    """
    Converts logistics mode text into TransportMode enum.
    """

    normalized_mode = safe_string(mode_text).upper()

    if normalized_mode == "AIR":
        return TransportMode.AIR

    if normalized_mode == "SURFACE":
        return TransportMode.SURFACE

    if normalized_mode == "MILK_RUN":
        return TransportMode.MILK_RUN

    if normalized_mode == "PART_TRUCK_LOAD":
        return TransportMode.PART_TRUCK_LOAD

    if normalized_mode == "FULL_TRUCK_LOAD":
        return TransportMode.FULL_TRUCK_LOAD

    if normalized_mode == "COURIER_EXPRESS":
        return TransportMode.COURIER_EXPRESS

    raise ValueError(f"Unsupported transport mode: {mode_text}")


def logistics_dataframe_to_routes(
    logistics_df: pd.DataFrame,
    rdc_source_mapping: dict[str, str],
    effective_start_datetime: datetime | pd.Timestamp,
    dealer_column: str = "dealer_code",
    pickup_buffer_hours: int = 4,
    drop_buffer_hours: int = 4,
    mode_names: tuple[str, ...] = ("air", "surface"),
    applicable_order_types_by_mode: dict[str, tuple[OrderType, ...]] | None = None,
    connectivity_available_default: bool = True,
) -> list:
    """
    Converts cleaned wide logistics dataframe into Route domain objects.

    Example logistics columns:
    - dealer_code
    - vepdc_air
    - vepdc_surface
    - vepdc_air_rate
    - vepdc_surface_rate
    - lucknow_air
    - lucknow_surface
    - lucknow_air_rate
    - lucknow_surface_rate

    rdc_source_mapping example:
        {
            "vepdc": "1110",
            "lucknow": "1158",
            "raipur": "1159"
        }

    Rules:
    - Each positive SLA value creates a Route.
    - SLA is interpreted as fixed transit days.
    - Rate is used as transport_cost.
    - If rate column is missing or blank, cost defaults to 0.
    - Route applicability can be controlled by applicable_order_types_by_mode.
    """

    if dealer_column not in logistics_df.columns:
        raise ValueError(f"Logistics dataframe missing dealer column: {dealer_column}")

    if applicable_order_types_by_mode is None:
        applicable_order_types_by_mode = {
            "AIR": (OrderType.VOR, OrderType.ACC, OrderType.REPLENISHMENT, OrderType.PUSH),
            "SURFACE": (OrderType.VOR, OrderType.ACC, OrderType.REPLENISHMENT, OrderType.PUSH),
            "MILK_RUN": (OrderType.VOR, OrderType.ACC, OrderType.REPLENISHMENT, OrderType.PUSH),
            "PART_TRUCK_LOAD": (OrderType.VOR, OrderType.ACC, OrderType.REPLENISHMENT, OrderType.PUSH),
            "FULL_TRUCK_LOAD": (OrderType.VOR, OrderType.ACC, OrderType.REPLENISHMENT, OrderType.PUSH),
            "COURIER_EXPRESS": (OrderType.VOR, OrderType.ACC, OrderType.REPLENISHMENT, OrderType.PUSH),
        }

    routes: list[Route] = []

    effective_start = safe_datetime(effective_start_datetime)

    for _, row in logistics_df.iterrows():
        destination_location = safe_string(row[dealer_column])

        if destination_location == "":
                    continue
        
        # ---------------------------------------------------------
        # Parent Milk Run route
        # ---------------------------------------------------------
        # Business rule:
        # If milk_run_surface exists for the dealer and parent_plant is available,
        # create a MILK_RUN route from parent_plant to dealer.
                # ---------------------------------------------------------
        # Parent Milk Run route
        # ---------------------------------------------------------
        # milk_run_surface represents SLA days for Milk Run from parent plant
        # to dealer. This route is especially important for VOR parent
        # fulfilment.
        if (
            "milk_run_surface" in logistics_df.columns
            and "parent_plant" in logistics_df.columns
        ):
            milk_run_sla_days = safe_decimal(row["milk_run_surface"])
            parent_source_location = safe_string(row["parent_plant"])

            if milk_run_sla_days > Decimal("0") and parent_source_location != "":
                milk_run_route = Route(
                    source_location=parent_source_location,
                    destination_location=destination_location,
                    transport_mode=TransportMode.MILK_RUN,
                    standard_sla_days=int(milk_run_sla_days),
                    pickup_buffer_hours=pickup_buffer_hours,
                    drop_buffer_hours=drop_buffer_hours,
                    transport_cost=Decimal("0"),
                    connectivity_available=connectivity_available_default,
                    applicable_order_types=(
                        OrderType.VOR,
                        OrderType.ACC,
                        OrderType.REPLENISHMENT,
                        OrderType.PUSH,
                    ),
                    effective_start_datetime=effective_start,
                    effective_end_datetime=None,
                    route_type="PARENT_MILK_RUN",
                )

                routes.append(milk_run_route)

        

        for rdc_prefix, source_location in rdc_source_mapping.items():
            normalized_prefix = safe_string(rdc_prefix).lower()

            for mode_name in mode_names:
                normalized_mode = safe_string(mode_name).lower()

                sla_column = f"{normalized_prefix}_{normalized_mode}"
                rate_column = f"{normalized_prefix}_{normalized_mode}_rate"

                if sla_column not in logistics_df.columns:
                    continue

                sla_days = safe_decimal(row[sla_column])

                if sla_days <= Decimal("0"):
                    continue

                transport_cost = Decimal("0")

                if rate_column in logistics_df.columns:
                    transport_cost = safe_decimal(row[rate_column])

                transport_mode = _transport_mode_from_text(normalized_mode)

                applicable_order_types = applicable_order_types_by_mode.get(
                    transport_mode.value,
                    (OrderType.VOR, OrderType.ACC, OrderType.REPLENISHMENT, OrderType.PUSH),
                )

                route = Route(
                    source_location=safe_string(source_location),
                    destination_location=destination_location,
                    transport_mode=transport_mode,
                    standard_sla_days=int(sla_days),
                    pickup_buffer_hours=pickup_buffer_hours,
                    drop_buffer_hours=drop_buffer_hours,
                    transport_cost=transport_cost,
                    connectivity_available=connectivity_available_default,
                    applicable_order_types=applicable_order_types,
                    effective_start_datetime=effective_start,
                    effective_end_datetime=None,
                    route_type="SOURCE_TO_DEALER",
                )

                routes.append(route)

    return routes