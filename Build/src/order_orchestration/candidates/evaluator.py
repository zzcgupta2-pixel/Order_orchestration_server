from __future__ import annotations
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from typing import Iterable, Optional

from order_orchestration.calendar.delivery_calculator import (
    calculate_route_delivery_result,
    calculate_route_delivery_result_for_location,
)
 

from order_orchestration.state.inventory_state import InventoryStateManager

from order_orchestration.domain.order import OrderLine
from order_orchestration.eligibility.safety_stock_policy import (
    evaluate_dynamic_safety_stock,
)
from order_orchestration.state.inventory_state import InventoryStateManager
from order_orchestration.calendar.working_calendar import WorkingCalendarConfig
from order_orchestration.domain.candidate import CandidateSource
from order_orchestration.domain.enums import OrderType, ReasonCode, SourceType
from order_orchestration.domain.inventory import InventoryPosition
from order_orchestration.domain.route import Route
from order_orchestration.eligibility.inventory_eligibility import (
    calculate_eligible_quantity,
    is_full_fill_capable,
)
from order_orchestration.eligibility.transport_eligibility import (
    evaluate_transport_eligibility,
)


def build_inventory_position_lookup(
    inventory_positions: Iterable[InventoryPosition],
) -> dict[tuple[str, str], InventoryPosition]:
    """
    Builds lookup dictionary for inventory positions.

    Key:
        (location, material_code)
    """

    lookup: dict[tuple[str, str], InventoryPosition] = {}

    for position in inventory_positions:
        key = (
            str(position.location).strip(),
            str(position.material_code).strip(),
        )
        lookup[key] = position

    return lookup


def build_route_lookup(
    routes: Iterable[Route],
) -> dict[tuple[str, str], Route]:
    """
    Builds route lookup dictionary.

    Key:
        (source_location, destination_location)

    If duplicate route keys exist, the last route wins.
    Duplicate route detection may be added later in data validation.
    """

    route_lookup: dict[tuple[str, str], Route] = {}

    for route in routes:
        key = (
            str(route.source_location).strip(),
            str(route.destination_location).strip(),
        )
        route_lookup[key] = route

    return route_lookup


def get_route_for_candidate(
    candidate: CandidateSource,
    destination_location: str,
    route_lookup: dict[tuple[str, str], Route],
) -> Optional[Route]:
    """
    Finds route for a candidate source to destination.

    Candidate location is treated as source location.
    Destination can be dealer code, dealer location, or delivery location
    depending on available route master design.
    """

    key = (
        str(candidate.location).strip(),
        str(destination_location).strip(),
    )

    return route_lookup.get(key)


def get_inventory_rejection_reasons(
    candidate: CandidateSource,
    eligible_quantity: Decimal,
    requested_quantity: Decimal,
    safety_stock: Decimal,
    safety_stock_protected: bool,
) -> list:
    """
    Returns inventory-related reason codes for a candidate.

    This function does not remove candidates. It only explains whether
    the candidate is eligible or rejected for stock-related reasons.
    """

    reason_codes: list[ReasonCode] = []

    if safety_stock_protected and safety_stock > Decimal("0"):
        reason_codes.append(ReasonCode.SAFETY_STOCK_PROTECTED)

    if eligible_quantity <= Decimal("0"):
        reason_codes.append(ReasonCode.NO_ELIGIBLE_STOCK)
        return reason_codes

    if eligible_quantity < requested_quantity:
        if candidate.source_type == SourceType.PARENT_RDC:
            reason_codes.append(ReasonCode.PARENT_INSUFFICIENT_QUANTITY)
        else:
            reason_codes.append(ReasonCode.INSUFFICIENT_QUANTITY)

    return reason_codes


def evaluate_physical_candidate_inventory(
    candidate: CandidateSource,
    inventory_position: InventoryPosition,
    order_type: OrderType,
    safety_stock_config: dict[str, bool],
) -> CandidateSource:
    """
    Evaluates inventory eligibility for one physical source candidate.

    Physical candidates include:
    - PARENT_RDC
    - CLUSTER_RDC
    - PAN_INDIA_RDC
    - VEPDC
    """

    eligible_quantity = calculate_eligible_quantity(
        inventory_position=inventory_position,
        order_type=order_type,
        safety_stock_config=safety_stock_config,
    )

    full_fill_capable = is_full_fill_capable(
        eligible_quantity=eligible_quantity,
        requested_quantity=candidate.requested_quantity,
    )

    candidate_eligible = eligible_quantity > Decimal("0")

    safety_stock_protected = bool(
        safety_stock_config.get(order_type.value, True)
    )

    inventory_reason_codes = get_inventory_rejection_reasons(
        candidate=candidate,
        eligible_quantity=eligible_quantity,
        requested_quantity=candidate.requested_quantity,
        safety_stock=inventory_position.safety_stock,
        safety_stock_protected=safety_stock_protected,
    )

    merged_reason_codes = list(candidate.rejection_reason_codes)
    merged_reason_codes.extend(inventory_reason_codes)

    return replace(
        candidate,
        available_quantity=inventory_position.actual_stock,
        safety_stock=inventory_position.safety_stock,
        eligible_quantity=eligible_quantity,
        full_fill_capable=full_fill_capable,
        eligible=candidate_eligible,
        rejection_reason_codes=merged_reason_codes,
    )


