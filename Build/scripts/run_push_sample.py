from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
from order_orchestration.data.rlt_resolver import build_rlt_lookup

from order_orchestration.calendar.location_calendar import resolve_decision_datetime
from order_orchestration.config import ConfigLoader
from order_orchestration.data.adapters import (
    git_dataframe_to_shipments,
    inventory_dataframe_to_positions,
    logistics_dataframe_to_routes,
    orders_dataframe_to_order_lines,
)
from order_orchestration.data.rlt_resolver import build_rlt_lookup
from order_orchestration.domain.candidate import CandidateSource
from order_orchestration.domain.decision import Decision
from order_orchestration.domain.enums import DecisionType, ReasonCode
from order_orchestration.domain.order import OrderLine
from order_orchestration.workflows.push import process_push_order


SAFETY_STOCK_CONFIG = {
    "VOR": True,
    "ACC": True,
    "REPLENISHMENT": True,
    "PUSH": True,
}


ALLOWED_TRANSPORT_MODES_CONFIG = {
    "VOR": ["AIR", "COURIER_EXPRESS", "SURFACE"],
    "ACC": ["AIR", "COURIER_EXPRESS", "SURFACE"],
    "REPLENISHMENT": ["MILK_RUN", "SURFACE", "PART_TRUCK_LOAD"],
    "PUSH": ["SURFACE", "PART_TRUCK_LOAD", "FULL_TRUCK_LOAD"],
}


RDC_SOURCE_MAPPING = {
    "vepdc": "1110",
    "bangalore": "1141",
    "jhajjer": "1153",
    "kolkata": "1155",
    "ludhiana": "1156",
    "lucknow": "1158",
    "hyderabad": "1152",
    "coimbatore": "1157",
    "raipur": "1159",
    "guwahati": "1161",
}


LOCATION_CLUSTER_MAP = {
    "1110": "VEPDC",
    "1141": "SOUTH",
    "1152": "SOUTH",
    "1153": "NORTH",
    "1155": "EAST",
    "1156": "NORTH",
    "1157": "SOUTH",
    "1158": "NORTH",
    "1159": "CENTRAL",
    "1161": "EAST",
}


VEPDC_LOCATION_CODE = "1110"


