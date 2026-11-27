from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from typing import Iterable, Optional

from order_orchestration.data.rlt_resolver import (
    resolve_rlt_days, 
    apply_rlt_defaults
)
from order_orchestration.calendar.delivery_calculator import (
    calculate_route_delivery_result_for_location,
)
from order_orchestration.candidates.evaluator import (
    evaluate_candidates_inventory_from_state,
)
from order_orchestration.candidates.generator import generate_all_source_candidates
from order_orchestration.domain.candidate import CandidateSource
from order_orchestration.domain.enums import (
    DecisionType,
    OrderType,
    ReasonCode,
    SourceType,
    TransportMode,
)


from order_orchestration.transport.route_policy import (
    apply_route_and_sla_defaults,
    enrich_candidates_with_route_policy,
)
from order_orchestration.domain.git import GitShipment
from order_orchestration.domain.inventory import InventoryPosition
from order_orchestration.domain.inventory_movement import InventoryMovement
from order_orchestration.domain.order import OrderLine
from order_orchestration.domain.route import Route
from order_orchestration.eligibility.transport_eligibility import (
    evaluate_transport_eligibility,
)
from order_orchestration.exceptions import DuplicateExecutionError, InventoryStateError
from order_orchestration.selection.source_selection import SourceSelectionResult
from order_orchestration.state.inventory_state import InventoryStateManager


# @dataclass(frozen=True)
# class VORWorkflowResult:
#     """
#     Output of VOR workflow for one order line.
#     """

#     selection_result: SourceSelectionResult
#     evaluated_candidates: list[CandidateSource]
#     inventory_movement: Optional[InventoryMovement]
@dataclass(frozen=True)
class VORWorkflowResult:
    selection_result: SourceSelectionResult
    evaluated_candidates: list[CandidateSource]
    inventory_movement: Optional[InventoryMovement]
    inventory_movements: list[InventoryMovement] | None = None
    source_allocations: list | None = None
    moq_allocation_result: object | None = None


def is_non_auto_customer(dealer_code: str) -> bool:
    """
    Identifies non-auto customers.

    Business rule:
    - customer/dealer code starts with 1E
    - OR customer/dealer code equals 1341596
    """

    dealer_code = str(dealer_code).strip().upper()
    return dealer_code.startswith("1E") or dealer_code == "1341596"


def calculate_vor_effective_requested_quantity(
    requested_quantity: Decimal,
    allowable_quantity: Decimal | None,
) -> tuple[Decimal, list[ReasonCode]]:
    """
    Calculates VOR allocatable quantity.

    VOR allocation must respect allowable quantity.

    If allowable quantity is missing or invalid, fallback to requested quantity
    and add ALLOWABLE_QTY_MISSING.
    """

    reason_codes: list[ReasonCode] = []

    if allowable_quantity is None or allowable_quantity <= Decimal("0"):
        reason_codes.append(ReasonCode.ALLOWABLE_QTY_MISSING)
        return requested_quantity, reason_codes

    effective_quantity = min(requested_quantity, allowable_quantity)

    if effective_quantity < requested_quantity:
        reason_codes.append(ReasonCode.ALLOWABLE_QTY_APPLIED)

    return effective_quantity, reason_codes


# def build_route_list_lookup(
#     routes: Iterable[Route],
# ) -> dict[tuple[str, str], list[Route]]:
#     """
#     Builds route lookup where one source-destination can have multiple modes.

#     Key:
#         (source_location, destination_location)
#     """

#     route_lookup: dict[tuple[str, str], list[Route]] = {}

#     for route in routes:
#         key = (
#             str(route.source_location).strip(),
#             str(route.destination_location).strip(),
#         )

#         route_lookup.setdefault(key, []).append(route)

#     return route_lookup


# def get_routes_for_candidate(
#     candidate: CandidateSource,
#     destination_location: str,
#     route_lookup: dict[tuple[str, str], list[Route]],
# ) -> list:
#     """
#     Returns all routes for candidate source to destination.
#     """