def evaluate_git_candidate_inventory(
    candidate: CandidateSource,
) -> CandidateSource:
    """
    Evaluates Parent GIT candidate from quantity perspective only.

    GIT threshold and EDA timing are evaluated in workflow modules,
    especially VOR.
    """

    full_fill_capable = candidate.eligible_quantity >= candidate.requested_quantity

    reason_codes = list(candidate.rejection_reason_codes)

    if candidate.eligible_quantity <= Decimal("0"):
        reason_codes.append(ReasonCode.NO_ELIGIBLE_STOCK)
    elif not full_fill_capable:
        reason_codes.append(ReasonCode.INSUFFICIENT_QUANTITY)

    return replace(
        candidate,
        full_fill_capable=full_fill_capable,
        eligible=candidate.eligible_quantity > Decimal("0"),
        rejection_reason_codes=reason_codes,
    )


# def evaluate_candidate_inventory(
#     candidate: CandidateSource,
#     inventory_lookup: dict[tuple[str, str], InventoryPosition],
#     order_type: OrderType,
#     safety_stock_config: dict[str, bool],
# ) -> CandidateSource:
#     """
#     Evaluates a single candidate for inventory eligibility.

#     Physical candidates use inventory positions.
#     Parent GIT candidates use their GIT quantity directly.
#     """

#     if candidate.source_type == SourceType.PARENT_GIT:
#         return evaluate_git_candidate_inventory(candidate)

#     key = (
#         str(candidate.location).strip(),
#         str(candidate.material_code).strip(),
#     )

#     inventory_position = inventory_lookup.get(key)

#     if inventory_position is None:
#         merged_reason_codes = list(candidate.rejection_reason_codes)
#         merged_reason_codes.append(ReasonCode.MISSING_MASTER_DATA)

#         return replace(
#             candidate,
#             eligible=False,
#             eligible_quantity=Decimal("0"),
#             full_fill_capable=False,
#             rejection_reason_codes=merged_reason_codes,
#         )

#     return evaluate_physical_candidate_inventory(
#         candidate=candidate,
#         inventory_position=inventory_position,
#         order_type=order_type,
#         safety_stock_config=safety_stock_config,
#     )


# def evaluate_candidates_inventory(
#     candidates: Iterable[CandidateSource],
#     inventory_positions: Iterable[InventoryPosition],
#     order_type: OrderType,
#     safety_stock_config: dict[str, bool],
# ) -> list:
#     """
#     Evaluates inventory eligibility for all candidates.

#     This function retains all candidates, including rejected ones.
#     """

#     inventory_lookup = build_inventory_position_lookup(inventory_positions)

#     evaluated_candidates = [
#         evaluate_candidate_inventory(
#             candidate=candidate,
#             inventory_lookup=inventory_lookup,
#             order_type=order_type,
#             safety_stock_config=safety_stock_config,
#         )
#         for candidate in candidates
#     ]

#     return evaluated_candidates


