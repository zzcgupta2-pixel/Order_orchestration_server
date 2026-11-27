from __future__ import annotations
from dataclasses import (
    asdict, 
    dataclass,
    replace,
)

from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd

from order_orchestration.calendar.location_calendar import resolve_decision_datetime
from order_orchestration.config import ConfigLoader
# from order_orchestration.data.adapters import (
#     git_dataframe_to_shipments,
#     inventory_dataframe_to_positions,
#     logistics_dataframe_to_routes,
#     orders_dataframe_to_order_lines,
# )
from order_orchestration.data.adapters import (
    inventory_dataframe_to_positions,
    logistics_dataframe_to_routes,
    orders_dataframe_to_order_lines,
)
from order_orchestration.data.rlt_resolver import build_rlt_lookup
from order_orchestration.domain.candidate import CandidateSource
from order_orchestration.domain.decision import Decision
from order_orchestration.domain.enums import DecisionType, ReasonCode, SourceType, TransportMode
from order_orchestration.domain.order import OrderLine
from order_orchestration.state.inventory_state import InventoryStateManager
from order_orchestration.workflows.push import process_push_order
from order_orchestration.workflows.vor import process_vor_order
from order_orchestration.workflows.replenishment import process_replenishment_order 

from order_orchestration.data.norms_resolver import (
    build_missing_norms_report,
    build_norms_lookup,
    merge_norms_into_inventory_master,
)

from order_orchestration.data.mad_resolver import (
    build_mad_lookup,
    build_missing_mad_report,
)

from order_orchestration.data.moq_resolver import (
    build_missing_moq_report,
    build_moq_lookup, 
    resolve_moq,
)

from order_orchestration.allocation.allocation_sorting import (
    build_replenishment_alternative_sort_key, 
)
 

from order_orchestration.data.moq_resolver import floor_to_moq

# from order_orchestration.allocation.moq_allocator import (
#     MOQAllocationResult,
#     allocate_parent_only_full_fill,
#     allocate_parent_then_multiple_alternatives,
#     allocate_push_parent_then_ageing_then_weighted,
#     allocate_vor_acc_parent_then_ranked_alternatives,
# )

from order_orchestration.allocation.moq_allocator import (
    MOQAllocationResult,
    allocate_parent_only_full_fill,
    allocate_push_parent_then_ageing_then_weighted,
    allocate_replenishment_parent_then_gated_weighted_alternatives,
    allocate_vor_acc_parent_then_ranked_alternatives,
)

from order_orchestration.state.git_state import (
    GitStateManager,
)
#
#  If your replenishment still lives in run_real_data_sample.py, we will call
# existing helper logic later. For now, this runner assumes you will expose
# process_replenishment_order() later.
# from order_orchestration.workflows.replenishment import process_replenishment_order


ALLOWED_TRANSPORT_MODES_CONFIG = {
    "VOR": ["MILK_RUN", "AIR", "COURIER_EXPRESS", "SURFACE"],
    "ACC": ["MILK_RUN", "AIR", "COURIER_EXPRESS", "SURFACE"],
    "REPLENISHMENT": ["MILK_RUN", "SURFACE", "PART_TRUCK_LOAD"],
    "PUSH": ["MILK_RUN", "SURFACE", "PART_TRUCK_LOAD", "FULL_TRUCK_LOAD"],
}


RDC_SOURCE_MAPPING = {
    "vepdc": "1110",
    "bangalore": "1153",
    "jhajjer": "1155",
    "kolkata": "1152",
    "ludhiana": "1161",
    "lucknow": "1158",
    "hyderabad": "1157",
    "coimbatore": "1156",
    "raipur": "1159",
    "guwahati": "1141",
}


LOCATION_CLUSTER_MAP = {
    "1110": "VEPDC",
    "1141": "EAST",
    "1152": "EAST",
    "1153": "SOUTH",
    "1155": "NORTH",
    "1156": "SOUTH",
    "1157": "SOUTH",
    "1158": "NORTH",
    "1159": "CENTRAL",
    "1161": "NORTH",
}


VEPDC_LOCATION_CODE = "1110"

DECISION_OUTPUT_COLUMNS = [
    # Order identification
    "order_id",
    # "line_id",
    "order_category",
    "colour_code",
    "order_create_datetime",
    "decision_timestamp",

    # Material and order context
    "material_code",
    "dealer_code",
    "dealer_norms",
    "parent_plant",
    "decision",

    # Selected source
    # "source_inventory_type",
    "selected_source",
    "selected_source_type",
    # "git_source_location",
    # "asn_number",
    "allocation_sequence",

    # Quantity
    "original_requested_quantity",
    "effective_requested_quantity",
    "moq_qty",
    "source_allocated_quantity",
    "source_git_reserved_quantity",
    "total_physical_allocated_quantity",
    "total_git_reserved_quantity",
    "total_fulfilled_quantity",
    "remaining_quantity",
    "remaining_quantity_owner",

    # Route and service
    "transport_mode",
    "source_sla_days",
    "source_rlt_days",
    "master_data_default_used",
    "transport_cost",
    "expected_dispatch",
    "expected_delivery",

    # GIT details
    "dispatch_datetime",
    "inbound_rlt_days",
    "expected_arrival_datetime",
    "arrival_days_from_decision",

    # Explanation
    "reason_codes",
    # "business_explanation",
]

CANDIDATE_AUDIT_OUTPUT_COLUMNS = [
    # Order context
    "order_id",
    # "line_id",
    "order_category",
    "colour_code",
    "order_create_datetime",
    "material_code",
    "dealer_code",
    "parent_plant",

    # Candidate
    "candidate_location",
    "candidate_source_type",
    # "candidate_eligible",

    # Quantity and inventory
    # "original_requested_quantity",
    "effective_requested_quantity",
    "norms",
    "mad",
    "calculated_safety_stock",
    "available_quantity",
    "eligible_quantity",
    "ageing_quantity",
    # "full_fill_capable",

    # Safety stock
 
   
    # "applied_safety_stock",
    # "safety_stock_protected",
    # "safety_stock_exempt_due_to_norms",

    # Route
    # "route_available",
    "selected_transport_mode",
    "configured_sla_days",
    "rlt_days",
    "master_data_default_used",
    "transport_cost",
    "expected_dispatch",
    "expected_delivery",

    # Scoring
    "weighted_score",
    "sla_score",
    "ageing_score",
    "rlt_score",
    "eligible_qty_score",
    "cost_score",
]


def normalize_raw_order_type(
    value,
) -> str:
    """
    Normalizes the original SAP order type.

    Examples:
        ZFMO
        ZMSO
    """

    if value is None:
        return ""

    normalized = str(value).strip().upper()

    if normalized in {
        "",
        "NAN",
        "NONE",
        "NULL",
        "<NA>",
    }:
        return ""

    return normalized

def make_datetimes_excel_safe(df: pd.DataFrame) -> pd.DataFrame:
    output_df = df.copy()

    for column in output_df.columns:
        output_df[column] = output_df[column].apply(
            lambda value: value.replace(tzinfo=None)
            if hasattr(value, "tzinfo") and value.tzinfo is not None
            else value
        )

    return output_df


def safe_decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    if value is None or pd.isna(value):
        return default

    try:
        return Decimal(str(value).strip())
    except Exception:
        return default


def build_allowable_quantity_lookup_from_file(
    allowable_qty_df: pd.DataFrame,
) -> dict:
    required_columns = ["material_code", "max_delivery_qty"]

    missing_columns = [
        column for column in required_columns
        if column not in allowable_qty_df.columns
    ]

    if missing_columns:
        raise ValueError(
            f"Allowable quantity dataframe missing columns: {missing_columns}"
        )

    allowable_data = allowable_qty_df.copy()

    allowable_data["material_code"] = (
        allowable_data["material_code"].astype(str).str.strip()
    )

    allowable_data["max_delivery_qty"] = pd.to_numeric(
        allowable_data["max_delivery_qty"],
        errors="coerce",
    ).fillna(0)

    lookup = {}

    has_dealer_column = "dealer_code" in allowable_data.columns

    if has_dealer_column:
        allowable_data["dealer_code"] = (
            allowable_data["dealer_code"].astype(str).str.strip()
        )

    for _, row in allowable_data.iterrows():
        material_code = str(row["material_code"]).strip()
        max_delivery_qty = safe_decimal(row["max_delivery_qty"])

        if has_dealer_column:
            dealer_code = str(row["dealer_code"]).strip()

            lookup[
                (
                    "DEALER_MATERIAL",
                    dealer_code,
                    material_code,
                )
            ] = max_delivery_qty

        lookup[
            (
                "MATERIAL",
                material_code,
            )
        ] = max_delivery_qty

    return lookup


def get_allowable_quantity_for_order(
    order_line: OrderLine,
    allowable_quantity_lookup: dict,
) -> Decimal | None:
    dealer_code = str(order_line.dealer_code).strip()
    material_code = str(order_line.material_code).strip()

    dealer_material_key = (
        "DEALER_MATERIAL",
        dealer_code,
        material_code,
    )

    material_key = (
        "MATERIAL",
        material_code,
    )

    if dealer_material_key in allowable_quantity_lookup:
        return allowable_quantity_lookup[dealer_material_key]

    if material_key in allowable_quantity_lookup:
        return allowable_quantity_lookup[material_key]

    return None

def normalize_output_code(
    value,
) -> str:
    normalized = str(value).strip().upper()

    if normalized.endswith(".0"):
        normalized = normalized[:-2]

    return normalized

def candidate_to_dict(
    order_line: OrderLine,
    candidate: CandidateSource,
    score_lookup: dict | None = None,
) -> dict:
    
    # candidate_key = (
    #     str(candidate.location).strip(),
    #     str(candidate.material_code).strip(),
    # )
    candidate_key = (
        normalize_output_code(
            candidate.location
        ),
        normalize_output_code(
            candidate.material_code
        ),
    )

    score_data = (
        score_lookup.get(candidate_key, {})
        if score_lookup is not None
        else {}
    )

    return {
        "order_id": order_line.order_id,
        "line_id": order_line.line_id,
        # "order_category": order_line.order_type.value,
        "order_category": order_line.raw_order_type,
        "order_create_datetime": order_line.order_creation_timestamp,
        "material_code": order_line.material_code,
        "dealer_code": order_line.dealer_code,
        "colour_code": order_line.colour_code,
        "parent_plant": order_line.parent_rdc,
        "candidate_location": candidate.location,
        "candidate_source_type": candidate.source_type.value,  
        "original_requested_quantity": order_line.requested_quantity,
        "effective_requested_quantity": candidate.requested_quantity,
        "available_quantity": candidate.available_quantity, 
        "norms": getattr(
            candidate,
            "norms",
            None,
        ),
        "norms_found": getattr(
            candidate,
            "norms_found",
            False,
        ),
        "safety_stock_exempt_due_to_norms": getattr(
            candidate,
            "safety_stock_exempt_due_to_norms",
            False,
        ),
        "mad": getattr(candidate, "mad", None),
        "mad_default_used": getattr(candidate, "mad_default_used", False), 
        "calculated_safety_stock": getattr(
            candidate,
            "calculated_safety_stock",
            None,
        ),
        "applied_safety_stock": candidate.safety_stock,
        "safety_stock_protected": getattr(
            candidate,
            "safety_stock_protected",
            False,
        ),
        "safety_stock_policy": getattr(
            candidate,
            "safety_stock_policy",
            None,
        ),
        "eligible_quantity": candidate.eligible_quantity, 
        "full_fill_capable": candidate.full_fill_capable,
        "ageing_quantity": candidate.ageing_quantity,
        "route_available": candidate.route_available,
        "selected_transport_mode": (
            candidate.selected_transport_mode.value
            if candidate.selected_transport_mode is not None
            else None
        ),
        "configured_sla_days": candidate.configured_sla_days,
        "rlt_days": getattr(candidate, "rlt_days", None),
        "transport_cost": candidate.transport_cost,
        "expected_dispatch": candidate.expected_dispatch,
        "expected_delivery": candidate.expected_delivery,
        "candidate_eligible": candidate.eligible,
        "weighted_score": score_data.get("total_score"),
        "sla_score": score_data.get("sla_score"),
        "ageing_score": score_data.get("ageing_score"),
        "rlt_score": score_data.get("rlt_score"),
        "eligible_qty_score": score_data.get(
            "eligible_quantity_score"
        ),
        "cost_score": score_data.get("cost_score"),
        "route_default_used": getattr(
            candidate,
            "route_default_used",
            False,
        ),

        "sla_default_used": getattr(
            candidate,
            "sla_default_used",
            False,
        ),

        "rlt_default_used": getattr(
            candidate,
            "rlt_default_used",
            False,
        ),

        "master_data_default_used": getattr(
            candidate,
            "master_data_default_used",
            False,
        ),
    }


def calculate_remaining_quantity_owner(
    order_line: OrderLine,
    allocated_quantity: Decimal,
    remaining_quantity: Decimal,
) -> str | None:
    if remaining_quantity > Decimal("0"):
        return order_line.parent_rdc

    if allocated_quantity == Decimal("0"):
        return order_line.parent_rdc

    return None


def build_business_explanation(
    order_line: OrderLine,
    selected_source: str | None,
    selected_source_type: str | None,
    allocated_quantity: Decimal,
    remaining_quantity: Decimal,
    # reason_codes: list[ReasonCode],
    reason_codes: list[ReasonCode | str],
    remaining_quantity_owner: str | None,
) -> str:
    reason_text = ",".join(
        reason_code_to_text(reason)
        for reason in reason_codes
    )

    if selected_source is None:
        return (
            f"Order {order_line.order_id}-{order_line.line_id} "
            f"({order_line.order_type.value}) for material {order_line.material_code} "
            f"could not be allocated. Requested quantity was "
            f"{order_line.requested_quantity}. Remaining quantity is "
            f"{remaining_quantity} at parent plant {remaining_quantity_owner}. "
            f"Reason codes: {reason_text}."
        )

    if remaining_quantity > Decimal("0"):
        return (
            f"Order {order_line.order_id}-{order_line.line_id} "
            f"({order_line.order_type.value}) for material {order_line.material_code} "
            f"was partially allocated from {selected_source} "
            f"({selected_source_type}). Allocated quantity is {allocated_quantity}. "
            f"Remaining quantity is {remaining_quantity} at parent plant "
            f"{remaining_quantity_owner}. Reason codes: {reason_text}."
        )

    return (
        f"Order {order_line.order_id}-{order_line.line_id} "
        f"({order_line.order_type.value}) for material {order_line.material_code} "
        f"was allocated from {selected_source} ({selected_source_type}). "
        f"Allocated quantity is {allocated_quantity}, remaining quantity is 0. "
        f"Reason codes: {reason_text}."
    )