#     key = (
#         str(candidate.location).strip(),
#         str(destination_location).strip(),
#     )

#     return route_lookup.get(key, [])


# def select_best_vor_route_for_candidate(
#     candidate: CandidateSource,
#     routes: list[Route],
#     order_type: OrderType,
#     decision_datetime: datetime,
#     allowed_transport_modes_config: dict[str, list[str]],
#     calendar_rules: dict,
#     parent_rdc: str,
# ) -> tuple[Optional[Route], Optional[datetime], Optional[datetime], list[ReasonCode]]:
#     """
#     Selects best route/mode for one candidate under VOR rules.

#     Parent RDC source:
#         1. Use MILK_RUN if available.
#         2. If no MILK_RUN, compare AIR and SURFACE by fastest delivery/SLA/cost.

#     Non-parent source:
#         Compare AIR and SURFACE by fastest delivery/SLA/cost.
#     """

#     reason_codes: list[ReasonCode] = []

#     source_location = str(candidate.location).strip()
#     parent_rdc = str(parent_rdc).strip()

#     if not routes:
#         return None, None, None, [ReasonCode.SLA_DATA_NOT_FOUND]

#     allowed_modes_for_vor = {
#         TransportMode.AIR,
#         TransportMode.SURFACE,
#     }

#     if source_location == parent_rdc:
#         milk_run_routes = [
#             route for route in routes
#             if route.transport_mode == TransportMode.MILK_RUN
#         ]

#         valid_milk_run_routes = []

#         for route in milk_run_routes:
#             transport_result = evaluate_transport_eligibility(
#                 route=route,
#                 order_type=order_type,
#                 decision_datetime=decision_datetime,
#                 allowed_transport_modes_config=allowed_transport_modes_config,
#             )

#             if transport_result.eligible:
#                 delivery_result = calculate_route_delivery_result_for_location(
#                     route=route,
#                     order_type=order_type,
#                     decision_datetime=decision_datetime,
#                     calendar_rules=calendar_rules,
#                     adjust_final_delivery_to_working_time=True,
#                 )

#                 valid_milk_run_routes.append(
#                     (
#                         route,
#                         delivery_result.expected_dispatch,
#                         delivery_result.expected_delivery,
#                     )
#                 )

#         if valid_milk_run_routes:
#             selected_route, expected_dispatch, expected_delivery = sorted(
#                 valid_milk_run_routes,
#                 key=lambda item: (
#                     item[0].standard_sla_days,
#                     item[0].transport_cost,
#                 ),
#             )[0]

#             return (
#                 selected_route,
#                 expected_dispatch,
#                 expected_delivery,
#                 [ReasonCode.MILK_RUN_SELECTED],
#             )

#         reason_codes.append(ReasonCode.MILK_RUN_NOT_AVAILABLE)

#     candidate_routes = [
#         route for route in routes
#         if route.transport_mode in allowed_modes_for_vor
#     ]

#     valid_route_options = []

#     for route in candidate_routes:
#         transport_result = evaluate_transport_eligibility(
#             route=route,
#             order_type=order_type,
#             decision_datetime=decision_datetime,
#             allowed_transport_modes_config=allowed_transport_modes_config,
#         )

#         if not transport_result.eligible:
#             reason_codes.extend(transport_result.reason_codes)
#             continue

#         delivery_result = calculate_route_delivery_result_for_location(
#             route=route,
#             order_type=order_type,
#             decision_datetime=decision_datetime,
#             calendar_rules=calendar_rules,
#             adjust_final_delivery_to_working_time=True,
#         )

#         valid_route_options.append(
#             (
#                 route,
#                 delivery_result.expected_dispatch,
#                 delivery_result.expected_delivery,
#             )
#         )

#     if not valid_route_options:
#         if ReasonCode.SLA_DATA_NOT_FOUND not in reason_codes:
#             reason_codes.append(ReasonCode.SLA_DATA_NOT_FOUND)

