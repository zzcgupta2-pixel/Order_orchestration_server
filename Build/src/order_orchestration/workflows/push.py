from __future__ import annotations

 
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from typing import Optional
import pandas as pd 
from order_orchestration.candidates.evaluator import (
    evaluate_candidates_inventory_from_state,
    evaluate_candidates_transport_with_calendar_rules,
)
from order_orchestration.transport.route_policy import (
    enrich_candidates_with_route_policy,
    apply_route_and_sla_defaults
)
from order_orchestration.domain.enums import SourceType 

from order_orchestration.data.rlt_resolver import (
    resolve_rlt_days,
    apply_rlt_defaults,
    enrich_candidates_with_rlt
)
from order_orchestration.candidates.generator import generate_all_source_candidates
from order_orchestration.domain.candidate import CandidateSource
from order_orchestration.domain.enums import DecisionType, ReasonCode, TransportMode
from order_orchestration.domain.git import GitShipment
from order_orchestration.domain.inventory import InventoryPosition
from order_orchestration.domain.inventory_movement import InventoryMovement
from order_orchestration.domain.order import OrderLine
from order_orchestration.domain.route import Route
from order_orchestration.exceptions import DuplicateExecutionError, InventoryStateError
from order_orchestration.selection.scored_source_selection import (
    select_best_source_by_weighted_score,
)
from order_orchestration.selection.source_selection import SourceSelectionResult
from order_orchestration.state.inventory_state import InventoryStateManager 

# @dataclass(frozen=True)
# class PushWorkflowResult:
#     """
#     Output of Push workflow for one order line.
    # """

    # selection_result: SourceSelectionResult
    # evaluated_candidates: list[CandidateSource]
    # inventory_movement: Optional[InventoryMovement]
    # inventory_movements: list[InventoryMovement] | None = None

@dataclass(frozen=True)
class PushWorkflowResult:
    selection_result: SourceSelectionResult
    evaluated_candidates: list[CandidateSource]
    inventory_movement: Optional[InventoryMovement]
    inventory_movements: list[InventoryMovement] | None = None
    source_allocations: list | None = None
    moq_allocation_result: object | None = None


# def is_non_auto_customer(dealer_code: str) -> bool:
#     """
#     Identifies non-auto customers.

#     Business rule:
#     - customer/dealer code starts with 1E
#     - OR customer/dealer code equals 1341596
#     """

#     dealer_code = str(dealer_code).strip().upper()
#     return dealer_code.startswith("1E") or dealer_code == "1341596"


# def select_non_auto_customer_vepdc_only(
#     candidates: list[CandidateSource],
#     requested_quantity: Decimal,
#     vepdc_location_code: str,
#     scoring_config: dict,
# ) -> SourceSelectionResult:
#     """
#     Non-auto customers can only be fulfilled from VEPDC.

#     If VEPDC has no valid stock, no rerouting is allowed.
#     """

#     vepdc_candidates = [
#         candidate
#         for candidate in candidates
#         if str(candidate.location).strip() == str(vepdc_location_code).strip()
#     ]

#     selection_result, _ = select_best_source_by_weighted_score(
#         candidates=vepdc_candidates,
#         requested_quantity=requested_quantity,
#         scoring_config=scoring_config,
#     )

#     if selection_result.selected_candidate is not None:
#         return SourceSelectionResult(
#             decision=selection_result.decision,
#             selected_candidate=selection_result.selected_candidate,
#             allocated_quantity=selection_result.allocated_quantity,
#             remaining_quantity=selection_result.remaining_quantity,
#             reason_codes=selection_result.reason_codes
#             + [ReasonCode.NON_AUTO_CUSTOMER_VEPDC_ONLY],
#         )

