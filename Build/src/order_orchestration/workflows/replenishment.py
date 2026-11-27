from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from typing import Optional
import pandas as pd
from order_orchestration.candidates.evaluator import (
    evaluate_candidates_inventory_from_state,
)

from order_orchestration.transport.route_policy import (
    enrich_candidates_with_route_policy,
    apply_route_and_sla_defaults
)

from order_orchestration.candidates.generator import generate_all_source_candidates
from order_orchestration.data.rlt_resolver import (
    resolve_rlt_days,
    apply_rlt_defaults,
    enrich_candidates_with_rlt
)
from order_orchestration.domain.candidate import CandidateSource
from order_orchestration.domain.enums import DecisionType, ReasonCode, SourceType
from order_orchestration.domain.git import GitShipment
from order_orchestration.domain.inventory import InventoryPosition
from order_orchestration.domain.inventory_movement import InventoryMovement
from order_orchestration.domain.order import OrderLine
from order_orchestration.domain.route import Route
from order_orchestration.exceptions import DuplicateExecutionError, InventoryStateError
from order_orchestration.selection.scored_source_selection import (
    select_best_source_by_weighted_score,
)
from order_orchestration.selection.source_selection import (
    SourceSelectionResult,
    select_best_source,
)
from order_orchestration.state.inventory_state import InventoryStateManager
from order_orchestration.domain.enums import (
    TransportMode,
)
# @dataclass(frozen=True)
# class ReplenishmentWorkflowResult:
#     """
#     Output of Replenishment workflow for one order line.
#     """

#     selection_result: SourceSelectionResult
#     evaluated_candidates: list[CandidateSource]
#     inventory_movement: Optional[InventoryMovement]
@dataclass(frozen=True)
class ReplenishmentWorkflowResult:
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
 