#         return None, None, None, reason_codes

#     selected_route, expected_dispatch, expected_delivery = sorted(
#         valid_route_options,
#         key=lambda item: (
#             item[2],
#             item[0].standard_sla_days,
#             item[0].transport_cost,
#         ),
#     )[0]

#     route_reason_codes = [ReasonCode.FASTEST_DELIVERY_SELECTED]

#     if selected_route.transport_mode == TransportMode.AIR:
#         route_reason_codes.append(ReasonCode.AIR_SELECTED_FOR_FASTEST_SLA)

#     elif selected_route.transport_mode == TransportMode.SURFACE:
#         route_reason_codes.append(ReasonCode.SURFACE_SELECTED_FOR_FASTEST_SLA)

#     return selected_route, expected_dispatch, expected_delivery, route_reason_codes


# def enrich_vor_candidates_with_best_route(
#     candidates: list[CandidateSource],
#     routes: list[Route],
#     order_line: OrderLine,
#     decision_datetime: datetime,
#     allowed_transport_modes_config: dict[str, list[str]],
#     calendar_rules: dict,
# ) -> list:
#     """
#     Adds best VOR route/mode to each candidate.

#     Candidates without valid route are marked ineligible.
#     """

#     route_lookup = build_route_list_lookup(routes)

#     enriched_candidates: list[CandidateSource] = []

#     for candidate in candidates:
#         candidate_routes = get_routes_for_candidate(
#             candidate=candidate,
#             destination_location=order_line.dealer_code,
#             route_lookup=route_lookup,
#         )

#         selected_route, expected_dispatch, expected_delivery, route_reason_codes = (
#             select_best_vor_route_for_candidate(
#                 candidate=candidate,
#                 routes=candidate_routes,
#                 order_type=order_line.order_type,
#                 decision_datetime=decision_datetime,
#                 allowed_transport_modes_config=allowed_transport_modes_config,
#                 calendar_rules=calendar_rules,
#                 parent_rdc=order_line.parent_rdc,
#             )
#         )

#         merged_reason_codes = list(candidate.rejection_reason_codes)
#         merged_reason_codes.extend(route_reason_codes)

#         if selected_route is None:
#             enriched_candidates.append(
#                 replace(
#                     candidate,
#                     route_available=False,
#                     eligible=False,
#                     rejection_reason_codes=merged_reason_codes,
#                 )
#             )
#             continue

#         enriched_candidates.append(
#             replace(
#                 candidate,
#                 route_available=True,
#                 selected_transport_mode=selected_route.transport_mode,
#                 configured_sla_days=selected_route.standard_sla_days,
#                 transport_cost=selected_route.transport_cost,
#                 expected_dispatch=expected_dispatch,
#                 expected_delivery=expected_delivery,
#                 eligible=candidate.eligible,
#                 rejection_reason_codes=merged_reason_codes,
#             )
#         )

#     return enriched_candidates


def select_parent_full_fill_for_vor(
    candidates: list[CandidateSource],
    requested_quantity: Decimal,
) -> CandidateSource | None:
    """
    Parent full-fill is a hard rule for VOR and ACC.

    If the parent can fully fulfil the effective allowable quantity,
    parent is selected without comparing it with alternative sources.
    """

    parent_full_fill_candidates = [
        candidate
        for candidate in candidates
        if candidate.source_type == SourceType.PARENT_RDC
        and candidate.eligible
        and candidate.eligible_quantity >= requested_quantity
        and candidate.full_fill_capable
    ]

    if not parent_full_fill_candidates:
        return None

    return sorted(
        parent_full_fill_candidates,
        key=lambda candidate: (
            _safe_sla_days(candidate),
            -_safe_ageing_quantity(candidate),
            -_safe_eligible_quantity(candidate),
            _safe_rlt_days(candidate),
            _safe_transport_cost(candidate),
            str(candidate.location).strip(),
        ),
    )[0]