def make_datetimes_excel_safe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Converts timezone-aware datetime values to timezone-naive values
    so Excel export works correctly.
    """

    output_df = df.copy()

    for column in output_df.columns:
        output_df[column] = output_df[column].apply(
            lambda value: value.replace(tzinfo=None)
            if hasattr(value, "tzinfo") and value.tzinfo is not None
            else value
        )

    return output_df


def build_rlt_map(rlt_df: pd.DataFrame) -> dict[str, int]:
    """
    Builds RDC-level RLT map.

    Expected columns:
    - location or plant
    - rlt_days
    """

    rlt_data = rlt_df.copy()

    if "location" not in rlt_data.columns and "plant" in rlt_data.columns:
        rlt_data = rlt_data.rename(columns={"plant": "location"})

    if "location" not in rlt_data.columns:
        raise ValueError("RLT dataframe must have 'location' or 'plant' column.")

    if "rlt_days" not in rlt_data.columns:
        raise ValueError("RLT dataframe must have 'rlt_days' column.")

    rlt_data["location"] = rlt_data["location"].astype(str).str.strip()

    rlt_data["rlt_days"] = pd.to_numeric(
        rlt_data["rlt_days"],
        errors="coerce",
    ).fillna(9999).astype(int)

    return dict(zip(rlt_data["location"], rlt_data["rlt_days"]))


def candidate_to_dict(
    order_line: OrderLine,
    candidate: CandidateSource,
) -> dict:
    """
    Converts candidate evaluation into a reporting dictionary.
    """

    return {
        "order_id": order_line.order_id,
        "line_id": order_line.line_id,
        "order_type": order_line.order_type.value,
        "material_code": order_line.material_code,
        "dealer_code": order_line.dealer_code,
        "parent_rdc": order_line.parent_rdc,
        "candidate_location": candidate.location,
        "candidate_source_type": candidate.source_type.value,
        "requested_quantity": candidate.requested_quantity,
        "available_quantity": candidate.available_quantity,
        "safety_stock": candidate.safety_stock,
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
        "rejection_reason_codes": ",".join(
            reason.value for reason in candidate.rejection_reason_codes
        ),
    }


def build_business_explanation(
    order_line: OrderLine,
    selected_source: str | None,
    selected_source_type: str | None,
    allocated_quantity: Decimal,
    remaining_quantity: Decimal,
    reason_codes: list[ReasonCode],
) -> str:
    """
    Creates deterministic explanation from Push decision facts.
    """

    reason_text = ", ".join(reason.value for reason in reason_codes)

    if selected_source is None:
        return (
            f"Push order {order_line.order_id}-{order_line.line_id} for material "
            f"{order_line.material_code} could not be allocated. "
            f"Requested quantity was {order_line.requested_quantity}. "
            f"Reason codes: {reason_text}."
        )

    return (
        f"Push order {order_line.order_id}-{order_line.line_id} for material "
        f"{order_line.material_code} was allocated from {selected_source} "
        f"({selected_source_type}). Allocated quantity is {allocated_quantity}, "
        f"remaining quantity is {remaining_quantity}. "
        f"Reason codes: {reason_text}."
    )


def build_decision_from_selection(
    order_line: OrderLine,
    selection_result,
    decision_timestamp: datetime,
) -> Decision:
    """
    Converts source selection result into final Decision object.
    """

    selected_candidate = selection_result.selected_candidate

    if selected_candidate is None:
        selected_source = None
        selected_source_type = None
        transport_mode = None
        expected_dispatch = None
        expected_delivery = None
        configured_sla_days = None
        transport_cost = None
    else:
        selected_source = selected_candidate.location
        selected_source_type = selected_candidate.source_type
        transport_mode = selected_candidate.selected_transport_mode
        expected_dispatch = selected_candidate.expected_dispatch
        expected_delivery = selected_candidate.expected_delivery
        configured_sla_days = selected_candidate.configured_sla_days
        transport_cost = selected_candidate.transport_cost

    first_fill_rate = (
        selection_result.allocated_quantity / order_line.requested_quantity
        if order_line.requested_quantity > Decimal("0")
        else Decimal("0")
    )

    explanation = build_business_explanation(
        order_line=order_line,
        selected_source=selected_source,
        selected_source_type=(
            selected_source_type.value if selected_source_type is not None else None
        ),
        allocated_quantity=selection_result.allocated_quantity,
        remaining_quantity=selection_result.remaining_quantity,
        reason_codes=selection_result.reason_codes,
    )

    return Decision(
        order_id=order_line.order_id,
        line_id=order_line.line_id,
        order_type=order_line.order_type.value,
        material_code=order_line.material_code,
        dealer_code=order_line.dealer_code,
        parent_rdc=order_line.parent_rdc,
        decision_timestamp=decision_timestamp,
        decision=selection_result.decision,
        requested_quantity=order_line.requested_quantity,
        allocated_quantity=selection_result.allocated_quantity,
        remaining_quantity=selection_result.remaining_quantity,
        selected_source=selected_source,
        selected_source_type=selected_source_type,
        transport_mode=transport_mode,
        expected_dispatch=expected_dispatch,
        expected_delivery=expected_delivery,
        configured_sla_hours=configured_sla_days,
        transport_cost=transport_cost,
        first_fill_rate=first_fill_rate,
        reason_codes=selection_result.reason_codes,
        business_explanation=explanation,
        candidate_evaluations=[],
        rule_version="1.0",
        configuration_version="1.0",
    )


def decision_to_dict(
    decision: Decision,
) -> dict:
    """
    Converts decision object into report-friendly dictionary.
    """

    return {
        "order_id": decision.order_id,
        "line_id": decision.line_id,
        "order_type": decision.order_type,
        "material_code": decision.material_code,
        "dealer_code": decision.dealer_code,
        "decision_timestamp": decision.decision_timestamp,
        "decision": decision.decision.value,
        "selected_source": decision.selected_source,
        "selected_source_type": (
            decision.selected_source_type.value
            if decision.selected_source_type is not None
            else None
        ),
        "requested_quantity": decision.requested_quantity,
        "allocated_quantity": decision.allocated_quantity,
        "remaining_quantity": decision.remaining_quantity,
        "transport_mode": (
            decision.transport_mode.value
            if decision.transport_mode is not None
            else None
        ),
        "expected_dispatch": decision.expected_dispatch,
        "expected_delivery": decision.expected_delivery,
        "configured_sla_days": decision.configured_sla_hours,
        "transport_cost": decision.transport_cost,
        "first_fill_rate": decision.first_fill_rate,
        "reason_codes": ",".join(reason.value for reason in decision.reason_codes),
        "business_explanation": decision.business_explanation,
        "rule_version": decision.rule_version,
        "configuration_version": decision.configuration_version,
    }


def run_push_sample(
    final_df: pd.DataFrame,
    inventory_master_df: pd.DataFrame,
    git_df: pd.DataFrame,
    logistics_df: pd.DataFrame,
    rlt_df: pd.DataFrame,
    sample_size: int = 100,
    output_dir: str | Path = "data/outputs",
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Runs Push order sample through deterministic engine.

    Current Push scope:
    - Physical stock only
    - No GIT
    - No Parent-first rule
    - Network-wide weighted scoring
    - Ageing-heavy selection
    - State-aware inventory
    - Calendar-aware dispatch and delivery
    """

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    config_loader = ConfigLoader("config")
    calendar_rules = config_loader.load_calendar_rules()
    business_rules = config_loader.load_business_rules()

    push_selection_config = business_rules.get(
        "push_selection",
        {
            "strategy": "WEIGHTED_SCORING",
            "weighted_scoring": {},
        },
    )

    run_datetime = pd.Timestamp.now(
        tz=calendar_rules.get("timezone", "Asia/Kolkata")
    ).to_pydatetime()

    push_df = final_df[
        final_df["order_category"].astype(str).str.upper() == "PUSH"
    ].copy()

    push_df = push_df.sort_values(
        by="order_create_datetime",
        ascending=True,
    ).head(sample_size)

    order_lines = orders_dataframe_to_order_lines(push_df)

    snapshot_timestamp = pd.Timestamp.now(tz="UTC")

    inventory_positions = inventory_dataframe_to_positions(
        inventory_df=inventory_master_df
    )

    git_shipments = git_dataframe_to_shipments(
        git_df=git_df,
        default_expected_arrival_datetime=snapshot_timestamp,
    )

    routes = logistics_dataframe_to_routes(
        logistics_df=logistics_df,
        rdc_source_mapping=RDC_SOURCE_MAPPING,
        effective_start_datetime=pd.Timestamp("2026-01-01 00:00:00", tz="UTC"),
        pickup_buffer_hours=4,
        drop_buffer_hours=4,
        mode_names=("air", "surface"),
    )

    rlt_lookup = build_rlt_lookup(rlt_df) 

    from order_orchestration.state.inventory_state import InventoryStateManager

    inventory_state = InventoryStateManager(
        inventory_positions=inventory_positions,
    )

    decision_rows: list[dict] = []
    candidate_rows: list[dict] = []

    for order_line in order_lines:
        decision_timestamp = resolve_decision_datetime(
            calendar_rules=calendar_rules,
            order_creation_datetime=order_line.order_creation_timestamp,
            run_datetime=run_datetime,
        )

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
            decision_timestamp=decision_timestamp,
        )

        for candidate in workflow_result.evaluated_candidates:
            candidate_rows.append(
                candidate_to_dict(
                    order_line=order_line,
                    candidate=candidate,
                )
            )

        decision = build_decision_from_selection(
            order_line=order_line,
            selection_result=workflow_result.selection_result,
            decision_timestamp=decision_timestamp,
        )

        decision_rows.append(decision_to_dict(decision))

    decisions_df = pd.DataFrame(decision_rows)
    candidates_df = pd.DataFrame(candidate_rows)

    movements_df = pd.DataFrame(
        [asdict(movement) for movement in inventory_state.get_movements()]
    )

    decisions_excel_df = make_datetimes_excel_safe(decisions_df)
    candidates_excel_df = make_datetimes_excel_safe(candidates_df)
    movements_excel_df = make_datetimes_excel_safe(movements_df)

    decisions_excel_df.to_excel(
        output_path / "push_sample_decisions.xlsx",
        index=False,
        engine="openpyxl",
    )

    candidates_excel_df.to_excel(
        output_path / "push_sample_candidate_audit.xlsx",
        index=False,
        engine="openpyxl",
    )

    movements_excel_df.to_excel(
        output_path / "push_sample_inventory_movements.xlsx",
        index=False,
        engine="openpyxl",
    )

    return decisions_df, candidates_df, movements_df