def evaluate_candidate_transport(
    candidate: CandidateSource,
    route: Optional[Route],
    order_type: OrderType,
    decision_datetime: datetime,
    allowed_transport_modes_config: dict[str, list[str]],
    calendar_config: WorkingCalendarConfig,
    adjust_final_delivery_to_working_time: bool = True,
) -> CandidateSource:
    """
    Evaluates route, transport eligibility, SLA, and delivery details
    for one candidate.

    This function keeps candidates even when route or transport fails.
    All failure reasons are appended to candidate rejection reason codes.
    """

    transport_result = evaluate_transport_eligibility(
        route=route,
        order_type=order_type,
        decision_datetime=decision_datetime,
        allowed_transport_modes_config=allowed_transport_modes_config,
    )

    merged_reason_codes = list(candidate.rejection_reason_codes)
    merged_reason_codes.extend(transport_result.reason_codes)

    if route is None:
        if ReasonCode.SLA_DATA_NOT_FOUND not in merged_reason_codes:
            merged_reason_codes.append(ReasonCode.SLA_DATA_NOT_FOUND)

        return replace(
            candidate,
            route_available=False,
            eligible=False,
            rejection_reason_codes=merged_reason_codes,
        )

    if not transport_result.eligible:
        return replace(
            candidate,
            route_available=True,
            selected_transport_mode=route.transport_mode,
            configured_sla_days=route.standard_sla_days,
            transport_cost=route.transport_cost,
            eligible=False,
            rejection_reason_codes=merged_reason_codes,
        )

    delivery_result = calculate_route_delivery_result(
        route=route,
        decision_datetime=decision_datetime,
        calendar_config=calendar_config,
        adjust_final_delivery_to_working_time=adjust_final_delivery_to_working_time,
    )

    return replace(
        candidate,
        route_available=True,
        selected_transport_mode=route.transport_mode,
        configured_sla_days=delivery_result.standard_sla_days,
        transport_cost=delivery_result.transport_cost,
        expected_dispatch=delivery_result.expected_dispatch,
        expected_delivery=delivery_result.expected_delivery,
        eligible=candidate.eligible and transport_result.eligible,
        rejection_reason_codes=merged_reason_codes,
    )


# def evaluate_candidates_transport(
#     candidates: Iterable[CandidateSource],
#     routes: Iterable[Route],
#     order_type: OrderType,
#     decision_datetime: datetime,
#     destination_location: str,
#     allowed_transport_modes_config: dict[str, list[str]],
#     calendar_config: WorkingCalendarConfig,
#     adjust_final_delivery_to_working_time: bool = True,
# ) -> list:
#     """
#     Evaluates transport and delivery details for all candidates.

#     This function retains every candidate and appends transport-related
#     reason codes to the candidate audit.
#     """

#     route_lookup = build_route_lookup(routes)

#     evaluated_candidates: list[CandidateSource] = []

#     for candidate in candidates:
#         route = get_route_for_candidate(
#             candidate=candidate,
#             destination_location=destination_location,
#             route_lookup=route_lookup,
#         )

#         evaluated_candidate = evaluate_candidate_transport(
#             candidate=candidate,
#             route=route,
#             order_type=order_type,
#             decision_datetime=decision_datetime,
#             allowed_transport_modes_config=allowed_transport_modes_config,
#             calendar_config=calendar_config,
#             adjust_final_delivery_to_working_time=adjust_final_delivery_to_working_time,
#         )

#         evaluated_candidates.append(evaluated_candidate)

#     return evaluated_candidates

def _append_reason_if_missing(
    reason_codes: list[ReasonCode],
    reason_code: ReasonCode,
) -> list:
    """
    Appends a reason code only if it is not already present.
    """

    updated_reason_codes = list(reason_codes)

    if reason_code not in updated_reason_codes:
        updated_reason_codes.append(reason_code)

    return updated_reason_codes


# def evaluate_candidate_inventory_from_state(
#     candidate: CandidateSource,
#     inventory_state: InventoryStateManager,
# ) -> CandidateSource:
#     """
#     Evaluates a candidate using the current inventory state.

#     This prevents stale inventory usage. If previous orders have already
#     consumed inventory, the candidate will see the reduced quantity.
#     """

#     if candidate.source_type == SourceType.PARENT_GIT:
#         return evaluate_git_candidate_inventory(candidate)

#     reason_codes = list(candidate.rejection_reason_codes)

#     has_position = inventory_state.has_inventory_position(
#         location=candidate.location,
#         material_code=candidate.material_code,
#     )

#     if not has_position:
#         reason_codes = _append_reason_if_missing(
#             reason_codes=reason_codes,
#             reason_code=ReasonCode.MISSING_MASTER_DATA,
#         )

#         return replace(
#             candidate,
#             available_quantity=Decimal("0"),
#             eligible_quantity=Decimal("0"),
#             full_fill_capable=False,
#             eligible=False,
#             rejection_reason_codes=reason_codes,
#         )

#     current_available_quantity = inventory_state.get_available_quantity(
#         location=candidate.location,
#         material_code=candidate.material_code,
#     )

#     full_fill_capable = current_available_quantity >= candidate.requested_quantity

#     if current_available_quantity <= Decimal("0"):
#         reason_codes = _append_reason_if_missing(
#             reason_codes=reason_codes,
#             reason_code=ReasonCode.NO_ELIGIBLE_STOCK,
#         )