# def select_fastest_full_fill_alternative_for_vor(
#     candidates: list[CandidateSource],
# ):
#     """
#     Selects fastest eligible non-parent full-fill source for VOR.
#     """
#     full_fill_alternatives = [
#     candidate for candidate in candidates
#     if candidate.source_type != SourceType.PARENT_RDC
#     and candidate.eligible
#     and candidate.eligible_quantity > Decimal("0")
#     and candidate.full_fill_capable
#     ]

#     if not full_fill_alternatives:
#         return None

#     return sorted(
#         full_fill_alternatives,
#         key=lambda candidate: (
#             candidate.expected_delivery,
#             candidate.configured_sla_days or 9999,
#             candidate.transport_cost or Decimal("999999999"),
#             str(candidate.location).strip(),
#         ),
#     )[0]


# def select_maximum_partial_for_vor(
#     candidates: list[CandidateSource],
# ):
#     """
#     Selects maximum partial quantity source for VOR when no source can fully fulfil.

#     Important:
#     This includes Parent RDC also.
#     """

#     eligible_candidates = [
#         candidate for candidate in candidates
#         if candidate.eligible
#         and candidate.eligible_quantity > Decimal("0")
#     ]

#     if not eligible_candidates:
#         return None

#     maximum_quantity = max(
#         candidate.eligible_quantity
#         for candidate in eligible_candidates
#     )

#     max_quantity_candidates = [
#         candidate for candidate in eligible_candidates
#         if candidate.eligible_quantity == maximum_quantity
#     ]

#     return sorted(
#         max_quantity_candidates,
#         key=lambda candidate: (
#             candidate.expected_delivery,
#             candidate.configured_sla_days or 9999,
#             candidate.transport_cost or Decimal("999999999"),
#             str(candidate.location).strip(),
#         ),
#     )[0]

def build_vor_selection_result(
    selected_candidate: Optional[CandidateSource],
    requested_quantity: Decimal,
    base_reason_codes: list[ReasonCode],
) -> SourceSelectionResult:
    """
    Builds SourceSelectionResult for VOR.
    """

    if selected_candidate is None:
        return SourceSelectionResult(
            decision=DecisionType.NO_ELIGIBLE_STOCK,
            selected_candidate=None,
            allocated_quantity=Decimal("0"),
            remaining_quantity=requested_quantity,
            reason_codes=base_reason_codes + [ReasonCode.NO_ELIGIBLE_STOCK],
        )

    allocated_quantity = min(
        selected_candidate.eligible_quantity,
        requested_quantity,
    )

    remaining_quantity = requested_quantity - allocated_quantity

    reason_codes = list(base_reason_codes)

    if selected_candidate.source_type == SourceType.PARENT_RDC:
        reason_codes.append(ReasonCode.PARENT_FULL_FILL)
    elif selected_candidate.source_type == SourceType.CLUSTER_RDC:
        reason_codes.append(ReasonCode.CLUSTER_FULL_FILL)
    elif selected_candidate.source_type == SourceType.PAN_INDIA_RDC:
        reason_codes.append(ReasonCode.PAN_INDIA_FULL_FILL)
    elif selected_candidate.source_type == SourceType.VEPDC:
        reason_codes.append(ReasonCode.VEPDC_FULL_FILL)
    else:
        reason_codes.append(ReasonCode.ALTERNATIVE_FULL_FILL)

    if selected_candidate.source_type != SourceType.PARENT_RDC:
        reason_codes.append(ReasonCode.SINGLE_SOURCE_REROUTE)

    if allocated_quantity < requested_quantity:
        reason_codes.append(ReasonCode.MAXIMUM_PARTIAL_FILL)

    return SourceSelectionResult(
        decision=DecisionType.ALLOCATE,
        selected_candidate=selected_candidate,
        allocated_quantity=allocated_quantity,
        remaining_quantity=remaining_quantity,
        reason_codes=reason_codes,
    )