# def build_push_multi_source_decision_rows(
#     order_line: OrderLine,
#     selection_result,
#     decision_timestamp: datetime,
#     evaluated_candidates: list[CandidateSource],
#     inventory_movements: list,
# ) -> list:
#     """
#     Builds one decision row per allocated source for Push multi-source ageing.

#     Order-level SLA/RLT is taken from the allocated source with maximum SLA days.
#     """

#     if not inventory_movements:
#         return [
#             build_decision_row(
#                 order_line=order_line,
#                 selection_result=selection_result,
#                 decision_timestamp=decision_timestamp,
#             )
#         ]

#     candidate_by_location = {
#         str(candidate.location).strip(): candidate
#         for candidate in evaluated_candidates
#     }

#     allocated_locations = [
#         str(movement.location).strip()
#         for movement in inventory_movements
#     ]

#     allocated_candidates = [
#         candidate_by_location[location]
#         for location in allocated_locations
#         if location in candidate_by_location
#     ]

#     if allocated_candidates:
#         worst_sla_candidate = sorted(
#             allocated_candidates,
#             key=lambda candidate: (
#                 candidate.configured_sla_days or 0,
#                 getattr(candidate, "rlt_days", 0) or 0,
#             ),
#             reverse=True,
#         )[0]

#         order_level_sla_days = worst_sla_candidate.configured_sla_days
#         order_level_rlt_days = getattr(worst_sla_candidate, "rlt_days", None)
#         order_level_sla_source = worst_sla_candidate.location
#     else:
#         order_level_sla_days = None
#         order_level_rlt_days = None
#         order_level_sla_source = None

#     rows: list[dict] = []

#     for movement in inventory_movements:
#         location = str(movement.location).strip()
#         candidate = candidate_by_location.get(location)

#         source_sla_days = (
#             candidate.configured_sla_days if candidate is not None else None
#         )

#         source_rlt_days = (
#             getattr(candidate, "rlt_days", None) if candidate is not None else None
#         )

#         source_transport_mode = (
#             candidate.selected_transport_mode.value
#             if candidate is not None and candidate.selected_transport_mode is not None
#             else None
#         )

#         source_transport_cost = (
#             candidate.transport_cost if candidate is not None else None
#         )

#         row = {
#             "order_id": order_line.order_id,
#             "line_id": order_line.line_id,
#             "order_category": order_line.order_type.value,
#             "priority_rank": None,
#             "order_create_datetime": order_line.order_creation_timestamp,
#             "decision_timestamp": decision_timestamp,
#             "material_code": order_line.material_code,
#             "dealer_code": order_line.dealer_code,
#             "parent_plant": order_line.parent_rdc,
#             "decision": selection_result.decision.value,
#             "selected_source": location,
#             "selected_source_type": "PUSH_AGEING_MULTI_SOURCE",
#             "requested_quantity": order_line.requested_quantity,
#             "allocated_quantity": movement.allocated_quantity,
#             "remaining_quantity": selection_result.remaining_quantity,
#             "remaining_quantity_owner": (
#                 order_line.parent_rdc
#                 if selection_result.remaining_quantity > Decimal("0")
#                 else None
#             ),
#             "transport_mode": source_transport_mode,
#             "expected_dispatch": (
#                 candidate.expected_dispatch if candidate is not None else None
#             ),
#             "expected_delivery": (
#                 candidate.expected_delivery if candidate is not None else None
#             ),
#             "configured_sla_days": source_sla_days,
#             # "rlt_days": source_rlt_days,
#             # "order_level_sla_days": order_level_sla_days,
#             # "order_level_rlt_days": order_level_rlt_days,
#             # "order_level_sla_source": order_level_sla_source,
#             "transport_cost": source_transport_cost,
#             # "first_fill_rate": (
#             #     selection_result.allocated_quantity / order_line.requested_quantity
#             #     if order_line.requested_quantity > Decimal("0")
#             #     else Decimal("0")
#             # ),
#             "reason_codes": ",".join(
#                 reason.value for reason in selection_result.reason_codes
#             ),
#             "business_explanation": (
#                 f"Push order {order_line.order_id}-{order_line.line_id} "
#                 f"was allocated from multiple ageing-stock locations. "
#                 f"This row represents allocation from {location}. "
#                 f"Allocated quantity from this source is {movement.allocated_quantity}. "
#                 f"Order-level SLA is based on slowest allocated source "
#                 f"{order_level_sla_source}."
#             ),
#             # "rule_version": "1.0",
#             # "configuration_version": "1.0",
#         }

#         rows.append(row)

#     return rows

# def build_decision_row(
#     order_line: OrderLine,
#     selection_result,
#     decision_timestamp: datetime,
# ) -> dict:
#     selected_candidate = selection_result.selected_candidate

#     is_push_multi_source = (
#         ReasonCode.PUSH_MULTI_SOURCE_AGEING_ALLOCATION
#         in selection_result.reason_codes
#     )

#     if is_push_multi_source:
#         selected_source = "MULTI_SOURCE"
#         selected_source_type = "PUSH_AGEING_MULTI_SOURCE"
#         transport_mode = None
#         expected_dispatch = None
#         expected_delivery = None
#         configured_sla_days = None
#         transport_cost = None
    
#     if selected_candidate is None:
#         selected_source = None
#         selected_source_type = None
#         transport_mode = None
#         expected_dispatch = None
#         expected_delivery = None
#         configured_sla_days = None
#         rlt_days = None
#         transport_cost = None
#     else:
#         selected_source = selected_candidate.location
#         selected_source_type = selected_candidate.source_type
#         transport_mode = selected_candidate.selected_transport_mode
#         expected_dispatch = selected_candidate.expected_dispatch
#         expected_delivery = selected_candidate.expected_delivery
#         configured_sla_days = selected_candidate.configured_sla_days
#         rlt_days = selected_candidate.rlt_days
#         transport_cost = selected_candidate.transport_cost

#     remaining_quantity_owner = calculate_remaining_quantity_owner(
#         order_line=order_line,
#         allocated_quantity=selection_result.allocated_quantity,
#         remaining_quantity=selection_result.remaining_quantity,
#     )

#     first_fill_rate = (
#         selection_result.allocated_quantity / order_line.requested_quantity
#         if order_line.requested_quantity > Decimal("0")
#         else Decimal("0")
#     )

#     explanation = build_business_explanation(
#         order_line=order_line,
#         selected_source=selected_source,
#         selected_source_type=(
#             selected_source_type.value if selected_source_type is not None else None
#         ),
#         allocated_quantity=selection_result.allocated_quantity,
#         remaining_quantity=selection_result.remaining_quantity,
#         reason_codes=selection_result.reason_codes,
#         remaining_quantity_owner=remaining_quantity_owner,
#     )

#     return {
#         "order_id": order_line.order_id,
#         "line_id": order_line.line_id,
#         "order_category": order_line.order_type.value,
#         "priority_rank": None,
#         "order_create_datetime": order_line.order_creation_timestamp,
#         "decision_timestamp": decision_timestamp,
#         "material_code": order_line.material_code,
#         "dealer_code": order_line.dealer_code,
#         "colour_code": order_line.colour_code,
#         "parent_plant": order_line.parent_rdc,
#         "decision": selection_result.decision.value,
#         "selected_source": selected_source,
#         "selected_source_type": (
#             selected_source_type.value
#             if hasattr(selected_source_type, "value")
#             else selected_source_type
#         ),
#         "original_requested_quantity": order_line.requested_quantity,
#         "effective_requested_quantity": allocation_order_line.requested_quantity,
#         "requested_quantity": order_line.requested_quantity,
#         "allocated_quantity": selection_result.allocated_quantity,
#         "remaining_quantity": selection_result.remaining_quantity,
#         "remaining_quantity_owner": remaining_quantity_owner,
#         "transport_mode": (
#             transport_mode.value if transport_mode is not None else None
#         ),
#         "expected_dispatch": expected_dispatch,
#         "expected_delivery": expected_delivery,
#         "configured_sla_days": configured_sla_days,
#         "rlt_days": rlt_days,
#         "transport_cost": transport_cost,
#         "first_fill_rate": first_fill_rate,
#         "reason_codes": ",".join(reason.value for reason in selection_result.reason_codes),
#         "business_explanation": explanation,
#         "rule_version": "1.0",
#         "configuration_version": "1.0",
#     }

# def build_moq_multi_source_decision_rows(
#     order_line: OrderLine,
#     allocation_order_line: OrderLine,
#     moq_result,
#     decision_timestamp: datetime,
#     priority_rank: int | None,
#     score_lookup: dict | None = None,
# ) -> list:

def reason_code_to_text(
    reason_code: ReasonCode | str,
) -> str:
    """
    Converts enum-based and string-based reason codes to text.
    """

    if isinstance(reason_code, ReasonCode):
        return reason_code.value

    return str(reason_code)