#     return SourceSelectionResult(
#         decision=DecisionType.NO_ELIGIBLE_STOCK,
#         selected_candidate=None,
#         allocated_quantity=Decimal("0"),
#         remaining_quantity=requested_quantity,
#         reason_codes=[
#             ReasonCode.NON_AUTO_CUSTOMER_VEPDC_ONLY,
#             ReasonCode.NON_AUTO_CUSTOMER_REROUTE_NOT_ALLOWED,
#             ReasonCode.NO_ELIGIBLE_STOCK,
#         ],
#     )


def add_sla_data_not_found_to_selection_if_needed(
    selection_result: SourceSelectionResult,
    candidates: list[CandidateSource],
) -> SourceSelectionResult:
    """
    Adds SLA_DATA_NOT_FOUND at decision level when no source is selected
    and any candidate failed due to missing SLA/route data.
    """

    has_sla_missing = any(
        ReasonCode.SLA_DATA_NOT_FOUND in candidate.rejection_reason_codes
        for candidate in candidates
    )

    if (
        selection_result.decision == DecisionType.NO_ELIGIBLE_STOCK
        and has_sla_missing
        and ReasonCode.SLA_DATA_NOT_FOUND not in selection_result.reason_codes
    ):
        return SourceSelectionResult(
            decision=selection_result.decision,
            selected_candidate=selection_result.selected_candidate,
            allocated_quantity=selection_result.allocated_quantity,
            remaining_quantity=selection_result.remaining_quantity,
            reason_codes=selection_result.reason_codes
            + [ReasonCode.SLA_DATA_NOT_FOUND],
        )

    return selection_result


def select_push_source_by_weighted_score(
    candidates: list[CandidateSource],
    requested_quantity: Decimal,
    scoring_config: dict,
) -> SourceSelectionResult:
    """
    Push source selection.

    Option B:
    - No Parent RDC first rule.
    - All eligible physical sources compete together.
    - Weighted scoring strongly prefers ageing stock.
    - Quantity is handled as gate inside scored_source_selection.
    """

    selection_result, _ = select_best_source_by_weighted_score(
        candidates=candidates,
        requested_quantity=requested_quantity,
        scoring_config=scoring_config,
    )

    return selection_result

def select_parent_full_fill_for_push(
    candidates: list[CandidateSource],
) -> CandidateSource | None:
    """
    Parent RDC full-fill hard rule for Push.

    If parent can fully fulfil, parent wins no matter ageing/SLA/cost.
    """

    parent_candidates = [
        candidate
        for candidate in candidates
        if candidate.source_type == SourceType.PARENT_RDC
        and candidate.eligible
        and candidate.eligible_quantity > Decimal("0")
        and candidate.full_fill_capable
    ]

    if not parent_candidates:
        return None

    return sorted(
        parent_candidates,
        key=lambda candidate: (
            candidate.expected_delivery,
            candidate.configured_sla_days or 9999,
            candidate.transport_cost or Decimal("999999999"),
            str(candidate.location).strip(),
        ),
    )[0]


def build_single_candidate_selection_result_for_push(
    selected_candidate: CandidateSource,
    requested_quantity: Decimal,
    base_reason_codes: list[ReasonCode] | None = None,
) -> SourceSelectionResult:
    """
    Builds single-source Push selection result.
    """

    if base_reason_codes is None:
        base_reason_codes = []

    allocated_quantity = min(
        selected_candidate.eligible_quantity,
        requested_quantity,
    )

    remaining_quantity = requested_quantity - allocated_quantity

    reason_codes = list(base_reason_codes)

    reason_codes.append(ReasonCode.PARENT_FULL_FILL)
    reason_codes.append(ReasonCode.PARENT_FULL_FILL_FORCED)

    return SourceSelectionResult(
        decision=DecisionType.ALLOCATE,
        selected_candidate=selected_candidate,
        allocated_quantity=allocated_quantity,
        remaining_quantity=remaining_quantity,
        reason_codes=reason_codes,
    )