def enrich_vor_acc_candidates_with_rlt(
    candidates: list[CandidateSource],
    rlt_lookup: dict,
    vepdc_location_code: str,
    missing_rdc_rlt: int = 9999,
    missing_vepdc_rlt: int = 9999,
) -> list[CandidateSource]:
    """
    Adds RLT to VOR and ACC candidates.

    Logic:
    - RDC candidates use location-level RLT.
use material/supplier-level RLT.
    """

    enriched_candidates: list[CandidateSource] = []

    for candidate in candidates:
        rlt_days = resolve_rlt_days(
            location=candidate.location,
            material_code=candidate.material_code,
            rlt_lookup=rlt_lookup,
            vepdc_location_code=vepdc_location_code,
            missing_rdc_rlt=missing_rdc_rlt,
            missing_vepdc_rlt=missing_vepdc_rlt,
        )

        enriched_candidates.append(
            replace(
                candidate,
                rlt_days=rlt_days,
            )
        )

    return enriched_candidates

def _safe_sla_days(candidate: CandidateSource) -> int:
    """
    Returns SLA days for sorting.

    Missing SLA receives a high value.
    """

    if candidate.configured_sla_days is None:
        return 9999

    return int(candidate.configured_sla_days)


def _safe_ageing_quantity(candidate: CandidateSource) -> Decimal:
    """
    Returns current state-aware ageing quantity.
    """

    if candidate.ageing_quantity is None:
        return Decimal("0")

    return Decimal(str(candidate.ageing_quantity))


def _safe_eligible_quantity(candidate: CandidateSource) -> Decimal:
    """
    Returns current state-aware eligible stock quantity.
    """

    if candidate.eligible_quantity is None:
        return Decimal("0")

    return Decimal(str(candidate.eligible_quantity))

 
# def apply_rlt_defaults(
#     candidates: list[CandidateSource],
#     default_rlt_days: int = 5,
# ) -> list:
#     """
#     Uses default RLT when a candidate's RLT is missing,
#     invalid, or represented by the 9999 sentinel.
#     """

#     enriched_candidates: list[
#         CandidateSource
#     ] = []

#     for candidate in candidates:
#         raw_rlt = getattr(
#             candidate,
#             "rlt_days",
#             None,
#         )

#         rlt_is_missing = True

#         if (
#             raw_rlt is not None
#             and not pd.isna(raw_rlt)
#         ):
#             try:
#                 numeric_rlt = float(
#                     raw_rlt
#                 )

#                 rlt_is_missing = not (
#                     0 <= numeric_rlt < 9999
#                 )

#             except (
#                 TypeError,
#                 ValueError,
#             ):
#                 rlt_is_missing = True

#         final_rlt_days = (
#             default_rlt_days
#             if rlt_is_missing
#             else int(float(raw_rlt))
#         )

#         enriched_candidates.append(
#             replace(
#                 candidate,
#                 rlt_days=final_rlt_days,
#                 rlt_default_used=(
#                     rlt_is_missing
#                 ),
#                 master_data_default_used=(
#                     rlt_is_missing
#                     or getattr(
#                         candidate,
#                         "route_default_used",
#                         False,
#                     )
#                     or getattr(
#                         candidate,
#                         "sla_default_used",
#                         False,
#                     )
#                 ),
#             )
#         )

#     return enriched_candidates


def _safe_rlt_days(candidate: CandidateSource) -> int:
    """
    Returns RLT days for sorting.

    Missing RLT receives a high value.
    """

    if candidate.rlt_days is None:
        return 9999

    return int(candidate.rlt_days)


def _safe_transport_cost(candidate: CandidateSource) -> Decimal:
    """
    Returns transport cost for sorting.

    Missing cost receives a high value.
    """

    if candidate.transport_cost is None:
        return Decimal("999999999")

    return Decimal(str(candidate.transport_cost))