#     elif current_available_quantity < candidate.requested_quantity:
#         if candidate.source_type == SourceType.PARENT_RDC:
#             reason_codes = _append_reason_if_missing(
#                 reason_codes=reason_codes,
#                 reason_code=ReasonCode.PARENT_INSUFFICIENT_QUANTITY,
#             )
#         else:
#             reason_codes = _append_reason_if_missing(
#                 reason_codes=reason_codes,
#                 reason_code=ReasonCode.INSUFFICIENT_QUANTITY,
#             )

#     return replace(
#         candidate,
#         available_quantity=current_available_quantity,
#         eligible_quantity=current_available_quantity,
#         full_fill_capable=full_fill_capable,
#         eligible=current_available_quantity > Decimal("0"),
#         rejection_reason_codes=reason_codes,
#     )

def evaluate_candidates_inventory_from_state(
    candidates: list[CandidateSource],
    inventory_state: InventoryStateManager,
    order_line: OrderLine,
    mad_lookup: dict,
    rlt_lookup: dict,
    norms_lookup: dict,
    missing_norms_combinations: (
        set[tuple[str, str]] | None
    ),
    missing_mad_combinations: set[tuple[str, str]] | None,
    vepdc_location_code: str,
    default_mad: Decimal = Decimal("1"),
    missing_rdc_rlt: int = 0,
    missing_vepdc_rlt: int = 0,
    round_up_safety_stock: bool = True,
) -> list:
    """
    Evaluates candidates using current physical inventory and dynamic
    safety-stock policy.

    Physical balance is maintained by InventoryStateManager.

    Eligibility:
        VOR / ACC:
            current physical stock

        Replenishment parent:
            current physical stock

        Replenishment alternative:
            current physical stock - dynamic safety stock

        Push parent and alternatives:
            current physical stock - dynamic safety stock

        Non-Auto:
            temporary policy protects safety stock at VEPDC
    """

    evaluated_candidates: list[CandidateSource] = []

    for candidate in candidates:
        rejection_reason_codes = list(
            candidate.rejection_reason_codes
        )

        has_inventory_position = (
            inventory_state.has_inventory_position(
                location=candidate.location,
                material_code=candidate.material_code,
            )
        )

        if not has_inventory_position:
            if (
                ReasonCode.NO_STOCK_AT_SOURCE
                not in rejection_reason_codes
            ):
                rejection_reason_codes.append(
                    ReasonCode.NO_STOCK_AT_SOURCE
                )

            evaluated_candidates.append(
                replace(
                    candidate,
                    available_quantity=Decimal("0"),
                    eligible_quantity=Decimal("0"),
                    ageing_quantity=Decimal("0"),
                    safety_stock=Decimal("0"),
                    calculated_safety_stock=Decimal("0"),
                    full_fill_capable=False,
                    eligible=False,
                    rejection_reason_codes=rejection_reason_codes,
                )
            )

            continue

        current_physical_quantity = (
            inventory_state.get_available_quantity(
                location=candidate.location,
                material_code=candidate.material_code,
            )
        )

        current_ageing_quantity = (
            inventory_state.get_available_ageing_quantity(
                location=candidate.location,
                material_code=candidate.material_code,
            )
        )

        safety_evaluation = evaluate_dynamic_safety_stock(
            order_line=order_line,
            candidate=candidate,
            mad_lookup=mad_lookup,
            rlt_lookup=rlt_lookup,
            norms_lookup=norms_lookup,
            missing_mad_combinations=missing_mad_combinations,
            missing_norms_combinations=(
                missing_norms_combinations
            ),
            vepdc_location_code=vepdc_location_code,
            default_mad=default_mad,
            missing_rdc_rlt=missing_rdc_rlt,
            missing_vepdc_rlt=missing_vepdc_rlt,
            round_up_to_whole_unit=round_up_safety_stock,
        )

        eligible_quantity = max(
            current_physical_quantity
            - safety_evaluation.applied_safety_stock,
            Decimal("0"),
        )

        # Ageing stock cannot exceed stock that this order may use.
        eligible_ageing_quantity = min(
            current_ageing_quantity,
            eligible_quantity,
        )

        full_fill_capable = (
            eligible_quantity >= candidate.requested_quantity
        )

        candidate_eligible = eligible_quantity > Decimal("0")

        if not candidate_eligible:
            if (
                ReasonCode.NO_STOCK_AT_SOURCE
                not in rejection_reason_codes
            ):
                rejection_reason_codes.append(
                    ReasonCode.NO_STOCK_AT_SOURCE
                )

        evaluated_candidates.append(
            replace(
                candidate,
                available_quantity=current_physical_quantity,
                safety_stock=safety_evaluation.applied_safety_stock,
                eligible_quantity=eligible_quantity,
                ageing_quantity=eligible_ageing_quantity,
                full_fill_capable=full_fill_capable,
                eligible=candidate_eligible,
                norms=safety_evaluation.norms,
                norms_found=safety_evaluation.norms_found,
                safety_stock_exempt_due_to_norms=(
                    safety_evaluation
                    .safety_stock_exempt_due_to_norms
                ),
                rlt_days=int(safety_evaluation.rlt_days),
                mad=safety_evaluation.mad,
                mad_default_used=safety_evaluation.mad_default_used,
                calculated_safety_stock=(
                    safety_evaluation.calculated_safety_stock
                ),
                safety_stock_protected=(
                    safety_evaluation.safety_stock_protected
                ),
                safety_stock_policy=(
                    safety_evaluation.safety_stock_policy
                ),
                rejection_reason_codes=rejection_reason_codes,
            )
        )

    return evaluated_candidates