def can_fulfil_push_from_combined_ageing(
    ageing_candidates: list[CandidateSource],
    requested_quantity: Decimal,
) -> bool:
    """
    Checks whether combined ageing stock from multiple locations can fulfil
    full Push order quantity.
    """

    total_ageing_allocatable = sum(
        (
            get_ageing_allocatable_quantity(candidate)
            for candidate in ageing_candidates
        ),
        Decimal("0"),
    )

    return total_ageing_allocatable >= requested_quantity

def get_push_ageing_candidates_for_multi_source(
    candidates: list[CandidateSource],
) -> list:
    """
    Returns eligible Push ageing sources ordered by:

    1. Minimum SLA
    2. Minimum RLT
    3. Maximum eligible quantity
    4. Lowest cost
    5. Location code
    """

    ageing_candidates = [
        candidate
        for candidate in candidates
        if candidate.eligible
        and candidate.eligible_quantity > Decimal("0")
        and candidate.ageing_quantity > Decimal("0")
        and get_ageing_allocatable_quantity(candidate)
        > Decimal("0")
    ]

    return sorted(
        ageing_candidates,
        key=lambda candidate: (
            (
                candidate.configured_sla_days
                if candidate.configured_sla_days is not None
                else 9999
            ),
            (
                candidate.rlt_days
                if candidate.rlt_days is not None
                else 9999
            ),
            -Decimal(
                str(candidate.eligible_quantity or 0)
            ),
            Decimal(
                str(
                    candidate.transport_cost
                    if candidate.transport_cost is not None
                    else Decimal("999999999")
                )
            ),
            str(candidate.location).strip(),
        ),
    )



def allocate_push_multi_source_ageing(
    order_line: OrderLine,
    ageing_candidates: list[CandidateSource],
    inventory_state: InventoryStateManager,
    decision_timestamp: datetime,
) -> tuple[SourceSelectionResult, list[InventoryMovement]]:
    """
    Allocates Push order from multiple ageing-stock locations.

    This is Push-specific exception to single-source rule.

    This function should be called only when combined ageing stock can fulfil
    full requested quantity.
    """

    remaining_quantity = order_line.requested_quantity
    allocated_total = Decimal("0")
    movements: list[InventoryMovement] = []
    first_selected_candidate: CandidateSource | None = None

    for candidate in ageing_candidates:
        if remaining_quantity <= Decimal("0"):
            break

        candidate_ageing_allocatable = min(
            get_ageing_allocatable_quantity(candidate),
            remaining_quantity,
        )

        if candidate_ageing_allocatable <= Decimal("0"):
            continue

        movement = inventory_state.allocate(
            order_id=order_line.order_id,
            line_id=order_line.line_id,
            location=candidate.location,
            material_code=order_line.material_code,
            quantity=candidate_ageing_allocatable,
            movement_timestamp=decision_timestamp,
            reason_code=ReasonCode.PUSH_MULTI_SOURCE_AGEING_ALLOCATION,
            remarks="Push multi-source ageing allocation.",
        )

        movements.append(movement)

        if first_selected_candidate is None:
            first_selected_candidate = candidate

        allocated_total += candidate_ageing_allocatable
        remaining_quantity -= candidate_ageing_allocatable

    reason_codes = [
        ReasonCode.PUSH_MULTI_SOURCE_AGEING_ALLOCATION,
        ReasonCode.AGEING_STOCK_PREFERRED,
    ]

    if remaining_quantity > Decimal("0"):
        reason_codes.append(ReasonCode.MAXIMUM_PARTIAL_FILL)
        reason_codes.append(ReasonCode.REMAINING_QTY_RETURNED_TO_PARENT)

    return (
        SourceSelectionResult(
            decision=DecisionType.ALLOCATE,
            selected_candidate=first_selected_candidate,
            allocated_quantity=allocated_total,
            remaining_quantity=remaining_quantity,
            reason_codes=reason_codes,
        ),
        movements,
    )

def get_ageing_allocatable_quantity(
    candidate: CandidateSource,
) -> Decimal:
    """
    Returns how much ageing stock can be allocated from this candidate.

    Ageing allocation cannot exceed:
    - eligible quantity
    - ageing quantity
    """

    return min(
        candidate.eligible_quantity,
        candidate.ageing_quantity,
    )