def build_moq_multi_source_decision_rows(
    order_line: OrderLine,
    allocation_order_line: OrderLine,
    moq_result,
    decision_timestamp: datetime,
    priority_rank: int | None,
    score_lookup: dict | None = None,
    decision_override: str | None = None,
) -> list:
    """
    Creates one decision row per contributing source.

    order_line:
        Original order line containing original open-order quantity.

    allocation_order_line:
        Quantity actually eligible for allocation.
        For VOR/ACC, this may be capped by allowable max quantity.
        For other order types, it normally equals the original order line.

    moq_result:
        Result from the MOQ allocation engine.

    For multi-source allocation:
        One row is created for each contributing location.

    For no allocation:
        One row is created with selected_source=None.
    """

    # Original open-order quantity
    original_requested_quantity = (
        order_line.requested_quantity
    )

    # Quantity considered by allocation logic.
    # For VOR/ACC, this may be lower due to allowable max quantity.
    effective_requested_quantity = (
        allocation_order_line.requested_quantity
    )

    # # Remaining quantity must be measured against the original order quantity.
    # final_remaining_quantity = max(
    #     original_requested_quantity
    #     - moq_result.total_allocated_quantity,
    #     Decimal("0"),
    # )

    total_git_reserved_quantity = getattr(
        moq_result,
        "total_git_reserved_quantity",
        Decimal("0"),
    )

    total_fulfilled_quantity = (
        moq_result.total_allocated_quantity
        + total_git_reserved_quantity
    )

    final_remaining_quantity = max(
        original_requested_quantity
        - total_fulfilled_quantity,
        Decimal("0"),
    )

    allocations = moq_result.allocations

    # reason_codes_text = ",".join(
    #     reason.value
    #     for reason in moq_result.reason_codes
    # )
    git_reservations = getattr(
        moq_result,
        "git_reservations",
        [],
    )

    has_physical_allocation = bool(
        allocations
    )

    has_git_reservation = bool(
        git_reservations
    )

    reason_codes_text = ",".join(
        reason_code_to_text(reason)
        for reason in moq_result.reason_codes
    )

    # ---------------------------------------------------------
    # No allocation case
    # ---------------------------------------------------------
    # if not allocations:
        # GIT-only fulfilment is written by
    # build_git_reservation_decision_rows().
    if (
        not has_physical_allocation
        and has_git_reservation
    ):
        return []

    # Genuine no-allocation case.
    if (
        not has_physical_allocation
        and not has_git_reservation
    ):
        return [
            {
                "order_id": order_line.order_id,
                "line_id": order_line.line_id,
                # "order_category": order_line.order_type.value,
                "order_category": order_line.raw_order_type,
                "priority_rank": priority_rank,
                "colour_code": order_line.colour_code,
                "order_create_datetime": (
                    order_line.order_creation_timestamp
                ),
                "decision_timestamp": decision_timestamp,
                "material_code": order_line.material_code,
                "dealer_code": order_line.dealer_code,
                "dealer_norms": (
                    order_line.dealer_norms
                ),
                "parent_plant": order_line.parent_rdc,
                # "decision": "NO_ELIGIBLE_STOCK",
                "decision": (
                    decision_override
                    if decision_override is not None
                    else "NO_ELIGIBLE_STOCK"
                ),
                "selected_source": None,
                "selected_source_type": None,
                "allocation_sequence": None,
                "original_requested_quantity": (
                    original_requested_quantity
                ),
                "effective_requested_quantity": (
                    effective_requested_quantity
                ),
                "moq_qty": moq_result.moq_qty,
                "moq_default_used": (
                    moq_result.moq_default_used
                ),
                "moq_eligible_quantity": (
                    moq_result.moq_eligible_quantity
                ),
                "moq_remainder_quantity": (
                    moq_result.moq_remainder_quantity
                ),
                "source_allocated_quantity": Decimal("0"),
                # "total_allocated_quantity": Decimal("0"),
                "total_allocated_quantity": (
                moq_result.total_allocated_quantity
                ),
                "total_physical_allocated_quantity": (
                    moq_result.total_allocated_quantity
                ),
                "total_git_reserved_quantity": (
                    total_git_reserved_quantity
                ),
                "total_fulfilled_quantity": (
                    total_fulfilled_quantity
                ),
                "remaining_quantity": (
                    final_remaining_quantity
                ),
                "remaining_quantity_owner": (
                    order_line.parent_rdc
                ),
                "source_sla_days": None,
                "source_rlt_days": None,
                "order_level_sla_days": None,
                "order_level_rlt_days": None,
                "order_level_sla_source": None,
                "transport_mode": None,
                "transport_cost": None,
                "expected_dispatch": None,
                "expected_delivery": None,
                "reason_codes": reason_codes_text,
                "business_explanation": (
                    (
                        f"Order {order_line.order_id}-"
                        f"{order_line.line_id} was not allocated because "
                        f"the dealer is credit blocked. Complete remaining "
                        f"quantity {final_remaining_quantity} is held at "
                        f"parent RDC {order_line.parent_rdc}."
                    )
                    if decision_override == "CREDIT_BLOCKED"
                    else (
                        f"Order {order_line.order_id}-"
                        f"{order_line.line_id} could not receive an "
                        f"MOQ-aligned allocation. Original requested "
                        f"quantity was {original_requested_quantity}. "
                        f"Effective allocation quantity was "
                        f"{effective_requested_quantity}. Remaining "
                        f"quantity {final_remaining_quantity} is held "
                        f"at parent RDC {order_line.parent_rdc}."
                    )
                ),
                # "business_explanation": (
                #     f"Order {order_line.order_id}-"
                #     f"{order_line.line_id} could not receive an "
                #     f"MOQ-aligned allocation. Original requested "
                #     f"quantity was {original_requested_quantity}. "
                #     f"Effective allocation quantity was "
                #     f"{effective_requested_quantity}. Remaining "
                #     f"quantity {final_remaining_quantity} is held "
                #     f"at parent RDC {order_line.parent_rdc}."
                # ),
                "rule_version": "1.0",
                "configuration_version": "1.0",
            }
        ]

    # ---------------------------------------------------------
    # Determine the slowest allocated source
    # ---------------------------------------------------------
    slowest_allocation = max(
        allocations,
        key=lambda allocation: (
            allocation.candidate.configured_sla_days
            if allocation.candidate.configured_sla_days
            is not None
            else 0,
            getattr(
                allocation.candidate,
                "rlt_days",
                0,
            )
            or 0,
        ),
    )

    slowest_candidate = slowest_allocation.candidate

    order_level_sla_days = (
        slowest_candidate.configured_sla_days
    )

    order_level_rlt_days = getattr(
        slowest_candidate,
        "rlt_days",
        None,
    )

    order_level_sla_source = (
        slowest_candidate.location
    )

    # decision_value = (
    #     "ALLOCATE"
    #     if moq_result.total_allocated_quantity > Decimal("0")
    #     else "NO_ELIGIBLE_STOCK"
    # )
    decision_value = (
        decision_override
        if decision_override is not None
        else (
            "ALLOCATE"
            if moq_result.total_allocated_quantity > Decimal("0")
            else "NO_ELIGIBLE_STOCK"
        )
    )

    rows: list[dict] = []

    # ---------------------------------------------------------
    # One output row per contributing source
    # ---------------------------------------------------------
    for allocation in allocations:
        candidate = allocation.candidate

        selected_source_type = (
            candidate.source_type.value
            if hasattr(candidate.source_type, "value")
            else str(candidate.source_type)
        )

        transport_mode = (
            candidate.selected_transport_mode.value
            if candidate.selected_transport_mode is not None
            else None
        )

        # candidate_key = (
        #     str(candidate.location).strip(),
        #     str(candidate.material_code).strip(),
        # )
        candidate_key = (
            normalize_output_code(
                candidate.location
            ),
            normalize_output_code(
                candidate.material_code
            ),
        )

        score_data = (
            score_lookup.get(candidate_key, {})
            if score_lookup is not None
            else {}
        )

        route_default_used = bool(
            getattr(
                candidate,
                "route_default_used",
                False,
            )
        )

        sla_default_used = bool(
            getattr(
                candidate,
                "sla_default_used",
                False,
            )
        )

        rlt_default_used = bool(
            getattr(
                candidate,
                "rlt_default_used",
                False,
            )
        )

        master_data_default_used = (
            route_default_used
            or sla_default_used
            or rlt_default_used
        )

        source_reason_codes = list(
            moq_result.reason_codes
        )

        if route_default_used:
            source_reason_codes.append(
                "DEFAULT_ROUTE_USED"
            )

        if sla_default_used:
            source_reason_codes.append(
                "DEFAULT_SLA_FIVE_DAYS_USED"
            )

        if rlt_default_used:
            source_reason_codes.append(
                "DEFAULT_RLT_FIVE_DAYS_USED"
            )

        source_reason_codes = list(
            dict.fromkeys(
                source_reason_codes
            )
        )

        rows.append(
            {
                "order_id": order_line.order_id,
                "line_id": order_line.line_id,
                "order_category": (
                    # order_line.order_type.value 
                    order_line.raw_order_type 
                ),
                "priority_rank": priority_rank,
                "colour_code": order_line.colour_code,
                "order_create_datetime": (
                    order_line.order_creation_timestamp
                ),
                "decision_timestamp": decision_timestamp,
                "material_code": order_line.material_code,
                "dealer_code": order_line.dealer_code,
                "dealer_norms": (
                    order_line.dealer_norms
                ),
                "parent_plant": order_line.parent_rdc,
                "decision": decision_value,
                "selected_source": candidate.location,
                "selected_source_type": (
                    selected_source_type
                ),
                "allocation_sequence": (
                    allocation.allocation_sequence
                ),
                "original_requested_quantity": (
                    original_requested_quantity
                ),
                "effective_requested_quantity": (
                    effective_requested_quantity
                ),
                "moq_qty": moq_result.moq_qty,
                "moq_default_used": (
                    moq_result.moq_default_used
                ),
                "moq_eligible_quantity": (
                    moq_result.moq_eligible_quantity
                ),
                "moq_remainder_quantity": (
                    moq_result.moq_remainder_quantity
                ),
                "source_allocated_quantity": (
                    allocation.allocated_quantity
                ),
                "total_allocated_quantity": (
                    moq_result.total_allocated_quantity
                ),
                "total_physical_allocated_quantity": (
                    moq_result.total_allocated_quantity
                ),
                "total_git_reserved_quantity": (
                    total_git_reserved_quantity
                ),
                "total_fulfilled_quantity": (
                    total_fulfilled_quantity
                ),
                "remaining_quantity": (
                    final_remaining_quantity
                ),
                "remaining_quantity_owner": (
                    order_line.parent_rdc
                    if final_remaining_quantity
                    > Decimal("0")
                    else None
                ),
                "source_sla_days": (
                    candidate.configured_sla_days
                ),
                "source_rlt_days": getattr(
                    candidate,
                    "rlt_days",
                    None,
                ),
                "order_level_sla_days": (
                    order_level_sla_days
                ),
                "order_level_rlt_days": (
                    order_level_rlt_days
                ),
                "order_level_sla_source": (
                    order_level_sla_source
                ),
                "route_default_used": (
                    route_default_used
                ),

                "sla_default_used": (
                    sla_default_used
                ),

                "rlt_default_used": (
                    rlt_default_used
                ),

                "master_data_default_used": (
                    master_data_default_used
                ),
                "transport_mode": transport_mode,
                "transport_cost": (
                    candidate.transport_cost
                ),
                "expected_dispatch": (
                    candidate.expected_dispatch
                ),
                "expected_delivery": (
                    candidate.expected_delivery
                ),
                "source_weighted_score": (
                    score_data.get("total_score")
                ),
                "reason_codes": reason_codes_text,
                # "reason_codes": ",".join(
                #     str(reason)
                #     for reason
                #     in source_reason_codes
                # ),
                "business_explanation": (
                    f"Order {order_line.order_id}-"
                    f"{order_line.line_id} was allocated from "
                    f"source {candidate.location}. This source "
                    f"allocated {allocation.allocated_quantity} "
                    f"units in MOQ multiple "
                    f"{moq_result.moq_qty}. Total allocated "
                    f"quantity is "
                    f"{moq_result.total_allocated_quantity}. "
                    f"Remaining quantity is "
                    f"{final_remaining_quantity}. "
                    f"Any remaining quantity is held at parent "
                    f"RDC {order_line.parent_rdc}. "
                    f"Order-level SLA is based on the slowest "
                    f"contributing source "
                    f"{order_level_sla_source}."
                ),
                "rule_version": "1.0",
                "configuration_version": "1.0",
            }
        )

    return rows

def get_enabled_categories(execution_config: dict)->list:
    execution_scope = execution_config.get("execution_scope", {})

    return [
        category
        for category, enabled in execution_scope.items()
        if enabled
    ]