def add_sla_data_not_found_to_selection_if_needed(
    selection_result: SourceSelectionResult,
    candidates: list[CandidateSource],
) -> SourceSelectionResult:
    """
    Adds SLA_DATA_NOT_FOUND at decision level when no source is selected
    and any candidate failed because SLA/route data was missing.
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


def select_non_auto_customer_vepdc_only(
    candidates: list[CandidateSource],
    requested_quantity: Decimal,
    vepdc_location_code: str,
    scoring_config: dict,
) -> SourceSelectionResult:
    """
    Non-auto customer rule.

    Non-auto customers can only be fulfilled from VEPDC.
    If VEPDC has no eligible stock, rerouting is not allowed.
    """

    vepdc_candidates = [
        candidate
        for candidate in candidates
        if str(candidate.location).strip() == str(vepdc_location_code).strip()
    ]

    selection_result, _ = select_best_source_by_weighted_score(
        candidates=vepdc_candidates,
        requested_quantity=requested_quantity,
        scoring_config=scoring_config,
    )

    if selection_result.selected_candidate is not None:
        return SourceSelectionResult(
            decision=selection_result.decision,
            selected_candidate=selection_result.selected_candidate,
            allocated_quantity=selection_result.allocated_quantity,
            remaining_quantity=selection_result.remaining_quantity,
            reason_codes=selection_result.reason_codes
            + [ReasonCode.NON_AUTO_CUSTOMER_VEPDC_ONLY],
        )

    return SourceSelectionResult(
        decision=DecisionType.NO_ELIGIBLE_STOCK,
        selected_candidate=None,
        allocated_quantity=Decimal("0"),
        remaining_quantity=requested_quantity,
        reason_codes=[
            ReasonCode.NON_AUTO_CUSTOMER_VEPDC_ONLY,
            ReasonCode.NON_AUTO_CUSTOMER_REROUTE_NOT_ALLOWED,
            ReasonCode.NO_ELIGIBLE_STOCK,
        ],
    )


def select_replenishment_parent_then_weighted_score(
    candidates: list[CandidateSource],
    requested_quantity: Decimal,
    scoring_config: dict,
) -> SourceSelectionResult:
    """
    Replenishment weighted-score strategy.

    Logic:
    1. Parent RDC full-fill first.
    2. If parent cannot fully fulfil, ignore parent partial.
    3. Score all alternative eligible candidates.
    4. Weighted scoring itself handles:
       - full-fill pool first
       - max-quantity partial pool if no full-fill exists
       - ageing, SLA, RLT, cost, source priority
    """

    parent_candidates = [
        candidate
        for candidate in candidates
        if candidate.source_type == SourceType.PARENT_RDC
        and candidate.eligible
        and candidate.eligible_quantity > Decimal("0")
    ]

    parent_full_fill_candidates = [
        candidate
        for candidate in parent_candidates
        if candidate.full_fill_capable
    ]

    if parent_full_fill_candidates:
        selection_result, _ = select_best_source_by_weighted_score(
            candidates=parent_full_fill_candidates,
            requested_quantity=requested_quantity,
            scoring_config=scoring_config,
        )
        return selection_result

    alternative_candidates = [
        candidate
        for candidate in candidates
        if candidate.source_type != SourceType.PARENT_RDC
    ]

    selection_result, _ = select_best_source_by_weighted_score(
        candidates=alternative_candidates,
        requested_quantity=requested_quantity,
        scoring_config=scoring_config,
    )

    return selection_result


def select_replenishment_parent_then_sequential_rules(
    candidates: list[CandidateSource],
    requested_quantity: Decimal,
    sequential_config: dict,
) -> SourceSelectionResult:
    """
    Backup sequential Replenishment strategy.

    Logic:
    1. Parent RDC full-fill first.
    2. If parent cannot fully fulfil, ignore parent partial.
    3. If alternative full-fill candidates exist, use configured tie-break order.
    4. If no full-fill candidates exist, choose max quantity first, then tie-break.
    """

    parent_candidates = [
        candidate
        for candidate in candidates
        if candidate.source_type == SourceType.PARENT_RDC
        and candidate.eligible
        and candidate.eligible_quantity > Decimal("0")
    ]

    parent_full_fill_candidates = [
        candidate
        for candidate in parent_candidates
        if candidate.full_fill_capable
    ]

    if parent_full_fill_candidates:
        return select_best_source(
            candidates=parent_full_fill_candidates,
            requested_quantity=requested_quantity,
            tie_break_order=[
                "shortest_sla",
                "lowest_cost",
                "source_priority",
            ],
            source_priority={
                "PARENT_RDC": 1,
            },
        )

    alternative_candidates = [
        candidate
        for candidate in candidates
        if candidate.source_type != SourceType.PARENT_RDC
        and candidate.eligible
        and candidate.eligible_quantity > Decimal("0")
    ]

    if not alternative_candidates:
        return SourceSelectionResult(
            decision=DecisionType.NO_ELIGIBLE_STOCK,
            selected_candidate=None,
            allocated_quantity=Decimal("0"),
            remaining_quantity=requested_quantity,
            reason_codes=[ReasonCode.NO_ELIGIBLE_STOCK],
        )

    full_fill_alternatives = [
        candidate
        for candidate in alternative_candidates
        if candidate.full_fill_capable
    ]

    if full_fill_alternatives:
        tie_break_order = sequential_config.get(
            "alternative_full_fill_tie_break_order",
            [
                "ageing_quantity",
                "shortest_sla",
                "shortest_rlt",
                "lowest_cost",
                "source_priority",
            ],
        )

        return select_best_source(
            candidates=full_fill_alternatives,
            requested_quantity=requested_quantity,
            tie_break_order=tie_break_order,
            source_priority={
                "CLUSTER_RDC": 1,
                "PAN_INDIA_RDC": 1,
                "VEPDC": 2,
                "PARENT_GIT": 3,
            },
        )

    tie_break_order = sequential_config.get(
        "alternative_partial_tie_break_order",
        [
            "maximum_quantity",
            "ageing_quantity",
            "shortest_sla",
            "shortest_rlt",
            "lowest_cost",
            "source_priority",
        ],
    )

    return select_best_source(
        candidates=alternative_candidates,
        requested_quantity=requested_quantity,
        tie_break_order=tie_break_order,
        source_priority={
            "CLUSTER_RDC": 1,
            "PAN_INDIA_RDC": 1,
            "VEPDC": 2,
            "PARENT_GIT": 3,
        },
    )


def select_replenishment_source_by_strategy(
    candidates: list[CandidateSource],
    requested_quantity: Decimal,
    replenishment_selection_config: dict,
) -> SourceSelectionResult:
    """
    Selects Replenishment source based on configured strategy.

    Supported strategies:
    - WEIGHTED_SCORING
    - SEQUENTIAL_RULES
    """

    strategy = replenishment_selection_config.get(
        "strategy",
        "WEIGHTED_SCORING",
    )

    if strategy == "WEIGHTED_SCORING":
        scoring_config = replenishment_selection_config.get(
            "weighted_scoring",
            {},
        )

        return select_replenishment_parent_then_weighted_score(
            candidates=candidates,
            requested_quantity=requested_quantity,
            scoring_config=scoring_config,
        )

    if strategy == "SEQUENTIAL_RULES":
        sequential_config = replenishment_selection_config.get(
            "sequential_rules",
            {},
        )

        return select_replenishment_parent_then_sequential_rules(
            candidates=candidates,
            requested_quantity=requested_quantity,
            sequential_config=sequential_config,
        )

    raise ValueError(f"Unsupported replenishment selection strategy: {strategy}")

def normalize_colour_code(
    value,
) -> int | None:
    """
    Converts colour-code values such as 11, 11.0, and '11'
    into an integer.
    """

    if value is None:
        return None

    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None

def is_parent_only_replenishment_colour(
    colour_code,
) -> bool:
    """
    Colour codes 11 to 15 are parent-only Replenishment orders.
    """

    normalized_code = normalize_colour_code(colour_code)

    return (
        normalized_code is not None
        and 11 <= normalized_code <= 15
    )

def is_rerouting_allowed_replenishment_colour(
    colour_code,
) -> bool:
    """
    Colour codes 16 to 20 follow the current parent-first
    Replenishment rerouting flow.
    """

    normalized_code = normalize_colour_code(colour_code)

    return (
        normalized_code is not None
        and 16 <= normalized_code <= 20
    )

def select_replenishment_parent_only(
    candidates: list[CandidateSource],
    requested_quantity: Decimal,
) -> SourceSelectionResult:
    """
    Selects Replenishment source for colour codes 11 to 15.

    Business rules:
    - Only Parent RDC is permitted.
    - Parent must fulfil the complete requested quantity.
    - Parent partial stock must not be allocated.
    - No rerouting to Cluster RDC, PAN-India RDC, or VEPDC.
    """

    parent_full_fill_candidates = [
        candidate
        for candidate in candidates
        if candidate.source_type == SourceType.PARENT_RDC
        and candidate.eligible
        and candidate.eligible_quantity >= requested_quantity
        and candidate.full_fill_capable
    ]

    if parent_full_fill_candidates:
        selected_candidate = sorted(
            parent_full_fill_candidates,
            key=lambda candidate: (
                candidate.expected_delivery
                if candidate.expected_delivery is not None
                else datetime.max,
                candidate.configured_sla_days
                if candidate.configured_sla_days is not None
                else 9999,
                candidate.transport_cost
                if candidate.transport_cost is not None
                else Decimal("999999999"),
                str(candidate.location).strip(),
            ),
        )[0]

        return SourceSelectionResult(
            decision=DecisionType.ALLOCATE,
            selected_candidate=selected_candidate,
            allocated_quantity=requested_quantity,
            remaining_quantity=Decimal("0"),
            reason_codes=[
                ReasonCode.REPLENISHMENT_PARENT_ONLY_COLOUR_CODE,
                ReasonCode.PARENT_ONLY_FULL_FILL,
                ReasonCode.PARENT_FULL_FILL,
            ],
        )

    return SourceSelectionResult(
        decision=DecisionType.NO_ELIGIBLE_STOCK,
        selected_candidate=None,
        allocated_quantity=Decimal("0"),
        remaining_quantity=requested_quantity,
        reason_codes=[
            ReasonCode.REPLENISHMENT_PARENT_ONLY_COLOUR_CODE,
            ReasonCode.PARENT_ONLY_STOCK_INSUFFICIENT,
            ReasonCode.NO_ELIGIBLE_STOCK,
            ReasonCode.REMAINING_QTY_RETURNED_TO_PARENT,
        ],
    )

def append_reason_code_once(
    selection_result: SourceSelectionResult,
    reason_code: ReasonCode,
) -> SourceSelectionResult:
    """
    Adds a reason code only when it is not already present.
    """

    reason_codes = list(selection_result.reason_codes)

    if reason_code not in reason_codes:
        reason_codes.append(reason_code)

    return SourceSelectionResult(
        decision=selection_result.decision,
        selected_candidate=selection_result.selected_candidate,
        allocated_quantity=selection_result.allocated_quantity,
        remaining_quantity=selection_result.remaining_quantity,
        reason_codes=reason_codes,
    )

def process_replenishment_order(
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
    replenishment_selection_config: dict,
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
    apply_safety_stock: bool = True,
    enforce_credit_block: bool = True,
) -> ReplenishmentWorkflowResult:
    """
    Processes one Replenishment order line.

    Replenishment colour-code logic:

    Colour codes 11 to 15:
    - Parent RDC only.
    - Parent full-fill is required.
    - Parent partial stock is not allocated.
    - Rerouting is not allowed.

    Colour codes 16 to 20:
    - Parent full-fill first.
    - If parent cannot fully fulfil, rerouting is allowed.
    - Alternative selection uses the configured weighted-scoring or
    sequential-rules strategy.
    """

    scoring_config = replenishment_selection_config.get(
        "weighted_scoring",
        {},
    )

    if (
        enforce_credit_block
        and order_line.is_credit_blocked
    ):
        selection_result = SourceSelectionResult(
            decision=DecisionType.DATA_EXCEPTION,
            selected_candidate=None,
            allocated_quantity=Decimal("0"),
            remaining_quantity=(
                order_line.requested_quantity
            ),
            reason_codes=[
                ReasonCode.CREDIT_BLOCKED
            ],
        )

        return ReplenishmentWorkflowResult(
            selection_result=selection_result,
            evaluated_candidates=[],
            inventory_movement=None,
        )

    candidates = generate_all_source_candidates(
        order_line=order_line,
        inventory_positions=inventory_positions,
        git_shipments=git_shipments,
        location_cluster_map=location_cluster_map,
        vepdc_location_code=vepdc_location_code,
        include_parent_git=False,
    )

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
    # ZFMO colour codes 16-20:
    # Do not calculate or apply safety stock for allocation.
    #
    # The inventory evaluator runs first so current physical
    # inventory, ageing, MAD, norms, and RLT remain available
    # for audit. Only the safety-stock-related outcome and
    # eligible quantity are overridden here.
    # ---------------------------------------------------------
    if not apply_safety_stock:
        inventory_evaluated_candidates = [
            replace(
                candidate,

                # No safety stock for ZFMO 16-20.
                calculated_safety_stock=Decimal("0"),

                # CandidateSource currently exposes the applied
                # safety stock through candidate.safety_stock.
                safety_stock=Decimal("0"),

                safety_stock_protected=False,

                # This is a business-policy exemption rather than
                # the norms-below-three exemption.
                safety_stock_exempt_due_to_norms=False,

                safety_stock_policy=(
                    "ZFMO_COLOUR_16_NO_SAFETY_STOCK"
                ),

                # Complete current physical stock is eligible.
                eligible_quantity=max(
                    candidate.available_quantity,
                    Decimal("0"),
                ),

                # Recalculate against the order quantity because
                # eligible quantity has changed.
                full_fill_capable=(
                    max(
                        candidate.available_quantity,
                        Decimal("0"),
                    )
                    >= candidate.requested_quantity
                ),

                # Candidate is usable when current physical stock
                # is positive. Route eligibility is determined
                # later during route enrichment.
                eligible=(
                    candidate.available_quantity
                    > Decimal("0")
                ),
            )
            for candidate
            in inventory_evaluated_candidates
        ]

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
    colour_code = normalize_colour_code(order_line.colour_code)

    # ---------------------------------------------------------
    # Replenishment colour codes 11 to 15:
    # Parent-only, full-fill required, no rerouting.
    # ---------------------------------------------------------
    if is_parent_only_replenishment_colour(colour_code):
        selection_result = select_replenishment_parent_only(
            candidates=fully_evaluated_candidates,
            requested_quantity=order_line.requested_quantity,
        )

    # ---------------------------------------------------------
    # Replenishment colour codes 16 to 20:
    # Current parent-first and rerouting flow.
    # ---------------------------------------------------------
    elif is_rerouting_allowed_replenishment_colour(colour_code):
        selection_result = select_replenishment_source_by_strategy(
                        candidates=fully_evaluated_candidates,
                        requested_quantity=order_line.requested_quantity,
                        replenishment_selection_config=replenishment_selection_config,
                    )
        # if is_non_auto_customer(order_line.dealer_code):
        #     selection_result = select_non_auto_customer_vepdc_only(
        #         candidates=fully_evaluated_candidates,
        #         requested_quantity=order_line.requested_quantity,
        #         vepdc_location_code=vepdc_location_code,
        #         scoring_config=scoring_config,
        #     )
        # else:
        #     selection_result = select_replenishment_source_by_strategy(
        #         candidates=fully_evaluated_candidates,
        #         requested_quantity=order_line.requested_quantity,
        #         replenishment_selection_config=replenishment_selection_config,
        #     )

        selection_result = append_reason_code_once(
            selection_result=selection_result,
            reason_code=(
                ReasonCode.REPLENISHMENT_REROUTE_ALLOWED_COLOUR_CODE
            ),
        )

    # ---------------------------------------------------------
    # Defensive fallback for unexpected Replenishment colour.
    # Cleaning should normally prevent this case.
    # ---------------------------------------------------------
    else:
        selection_result = SourceSelectionResult(
            decision=DecisionType.DATA_EXCEPTION,
            selected_candidate=None,
            allocated_quantity=Decimal("0"),
            remaining_quantity=order_line.requested_quantity,
            reason_codes=[
                ReasonCode.INVALID_REPLENISHMENT_COLOUR_CODE,
                ReasonCode.REMAINING_QTY_RETURNED_TO_PARENT,
            ],
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
                remarks="Replenishment order allocation.",
            )
        except (InventoryStateError, DuplicateExecutionError):
            selection_result = SourceSelectionResult(
                decision=DecisionType.RULE_EXCEPTION,
                selected_candidate=None,
                allocated_quantity=Decimal("0"),
                remaining_quantity=order_line.requested_quantity,
                reason_codes=[ReasonCode.RULE_EXCEPTION],
            )

    return ReplenishmentWorkflowResult(
        selection_result=selection_result,
        evaluated_candidates=fully_evaluated_candidates,
        inventory_movement=inventory_movement,
    )