# def select_single_source_ageing_full_fill_for_push(
#     candidates: list[CandidateSource],
#     requested_quantity: Decimal,
# ) -> CandidateSource | None:
#     """
#     Push ageing-first rule.

#     If one location has enough ageing stock to fulfil full order quantity,
#     select that location first.
#     """

#     ageing_full_fill_candidates = []

#     for candidate in candidates:
#         if not candidate.eligible:
#             continue

#         if candidate.eligible_quantity <= Decimal("0"):
#             continue

#         ageing_allocatable_quantity = get_ageing_allocatable_quantity(candidate)

#         if ageing_allocatable_quantity >= requested_quantity:
#             ageing_full_fill_candidates.append(candidate)

#     if not ageing_full_fill_candidates:
#         return None

#     return sorted(
#         ageing_full_fill_candidates,
#         key=lambda candidate: (
#             -get_ageing_allocatable_quantity(candidate),
#             candidate.expected_delivery,
#             candidate.configured_sla_days or 9999,
#             candidate.transport_cost or Decimal("999999999"),
#             str(candidate.location).strip(),
#         ),
#     )[0]
def select_single_source_ageing_full_fill_for_push(
    candidates: list[CandidateSource],
    requested_quantity: Decimal,
) -> CandidateSource | None:
    """
    Selects a Push source when one or more locations can fulfil the
    complete requested quantity from current ageing stock.

    Ageing quantity is used only as a qualification rule.

    Ranking among qualifying sources:
    1. Minimum SLA
    2. Minimum RLT
    3. Maximum eligible quantity
    4. Lowest cost
    5. Location code
    """

    ageing_full_fill_candidates = [
        candidate
        for candidate in candidates
        if candidate.eligible
        and candidate.eligible_quantity > Decimal("0")
        and get_ageing_allocatable_quantity(candidate)
        >= requested_quantity
    ]

    if not ageing_full_fill_candidates:
        return None

    return sorted(
        ageing_full_fill_candidates,
        key=lambda candidate: (
            (
                candidate.configured_sla_days
                if candidate.configured_sla_days is not None
                else 9999
            ),
            (
                candidate.rlt_days
                if candidate.rlt_days is not None
                else 9999
            ),
            -Decimal(
                str(candidate.eligible_quantity or 0)
            ),
            Decimal(
                str(
                    candidate.transport_cost
                    if candidate.transport_cost is not None
                    else Decimal("999999999")
                )
            ),
            str(candidate.location).strip(),
        ),
    )[0]

def build_single_source_ageing_selection_result_for_push(
    selected_candidate: CandidateSource,
    requested_quantity: Decimal,
) -> SourceSelectionResult:
    """
    Builds Push selection result when one ageing location can fulfil full order.
    """

    allocated_quantity = requested_quantity
    remaining_quantity = Decimal("0")

    return SourceSelectionResult(
        decision=DecisionType.ALLOCATE,
        selected_candidate=selected_candidate,
        allocated_quantity=allocated_quantity,
        remaining_quantity=remaining_quantity,
        reason_codes=[
            ReasonCode.PUSH_SINGLE_SOURCE_AGEING_ALLOCATION,
            ReasonCode.AGEING_STOCK_PREFERRED,
        ],
    )