def select_vor_acc_rerouting_candidate(
    candidates: list[CandidateSource],
    requested_quantity: Decimal,
) -> CandidateSource | None:
    """
    Selects the best VOR/ACC candidate after parent full-fill fails.

    Logic:
    1. If a non-parent full-fill alternative exists, rank full-fill alternatives.
    2. If no source can fully fulfil, include parent and all alternatives.
    3. Keep only candidates with maximum partial quantity.
    4. Rank the selected pool by:
       - minimum SLA
       - maximum current ageing quantity
       - maximum current eligible stock
       - minimum RLT
       - lowest cost
       - location code
    """

    eligible_candidates = [
        candidate
        for candidate in candidates
        if candidate.eligible
        and candidate.eligible_quantity > Decimal("0")
    ]

    if not eligible_candidates:
        return None

    # Parent full-fill was already checked before calling this function.
    # Therefore, full-fill rerouting candidates should be non-parent sources.
    full_fill_alternatives = [
        candidate
        for candidate in eligible_candidates
        if candidate.source_type != SourceType.PARENT_RDC
        and candidate.full_fill_capable
        and candidate.eligible_quantity >= requested_quantity
    ]

    if full_fill_alternatives:
        candidate_pool = full_fill_alternatives

    else:
        # No full-fill source exists.
        # Parent RDC and all alternatives participate in partial allocation.
        maximum_partial_quantity = max(
            candidate.eligible_quantity
            for candidate in eligible_candidates
        )

        candidate_pool = [
            candidate
            for candidate in eligible_candidates
            if candidate.eligible_quantity == maximum_partial_quantity
        ]

    return sorted(
        candidate_pool,
        key=lambda candidate: (
            _safe_sla_days(candidate),
            -_safe_ageing_quantity(candidate),
            -_safe_eligible_quantity(candidate),
            _safe_rlt_days(candidate),
            _safe_transport_cost(candidate),
            str(candidate.location).strip(),
        ),
    )[0]

def select_vor_source(
    candidates: list[CandidateSource],
    requested_quantity: Decimal,
    base_reason_codes: list[ReasonCode],
) -> SourceSelectionResult:
    """
    VOR and ACC source selection.

    Logic:
    1. Parent full-fill first.
    2. If parent cannot full-fill, use full-fill alternatives.
    3. If no full-fill alternative exists, use maximum-partial pool.
    4. Rank candidate pool by:
       - minimum SLA
       - maximum ageing quantity
       - maximum eligible stock
       - minimum RLT
       - lowest cost
       - location code
    """

    parent_candidate = select_parent_full_fill_for_vor(
        candidates=candidates,
        requested_quantity=requested_quantity,
    )

    if parent_candidate is not None:
        return build_vor_selection_result(
            selected_candidate=parent_candidate,
            requested_quantity=requested_quantity,
            base_reason_codes=base_reason_codes,
        )

    alternative_candidate = select_vor_acc_rerouting_candidate(
        candidates=candidates,
        requested_quantity=requested_quantity,
    )

    return build_vor_selection_result(
        selected_candidate=alternative_candidate,
        requested_quantity=requested_quantity,
        base_reason_codes=base_reason_codes,
    )

def select_non_auto_customer_vepdc_only_for_vor(
    candidates: list[CandidateSource],
    requested_quantity: Decimal,
    vepdc_location_code: str,
    base_reason_codes: list[ReasonCode],
) -> SourceSelectionResult:
    """
    Non-auto customers can only be fulfilled from VEPDC.
    """

    vepdc_candidates = [
        candidate for candidate in candidates
        if str(candidate.location).strip() == str(vepdc_location_code).strip()
        and candidate.eligible
        and candidate.eligible_quantity > Decimal("0")
    ]

    if not vepdc_candidates:
        return SourceSelectionResult(
            decision=DecisionType.NO_ELIGIBLE_STOCK,
            selected_candidate=None,
            allocated_quantity=Decimal("0"),
            remaining_quantity=requested_quantity,
            reason_codes=base_reason_codes
            + [
                ReasonCode.NON_AUTO_CUSTOMER_VEPDC_ONLY,
                ReasonCode.NON_AUTO_CUSTOMER_REROUTE_NOT_ALLOWED,
                ReasonCode.NO_ELIGIBLE_STOCK,
            ],
        )

    selected_candidate = sorted(
        vepdc_candidates,
        key=lambda candidate: (
            not candidate.full_fill_capable,
            candidate.expected_delivery,
            candidate.configured_sla_days or 9999,
            candidate.transport_cost or Decimal("999999999"),
        ),
    )[0]

    result = build_vor_selection_result(
        selected_candidate=selected_candidate,
        requested_quantity=requested_quantity,
        base_reason_codes=base_reason_codes
        + [ReasonCode.NON_AUTO_CUSTOMER_VEPDC_ONLY],
    )

    return result