def filter_valid_dealer_orders(
    order_df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Keeps only valid dealer orders before orchestration logic runs.

    Valid dealer:
        dealer/customer code starts with '1S'

    Excluded:
        - Export dealers starting with '1XS'
        - Non-Auto customers starting with '1E'
        - Dealer/customer codes containing only numbers
        - Blank or missing dealer codes
        - Any other code not starting with '1S'

    Returns:
        valid_orders_df
        excluded_orders_df
    """

    if "customer_code" not in order_df.columns:
        raise ValueError(
            "Open order dataframe must contain 'customer_code' "
            "for dealer eligibility filtering."
        )

    working_df = order_df.copy()

    working_df["customer_code"] = (
        working_df["customer_code"]
        .astype(str)
        .str.strip()
        .str.upper()
    )

    working_df["dealer_filter_reason"] = "VALID_DEALER"

    blank_mask = working_df["customer_code"].isin(
        ["", "NAN", "NONE"]
    )

    export_mask = working_df["customer_code"].str.startswith(
        "1XS",
        na=False,
    )

    non_auto_prefix_mask = working_df["customer_code"].str.startswith(
        "1E",
        na=False,
    )

    numeric_customer_mask = working_df["customer_code"].str.fullmatch(
        r"\d+",
        na=False,
    )

    valid_dealer_mask = working_df["customer_code"].str.startswith(
        "1S",
        na=False,
    )

    working_df.loc[
        blank_mask,
        "dealer_filter_reason",
    ] = "MISSING_DEALER_CODE"

    working_df.loc[
        export_mask,
        "dealer_filter_reason",
    ] = "EXPORT_DEALER_EXCLUDED"

    working_df.loc[
        non_auto_prefix_mask,
        "dealer_filter_reason",
    ] = "NON_AUTO_DEALER_EXCLUDED"

    working_df.loc[
        numeric_customer_mask,
        "dealer_filter_reason",
    ] = "NUMERIC_CUSTOMER_EXCLUDED"

    other_invalid_mask = (
        ~valid_dealer_mask
        & ~blank_mask
        & ~export_mask
        & ~non_auto_prefix_mask
        & ~numeric_customer_mask
    )

    working_df.loc[
        other_invalid_mask,
        "dealer_filter_reason",
    ] = "INVALID_DEALER_CODE_EXCLUDED"

    valid_orders_df = working_df[
        valid_dealer_mask
    ].copy()

    excluded_orders_df = working_df[
        ~valid_dealer_mask
    ].copy()

    valid_orders_df = valid_orders_df.drop(
        columns=["dealer_filter_reason"],
        errors="ignore",
    )

    return valid_orders_df, excluded_orders_df

def prepare_order_dataframe(
    final_df: pd.DataFrame,
    execution_config: dict,
) -> pd.DataFrame:
    enabled_categories = get_enabled_categories(execution_config)

    priority_map = execution_config.get(
        "execution_priority",
        {
            "VOR": 1,
            "ACC": 2,
            "REPLENISHMENT": 3,
            "PUSH": 4,
        },
    )

    order_df = final_df.copy()

    order_df["order_category_upper"] = (
        order_df["order_category"].astype(str).str.upper()
    )

    enabled_categories_upper = [
        str(category).upper()
        for category in enabled_categories
    ]

    order_df = order_df[
        order_df["order_category_upper"].isin(enabled_categories_upper)
    ].copy()

    order_df["execution_priority"] = (
        order_df["order_category_upper"].map(priority_map)
    )

    order_df = order_df.sort_values(
        by=[
            "execution_priority",
            "order_create_datetime",
        ],
        ascending=[True, True],
    )

    return order_df

# def build_git_reservation_decision_rows(
#     order_line: OrderLine,
#     allocation_order_line: OrderLine,
#     moq_result: MOQAllocationResult,
#     decision_timestamp: datetime,
#     priority_rank: int | None,
# ) -> list:
#     """
#     Creates one decision row for every GIT reservation.
#     """

#     git_reservations = getattr(
#         moq_result,
#         "git_reservations",
#         [],
#     )

#     if not git_reservations:
#         return []

#     original_requested_quantity = (
#         order_line.requested_quantity
#     )

#     total_git_reserved_quantity = getattr(
#         moq_result,
#         "total_git_reserved_quantity",
#         Decimal("0"),
#     )

#     total_fulfilled_quantity = (
#         moq_result.total_allocated_quantity
#         + total_git_reserved_quantity
#     )

#     final_remaining_quantity = max(
#         original_requested_quantity
#         - total_fulfilled_quantity,
#         Decimal("0"),
#     )

#     rows: list[dict] = []

#     starting_sequence = (
#         len(moq_result.allocations) + 1
#     )

#     for index, movement in enumerate(
#         git_reservations,
#         start=starting_sequence,
#     ):
#         rows.append(
#             {
#                 "order_id": order_line.order_id,
#                 "line_id": order_line.line_id,
#                 "order_category": (
#                     order_line.order_type.value
#                 ),
#                 "priority_rank": priority_rank,
#                 "colour_code": (
#                     order_line.colour_code
#                 ),
#                 "order_create_datetime": (
#                     order_line
#                     .order_creation_timestamp
#                 ),
#                 "decision_timestamp": (
#                     decision_timestamp
#                 ),
#                 "material_code": (
#                     order_line.material_code
#                 ),
#                 "dealer_code": (
#                     order_line.dealer_code
#                 ),
#                 "parent_plant": (
#                     order_line.parent_rdc
#                 ),
#                 "decision": (
#                     "DEFERRED_GIT_ALLOCATION"
#                 ),
#                 "source_inventory_type": "GIT",
#                 "selected_source": (
#                     movement
#                     .destination_location
#                 ),
#                 "selected_source_type": (
#                     "PARENT_GIT"
#                 ),
#                 "git_source_location": (
#                     movement.source_location
#                 ),
#                 "asn_number": (
#                     movement.asn_number
#                 ),
#                 "allocation_sequence": index,
#                 "original_requested_quantity": (
#                     original_requested_quantity
#                 ),
#                 "effective_requested_quantity": (
#                     allocation_order_line
#                     .requested_quantity
#                 ),
#                 "moq_qty": (
#                     moq_result.moq_qty
#                 ),
#                 "source_allocated_quantity": (
#                     Decimal("0")
#                 ),
#                 "source_git_reserved_quantity": (
#                     movement.reserved_quantity
#                 ),
#                 "total_physical_allocated_quantity": (
#                     moq_result
#                     .total_allocated_quantity
#                 ),
#                 "total_git_reserved_quantity": (
#                     total_git_reserved_quantity
#                 ),
#                 "total_fulfilled_quantity": (
#                     total_fulfilled_quantity
#                 ),
#                 "remaining_quantity": (
#                     final_remaining_quantity
#                 ),
#                 "remaining_quantity_owner": (
#                     order_line.parent_rdc
#                     if final_remaining_quantity
#                     > Decimal("0")
#                     else None
#                 ),
#                 "dispatch_datetime": (
#                     movement.dispatch_datetime
#                 ),
#                 "expected_arrival_datetime": (
#                     movement
#                     .expected_arrival_datetime
#                 ),
#                 "inbound_rlt_days": (
#                     movement.inbound_rlt_days
#                 ),
#                 "arrival_days_from_decision": (
#                     movement
#                     .arrival_days_from_decision
#                 ),
#                 "reason_codes": (
#                     movement.reason_code
#                 ),
#                 "business_explanation": (
#                     f"Reserved "
#                     f"{movement.reserved_quantity} "
#                     f"units from GIT ASN "
#                     f"{movement.asn_number}. "
#                     f"The ASN is expected at parent "
#                     f"RDC "
#                     f"{movement.destination_location} "
#                     f"on "
#                     f"{movement.expected_arrival_datetime}. "
#                     f"This is a deferred allocation."
#                 ),
#                 "rule_version": "1.0",
#                 "configuration_version": "1.0",
#             }
#         )

#     return rows
# def build_git_reservation_decision_rows(
#     order_line: OrderLine,
#     allocation_order_line: OrderLine,
#     moq_result: MOQAllocationResult,
#     decision_timestamp: datetime,
#     priority_rank: int | None,
#     evaluated_candidates: list[CandidateSource],
# ) -> list[dict]:
#     """
#     Creates one decision row for every GIT reservation.

#     Date flow:
#         Supplier dispatch
#         + suppliernbound RLT
#         = expected arrival at parent RDC

#         Expected arrival at parent RDC
#         + 1 calendar-day processing buffer
#         = expected dispatch from parent RDC

#         Expected dispatch from parent RDC
#         + selected parent-to-customer transport-mode SLA
#         = expected delivery to customer

#     The parent-to-customer route values come from the evaluated
#     parent RDC candidate:
#         - configured_sla_days
#         - selected_transport_mode
#         - transport_cost
#     """

#     git_reservations = getattr(
#         moq_result,
#         "git_reservations",
#         [],
#     )

#     if not git_reservations:
#         return []

#     # ---------------------------------------------------------
#     # Find the evaluated parent RDC candidate
#     # ---------------------------------------------------------
#     parent_location = str(
#         order_line.parent_rdc
#     ).strip()

#     parent_candidate = next(
#         (
#             candidate
#             for candidate in evaluated_candidates
#             if (
#                 candidate.source_type
#                 == SourceType.PARENT_RDC
#             )
#             or (
#                 str(candidate.location).strip()
#                 == parent_location
#             )
#         ),
#         None,
#     )

#     # ---------------------------------------------------------
#     # Read parent-to-customer logistics values
#     # ---------------------------------------------------------
#     parent_sla_days: int | None = None
#     parent_transport_mode: str | None = None
#     parent_transport_cost = None

#     if parent_candidate is not None:
#         raw_parent_sla = getattr(
#             parent_candidate,
#             "configured_sla_days",
#             None,
#         )

#         if raw_parent_sla is not None:
#             try:
#                 parent_sla_days = max(
#                     int(raw_parent_sla),
#                     0,
#                 )
#             except (
#                 TypeError,
#                 ValueError,
#             ):
#                 parent_sla_days = None

#         selected_transport_mode = getattr(
#             parent_candidate,
#             "selected_transport_mode",
#             None,
#         )

#         if selected_transport_mode is not None:
#             parent_transport_mode = (
#                 selected_transport_mode.value
#                 if hasattr(
#                     selected_transport_mode,
#                     "value",
#                 )
#                 else str(selected_transport_mode)
#             )

#         parent_transport_cost = getattr(
#             parent_candidate,
#             "transport_cost",
#             None,
#         )

#     # ---------------------------------------------------------
#     # Order-level quantities
#     # ---------------------------------------------------------
#     original_requested_quantity = (
#         order_line.requested_quantity
#     )

#     total_git_reserved_quantity = getattr(
#         moq_result,
#         "total_git_reserved_quantity",
#         Decimal("0"),
#     )

#     total_physical_allocated_quantity = (
#         moq_result.total_allocated_quantity
#     )

#     total_fulfilled_quantity = (
#         total_physical_allocated_quantity
#         + total_git_reserved_quantity
#     )

#     final_remaining_quantity = max(
#         original_requested_quantity
#         - total_fulfilled_quantity,
#         Decimal("0"),
#     )

#     rows: list[dict] = []

#     starting_sequence = (
#         len(moq_result.allocations) + 1
#     )

#     # ---------------------------------------------------------
#     # Create one decision row for each reserved ASN
#     # ---------------------------------------------------------
#     for index, movement in enumerate(
#         git_reservations,
#         start=starting_sequence,
#     ):
#         # GIT arrival date at the parent RDC.
#         expected_arrival_at_parent = (
#             movement.expected_arrival_datetime
#         )

#         # Add the fixed processing buffer at the parent RDC.
#         expected_dispatch = (
#             expected_arrival_at_parent
#             + timedelta(days=1)
#             if expected_arrival_at_parent
#             is not None
#             else None
#         )

#         # Add the SLA of the selected parent-to-customer
#         # transport route.
#         expected_delivery = (
#             expected_dispatch
#             + timedelta(days=parent_sla_days)
#             if (
#                 expected_dispatch is not None
#                 and parent_sla_days is not None
#             )
#             else None
#         )

#         movement_reason_code = (
#             movement.reason_code
#         )

#         output_reason_codes = [
#             str(movement_reason_code)
#         ]

#         if parent_candidate is None:
#             output_reason_codes.append(
#                 "PARENT_ROUTE_CANDIDATE_NOT_FOUND"
#             )

#         elif parent_sla_days is None:
#             output_reason_codes.append(
#                 "PARENT_TO_CUSTOMER_SLA_NOT_FOUND"
#             )

#         if parent_transport_mode is None:
#             output_reason_codes.append(
#                 "PARENT_TRANSPORT_MODE_NOT_FOUND"
#             )

#         reason_codes_text = ",".join(
#             dict.fromkeys(
#                 output_reason_codes
#             )
#         )

#         rows.append(
#             {
#                 "order_id": order_line.order_id,
#                 "line_id": order_line.line_id,
#                 "order_category": (
#                     # order_line.order_type.value
#                     order_line.raw_order_type

#                 ),
#                 "priority_rank": priority_rank,
#                 "colour_code": (
#                     order_line.colour_code
#                 ),
#                 "order_create_datetime": (
#                     order_line
#                     .order_creation_timestamp
#                 ),
#                 "decision_timestamp": (
#                     decision_timestamp
#                 ),
#                 "material_code": (
#                     order_line.material_code
#                 ),
#                 "dealer_code": (
#                     order_line.dealer_code
#                 ),
#                 "parent_plant": (
#                     order_line.parent_rdc
#                 ),
#                 "decision": (
#                     "DEFERRED_GIT_ALLOCATION"
#                 ),
#                 "source_inventory_type": "GIT",
#                 "selected_source": (
#                     movement.destination_location
#                 ),
#                 "selected_source_type": (
#                     "PARENT_GIT"
#                 ),
#                 "git_source_location": (
#                     movement.source_location
#                 ),
#                 "asn_number": (
#                     movement.asn_number
#                 ),
#                 "allocation_sequence": index,

#                 # ---------------------------------------------
#                 # Quantity fields
#                 # ---------------------------------------------
#                 "original_requested_quantity": (
#                     original_requested_quantity
#                 ),
#                 "effective_requested_quantity": (
#                     allocation_order_line
#                     .requested_quantity
#                 ),
#                 "moq_qty": (
#                     moq_result.moq_qty
#                 ),
#                 "source_allocated_quantity": (
#                     Decimal("0")
#                 ),
#                 "source_git_reserved_quantity": (
#                     movement.reserved_quantity
#                 ),
#                 "total_allocated_quantity": (
#                     total_physical_allocated_quantity
#                 ),
#                 "total_physical_allocated_quantity": (
#                     total_physical_allocated_quantity
#                 ),
#                 "total_git_reserved_quantity": (
#                     total_git_reserved_quantity
#                 ),
#                 "total_fulfilled_quantity": (
#                     total_fulfilled_quantity
#                 ),
#                 "remaining_quantity": (
#                     final_remaining_quantity
#                 ),
#                 "remaining_quantity_owner": (
#                     order_line.parent_rdc
#                     if final_remaining_quantity
#                     > Decimal("0")
#                     else None
#                 ),

#                 # ---------------------------------------------
#                 # Supplier-to-parent GIT segment
#                 # ---------------------------------------------
#                 "dispatch_datetime": (
#                     movement.dispatch_datetime
#                 ),
#                 "inbound_rlt_days": (
#                     movement.inbound_rlt_days
#                 ),
#                 "expected_arrival_datetime": (
#                     expected_arrival_at_parent
#                 ),
#                 "arrival_days_from_decision": (
#                     movement
#                     .arrival_days_from_decision
#                 ),

#                 # ---------------------------------------------
#                 # Parent processing and customer delivery
#                 # ---------------------------------------------
#                 "parent_processing_buffer_days": 1,
#                 "expected_dispatch": (
#                     expected_dispatch
#                 ),
#                 "source_sla_days": (
#                     parent_sla_days
#                 ),
#                 "expected_delivery": (
#                     expected_delivery
#                 ),
#                 "transport_mode": (
#                     parent_transport_mode
#                 ),
#                 "transport_cost": (
#                     parent_transport_cost
#                 ),

#                 # Parent-to-customer delivery uses SLA, not RLT.
#                 "source_rlt_days": None,

#                 # ---------------------------------------------
#                 # Audit explanation
#                 # ---------------------------------------------
#                 "reason_codes": (
#                     reason_codes_text
#                 ),
#                 # "business_explanation": (
#                 #     f"Reserved "
#                 #     f"{movement.reserved_quantity} "
#                 #     f"units from GIT ASN "
#                 #     f"{movement.asn_number}. "
#                 #     f"The ASN was dispatched by source "
#                 #     f"{movement.source_location} on "
#                 #     f"{movement.dispatch_datetime} and is "
#                 #     f"expected to arrive at parent RDC "
#                 #     f"{movement.destination_location} on "
#                 #     f"{expected_arrival_at_parent}. "
#                 #     f"After a one-day processing buffer, "
#                 #     f"expected dispatch from the parent RDC "
#                 #     f"is {expected_dispatch}. "
#                 #     f"The selected parent-to-customer "
#                 #     f"transport mode is "
#                 #     f"{parent_transport_mode}, with SLA "
#                 #     f"{parent_sla_days} days and transport "
#                 #     f"cost {parent_transport_cost}. "
#                 #     f"Expected delivery to the customer is "
#                 #     f"{expected_delivery}."
#                 # ),
#                 # "rule_version": "1.0",
#                 # "configuration_version": "1.0",
#             }
#         )

#     return rows


def build_git_reservation_decision_rows(
    order_line: OrderLine,
    allocation_order_line: OrderLine,
    moq_result: MOQAllocationResult,
    decision_timestamp: datetime,
    priority_rank: int | None,
    evaluated_candidates: list[CandidateSource],
) -> list:
    """
    Creates one decision row for every GIT reservation.

    Inbound:
        supplier dispatch + inbound RLT
        = arrival at parent RDC

    Parent processing:
        arrival at parent + 1 day
        = expected parent dispatch

    Customer delivery:
        expected parent dispatch + selected logistics SLA
        = expected customer delivery
    """

    git_reservations = getattr(
        moq_result,
        "git_reservations",
        [],
    )

    if not git_reservations:
        return []

    parent_location = normalize_output_code(
        order_line.parent_rdc
    )

    # Prefer an actual PARENT_RDC candidate.
    parent_candidate = next(
        (
            candidate
            for candidate in evaluated_candidates
            if (
                candidate.source_type
                == SourceType.PARENT_RDC
                and normalize_output_code(
                    candidate.location
                )
                == parent_location
            )
        ),
        None,
    )

    # Defensive fallback if source type was not marked correctly.
    if parent_candidate is None:
        parent_candidate = next(
            (
                candidate
                for candidate in evaluated_candidates
                if normalize_output_code(
                    candidate.location
                )
                == parent_location
            ),
            None,
        )

    parent_sla_days: int | None = None
    parent_rlt_days: int | None = None
    parent_transport_mode: str | None = None
    parent_transport_cost = None

    if parent_candidate is not None:
        raw_sla = getattr(
            parent_candidate,
            "configured_sla_days",
            None,
        )

        if raw_sla is not None:
            try:
                parent_sla_days = int(
                    raw_sla
                )
            except (
                TypeError,
                ValueError,
            ):
                parent_sla_days = None

        raw_rlt = getattr(
            parent_candidate,
            "rlt_days",
            None,
        )

        if raw_rlt is not None:
            try:
                parent_rlt_days = int(
                    raw_rlt
                )
            except (
                TypeError,
                ValueError,
            ):
                parent_rlt_days = None

        selected_mode = getattr(
            parent_candidate,
            "selected_transport_mode",
            None,
        )

        if selected_mode is not None:
            parent_transport_mode = (
                selected_mode.value
                if hasattr(
                    selected_mode,
                    "value",
                )
                else str(selected_mode)
            )

        parent_transport_cost = getattr(
            parent_candidate,
            "transport_cost",
            None,
        )

    original_requested_quantity = (
        order_line.requested_quantity
    )

    total_physical_allocated_quantity = (
        moq_result.total_allocated_quantity
    )

    total_git_reserved_quantity = getattr(
        moq_result,
        "total_git_reserved_quantity",
        Decimal("0"),
    )

    total_fulfilled_quantity = (
        total_physical_allocated_quantity
        + total_git_reserved_quantity
    )

    final_remaining_quantity = max(
        original_requested_quantity
        - total_fulfilled_quantity,
        Decimal("0"),
    )

    rows: list[dict] = []

    starting_sequence = (
        len(moq_result.allocations) + 1
    )

    for index, movement in enumerate(
        git_reservations,
        start=starting_sequence,
    ):
        expected_arrival_at_parent = (
            movement.expected_arrival_datetime
        )

        expected_dispatch = (
            expected_arrival_at_parent
            + timedelta(days=1)
            if expected_arrival_at_parent
            is not None
            else None
        )

        # Customer delivery uses SLA of selected
        # parent-to-customer transport mode.
        expected_delivery = (
            expected_dispatch
            + timedelta(
                days=parent_sla_days
            )
            if (
                expected_dispatch is not None
                and parent_sla_days is not None
            )
            else None
        )

        output_reasons = [
            str(movement.reason_code)
        ]

        if parent_candidate is None:
            output_reasons.append(
                "PARENT_ROUTE_CANDIDATE_NOT_FOUND"
            )
        else:
            if parent_sla_days is None:
                output_reasons.append(
                    "PARENT_TO_CUSTOMER_SLA_NOT_FOUND"
                )

            if parent_transport_mode is None:
                output_reasons.append(
                    "PARENT_TRANSPORT_MODE_NOT_FOUND"
                )

            if parent_transport_cost is None:
                output_reasons.append(
                    "PARENT_TRANSPORT_COST_NOT_FOUND"
                )

        rows.append(
            {
                "order_id": order_line.order_id,
                "line_id": order_line.line_id,
                "order_category": (
                    getattr(
                        order_line,
                        "raw_order_type",
                        None,
                    )
                    or order_line.order_type.value
                ),
                "priority_rank": priority_rank,
                "colour_code": (
                    order_line.colour_code
                ),
                "order_create_datetime": (
                    order_line
                    .order_creation_timestamp
                ),
                "decision_timestamp": (
                    decision_timestamp
                ),
                "material_code": (
                    order_line.material_code
                ),
                "dealer_code": (
                    order_line.dealer_code
                ),
                "dealer_norms": (
                    order_line.dealer_norms
                ),
                "parent_plant": (
                    order_line.parent_rdc
                ),

                "decision": (
                    "DEFERRED_GIT_ALLOCATION"
                ),
                "source_inventory_type": "GIT",
                "selected_source": (
                    movement.destination_location
                ),
                "selected_source_type": (
                    "PARENT_GIT"
                ),
                "git_source_location": (
                    movement.source_location
                ),
                "asn_number": (
                    movement.asn_number
                ),
                "allocation_sequence": index,

                "original_requested_quantity": (
                    original_requested_quantity
                ),
                "effective_requested_quantity": (
                    allocation_order_line
                    .requested_quantity
                ),
                "moq_qty": (
                    moq_result.moq_qty
                ),
                "source_allocated_quantity": (
                    Decimal("0")
                ),
                "source_git_reserved_quantity": (
                    movement.reserved_quantity
                ),
                "total_allocated_quantity": (
                    total_physical_allocated_quantity
                ),
                "total_physical_allocated_quantity": (
                    total_physical_allocated_quantity
                ),
                "total_git_reserved_quantity": (
                    total_git_reserved_quantity
                ),
                "total_fulfilled_quantity": (
                    total_fulfilled_quantity
                ),
                "remaining_quantity": (
                    final_remaining_quantity
                ),
                "remaining_quantity_owner": (
                    order_line.parent_rdc
                    if final_remaining_quantity
                    > Decimal("0")
                    else None
                ),

                # Supplier to parent
                "dispatch_datetime": (
                    movement.dispatch_datetime
                ),
                "inbound_rlt_days": (
                    movement.inbound_rlt_days
                ),
                "expected_arrival_datetime": (
                    expected_arrival_at_parent
                ),
                "arrival_days_from_decision": (
                    movement
                    .arrival_days_from_decision
                ),

                # Parent processing and delivery
                "parent_processing_buffer_days": 1,
                "expected_dispatch": (
                    expected_dispatch
                ),
                "expected_delivery": (
                    expected_delivery
                ),

                # Parent route values
                "source_sla_days": (
                    parent_sla_days
                ),
                "source_rlt_days": (
                    parent_rlt_days
                ),
                "order_level_sla_days": (
                    parent_sla_days
                ),
                "order_level_rlt_days": (
                    parent_rlt_days
                ),
                "order_level_sla_source": (
                    order_line.parent_rdc
                    if parent_candidate is not None
                    else None
                ),
                "transport_mode": (
                    parent_transport_mode
                ),
                "transport_cost": (
                    parent_transport_cost
                ),

                # GIT is selected before physical weighted scoring.
                "source_weighted_score": None,

                "reason_codes": ",".join(
                    dict.fromkeys(
                        output_reasons
                    )
                ),
                "business_explanation": (
                    f"Reserved "
                    f"{movement.reserved_quantity} "
                    f"units from GIT ASN "
                    f"{movement.asn_number}. "
                    f"Expected arrival at parent RDC "
                    f"{movement.destination_location} is "
                    f"{expected_arrival_at_parent}. "
                    f"After one processing buffer day, "
                    f"expected dispatch is "
                    f"{expected_dispatch}. "
                    f"Parent-to-customer mode is "
                    f"{parent_transport_mode}, SLA is "
                    f"{parent_sla_days} day(s), and "
                    f"expected customer delivery is "
                    f"{expected_delivery}."
                ),
                "rule_version": "1.0",
                "configuration_version": "1.0",
            }
        )

    return rows

def select_output_columns(
    df: pd.DataFrame,
    requested_columns: list[str],
) -> pd.DataFrame:
    """
    Selects and orders output columns safely.

    Missing requested columns are created as blank columns so physical,
    GIT, no-allocation, and credit-block decision rows all retain the
    same output schema.
    """

    output_df = df.copy()

    for column in requested_columns:
        if column not in output_df.columns:
            output_df[column] = None

    return output_df[
        requested_columns
    ].copy()

# @dataclass
# class PendingReplenishmentExecution:
#     order_line: OrderLine
#     allocation_order_line: OrderLine
#     decision_timestamp: datetime

#     moq_qty: Decimal
#     moq_default_used: bool

#     raw_order_type: str
#     colour_code: int

#     is_zfmo_16_to_20: bool
#     is_zmso_16_to_20: bool

#     parent_pass_result: MOQAllocationResult
@dataclass
class PendingReplenishmentExecution:
    order_line: OrderLine
    allocation_order_line: OrderLine
    decision_timestamp: datetime

    moq_qty: Decimal
    moq_default_used: bool

    raw_order_type: str
    colour_code: int

    is_zfmo_colour_16: bool
    is_zmso_colour_16: bool

    # ZFMO ignores credit block for colours 16-20.
    enforce_credit_block: bool

    parent_pass_result: MOQAllocationResult
 
def candidate_has_valid_sla(
    candidate: CandidateSource,
) -> bool:
    """
    Returns True when a candidate has usable logistics
    route, transport mode, and SLA data.
    """

    route_available = bool(
        getattr(
            candidate,
            "route_available",
            False,
        )
    )

    transport_mode = getattr(
        candidate,
        "selected_transport_mode",
        None,
    )

    raw_sla = getattr(
        candidate,
        "configured_sla_days",
        None,
    )

    if (
        raw_sla is None
        or pd.isna(raw_sla)
    ):
        return False

    try:
        sla_days = float(raw_sla)
    except (
        TypeError,
        ValueError,
    ):
        return False

    return (
        route_available
        and transport_mode is not None
        and sla_days >= 0
        and sla_days < 9999
    )


def is_sla_data_missing_for_all_candidates(
    evaluated_candidates: list[
        CandidateSource
    ],
) -> bool:
    """
    Returns True when candidates exist but none has
    valid logistics SLA data.
    """

    if not evaluated_candidates:
        return False

    return not any(
        candidate_has_valid_sla(
            candidate
        )
        for candidate
        in evaluated_candidates
    )


# def resolve_no_allocation_decision_override(
#     moq_result: MOQAllocationResult,
#     evaluated_candidates: list[
#         CandidateSource
#     ],
#     existing_override: str | None = None,
# ) -> str | None:
#     """
#     Decision priority:

#     1. Existing override, such as CREDIT_BLOCKED
#     2. SLA_DATA_NOT_FOUND
#     3. None, allowing NO_ELIGIBLE_STOCK
#     """

#     if existing_override is not None:
#         return existing_override

#     physical_allocated_quantity = (
#         moq_result.total_allocated_quantity
#     )

#     git_reserved_quantity = getattr(
#         moq_result,
#         "total_git_reserved_quantity",
#         Decimal("0"),
#     )

#     total_fulfilled_quantity = (
#         physical_allocated_quantity
#         + git_reserved_quantity
#     )

#     no_allocation_happened = (
#         total_fulfilled_quantity
#         <= Decimal("0")
#     )

#     quantity_is_remaining = (
#         moq_result.remaining_quantity
#         > Decimal("0")
#     )

#     sla_data_is_missing = (
#         is_sla_data_missing_for_all_candidates(
#             evaluated_candidates
#         )
#     )

#     if (
#         no_allocation_happened
#         and quantity_is_remaining
#         and sla_data_is_missing
#     ):
#         return "SLA_DATA_NOT_FOUND"

#     return None


def add_sla_missing_reason(
    moq_result: MOQAllocationResult,
    decision_override: str | None,
) -> MOQAllocationResult:
    """
    Adds SLA_DATA_NOT_FOUND to reason codes when applicable.
    """

    if (
        decision_override
        != "SLA_DATA_NOT_FOUND"
    ):
        return moq_result

    return replace(
        moq_result,
        reason_codes=list(
            dict.fromkeys(
                [
                    *moq_result.reason_codes,
                    "SLA_DATA_NOT_FOUND",
                ]
            )
        ),
    )

def resolve_replenishment_scoring_config(
    is_zfmo_colour_16: bool,
    is_zmso_colour_16: bool,
    zfmo_colour_16_config: dict,
    zmso_colour_16_config: dict,
    standard_config: dict,
) -> dict:
    """
    Resolves Replenishment weighted-s*oring configuration.

    ZFMO colour 16:
        ZFMO-specific weights

    ZMSO colour 16:
        ZMS* colour-16-specific weights

    Z*MO/ZMSO colours 17-20:
        Sta*dard Replenishment weights
    """

    if is_zfmo_colour_16:
       return zfmo_colour_16_config

    if is_zmso_colour_16:
        return zmso_colour_16_config

    return standard_config

def run_unified_order_execution(
    final_df: pd.DataFrame,
    inventory_master_df: pd.DataFrame,
    allowable_qty_df: pd.DataFrame,
    git_df: pd.DataFrame,
    logistics_df: pd.DataFrame,
    rlt_df: pd.DataFrame,
    mad_df: pd.DataFrame | None = None,
    moq_df: pd.DataFrame | None = None,
    norms_df: pd.DataFrame | None = None,
    sample_size: int | None = None,
    output_dir: str | Path | None = None,
    execution_datetime: datetime | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    
    execution_dt = (
        execution_datetime
        if execution_datetime is not None
        else datetime.now()
    )

    run_folder_name = execution_dt.strftime("%d%b%y")

    output_dir = (
        Path(output_dir)
        / run_folder_name
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    print(
        f"Output directory: {output_dir}"
    )
    """
    Unified execution runner.

    Supports:
    - VOR
    - ACC
    - Replenishment, placeholder to be connected to workflow module
    - Push

    Uses one shared InventoryStateManager across all enabled order categories.
    """

    config_loader = ConfigLoader("config")

    calendar_rules = config_loader.load_calendar_rules()
    business_rules = config_loader.load_business_rules()

    execution_defaults = business_rules.get(
        "execution_defaults",
        {},
    )

    default_sla_days = int(
        execution_defaults.get(
            "missing_sla_days",
            5,
        )
    )

    default_rlt_days = int(
        execution_defaults.get(
            "missing_rlt_days",
            5,
        )
    )

    raw_default_route_transport_mode = str(
        execution_defaults.get(
            "missing_route_transport_mode",
            "SURFACE",
        )
    ).strip().upper()

    try:
        default_route_transport_mode = TransportMode(
            raw_default_route_transport_mode
        )

    except ValueError as exc:
        raise ValueError(
            "Invalid missing_route_transport_mode in "
            "business_rules.yaml. "
            f"Received={raw_default_route_transport_mode}. "
            f"Allowed values="
            f"{[mode.value for mode in TransportMode]}"
        ) from exc

    default_route_transport_cost = Decimal(
        str(
            execution_defaults.get(
                "missing_route_transport_cost",
                999999999,
            )
        )
    )

    execution_config = config_loader.load_execution_scope()

    output_config = execution_config.get("output", {})

    if output_dir is None:
        output_dir = output_config.get("output_dir", "data/outputs")

    output_prefix = output_config.get("output_prefix", "unified_execution")

    if output_dir is None:
        raise ValueError("output_dir cannot be None")

    output_path = Path(output_dir)

    output_path.mkdir(parents=True, exist_ok=True)

    # run_datetime = pd.Timestamp.now(
    #     tz=calendar_rules.get("timezone", "Asia/Kolkata")
    # ).to_pydatetime()

    execution_timezone = calendar_rules.get(
        "timezone",
        "Asia/Kolkata",
    )

    if execution_datetime is None:
        run_datetime = pd.Timestamp.now(
            tz=execution_timezone,
        ).to_pydatetime()

    else:
        execution_timestamp = pd.Timestamp(
            execution_datetime
        )

        if execution_timestamp.tzinfo is None:
            execution_timestamp = (
                execution_timestamp.tz_localize(
                    execution_timezone
                )
            )
        else:
            execution_timestamp = (
                execution_timestamp.tz_convert(
                    execution_timezone
                )
            )

        run_datetime = (
            execution_timestamp.to_pydatetime()
        )

    print(
        "Orchestration execution datetime:",
        run_datetime,
    )

    valid_order_df, excluded_dealer_orders_df = filter_valid_dealer_orders(
        order_df=final_df,
    )

    print("Original open order rows:", len(final_df))
    print("Valid dealer order rows:", len(valid_order_df))
    print("Excluded dealer order rows:", len(excluded_dealer_orders_df))

    if not excluded_dealer_orders_df.empty:
        print("\nExcluded dealer reason counts:")
        print(
            excluded_dealer_orders_df[
                "dealer_filter_reason"
            ].value_counts(dropna=False)
        )

    order_df = prepare_order_dataframe(
        final_df=valid_order_df,
        execution_config=execution_config,
    )

    if sample_size is not None:
        order_df = order_df.head(sample_size)

    order_lines = orders_dataframe_to_order_lines(order_df)

    from collections import Counter

    order_key_counts = Counter(
        (
            str(order.order_id).strip(),
            str(order.line_id).strip(),
        )
        for order in order_lines
    )

    duplicate_order_keys = {
        key: count
        for key, count in order_key_counts.items()
        if count > 1
    }

    if duplicate_order_keys:
        raise ValueError(
            "Duplicate order-line keys found before execution: "
            f"{list(duplicate_order_keys.items())[:20]}"
        )

    priority_lookup = {
        row["order_category_upper"]: row["execution_priority"]
        for _, row in order_df.drop_duplicates("order_category_upper").iterrows()
    }

    allowable_quantity_lookup = build_allowable_quantity_lookup_from_file(
        allowable_qty_df=allowable_qty_df,
    )

    inventory_master_with_norms_df = (
        merge_norms_into_inventory_master(
            inventory_master_df=(
                inventory_master_df
            ),
            norms_df=norms_df,
        )
    )

    # inventory_positions = inventory_dataframe_to_positions(
    #     inventory_df=inventory_master_df
    # )
    inventory_positions = inventory_dataframe_to_positions(
        inventory_df=inventory_master_with_norms_df
    )

    # ---------------------------------------------------------
    # Stateful GIT initialization
    # ---------------------------------------------------------
    # The cleaned GIT dataframe is used directly by GitStateManager.
    #
    # GIT columns:
    # - material_code
    # - destination_location
    # - source_location
    # - git_quantity
    # - delivery_status
    # - asn_number
    # - dispatch_datetime
    # - inbound_rlt_days
    # - expected_arrival_datetime
    # - rlt_found
    git_state = GitStateManager(
        git_df=git_df,
    )

    # Workflow candidate generation still accepts git_shipments,
    # but the legacy GIT-candidate logic is not being used.
    #
    # Replenishment 16-20 GIT is handled later by GitStateManager
    # inside the dedicated MOQ allocator.
    git_shipments = []

    routes = logistics_dataframe_to_routes(
        logistics_df=logistics_df,
        rdc_source_mapping=RDC_SOURCE_MAPPING,
        effective_start_datetime=pd.Timestamp("2026-01-01 00:00:00", tz="UTC"),
        pickup_buffer_hours=4,
        drop_buffer_hours=4,
        mode_names=("air", "surface"),
    )


    rlt_lookup = build_rlt_lookup(rlt_df)

    # mad_lookup = build_mad_lookup(mad_df)

    # missing_mad_combinations: set[tuple[str, str]] = set()

    mad_lookup = build_mad_lookup(mad_df)

    moq_lookup = build_moq_lookup(moq_df)

    norms_lookup = build_norms_lookup(
        norms_df=norms_df
    )

    track_missing_norms = (
        norms_df is not None
        and not norms_df.empty
    )

    missing_norms_combinations: set[
        tuple[str, str]
    ] = set()

    track_missing_moq = (
        moq_df is not None
        and not moq_df.empty
    )

    missing_moq_materials: set[str] = set()
    # Record missing combinations only when a MAD file is provided.
    track_missing_mad = mad_df is not None and not mad_df.empty

    missing_mad_combinations: set[tuple[str, str]]  = set()
 
    inventory_state = InventoryStateManager(
        inventory_positions=inventory_positions,
    )

    push_selection_config = business_rules.get(
        "push_selection",
        {
            "strategy": "WEIGHTED_SCORING",
            "weighted_scoring": {},
        },
    )

    replenishment_selection_config = business_rules.get(
        "replenishment_selection",
        {
            "strategy": "WEIGHTED_SCORING",
            "weighted_scoring": {},
        },
    )

    replenishment_moq_scoring_config = (
        business_rules.get(
            "replenishment_moq_scoring",
            {
                "weights": {
                    "sla": 0.30,
                    "ageing": 0.25,
                    "rlt": 0.20,
                    "eligible_quantity": 0.15,
                    "cost": 0.10,
                },
                "missing_values": {
                    "sla": 9999,
                    "rlt": 9999,
                    "cost": 999999999,
                },
            },
        )
    )

    zfmo_replenishment_moq_scoring_config = (
        business_rules.get(
            "zfmo_replenishment_moq_scoring",
            {
                "weights": {
                    "sla": 0.50,
                    "ageing": 0.05,
                    "rlt": 0.15,
                    "eligible_quantity": 0.20,
                    "cost": 0.10,
                },
                "missing_values": {
                    "sla": 9999,
                    "rlt": 9999,
                    "cost": 999999999,
                },
            },
        )
    )

    zmso_colour_16_moq_scoring_config = (
        business_rules.get(
            "zmso_colour_16_moq_scoring",
            {
                "weights": {
                    "sla": 0.40,
                    "ageing": 0.20,
                    "rlt": 0.15,
                    "eligible_quantity": 0.15,
                    "cost": 0.10,
                },
                "missing_values": {
                    "sla": 9999,
                    "rlt": 9999,
                    "cost": 999999999,
                },
            },
        )
    )


    push_moq_scoring_config = business_rules.get(
        "push_moq_scoring",
        {
            "weights": {
                "sla": 0.25,
                "ageing": 0.35,
                "rlt": 0.15,
                "eligible_quantity": 0.15,
                "cost": 0.10,
            },
            "missing_values": {
                "sla": 9999,
                "rlt": 9999,
                "cost": 999999999,
            },
        },
    )

    decision_rows: list[dict] = []
    candidate_rows: list[dict] = []

    pending_replenishment_orders: list[
        PendingReplenishmentExecution
    ] = []

    for order_line in order_lines:
        decision_timestamp = resolve_decision_datetime(
            calendar_rules=calendar_rules,
            order_creation_datetime=order_line.order_creation_timestamp,
            run_datetime=run_datetime,
        )

        raw_order_type = normalize_raw_order_type(
            getattr(
                order_line,
                "raw_order_type",
                None,
            )
        )

        colour_code = order_line.colour_code

        is_replenishment = (
            order_line.order_type.value
            == "REPLENISHMENT"
        )

        is_zfmo_replenishment = (
            is_replenishment
            and raw_order_type == "ZFMO"
        )

        is_zmso_replenishment = (
            is_replenishment
            and raw_order_type == "ZMSO"
        )

        is_zfmo_11_to_15 = (
            is_zfmo_replenishment
            and colour_code is not None
            and 11 <= int(colour_code) <= 15
        )

        # Two-pass execution applies to every Replenishment
        # order from colour 16 through 20.
        is_replenishment_16_to_20 = (
            is_replenishment
            and colour_code is not None
            and 16 <= int(colour_code) <= 20
        )

        is_zfmo_colour_16 = (
            is_zfmo_replenishment
            and colour_code is not None
            and int(colour_code) == 16
        )

        is_zmso_colour_16 = (
            is_zmso_replenishment
            and colour_code is not None
            and int(colour_code) == 16
        )

        is_replenishment_16_to_20 = (
            order_line.order_type.value
            == "REPLENISHMENT"
            and colour_code is not None
            and 16 <= int(colour_code) <= 20
        )

        # # Special policy applies only to ZFMO colour 16.
        # is_zfmo_colour_16 = (
        #     is_zfmo_replenishment
        #     and colour_code is not None
        #     and int(colour_code) == 16
        # )

        # is_zmso_colour_16 = (
        #     is_zmso_replenishment
        #     and colour_code is not None
        #     and int(colour_code) == 16
        # )

        # is_zfmo_17_to_20 = (
        #     is_zfmo_replenishment
        #     and colour_code is not None
        #     and 17 <= int(colour_code) <= 20
        # )

        # is_zmso_17_to_20 = (
        #     is_zmso_replenishment
        #     and colour_code is not None
        #     and 17 <= int(colour_code) <= 20
        # )

        # ---------------------------------------------------------
        # Replenishment policy selection
        # ---------------------------------------------------------

        # Only ZFMO colour 16 disables safety stock completely.
        #
        # All other Replenishment orders use the existing policy:
        # - Parent safety stock is calculated but not deducted.
        # - Alternative safety stock is calculated and deducted.
        apply_replenishment_safety_stock = (
            not is_zfmo_colour_16
        )

        # Only ZFMO colour 16 uses SLA-heavy scoring.
        #
        # ZMSO colour 16 and all ZFMO/ZMSO colours 17-20
        # use the standard Replenishment scoring.
        use_zfmo_colour_16_scoring = (
            is_zfmo_colour_16
        )

        # Every ZFMO Replenishment order ignores credit block.
        # Every ZMSO Replenishment order enforces credit block.
        enforce_replenishment_credit_block = (
            not is_zfmo_replenishment
        )

        # is_zfmo_replenishment = (
        #     order_line.order_type.value
        #     == "REPLENISHMENT"
        #     and raw_order_type == "ZFMO"
        # )

        # is_zmso_replenishment = (
        #     order_line.order_type.value
        #     == "REPLENISHMENT"
        #     and raw_order_type == "ZMSO"
        # )

        # is_zfmo_11_to_15 = (
        #     is_zfmo_replenishment
        #     and colour_code is not None
        #     and 11 <= int(colour_code) <= 15
        # )

        # is_zfmo_16_to_20 = (
        #     is_zfmo_replenishment
        #     and colour_code is not None
        #     and 16 <= int(colour_code) <= 20
        # )

        # is_zmso_16_to_20 = (
        #     is_zmso_replenishment
        #     and colour_code is not None
        #     and 16 <= int(colour_code) <= 20
        # )

        evaluated_candidates: list[CandidateSource] = []
     
        decision_override: str | None = None
        
        decision_score_lookup: dict | None = None 

        if order_line.order_type.value in ["VOR", "ACC"]:
            allowable_quantity = get_allowable_quantity_for_order(
                order_line=order_line,
                allowable_quantity_lookup=allowable_quantity_lookup,
            )

            workflow_result = process_vor_order(
                order_line=order_line,
                allowable_quantity=allowable_quantity,
                inventory_positions=inventory_positions,
                inventory_state=inventory_state,
                git_shipments=git_shipments,
                routes=routes,
                location_cluster_map=LOCATION_CLUSTER_MAP,
                vepdc_location_code=VEPDC_LOCATION_CODE,
                allowed_transport_modes_config=ALLOWED_TRANSPORT_MODES_CONFIG,
                calendar_rules=calendar_rules,
                rlt_lookup=rlt_lookup,
                mad_lookup=mad_lookup, 
                missing_mad_combinations=(
                    missing_mad_combinations
                    if track_missing_mad
                    else None
                ),
                norms_lookup=norms_lookup,
                missing_norms_combinations=(
                    missing_norms_combinations
                    if track_missing_norms
                    else None
                ),
                decision_timestamp=decision_timestamp,
                default_sla_days=default_sla_days,
                default_rlt_days=default_rlt_days,
                default_route_transport_mode=(
                    default_route_transport_mode
                ),
                default_route_transport_cost=(
                    default_route_transport_cost
                ),
                defer_inventory_allocation=True,
            )

            selection_result = workflow_result.selection_result
            evaluated_candidates = workflow_result.evaluated_candidates

        elif order_line.order_type.value == "PUSH":
            workflow_result = process_push_order(
                order_line=order_line,
                inventory_positions=inventory_positions,
                inventory_state=inventory_state,
                git_shipments=git_shipments,
                routes=routes,
                location_cluster_map=LOCATION_CLUSTER_MAP,
                vepdc_location_code=VEPDC_LOCATION_CODE,
                allowed_transport_modes_config=ALLOWED_TRANSPORT_MODES_CONFIG,
                calendar_rules=calendar_rules,
                rlt_lookup=rlt_lookup,
                push_selection_config=push_selection_config,
                mad_lookup=mad_lookup,
                missing_mad_combinations=(
                    missing_mad_combinations
                    if track_missing_mad
                    else None
                ),
                norms_lookup=norms_lookup,
                missing_norms_combinations=(
                    missing_norms_combinations
                    if track_missing_norms
                    else None
                ),
                decision_timestamp=decision_timestamp,
                default_sla_days=default_sla_days,
                default_rlt_days=default_rlt_days,
                default_route_transport_mode=(
                    default_route_transport_mode
                ),
                default_route_transport_cost=(
                    default_route_transport_cost
                ),
                defer_inventory_allocation=True,
            )

            selection_result = workflow_result.selection_result
            evaluated_candidates = workflow_result.evaluated_candidates

        elif order_line.order_type.value == "REPLENISHMENT":
            workflow_result = process_replenishment_order(
                order_line=order_line,
                inventory_positions=inventory_positions,
                inventory_state=inventory_state,
                git_shipments=git_shipments,
                routes=routes,
                location_cluster_map=LOCATION_CLUSTER_MAP,
                vepdc_location_code=VEPDC_LOCATION_CODE,
                allowed_transport_modes_config=ALLOWED_TRANSPORT_MODES_CONFIG,
                calendar_rules=calendar_rules,
                rlt_lookup=rlt_lookup,
                replenishment_selection_config=replenishment_selection_config,
                mad_lookup=mad_lookup,
                missing_mad_combinations=(
                    missing_mad_combinations
                    if track_missing_mad
                    else None
                ),
                norms_lookup=norms_lookup,
                missing_norms_combinations=(
                    missing_norms_combinations
                    if track_missing_norms
                    else None
                ),
                decision_timestamp=decision_timestamp,
                # New policy:
                # ZFMO 16-20 does not calculate or apply safety stock.
                # Only ZFMO colour 16 disables safety stock.
                apply_safety_stock=(
                    apply_replenishment_safety_stock
                ),

                # ZFMO ignores credit block.
                # ZMSO enforces credit block.
                enforce_credit_block=(
                    enforce_replenishment_credit_block
                ),
                # apply_safety_stock=(
                #     not is_zfmo_16_to_20
                # ),
                # # All ZFMO Replenishment orders ignore credit block.
                # # ZMSO Replenishment orders enforce credit block.
                # enforce_credit_block=(
                #     not is_zfmo_replenishment
                # ),
                default_sla_days=default_sla_days,
                default_rlt_days=default_rlt_days,
                default_route_transport_mode=(
                    default_route_transport_mode
                ),
                default_route_transport_cost=(
                    default_route_transport_cost
                ),
                defer_inventory_allocation=True,
            )

            selection_result = workflow_result.selection_result
            evaluated_candidates = workflow_result.evaluated_candidates

        else:
            from order_orchestration.selection.source_selection import SourceSelectionResult

            selection_result = SourceSelectionResult(
                decision=DecisionType.DATA_EXCEPTION,
                selected_candidate=None,
                allocated_quantity=Decimal("0"),
                remaining_quantity=order_line.requested_quantity,
                reason_codes=[ReasonCode.INVALID_ORDER_TYPE],
            )

            evaluated_candidates = []

        # -----------------------------------------------------
        # Generic MOQ-based parent-first multi-source allocation
        # -----------------------------------------------------
        moq_qty, moq_default_used = resolve_moq(
            material_code=order_line.material_code,
            moq_lookup=moq_lookup,
            missing_materials=(
                missing_moq_materials
                if track_missing_moq
                else None
            ),
            default_moq=Decimal("1"),
        )

        # For VOR and ACC, allocate against effective allowable quantity.
        allocation_order_line = order_line

        if order_line.order_type.value in ["VOR", "ACC"]:
            allowable_quantity = get_allowable_quantity_for_order(
                order_line=order_line,
                allowable_quantity_lookup=allowable_quantity_lookup,
            )

            effective_quantity = (
                min(
                    order_line.requested_quantity,
                    allowable_quantity,
                )
                if allowable_quantity is not None
                and allowable_quantity > Decimal("0")
                else order_line.requested_quantity
            )

            allocation_order_line = replace(
                order_line,
                requested_quantity=effective_quantity,
                remaining_quantity=effective_quantity,
            )

        # colour_code = order_line.colour_code

        # is_parent_only_replenishment = (
        #     order_line.order_type.value == "REPLENISHMENT"
        #     and colour_code is not None
        #     and 11 <= int(colour_code) <= 15
        # )
        is_parent_only_replenishment = (
            is_zfmo_11_to_15
        )

        # -----------------------------------------------------
        # Credit-block execution rule
        # -----------------------------------------------------

        # -----------------------------------------------------
        # Credit-block execution rule
        # -----------------------------------------------------
        # VOR and ACC:
        #     Ignore credit block.
        #
        # ZFMO Replenishment:
        #     Ignore credit block.
        #
        # ZMSO Replenishment:
        #     Enforce credit block.
        #
        # Push:
        #     Enforce credit block.

        is_credit_blocked_for_execution = (
            bool(order_line.is_credit_blocked)
            and (
                order_line.order_type.value
                == "PUSH"
                or (
                    order_line.order_type.value
                    == "REPLENISHMENT"
                    and raw_order_type != "ZFMO"
                )
            )
        )

        # -----------------------------------------------------
        # Debug: no workflow should allocate before MOQ allocator
        # -----------------------------------------------------
        existing_order_movements = [
            movement
            for movement in inventory_state.get_movements()
            if str(movement.order_id).strip()
            == str(order_line.order_id).strip()
            and str(movement.line_id).strip()
            == str(order_line.line_id).strip()
        ]

        if existing_order_movements:
            raise RuntimeError(
                "Inventory was allocated before the MOQ allocator. "
                f"Order={order_line.order_id}, "
                f"line={order_line.line_id}, "
                f"movements={existing_order_movements}"
            )

         
        moq_result: MOQAllocationResult

        if is_credit_blocked_for_execution:
            # -------------------------------------------------
            # Do not call any allocator.
            # Do not create any inventory movement.
            # Keep the complete requested quantity at parent.
            # -------------------------------------------------
            moq_eligible_quantity = floor_to_moq(
                quantity=allocation_order_line.requested_quantity,
                moq_qty=moq_qty,
            )

            moq_remainder_quantity = (
                allocation_order_line.requested_quantity
                - moq_eligible_quantity
            )

            blocked_reason_codes: list[ReasonCode | str] = [
                ReasonCode.CREDIT_BLOCKED,
                ReasonCode.REMAINING_QTY_HELD_AT_PARENT,
            ]

            if moq_default_used:
                blocked_reason_codes.append(
                    ReasonCode.MOQ_NOT_FOUND_DEFAULT_ONE_USED
                )

            if moq_remainder_quantity > Decimal("0"):
                blocked_reason_codes.extend(
                    [
                        ReasonCode.ORDER_QTY_PARTIALLY_MOQ_ALIGNED,
                        ReasonCode.MOQ_REMAINDER_HELD_AT_PARENT,
                    ]
                )

            # Remove duplicate reason codes while preserving order.
            blocked_reason_codes = list(
                dict.fromkeys(blocked_reason_codes)
            )

            moq_result = MOQAllocationResult(
                original_requested_quantity=(
                    allocation_order_line.requested_quantity
                ),
                moq_qty=moq_qty,
                moq_default_used=moq_default_used,
                moq_eligible_quantity=moq_eligible_quantity,
                moq_remainder_quantity=moq_remainder_quantity,
                total_allocated_quantity=Decimal("0"),
                total_git_reserved_quantity=Decimal("0"),
                total_fulfilled_quantity=Decimal("0"),
                remaining_quantity=(
                                    allocation_order_line.requested_quantity
                                ),
                allocations=[],
                git_reservations=[],
                reason_codes=blocked_reason_codes,
            )

            decision_override = "CREDIT_BLOCKED"

        elif is_parent_only_replenishment:
            moq_result = allocate_parent_only_full_fill(
                order_line=allocation_order_line,
                candidates=evaluated_candidates,
                moq_qty=moq_qty,
                moq_default_used=moq_default_used,
                inventory_state=inventory_state,
                decision_timestamp=decision_timestamp,
            )

        elif order_line.order_type.value in ["VOR", "ACC"]:
            moq_result = (
                allocate_vor_acc_parent_then_ranked_alternatives(
                    order_line=allocation_order_line,
                    candidates=evaluated_candidates,
                    moq_qty=moq_qty,
                    moq_default_used=moq_default_used,
                    inventory_state=inventory_state,
                    decision_timestamp=decision_timestamp,
                )
            )

        elif order_line.order_type.value == "PUSH":
            moq_result = (
                allocate_push_parent_then_ageing_then_weighted(
                    order_line=allocation_order_line,
                    candidates=evaluated_candidates,
                    moq_qty=moq_qty,
                    moq_default_used=moq_default_used,
                    inventory_state=inventory_state,
                    decision_timestamp=decision_timestamp,
                    scoring_config=push_moq_scoring_config,
                )
            )

        # elif (
        #     is_zfmo_16_to_20
        #     or is_zmso_16_to_20
        # ):
        elif is_replenishment_16_to_20:
            if colour_code is None:
                raise ValueError(
                    "Colour code cannot be None for "
                    "Replenishment 16-20 execution. "
                    f"order_id={order_line.order_id}, "
                    f"line_id={order_line.line_id}."
                )

            normalized_colour_code = int(
                colour_code
            )

            selected_replenishment_scoring_config = (
                resolve_replenishment_scoring_config(
                    is_zfmo_colour_16=(
                        is_zfmo_colour_16
                    ),
                    is_zmso_colour_16=(
                        is_zmso_colour_16
                    ),
                    zfmo_colour_16_config=(
                        zfmo_replenishment_moq_scoring_config
                    ),
                    zmso_colour_16_config=(
                        zmso_colour_16_moq_scoring_config
                    ),
                    standard_config=(
                        replenishment_moq_scoring_config
                    ),
                )
            )


            parent_pass_result = (
                allocate_replenishment_parent_then_gated_weighted_alternatives(
                    order_line=(
                        allocation_order_line
                    ),
                    candidates=(
                        evaluated_candidates
                    ),
                    moq_qty=moq_qty,
                    moq_default_used=(
                        moq_default_used
                    ),
                    inventory_state=(
                        inventory_state
                    ),
                    git_state=git_state,
                    decision_timestamp=(
                        decision_timestamp
                    ),
                    git_reference_timestamp=(
                        run_datetime
                    ),
                    # scoring_config=(
                    #     zfmo_replenishment_moq_scoring_config
                    #     if is_zfmo_16_to_20
                    #     else replenishment_moq_scoring_config
                    # ),
                    # scoring_config=(
                    #     zfmo_replenishment_moq_scoring_config
                    #     if use_zfmo_colour_16_scoring
                    #     else replenishment_moq_scoring_config
                    # ),  
                    scoring_config=(
                        selected_replenishment_scoring_config
                    ),
                    execution_phase=(
                        "PARENT_ONLY"
                    ),
                    prior_result=None,
                )
            )

            pending_replenishment_orders.append(
                PendingReplenishmentExecution(
                    order_line=order_line,
                    allocation_order_line=(
                        allocation_order_line
                    ),
                    decision_timestamp=(
                        decision_timestamp
                    ),
                    moq_qty=moq_qty,
                    moq_default_used=(
                        moq_default_used
                    ),
                    raw_order_type=(
                        raw_order_type
                    ),
                    colour_code=(
                        normalized_colour_code
                    ),
                    # is_zfmo_16_to_20=(
                    #     is_zfmo_16_to_20
                    # ),
                    # is_zmso_16_to_20=(
                    #     is_zmso_16_to_20
                    # ),
                    # use_zfmo_colour_16_policy=(
                    #     is_zfmo_colour_16
                    # ),

                    # enforce_credit_block=(
                    #     enforce_replenishment_credit_block
                    # ),
                    is_zfmo_colour_16=(
                        is_zfmo_colour_16
                    ),
                    is_zmso_colour_16=(
                        is_zmso_colour_16
                    ),
                    enforce_credit_block=(
                        not is_zfmo_replenishment
                    ),
                    parent_pass_result=(
                        parent_pass_result
                    ),
                )
            )

            # Do not build decision or candidate rows yet.
            # The final output is created after Pass 2.
            continue

        elif (
            order_line.order_type.value
            == "REPLENISHMENT"
        ):
            raise ValueError(
                "Unsupported Replenishment combination. "
                f"order_id={order_line.order_id}, "
                f"line_id={order_line.line_id}, "
                f"raw_order_type={raw_order_type}, "
                f"colour_code={colour_code}."
            )

        else:
            raise ValueError(
                "No MOQ allocator configured for "
                f"order_id={order_line.order_id}, "
                f"line_id={order_line.line_id}, "
                f"order_type={order_line.order_type.value}, "
                f"raw_order_type={raw_order_type},"
                f"colour_code={colour_code}."
            )


        zfmo_credit_block_ignored = (
            bool(order_line.is_credit_blocked)
            and is_zfmo_replenishment
        )

        if zfmo_credit_block_ignored:
            moq_result = replace(
                moq_result,
                reason_codes=list(
                    dict.fromkeys(
                        [
                            *moq_result.reason_codes,
                            "ZFMO_CREDIT_BLOCK_IGNORED",
                        ]
                    )
                ),
            )

        # ---------------------------------------------------------
        # Resolve final no-allocation decision
        # ---------------------------------------------------------
        # decision_override = (
        #     resolve_no_allocation_decision_override(
        #         moq_result=moq_result,
        #         evaluated_candidates=(
        #             evaluated_candidates
        #         ),
        #         existing_override=(
        #             decision_override
        #         ),
        #     )
        # )

        moq_result = add_sla_missing_reason(
            moq_result=moq_result,
            decision_override=(
                decision_override
            ),
        )

        allocator_score_lookup = getattr(
            moq_result,
            "candidate_score_lookup",
            {},
        )

        for candidate in evaluated_candidates:
            candidate_rows.append(
                candidate_to_dict(
                    order_line=order_line,
                    candidate=candidate,
                    score_lookup=(
                        allocator_score_lookup
                        if allocator_score_lookup
                        else None
                    ),
                )
            )
       
        decision_score_lookup = (
            allocator_score_lookup
            if allocator_score_lookup
            else None
        )
 
        moq_decision_rows = (
            build_moq_multi_source_decision_rows(
                order_line=order_line,
                allocation_order_line=allocation_order_line,
                moq_result=moq_result,
                decision_timestamp=decision_timestamp,
                priority_rank=priority_lookup.get(
                    order_line.order_type.value,
                    None,
                ),
                score_lookup=decision_score_lookup,
                decision_override=decision_override,
            )
        )

        decision_rows.extend(moq_decision_rows) 


        # git_decision_rows = (
        #     build_git_reservation_decision_rows(
        #         order_line=order_line,
        #         allocation_order_line=(
        #             allocation_order_line
        #         ),
        #         moq_result=moq_result,
        #         decision_timestamp=(
        #             decision_timestamp
        #         ),
        #         priority_rank=(
        #             priority_lookup.get(
        #                 order_line.order_type.value,
        #                 None,
        #             )
        #         ),
        #     )
        # )

        if getattr(
            moq_result,
            "git_reservations",
            [],
        ):
            print(
                "\n[GIT PARENT ROUTE DEBUG]",
                {
                    "order_id": order_line.order_id,
                    "parent_rdc": order_line.parent_rdc,
                    "material_code": (
                        order_line.material_code
                    ),
                    "evaluated_candidate_count": (
                        len(evaluated_candidates)
                    ),
                },
            )

            for candidate in evaluated_candidates:
                print(
                    {
                        "candidate_location": (
                            candidate.location
                        ),
                        "candidate_source_type": (
                            candidate.source_type.value
                            if hasattr(
                                candidate.source_type,
                                "value",
                            )
                            else str(
                                candidate.source_type
                            )
                        ),
                        "candidate_eligible": (
                            candidate.eligible
                        ),
                        "configured_sla_days": (
                            candidate
                            .configured_sla_days
                        ),
                        "rlt_days": getattr(
                            candidate,
                            "rlt_days",
                            None,
                        ),
                        "selected_transport_mode": (
                            candidate
                            .selected_transport_mode
                            .value
                            if candidate
                            .selected_transport_mode
                            is not None
                            else None
                        ),
                        "transport_cost": (
                            candidate.transport_cost
                        ),
                        "expected_dispatch": (
                            candidate.expected_dispatch
                        ),
                        "expected_delivery": (
                            candidate.expected_delivery
                        ),
                    }
                )
                
        git_decision_rows = (
            build_git_reservation_decision_rows(
                order_line=order_line,
                allocation_order_line=(
                    allocation_order_line
                ),
                moq_result=moq_result,
                decision_timestamp=(
                    decision_timestamp
                ),
                priority_rank=(
                    priority_lookup.get(
                        order_line.order_type.value,
                        None,
                    )
                ),
                evaluated_candidates=(
                    evaluated_candidates
                ),
            )
        )

        decision_rows.extend(
            git_decision_rows
        )

    # =========================================================
    # PASS 2: GIT AND ALTERNATIVE ORCHESTRATION
    # =========================================================
    for pending in pending_replenishment_orders:
        order_line = pending.order_line

        # -----------------------------------------------------
        # Skip second-pass orchestration when parent already
        # fulfilled the complete MOQ-aligned quantity.
        # The final decision row still needs to be created.
        # -----------------------------------------------------
        remaining_after_parent = max(
            pending
            .parent_pass_result
            .moq_eligible_quantity
            - pending
            .parent_pass_result
            .total_allocated_quantity
            - getattr(
                pending.parent_pass_result,
                "total_git_reserved_quantity",
                Decimal("0"),
            ),
            Decimal("0"),
        )

        # -----------------------------------------------------
        # Re-evaluate candidates using inventory state AFTER
        # every order has received parent-first priority.
        # -----------------------------------------------------
        workflow_result = (
            process_replenishment_order(
                order_line=order_line,
                inventory_positions=(
                    inventory_positions
                ),
                inventory_state=(
                    inventory_state
                ),
                git_shipments=git_shipments,
                routes=routes,
                location_cluster_map=(
                    LOCATION_CLUSTER_MAP
                ),
                vepdc_location_code=(
                    VEPDC_LOCATION_CODE
                ),
                allowed_transport_modes_config=(
                    ALLOWED_TRANSPORT_MODES_CONFIG
                ),
                calendar_rules=calendar_rules,
                rlt_lookup=rlt_lookup,
                replenishment_selection_config=(
                    replenishment_selection_config
                ),
                mad_lookup=mad_lookup,
                missing_mad_combinations=(
                    missing_mad_combinations
                    if track_missing_mad
                    else None
                ),
                norms_lookup=norms_lookup,
                missing_norms_combinations=(
                    missing_norms_combinations
                    if track_missing_norms
                    else None
                ),
                decision_timestamp=(
                    pending.decision_timestamp
                ),
                # Only ZFMO colour 16 disables safety stock.
                # apply_safety_stock=(
                #     not pending
                #     .use_zfmo_colour_16_policy
                # ),
                apply_safety_stock=(
                    not pending.is_zfmo_colour_16
                ),

                # Credit-block policy is stored explicitly.
                enforce_credit_block=(
                    pending.enforce_credit_block
                ),
                # apply_safety_stock=(
                #     not pending
                #     .is_zfmo_16_to_20
                # ),
                # enforce_credit_block=(
                #     not (
                #         pending
                #         .is_zfmo_16_to_20
                #     )
                # ),
                default_sla_days=default_sla_days,
                default_rlt_days=default_rlt_days,
                default_route_transport_mode=(
                    default_route_transport_mode
                ),
                default_route_transport_cost=(
                    default_route_transport_cost
                ),
                defer_inventory_allocation=True,
            )
        )

        evaluated_candidates = (
            workflow_result
            .evaluated_candidates
        )

        # -----------------------------------------------------
        # Continue from parent-pass result.
        # Do not allocate parent physical inventory again.
        # -----------------------------------------------------
        if remaining_after_parent > Decimal("0"):
            scoring_config = (
                resolve_replenishment_scoring_config(
                    is_zfmo_colour_16=(
                        pending.is_zfmo_colour_16
                    ),
                    is_zmso_colour_16=(
                        pending.is_zmso_colour_16
                    ),
                    zfmo_colour_16_config=(
                        zfmo_replenishment_moq_scoring_config
                    ),
                    zmso_colour_16_config=(
                        zmso_colour_16_moq_scoring_config
                    ),
                    standard_config=(
                        replenishment_moq_scoring_config
                    ),
                )
            )
            # scoring_config = (
            #     zfmo_replenishment_moq_scoring_config
            #     if pending
            #     .use_zfmo_colour_16_policy
            #     else replenishment_moq_scoring_config
            # )
            # scoring_config = (
            #     zfmo_replenishment_moq_scoring_config
            #     if pending.is_zfmo_16_to_20
            #     else replenishment_moq_scoring_config
            # )

            moq_result = (
                allocate_replenishment_parent_then_gated_weighted_alternatives(
                    order_line=(
                        pending
                        .allocation_order_line
                    ),
                    candidates=(
                        evaluated_candidates
                    ),
                    moq_qty=(
                        pending.moq_qty
                    ),
                    moq_default_used=(
                        pending
                        .moq_default_used
                    ),
                    inventory_state=(
                        inventory_state
                    ),
                    git_state=git_state,
                    decision_timestamp=(
                        pending
                        .decision_timestamp
                    ),
                    git_reference_timestamp=(
                        run_datetime
                    ),
                    scoring_config=(
                        scoring_config
                    ),
                    execution_phase=(
                        "REMAINDER_ONLY"
                    ),
                    prior_result=(
                        pending
                        .parent_pass_result
                    ),
                )
            )

        else:
            # Parent already fulfilled the aligned quantity.
            moq_result = (
                pending.parent_pass_result
            )

        # -----------------------------------------------------
        # Add ZFMO credit-block-ignored audit reason
        # -----------------------------------------------------
        # if (
        #     pending.is_zfmo_16_to_20
        #     and bool(
        #         order_line.is_credit_blocked
        #     )
        # ):
        if (
            pending.raw_order_type
            == "ZFMO"
            and bool(
                order_line.is_credit_blocked
            )
        ):
            moq_result = replace(
                moq_result,
                reason_codes=list(
                    dict.fromkeys(
                        [
                            *moq_result.reason_codes,
                            "ZFMO_CREDIT_BLOCK_IGNORED",
                        ]
                    )
                ),
            )
            # moq_result = replace(
            #     moq_result,
            #     reason_codes=list(
            #         dict.fromkeys(
            #             [
            #                 *moq_result.reason_codes,
            #                 "ZFMO_CREDIT_BLOCK_IGNORED",
            #             ]
            #         )
            #     ),
            # )

        # -----------------------------------------------------
        # Resolve final Pass-2 no-allocation decision
        # # -----------------------------------------------------
        # pending_decision_override = (
        #     resolve_no_allocation_decision_override(
        #         moq_result=moq_result,
        #         evaluated_candidates=(
        #             evaluated_candidates
        #         ),
        #         existing_override=None,
        #     )
        # )

        # moq_result = add_sla_missing_reason(
        #     moq_result=moq_result,
        #     decision_override=(
        #         pending_decision_override
        #     ),
        # )

        # -----------------------------------------------------
        # Candidate audit
        # -----------------------------------------------------
        allocator_score_lookup = getattr(
            moq_result,
            "candidate_score_lookup",
            {},
        )

        for candidate in evaluated_candidates:
            candidate_rows.append(
                candidate_to_dict(
                    order_line=order_line,
                    candidate=candidate,
                    score_lookup=(
                        allocator_score_lookup
                        if allocator_score_lookup
                        else None
                    ),
                )
            )

        decision_score_lookup = (
            allocator_score_lookup
            if allocator_score_lookup
            else None
        )

        # -----------------------------------------------------
        # Physical decision rows
        # -----------------------------------------------------
        moq_decision_rows = (
            build_moq_multi_source_decision_rows(
                order_line=order_line,
                allocation_order_line=(
                    pending
                    .allocation_order_line
                ),
                moq_result=moq_result,
                decision_timestamp=(
                    pending
                    .decision_timestamp
                ),
                priority_rank=(
                    priority_lookup.get(
                        order_line
                        .order_type.value,
                        None,
                    )
                ),
                score_lookup=(
                    decision_score_lookup
                ),
                # decision_override=(
                #     pending_decision_override
                # ),
                decision_override=None,
            )
        )

        decision_rows.extend(
            moq_decision_rows
        )

        # -----------------------------------------------------
        # GIT decision rows
        # -----------------------------------------------------
        git_decision_rows = (
            build_git_reservation_decision_rows(
                order_line=order_line,
                allocation_order_line=(
                    pending
                    .allocation_order_line
                ),
                moq_result=moq_result,
                decision_timestamp=(
                    pending
                    .decision_timestamp
                ),
                priority_rank=(
                    priority_lookup.get(
                        order_line
                        .order_type.value,
                        None,
                    )
                ),
                evaluated_candidates=(
                    evaluated_candidates
                ),
            )
        )

        decision_rows.extend(
            git_decision_rows
        )

    decisions_df = pd.DataFrame(decision_rows)
    candidates_df = pd.DataFrame(candidate_rows)

    decisions_output_df = select_output_columns(
    df=decisions_df,
        requested_columns=(
            DECISION_OUTPUT_COLUMNS
        ),
    )

    candidates_output_df = select_output_columns(
        df=candidates_df,
        requested_columns=(
            CANDIDATE_AUDIT_OUTPUT_COLUMNS
        ),
    )

    movements_df = pd.DataFrame(
        [asdict(movement) for movement in inventory_state.get_movements()]
    )

    git_movements_df = pd.DataFrame(
        [
            asdict(movement)
            for movement
            in git_state.get_movements()
        ]
    )

    decisions_excel_df = make_datetimes_excel_safe(decisions_output_df)
    candidates_excel_df = make_datetimes_excel_safe(candidates_output_df)
    movements_excel_df = make_datetimes_excel_safe(movements_df)
    git_movements_excel_df = (
        make_datetimes_excel_safe(
            git_movements_df
        )
    )

    decisions_excel_df.to_excel(
        output_path / f"{output_prefix}_decisions.xlsx",
        index=False,
        engine="openpyxl",
    )

    candidates_excel_df.to_excel(
        output_path / f"{output_prefix}_candidate_audit.xlsx",
        index=False,
        engine="openpyxl",
    )

    movements_excel_df.to_excel(
        output_path / f"{output_prefix}_inventory_movements.xlsx",
        index=False,
        engine="openpyxl",
    )

    git_movements_excel_df.to_excel(
        output_path
        / f"{output_prefix}_git_movements.xlsx",
        index=False,
        engine="openpyxl",
    )

    if track_missing_mad:
        missing_mad_df = build_missing_mad_report(
            missing_combinations=missing_mad_combinations,
            default_mad=Decimal("1"),
        )

        missing_mad_df.to_excel(
            output_path / f"{output_prefix}_missing_mad_combinations.xlsx",
            index=False,
            engine="openpyxl",
        )

        print(
            "Missing MAD combinations:",
            len(missing_mad_df),
        )

    if not excluded_dealer_orders_df.empty:
        excluded_dealer_orders_excel_df = make_datetimes_excel_safe(
            excluded_dealer_orders_df
        )

        excluded_dealer_orders_excel_df.to_excel(
            output_path
            / f"{output_prefix}_excluded_dealer_orders.xlsx",
            index=False,
            engine="openpyxl",
        )

    if track_missing_moq:
        missing_moq_df = build_missing_moq_report(
            missing_materials=missing_moq_materials,
            default_moq=Decimal("1"),
        )

        missing_moq_df.to_excel(
            output_path
            / f"{output_prefix}_missing_moq_materials.xlsx",
            index=False,
            engine="openpyxl",
        )

        print(
            "Missing MOQ materials:",
            len(missing_moq_df),
        )

    if track_missing_norms:
        missing_norms_df = (
            build_missing_norms_report(
                missing_combinations=(
                    missing_norms_combinations
                ),
            )
        )

        missing_norms_df.to_excel(
            output_path
            / f"{output_prefix}_missing_norms_combinations.xlsx",
            index=False,
            engine="openpyxl",
        )

        print(
            "Missing norms combinations:",
            len(missing_norms_df),
        )

    return decisions_df, candidates_df, movements_df