def process_push_order(
    order_line: OrderLine,
    inventory_positions: list[InventoryPosition],
    inventory_state: InventoryStateManager,
    git_shipments: list[GitShipment],
    routes: list[Route],
    location_cluster_map: dict[str, str],
    vepdc_location_code: str,
    allowed_transport_modes_config: dict[str, list[str]],
    calendar_rules: dict,
    rlt_lookup: dict,
    push_selection_config: dict,
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
) -> PushWorkflowResult:
    """
    Processes one Push order line.

    Push logic:
    1. Credit block check.
    2. Generate physical candidates only.
    3. State-aware inventory evaluation.
    4. Route/SLA/calendar evaluation.
    5. RLT enrichment.
    6. Non-auto customer VEPDC-only rule.
    7. Weighted scoring across all sources.
    8. Allocate selected source.
    """

    scoring_config = push_selection_config.get("weighted_scoring", {})

    # ---------------------------------------------------------
    # 1. Credit block check
    # ---------------------------------------------------------
    if order_line.is_credit_blocked:
        selection_result = SourceSelectionResult(
            decision=DecisionType.DATA_EXCEPTION,
            selected_candidate=None,
            allocated_quantity=Decimal("0"),
            remaining_quantity=order_line.requested_quantity,
            reason_codes=[ReasonCode.CREDIT_BLOCKED],
        )

        return PushWorkflowResult(
            selection_result=selection_result,
            evaluated_candidates=[],
            inventory_movement=None,
            inventory_movements=[],
        )

    # ---------------------------------------------------------
    # 2. Generate physical candidates only
    # ---------------------------------------------------------
    candidates = generate_all_source_candidates(
        order_line=order_line,
        inventory_positions=inventory_positions,
        git_shipments=git_shipments,
        location_cluster_map=location_cluster_map,
        vepdc_location_code=vepdc_location_code,
        include_parent_git=False,
    )

    # ---------------------------------------------------------
    # 3. State-aware inventory evaluation
    # ---------------------------------------------------------
    # inventory_evaluated_candidates = evaluate_candidates_inventory_from_state(
    #     candidates=candidates,
    #     inventory_state=inventory_state,
    # )
    inventory_evaluated_candidates = evaluate_candidates_inventory_from_state(
        candidates=candidates,
        inventory_state=inventory_state,
        order_line=order_line,
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
    
    # ---------------------------------------------------------
    # 4. Transport, SLA, calendar evaluation
    # ---------------------------------------------------------
    transport_evaluated_candidates = enrich_candidates_with_route_policy(
        candidates=inventory_evaluated_candidates,
        routes=routes,
        order_type=order_line.order_type,
        decision_datetime=decision_timestamp,
        destination_location=order_line.dealer_code,
        allowed_transport_modes_config=allowed_transport_modes_config,
        calendar_rules=calendar_rules,
        vepdc_location_code=vepdc_location_code,
    )

    transport_evaluated_candidates = (
        apply_route_and_sla_defaults(
            candidates=(
                transport_evaluated_candidates
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

    # ---------------------------------------------------------
    # 5. Add RLT
    # ---------------------------------------------------------
    fully_evaluated_candidates = enrich_candidates_with_rlt(
        candidates=transport_evaluated_candidates,
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
    # ---------------------------------------------------------
    # Deferred allocation mode
    # ---------------------------------------------------------
    # The unified MOQ allocator will perform all physical allocations.
    # Push workflow only evaluates candidates and returns them.
    if defer_inventory_allocation:
        deferred_selection_result = (
            select_push_source_by_weighted_score(
                candidates=fully_evaluated_candidates,
                requested_quantity=order_line.requested_quantity,
                scoring_config=scoring_config,
            )
        )

        deferred_selection_result = (
            add_sla_data_not_found_to_selection_if_needed(
                selection_result=deferred_selection_result,
                candidates=fully_evaluated_candidates,
            )
        )

        return PushWorkflowResult(
            selection_result=deferred_selection_result,
            evaluated_candidates=fully_evaluated_candidates,
            inventory_movement=None,
            inventory_movements=[],
            source_allocations=[],
            moq_allocation_result=None,
        )

    # # ---------------------------------------------------------
    # # 6. Non-auto customer VEPDC-only logic
    # # ---------------------------------------------------------
    # if is_non_auto_customer(order_line.dealer_code):
    #     selection_result = select_non_auto_customer_vepdc_only(
    #         candidates=fully_evaluated_candidates,
    #         requested_quantity=order_line.requested_quantity,
    #         vepdc_location_code=vepdc_location_code,
    #         scoring_config=scoring_config,
    #     )

    #     selection_result = add_sla_data_not_found_to_selection_if_needed(
    #         selection_result=selection_result,
    #         candidates=fully_evaluated_candidates,
    #     )

    #     inventory_movement = None

    #     if (
    #         not defer_inventory_allocation
    #         and selection_result.decision == DecisionType.ALLOCATE
    #         and selection_result.selected_candidate is not None
    #         and selection_result.allocated_quantity > Decimal("0")
    #     ):
    #         try:
    #             inventory_movement = inventory_state.allocate(
    #                 order_id=order_line.order_id,
    #                 line_id=order_line.line_id,
    #                 location=selection_result.selected_candidate.location,
    #                 material_code=order_line.material_code,
    #                 quantity=selection_result.allocated_quantity,
    #                 movement_timestamp=decision_timestamp,
    #                 reason_code=selection_result.reason_codes[0],
    #                 remarks="Push order allocation.",
    #             )
    #         except (InventoryStateError, DuplicateExecutionError):
    #             selection_result = SourceSelectionResult(
    #                 decision=DecisionType.RULE_EXCEPTION,
    #                 selected_candidate=None,
    #                 allocated_quantity=Decimal("0"),
    #                 remaining_quantity=order_line.requested_quantity,
    #                 reason_codes=[ReasonCode.RULE_EXCEPTION],
    #             )

    #     if not defer_inventory_allocation:
    #         return PushWorkflowResult(
    #             selection_result=selection_result,
    #             evaluated_candidates=fully_evaluated_candidates,
    #             inventory_movement=inventory_movement,
    #             inventory_movements=[inventory_movement] if inventory_movement is not None else []
    #         )

    # ---------------------------------------------------------
    # 7. Push ageing-first single-source full-fill
    # ---------------------------------------------------------
    single_ageing_candidate = select_single_source_ageing_full_fill_for_push(
        candidates=fully_evaluated_candidates,
        requested_quantity=order_line.requested_quantity,
    )

    if single_ageing_candidate is not None:
        selection_result = (
            build_single_source_ageing_selection_result_for_push(
                selected_candidate=single_ageing_candidate,
                requested_quantity=order_line.requested_quantity,
            )
        )

        inventory_movement = None

        if (
            not defer_inventory_allocation
            and selection_result.selected_candidate is not None
            ):
            try:
                inventory_movement = inventory_state.allocate(
                    order_id=order_line.order_id,
                    line_id=order_line.line_id,
                    location=(
                        selection_result.selected_candidate.location
                    ),
                    material_code=order_line.material_code,
                    quantity=selection_result.allocated_quantity,
                    movement_timestamp=decision_timestamp,
                    reason_code=selection_result.reason_codes[0],
                    remarks="Push single-source ageing allocation.",
                )
            except (
                InventoryStateError,
                DuplicateExecutionError,
            ):
                selection_result = SourceSelectionResult(
                    decision=DecisionType.RULE_EXCEPTION,
                    selected_candidate=None,
                    allocated_quantity=Decimal("0"),
                    remaining_quantity=(
                        order_line.requested_quantity
                    ),
                    reason_codes=[ReasonCode.RULE_EXCEPTION],
                )

        return PushWorkflowResult(
            selection_result=selection_result,
            evaluated_candidates=fully_evaluated_candidates,
            inventory_movement=inventory_movement,
            inventory_movements=(
                [inventory_movement]
                if inventory_movement is not None
                else []
            ),
            source_allocations=[],
            moq_allocation_result=None,
        )

    # ---------------------------------------------------------
    # 8. Push ageing-first multi-source full-fill
    # ---------------------------------------------------------
    ageing_candidates = (
        get_push_ageing_candidates_for_multi_source(
            candidates=fully_evaluated_candidates,
        )
    )

    if can_fulfil_push_from_combined_ageing(
        ageing_candidates=ageing_candidates,
        requested_quantity=order_line.requested_quantity,
    ):
        if defer_inventory_allocation:
            deferred_candidate = (
                ageing_candidates[0]
                if ageing_candidates
                else None
            )

            selection_result = SourceSelectionResult(
                decision=(
                    DecisionType.ALLOCATE
                    if deferred_candidate is not None
                    else DecisionType.NO_ELIGIBLE_STOCK
                ),
                selected_candidate=deferred_candidate,
                allocated_quantity=Decimal("0"),
                remaining_quantity=(
                    order_line.requested_quantity
                ),
                reason_codes=[
                    ReasonCode.PUSH_MULTI_SOURCE_AGEING_ALLOCATION,
                    ReasonCode.AGEING_STOCK_PREFERRED,
                ],
            )

            return PushWorkflowResult(
                selection_result=selection_result,
                evaluated_candidates=fully_evaluated_candidates,
                inventory_movement=None,
                inventory_movements=[],
                source_allocations=[],
                moq_allocation_result=None,
            )

    # ---------------------------------------------------------
    # 9. Parent full-fill hard rule for Push
    # ---------------------------------------------------------
    parent_full_fill_candidate = select_parent_full_fill_for_push(
        candidates=fully_evaluated_candidates,
    )

    if parent_full_fill_candidate is not None:
        selection_result = (
            build_single_candidate_selection_result_for_push(
                selected_candidate=parent_full_fill_candidate,
                requested_quantity=order_line.requested_quantity,
            )
        )

        inventory_movement = None

        if (
            not defer_inventory_allocation
            and selection_result.selected_candidate is not None
            ):
            try:
                inventory_movement = inventory_state.allocate(
                    order_id=order_line.order_id,
                    line_id=order_line.line_id,
                    location=(
                        selection_result
                        .selected_candidate
                        .location
                    ),
                    material_code=order_line.material_code,
                    quantity=selection_result.allocated_quantity,
                    movement_timestamp=decision_timestamp,
                    reason_code=selection_result.reason_codes[0],
                    remarks="Push parent full-fill allocation.",
                )
            except (
                InventoryStateError,
                DuplicateExecutionError,
            ):
                selection_result = SourceSelectionResult(
                    decision=DecisionType.RULE_EXCEPTION,
                    selected_candidate=None,
                    allocated_quantity=Decimal("0"),
                    remaining_quantity=(
                        order_line.requested_quantity
                    ),
                    reason_codes=[ReasonCode.RULE_EXCEPTION],
                )

        return PushWorkflowResult(
            selection_result=selection_result,
            evaluated_candidates=fully_evaluated_candidates,
            inventory_movement=inventory_movement,
            inventory_movements=(
                [inventory_movement]
                if inventory_movement is not None
                else []
            ),
            source_allocations=[],
            moq_allocation_result=None,
        )

    # ---------------------------------------------------------
    # 10. Fallback single-source weighted scoring
    # ---------------------------------------------------------
    selection_result = select_push_source_by_weighted_score(
        candidates=fully_evaluated_candidates,
        requested_quantity=order_line.requested_quantity,
        scoring_config=scoring_config,
    )

    selection_result = add_sla_data_not_found_to_selection_if_needed(
        selection_result=selection_result,
        candidates=fully_evaluated_candidates,
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
                remarks="Push fallback weighted-score allocation.",
            )
        except (InventoryStateError, DuplicateExecutionError):
            selection_result = SourceSelectionResult(
                decision=DecisionType.RULE_EXCEPTION,
                selected_candidate=None,
                allocated_quantity=Decimal("0"),
                remaining_quantity=order_line.requested_quantity,
                reason_codes=[ReasonCode.RULE_EXCEPTION],
            )

    return PushWorkflowResult(
        selection_result=selection_result,
        evaluated_candidates=fully_evaluated_candidates,
        inventory_movement=inventory_movement,
        inventory_movements=[inventory_movement] if inventory_movement is not None else []
    )