def adjust_vor_selection_result_to_original_quantity(
    selection_result: SourceSelectionResult,
    original_requested_quantity: Decimal,
) -> SourceSelectionResult:
    """
    Adjusts VOR selection result remaining quantity back to original order quantity.

    VOR source selection and inventory checks use effective allowable quantity:
        effective_requested_quantity = min(open_order_qty, max_delivery_qty)

    But final decision should report remaining quantity against original order qty.

    Example:
        original_requested_quantity = 4
        effective_requested_quantity = 1
        allocated_quantity = 1

        final remaining_quantity = 4 - 1 = 3
    """

    adjusted_remaining_quantity = (
        original_requested_quantity - selection_result.allocated_quantity
    )

    if adjusted_remaining_quantity < Decimal("0"):
        adjusted_remaining_quantity = Decimal("0")

    return SourceSelectionResult(
        decision=selection_result.decision,
        selected_candidate=selection_result.selected_candidate,
        allocated_quantity=selection_result.allocated_quantity,
        remaining_quantity=adjusted_remaining_quantity,
        reason_codes=selection_result.reason_codes,
    )

def process_vor_order(
    order_line: OrderLine,
    allowable_quantity: Decimal | None,
    inventory_positions: list[InventoryPosition],
    inventory_state: InventoryStateManager,
    git_shipments: list[GitShipment],
    routes: list[Route],
    location_cluster_map: dict[str, str],
    vepdc_location_code: str,
    allowed_transport_modes_config: dict[str, list[str]],
    calendar_rules: dict,
    rlt_lookup: dict,
    decision_timestamp: datetime,
    mad_lookup: dict,
    norms_lookup: dict,
    missing_norms_combinations: (
        set[tuple[str, str]] | None
    ),
    missing_mad_combinations: set[tuple[str, str]] | None,  
    default_sla_days: int = 5,
    default_rlt_days: int = 5,
    default_route_transport_mode: TransportMode = (
        TransportMode.SURFACE
    ),
    default_route_transport_cost: Decimal = Decimal(
        "999999999"
    ), 
    defer_inventory_allocation: bool = False,
) -> VORWorkflowResult:
    """
    Processes one VOR order line.

    Current VOR scope:
    - Credit block does not block allocation.
    - Allocation quantity is capped by allowable quantity.
    - Parent RDC full-fill first.
    - Parent uses MILK_RUN if available.
    - If parent has no MILK_RUN, compare AIR and SURFACE.
    - Alternatives compare AIR and SURFACE by fastest delivery/SLA/cost.
    - No GIT for now.
    """

    original_requested_quantity = order_line.requested_quantity

    effective_requested_quantity, base_reason_codes = (
        calculate_vor_effective_requested_quantity(
            requested_quantity=original_requested_quantity,
            allowable_quantity=allowable_quantity,
        )
    )

    if order_line.is_credit_blocked:
        base_reason_codes.append(ReasonCode.VOR_CREDIT_BLOCK_IGNORED)

    adjusted_order_line = replace(
        order_line,
        requested_quantity=effective_requested_quantity,
        remaining_quantity=effective_requested_quantity,
    )

    candidates = generate_all_source_candidates(
        order_line=adjusted_order_line,
        inventory_positions=inventory_positions,
        git_shipments=git_shipments,
        location_cluster_map=location_cluster_map,
        vepdc_location_code=vepdc_location_code,
        include_parent_git=False,
    )

    inventory_evaluated_candidates = evaluate_candidates_inventory_from_state(
        candidates=candidates,
        inventory_state=inventory_state,
        order_line=adjusted_order_line,
        mad_lookup=mad_lookup,
        rlt_lookup=rlt_lookup,
        norms_lookup=norms_lookup,
        missing_norms_combinations=(
            missing_norms_combinations
        ),
        missing_mad_combinations=missing_mad_combinations,
        vepdc_location_code=vepdc_location_code,
        default_mad=Decimal("1"),
        missing_rdc_rlt=default_rlt_days,
        missing_vepdc_rlt=default_rlt_days,
        round_up_safety_stock=True,
    )

    route_evaluated_candidates = enrich_candidates_with_route_policy(
        candidates=inventory_evaluated_candidates,
        routes=routes,
        order_type=adjusted_order_line.order_type,
        decision_datetime=decision_timestamp,
        destination_location=adjusted_order_line.dealer_code,
        allowed_transport_modes_config=allowed_transport_modes_config,
        calendar_rules=calendar_rules,
        vepdc_location_code=vepdc_location_code,
    )

    route_evaluated_candidates = (
        apply_route_and_sla_defaults(
            candidates=(
                route_evaluated_candidates
            ),
            decision_datetime=(
                decision_timestamp
            ),
            default_sla_days=(
                default_sla_days
            ),
            default_transport_mode=(
                default_route_transport_mode
            ),
            default_transport_cost=(
                default_route_transport_cost
            ),
        )
    )
    fully_evaluated_candidates = enrich_vor_acc_candidates_with_rlt(
        candidates=route_evaluated_candidates,
        rlt_lookup=rlt_lookup,
        vepdc_location_code=vepdc_location_code,
    )

    fully_evaluated_candidates = (
        apply_rlt_defaults(
            candidates=(
                fully_evaluated_candidates
            ),
            default_rlt_days=(
                default_rlt_days
            ),
        )
    )

    if is_non_auto_customer(order_line.dealer_code):
        selection_result = select_non_auto_customer_vepdc_only_for_vor(
            candidates=fully_evaluated_candidates,
            requested_quantity=effective_requested_quantity,
            vepdc_location_code=vepdc_location_code,
            base_reason_codes=base_reason_codes,
        )
    else:
        selection_result = select_vor_source(
            candidates=fully_evaluated_candidates,
            requested_quantity=effective_requested_quantity,
            base_reason_codes=base_reason_codes,
        )

        selection_result = adjust_vor_selection_result_to_original_quantity(
            selection_result=selection_result,
            original_requested_quantity=original_requested_quantity,
        )
        
    inventory_movement = None

    if (
        not defer_inventory_allocation
        and selection_result.decision == DecisionType.ALLOCATE
        and selection_result.selected_candidate is not None
        and selection_result.allocated_quantity > Decimal("0")
    ):
        try:
            inventory_movement = inventory_state.allocate(
                order_id=order_line.order_id,
                line_id=order_line.line_id,
                location=selection_result.selected_candidate.location,
                material_code=order_line.material_code,
                quantity=selection_result.allocated_quantity,
                movement_timestamp=decision_timestamp,
                reason_code=selection_result.reason_codes[0],
                remarks="VOR order allocation.",
            )
        except (InventoryStateError, DuplicateExecutionError):
            selection_result = SourceSelectionResult(
                decision=DecisionType.RULE_EXCEPTION,
                selected_candidate=None,
                allocated_quantity=Decimal("0"),
                remaining_quantity=effective_requested_quantity,
                reason_codes=[ReasonCode.RULE_EXCEPTION],
            )

    return VORWorkflowResult(
        selection_result=selection_result,
        evaluated_candidates=fully_evaluated_candidates,
        inventory_movement=inventory_movement,
    )