def evaluate_candidate_transport_with_calendar_rules(
    candidate: CandidateSource,
    route: Optional[Route],
    order_type: OrderType,
    decision_datetime: datetime,
    allowed_transport_modes_config: dict[str, list[str]],
    calendar_rules: dict,
    adjust_final_delivery_to_working_time: bool = True,
) -> CandidateSource:
    """
    Evaluates route, transport eligibility, SLA, and delivery details
    for one candidate using location-wise calendar rules.

    This function respects:
    - source location working calendar
    - holiday/date overrides
    - Sunday rules
    - order-type allowed calendar rules
    - location-specific working hours

    It keeps rejected candidates in the audit with reason codes.
    """

    transport_result = evaluate_transport_eligibility(
        route=route,
        order_type=order_type,
        decision_datetime=decision_datetime,
        allowed_transport_modes_config=allowed_transport_modes_config,
    )

    merged_reason_codes = list(candidate.rejection_reason_codes)
    merged_reason_codes.extend(transport_result.reason_codes)

    if route is None:
        if ReasonCode.SLA_DATA_NOT_FOUND not in merged_reason_codes:
            merged_reason_codes.append(ReasonCode.SLA_DATA_NOT_FOUND)

        return replace(
            candidate,
            route_available=False,
            eligible=False,
            rejection_reason_codes=merged_reason_codes,
        )

    if not transport_result.eligible:
        return replace(
            candidate,
            route_available=True,
            selected_transport_mode=route.transport_mode,
            configured_sla_days=route.standard_sla_days,
            transport_cost=route.transport_cost,
            eligible=False,
            rejection_reason_codes=merged_reason_codes,
        )

    delivery_result = calculate_route_delivery_result_for_location(
        route=route,
        order_type=order_type,
        decision_datetime=decision_datetime,
        calendar_rules=calendar_rules,
        adjust_final_delivery_to_working_time=adjust_final_delivery_to_working_time,
    )

    return replace(
        candidate,
        route_available=True,
        selected_transport_mode=route.transport_mode,
        configured_sla_days=delivery_result.standard_sla_days,
        transport_cost=delivery_result.transport_cost,
        expected_dispatch=delivery_result.expected_dispatch,
        expected_delivery=delivery_result.expected_delivery,
        eligible=candidate.eligible and transport_result.eligible,
        rejection_reason_codes=merged_reason_codes,
    )


def evaluate_candidates_transport_with_calendar_rules(
    candidates: Iterable[CandidateSource],
    routes: Iterable[Route],
    order_type: OrderType,
    decision_datetime: datetime,
    destination_location: str,
    allowed_transport_modes_config: dict[str, list[str]],
    calendar_rules: dict,
    adjust_final_delivery_to_working_time: bool = True,
) -> list:
    """
    Evaluates transport and delivery details for all candidates using
    location-wise calendar rules.

    This function should be used in the orchestration engine going forward.
    """

    route_lookup = build_route_lookup(routes)

    evaluated_candidates: list[CandidateSource] = []

    for candidate in candidates:
        route = get_route_for_candidate(
            candidate=candidate,
            destination_location=destination_location,
            route_lookup=route_lookup,
        )

        evaluated_candidate = evaluate_candidate_transport_with_calendar_rules(
            candidate=candidate,
            route=route,
            order_type=order_type,
            decision_datetime=decision_datetime,
            allowed_transport_modes_config=allowed_transport_modes_config,
            calendar_rules=calendar_rules,
            adjust_final_delivery_to_working_time=adjust_final_delivery_to_working_time,
        )

        evaluated_candidates.append(evaluated_candidate)

    return evaluated_candidates