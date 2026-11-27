from __future__ import annotations
from dataclasses import dataclass, field
# from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Callable
from typing import Literal
from collections.abc import Sequence

from order_orchestration.allocation.allocation_sorting import (
    build_replenishment_alternative_sort_key,
) 

from order_orchestration.data.moq_resolver import floor_to_moq
from order_orchestration.domain.candidate import CandidateSource
from order_orchestration.domain.enums import ReasonCode, SourceType
from order_orchestration.domain.inventory_movement import InventoryMovement
from order_orchestration.domain.order import OrderLine
from order_orchestration.exceptions import (
    DuplicateExecutionError,
    InventoryStateError,
)
from order_orchestration.state.inventory_state import InventoryStateManager

from order_orchestration.state.git_state import (
    GitReservationMovement,
    GitStateManager,
)

from order_orchestration.allocation.replenishment_git import (
    allocate_priority_replenishment_git,
)

@dataclass(frozen=True)
class SourceAllocation:
    """
    One source contribution to an order.
    """

    candidate: CandidateSource
    allocated_quantity: Decimal
    allocation_sequence: int
    inventory_movement: InventoryMovement


# @dataclass(frozen=True)
# class MOQAllocationResult:
#     """
#     Complete MOQ-based allocation result.
#     """

#     original_requested_quantity: Decimal
#     moq_qty: Decimal
#     moq_default_used: bool
#     moq_eligible_quantity: Decimal
#     moq_remainder_quantity: Decimal
#     total_allocated_quantity: Decimal
#     remaining_quantity: Decimal
#     allocations: list[SourceAllocation]
#     reason_codes: list[ReasonCode]

@dataclass(frozen=True)
class MOQAllocationResult:
    """
    Complete MOQ-based allocation result.
    """

    original_requested_quantity: Decimal
    moq_qty: Decimal
    moq_default_used: bool
    moq_eligible_quantity: Decimal
    moq_remainder_quantity: Decimal

    # Physical allocation only
    total_allocated_quantity: Decimal

    # Deferred GIT reservation only
    total_git_reserved_quantity: Decimal

    # Physical + GIT
    total_fulfilled_quantity: Decimal

    remaining_quantity: Decimal

    allocations: list[SourceAllocation]
    git_reservations: list[
        GitReservationMovement
    ]

    reason_codes: list[ReasonCode | str]

    # Scores calculated for candidates that entered
    # a weighted-scoring pool.
    candidate_score_lookup: dict[
        tuple[str, str],
        dict[str, Decimal | float | int | None],
    ] = field(
        default_factory=dict
    )


def deduplicate_reason_codes(
    reason_codes: Sequence[ReasonCode | str],
) -> list[ReasonCode | str]:
    """
    Removes duplicate reason codes while preserving their order.

    Accepts:
    - list[ReasonCode]
    - list[str]
    - list[ReasonCode | str]
    - tuple[ReasonCode | str, ...]
    """

    return list(dict.fromkeys(reason_codes))

def get_moq_aligned_available_quantity(
    candidate: CandidateSource,
    remaining_quantity: Decimal,
    moq_qty: Decimal,
) -> Decimal:
    """
    Computes how much the candidate may allocate in valid MOQ multiples.
    """

    available_quantity = min(
        candidate.eligible_quantity,
        remaining_quantity,
    )

    return floor_to_moq(
        quantity=available_quantity,
        moq_qty=moq_qty,
    )

def build_quantity_gated_candidate_pool(
    candidates: list[CandidateSource],
    remaining_quantity: Decimal,
    moq_qty: Decimal,
) -> tuple[list[CandidateSource], bool, Decimal]:
    """
    Creates a quantity-qualified candidate pool.

    Logic:
    1. Calculate MOQ-aligned capacity for every eligible candidate.
    2. If one or more candidates can fulfil the complete remaining quantity,
       return only those full-fill candidates.
    3. Otherwise, identify maximum MOQ-aligned partial capacity and return
       only candidates tied at that capacity.

    Returns:
        candidate_pool
        is_full_fill_pool
        pool_allocation_quantity
    """

    candidate_capacities: list[
        tuple[CandidateSource, Decimal]
    ] = []

    for candidate in candidates:
        if not candidate.eligible:
            continue

        if candidate.eligible_quantity is None:
            continue

        if candidate.eligible_quantity <= Decimal("0"):
            continue

        candidate_capacity = (
            get_moq_aligned_available_quantity(
                candidate=candidate,
                remaining_quantity=remaining_quantity,
                moq_qty=moq_qty,
            )
        )

        if candidate_capacity <= Decimal("0"):
            continue

        candidate_capacities.append(
            (
                candidate,
                candidate_capacity,
            )
        )

    if not candidate_capacities:
        return [], False, Decimal("0")

    full_fill_candidates = [
        candidate
        for candidate, capacity in candidate_capacities
        if capacity >= remaining_quantity
    ]

    if full_fill_candidates:
        return (
            full_fill_candidates,
            True,
            remaining_quantity,
        )

    maximum_partial_quantity = max(
        capacity
        for _, capacity in candidate_capacities
    )

    maximum_partial_candidates = [
        candidate
        for candidate, capacity in candidate_capacities
        if capacity == maximum_partial_quantity
    ]

    return (
        maximum_partial_candidates,
        False,
        maximum_partial_quantity,
    )

def deduplicate_candidates_by_location(
    candidates: list[CandidateSource],
) -> list:
    """
    Keeps one candidate per location-material combination.

    Candidate preference:
    1. Parent RDC classification first when the same physical location
       appears under more than one source type.
    2. Eligible candidate first.
    3. Higher eligible quantity.
    4. Lower SLA.
    5. Lower RLT.
    6. Lower transport cost.
    """

    best_candidate_by_key: dict[
        tuple[str, str],
        CandidateSource,
    ] = {}

    def candidate_rank(
        candidate: CandidateSource,
    ) -> tuple:
        eligible_quantity = Decimal(
            str(candidate.eligible_quantity or 0)
        )

        sla_days = (
            candidate.configured_sla_days
            if candidate.configured_sla_days is not None
            else 9999
        )

        rlt_days = (
            candidate.rlt_days
            if candidate.rlt_days is not None
            else 9999
        )

        transport_cost = Decimal(
            str(
                candidate.transport_cost
                if candidate.transport_cost is not None
                else Decimal("999999999")
            )
        )

        is_not_parent = (
            candidate.source_type != SourceType.PARENT_RDC
        )

        return (
            is_not_parent,
            not candidate.eligible,
            -eligible_quantity,
            sla_days,
            rlt_days,
            transport_cost,
            str(candidate.location).strip(),
        )

    for candidate in candidates:
        candidate_key = (
            str(candidate.location).strip(),
            str(candidate.material_code).strip(),
        )

        existing_candidate = best_candidate_by_key.get(
            candidate_key
        )

        if existing_candidate is None:
            best_candidate_by_key[candidate_key] = candidate
            continue

        if candidate_rank(candidate) < candidate_rank(
            existing_candidate
        ):
            best_candidate_by_key[candidate_key] = candidate

    return list(best_candidate_by_key.values())

def allocate_from_candidate(
    order_line: OrderLine,
    candidate: CandidateSource,
    quantity: Decimal,
    allocation_sequence: int,
    inventory_state: InventoryStateManager,
    decision_timestamp: datetime,
    reason_code: ReasonCode,
) -> SourceAllocation:
    movement = inventory_state.allocate(
        order_id=order_line.order_id,
        line_id=order_line.line_id,
        location=candidate.location,
        material_code=order_line.material_code,
        quantity=quantity,
        movement_timestamp=decision_timestamp,
        reason_code=reason_code,
        remarks=(
            f"MOQ allocation sequence {allocation_sequence}. "
            f"Source={candidate.location}."
        ),
    )

    return SourceAllocation(
        candidate=candidate,
        allocated_quantity=quantity,
        allocation_sequence=allocation_sequence,
        inventory_movement=movement,
    )


def allocate_parent_only_full_fill(
    order_line: OrderLine,
    candidates: list[CandidateSource],
    moq_qty: Decimal,
    moq_default_used: bool,
    inventory_state: InventoryStateManager,
    decision_timestamp: datetime,
) -> MOQAllocationResult:
    """
    Strict Replenishment colour 11-15 logic.

    Parent must fully fulfil the MOQ-eligible quantity.
    No partial parent allocation.
    No rerouting.
    """

    candidates = deduplicate_candidates_by_location(
        candidates=candidates,
    )

    original_quantity = order_line.requested_quantity

    moq_eligible_quantity = floor_to_moq(
        quantity=original_quantity,
        moq_qty=moq_qty,
    )

    moq_remainder_quantity = (
        original_quantity - moq_eligible_quantity
    )

    reason_codes: list[ReasonCode] = [
        ReasonCode.REPLENISHMENT_PARENT_ONLY_COLOUR_CODE,
    ]

    if moq_default_used:
        reason_codes.append(
            ReasonCode.MOQ_NOT_FOUND_DEFAULT_ONE_USED
        )

    if moq_remainder_quantity > Decimal("0"):
        reason_codes.extend(
            [
                ReasonCode.ORDER_QTY_PARTIALLY_MOQ_ALIGNED,
                ReasonCode.MOQ_REMAINDER_HELD_AT_PARENT,
            ]
        )

    parent_candidates = [
        candidate
        for candidate in candidates
        if candidate.source_type == SourceType.PARENT_RDC
        and candidate.eligible
    ]

    if not parent_candidates or moq_eligible_quantity <= Decimal("0"):
        reason_codes.extend(
            [
                ReasonCode.PARENT_ONLY_STOCK_INSUFFICIENT,
                ReasonCode.REMAINING_QTY_HELD_AT_PARENT,
            ]
        )

        return MOQAllocationResult(
            original_requested_quantity=original_quantity,
            moq_qty=moq_qty,
            moq_default_used=moq_default_used,
            moq_eligible_quantity=moq_eligible_quantity,
            moq_remainder_quantity=moq_remainder_quantity,
            total_allocated_quantity=Decimal("0"),
            remaining_quantity=original_quantity,
            allocations=[],
            total_git_reserved_quantity=Decimal("0"),
            total_fulfilled_quantity=Decimal("0"),
            git_reservations=[],
            reason_codes=deduplicate_reason_codes(
                reason_codes
            ),
        )

    parent_candidate = sorted(
        parent_candidates,
        key=lambda candidate: (
            str(candidate.location).strip(),
        ),
    )[0]

    parent_moq_available = floor_to_moq(
        quantity=parent_candidate.eligible_quantity,
        moq_qty=moq_qty,
    )

    if parent_moq_available < moq_eligible_quantity:
        reason_codes.extend(
            [
                ReasonCode.PARENT_ONLY_STOCK_INSUFFICIENT,
                ReasonCode.REMAINING_QTY_HELD_AT_PARENT,
            ]
        )

        return MOQAllocationResult(
            original_requested_quantity=original_quantity,
            moq_qty=moq_qty,
            moq_default_used=moq_default_used,
            moq_eligible_quantity=moq_eligible_quantity,
            moq_remainder_quantity=moq_remainder_quantity,
            total_allocated_quantity=Decimal("0"),
            remaining_quantity=original_quantity,
            allocations=[],
            total_git_reserved_quantity=Decimal("0"),
            total_fulfilled_quantity=Decimal("0"),
            git_reservations=[],
            reason_codes=deduplicate_reason_codes(
                reason_codes
            ),
        )

    source_allocation = allocate_from_candidate(
        order_line=order_line,
        candidate=parent_candidate,
        quantity=moq_eligible_quantity,
        allocation_sequence=1,
        inventory_state=inventory_state,
        decision_timestamp=decision_timestamp,
        reason_code=ReasonCode.PARENT_ONLY_FULL_FILL,
    )

    reason_codes.extend(
        [
            ReasonCode.PARENT_ONLY_FULL_FILL,
            ReasonCode.PARENT_FULL_FILL,
        ]
    )

    if moq_remainder_quantity > Decimal("0"):
        reason_codes.append(
            ReasonCode.REMAINING_QTY_HELD_AT_PARENT
        )

    return MOQAllocationResult(
        original_requested_quantity=original_quantity,
        moq_qty=moq_qty,
        moq_default_used=moq_default_used,
        moq_eligible_quantity=moq_eligible_quantity,
        moq_remainder_quantity=moq_remainder_quantity,
        total_allocated_quantity=moq_eligible_quantity,
        remaining_quantity=moq_remainder_quantity,
        allocations=[source_allocation],
        total_git_reserved_quantity=Decimal("0"),
        total_fulfilled_quantity=Decimal("0"),
        git_reservations=[],
        reason_codes=deduplicate_reason_codes(
            reason_codes
        ),
    )


# def deduplicate_candidates_by_location(
#     candidates: list[CandidateSource],
# ) -> list:
#     """
#     Keeps one candidate per location-material pair.

#     Duplicate candidates can occur when multiple route records or inventory
#     rows exist for the same source. The retained candidate is selected using:

#     1. Eligible candidate first
#     2. Higher eligible quantity
#     3. Lower SLA
#     4. Lower RLT
#     5. Lower transport cost
#     """

#     best_candidate_by_key: dict[
#         tuple[str, str],
#         CandidateSource,
#     ] = {}

#     for candidate in candidates:
#         key = (
#             str(candidate.location).strip(),
#             str(candidate.material_code).strip(),
#         )

#         existing_candidate = best_candidate_by_key.get(key)

#         if existing_candidate is None:
#             best_candidate_by_key[key] = candidate
#             continue

#         candidate_sort_key = (
#             not candidate.eligible,
#             -candidate.eligible_quantity,
#             (
#                 candidate.configured_sla_days
#                 if candidate.configured_sla_days is not None
#                 else 9999
#             ),
#             (
#                 candidate.rlt_days
#                 if candidate.rlt_days is not None
#                 else 9999
#             ),
#             (
#                 candidate.transport_cost
#                 if candidate.transport_cost is not None
#                 else Decimal("999999999")
#             ),
#         )

#         existing_sort_key = (
#             not existing_candidate.eligible,
#             -existing_candidate.eligible_quantity,
#             (
#                 existing_candidate.configured_sla_days
#                 if existing_candidate.configured_sla_days is not None
#                 else 9999
#             ),
#             (
#                 existing_candidate.rlt_days
#                 if existing_candidate.rlt_days is not None
#                 else 9999
#             ),
#             (
#                 existing_candidate.transport_cost
#                 if existing_candidate.transport_cost is not None
#                 else Decimal("999999999")
#             ),
#         )

#         if candidate_sort_key < existing_sort_key:
#             best_candidate_by_key[key] = candidate

#     return list(best_candidate_by_key.values())
# def allocate_parent_then_multiple_alternatives(
#     order_line: OrderLine,
#     candidates: list[CandidateSource],
#     moq_qty: Decimal,
#     moq_default_used: bool,
#     inventory_state: InventoryStateManager,
#     decision_timestamp: datetime,
#     alternative_sort_key: Callable[
#         [CandidateSource],
#         tuple,
#     ],
# ) -> MOQAllocationResult:
#     """
#     Parent-first MOQ allocation for VOR, ACC, Replenishment 16-20,
#     and Push fallback.

#     The remaining MOQ-eligible quantity may be completed by multiple
#     alternative locations.
#     """

#     candidates = deduplicate_candidates_by_location(
#             candidates=candidates,
#         )
    
#     original_quantity = order_line.requested_quantity

#     moq_eligible_quantity = floor_to_moq(
#         quantity=original_quantity,
#         moq_qty=moq_qty,
#     )

#     moq_remainder_quantity = (
#         original_quantity - moq_eligible_quantity
#     )

#     remaining_moq_quantity = moq_eligible_quantity
#     allocations: list[SourceAllocation] = []
#     reason_codes: list[ReasonCode] = []

#     if moq_default_used:
#         reason_codes.append(
#             ReasonCode.MOQ_NOT_FOUND_DEFAULT_ONE_USED
#         )

#     if moq_remainder_quantity > Decimal("0"):
#         reason_codes.extend(
#             [
#                 ReasonCode.ORDER_QTY_PARTIALLY_MOQ_ALIGNED,
#                 ReasonCode.MOQ_REMAINDER_HELD_AT_PARENT,
#             ]
#         )

#     if moq_eligible_quantity <= Decimal("0"):
#         reason_codes.extend(
#             [
#                 ReasonCode.INSUFFICIENT_MOQ_ALIGNED_STOCK,
#                 ReasonCode.REMAINING_QTY_HELD_AT_PARENT,
#             ]
#         )

#         return MOQAllocationResult(
#             original_requested_quantity=original_quantity,
#             moq_qty=moq_qty,
#             moq_default_used=moq_default_used,
#             moq_eligible_quantity=Decimal("0"),
#             moq_remainder_quantity=original_quantity,
#             total_allocated_quantity=Decimal("0"),
#             remaining_quantity=original_quantity,
#             allocations=[],
#             reason_codes=deduplicate_reason_codes(
#                 reason_codes
#             ),
#         )

#     parent_location: str | None = None

#     parent_candidates = [
#         candidate
#         for candidate in candidates
#         if candidate.source_type == SourceType.PARENT_RDC
#         and candidate.eligible
#         and candidate.eligible_quantity > Decimal("0")
#     ]
 
#     allocation_sequence = 1

#     if parent_candidates:
#         parent_candidate = sorted(
#             parent_candidates,
#             key=lambda candidate: (
#                 str(candidate.location).strip(),
#             ),
#         )[0]

#         parent_location = str(
#             parent_candidate.location
#         ).strip()

#         parent_allocation_quantity = (
#             get_moq_aligned_available_quantity(
#                 candidate=parent_candidate,
#                 remaining_quantity=remaining_moq_quantity,
#                 moq_qty=moq_qty,
#             )
#         )

#         if parent_allocation_quantity > Decimal("0"):
#             parent_reason = (
#                 ReasonCode.PARENT_FULL_FILL
#                 if parent_allocation_quantity
#                 == remaining_moq_quantity
#                 else ReasonCode.PARENT_MOQ_PARTIAL_ALLOCATION
#             )

#             parent_allocation = allocate_from_candidate(
#                 order_line=order_line,
#                 candidate=parent_candidate,
#                 quantity=parent_allocation_quantity,
#                 allocation_sequence=allocation_sequence,
#                 inventory_state=inventory_state,
#                 decision_timestamp=decision_timestamp,
#                 reason_code=parent_reason,
#             )

#             allocations.append(parent_allocation)
#             remaining_moq_quantity -= parent_allocation_quantity
#             reason_codes.append(parent_reason)
#             allocation_sequence += 1
             
#     # allocated_location_keys = {
#     #     (
#     #         str(allocation.candidate.location).strip(),
#     #         str(order_line.material_code).strip(),
#     #     )
#     #     for allocation in allocations
#     # }

#     alternative_candidates = [
#         candidate
#         for candidate in candidates
#         if candidate.source_type != SourceType.PARENT_RDC
#         and candidate.eligible
#         and candidate.eligible_quantity > Decimal("0")
#         and (
#             parent_location is None
#             or str(candidate.location).strip() != parent_location
#         )
#     ]

#     alternative_candidates = sorted(
#         alternative_candidates,
#         key=alternative_sort_key,
#     )

#     allocated_location_keys = {
#         (
#             str(allocation.candidate.location).strip(),
#             str(order_line.material_code).strip(),
#         )
#         for allocation in allocations
#     }

#     for candidate in alternative_candidates:
#         if remaining_moq_quantity <= Decimal("0"):
#             break

#         candidate_location_key = (
#             str(candidate.location).strip(),
#             str(order_line.material_code).strip(),
#         )

#         if candidate_location_key in allocated_location_keys:
#             continue

#         allocation_quantity = (
#             get_moq_aligned_available_quantity(
#                 candidate=candidate,
#                 remaining_quantity=remaining_moq_quantity,
#                 moq_qty=moq_qty,
#             )
#         )

#         if allocation_quantity <= Decimal("0"):
#             continue

#         try:
#             source_allocation = allocate_from_candidate(
#                 order_line=order_line,
#                 candidate=candidate,
#                 quantity=allocation_quantity,
#                 allocation_sequence=allocation_sequence,
#                 inventory_state=inventory_state,
#                 decision_timestamp=decision_timestamp,
#                 reason_code=ReasonCode.MULTI_SOURCE_MOQ_ALLOCATION,
#             )

#         except DuplicateExecutionError as error:
#             print(
#                 "Duplicate MOQ source skipped:",
#                 order_line.order_id,
#                 order_line.line_id,
#                 candidate.location,
#                 order_line.material_code,
#                 str(error),
#             )
#             continue

#         except InventoryStateError as error:
#             print(
#                 "Invalid MOQ source skipped:",
#                 order_line.order_id,
#                 order_line.line_id,
#                 candidate.location,
#                 order_line.material_code,
#                 str(error),
#             )
#             continue

#         allocations.append(source_allocation)
#         allocated_location_keys.add(candidate_location_key)

#         remaining_moq_quantity -= allocation_quantity
#         allocation_sequence += 1

#     total_allocated_quantity = sum(
#         (
#             allocation.allocated_quantity
#             for allocation in allocations
#         ),
#         Decimal("0"),
#     )

#     final_remaining_quantity = (
#         original_quantity - total_allocated_quantity
#     )

#     if len(allocations) > 1:
#         reason_codes.append(
#             ReasonCode.MULTI_SOURCE_MOQ_ALLOCATION
#         )

#     if total_allocated_quantity > Decimal("0"):
#         reason_codes.append(
#             ReasonCode.MAXIMUM_MOQ_ALIGNED_ALLOCATION
#         )

#     if remaining_moq_quantity > Decimal("0"):
#         reason_codes.extend(
#             [
#                 ReasonCode.INSUFFICIENT_MOQ_ALIGNED_STOCK,
#                 ReasonCode.REMAINING_QTY_HELD_AT_PARENT,
#             ]
#         )

#     elif moq_remainder_quantity > Decimal("0"):
#         reason_codes.append(
#             ReasonCode.REMAINING_QTY_HELD_AT_PARENT
#         )

#     return MOQAllocationResult(
#         original_requested_quantity=original_quantity,
#         moq_qty=moq_qty,
#         moq_default_used=moq_default_used,
#         moq_eligible_quantity=moq_eligible_quantity,
#         moq_remainder_quantity=moq_remainder_quantity,
#         total_allocated_quantity=total_allocated_quantity,
#         remaining_quantity=final_remaining_quantity,
#         allocations=allocations,
#         reason_codes=deduplicate_reason_codes(
#             reason_codes
#         ),
#     )


def allocate_parent_then_multiple_alternatives(
    order_line: OrderLine,
    candidates: list[CandidateSource],
    moq_qty: Decimal,
    moq_default_used: bool,
    inventory_state: InventoryStateManager,
    decision_timestamp: datetime,
    alternative_sort_key: Callable[
        [CandidateSource],
        tuple,
    ],
) -> MOQAllocationResult:
    """
    Parent-first MOQ allocation for VOR, ACC,
    Replenishment colour codes 16-20, and Push fallback.

    Logic:
    1. Floor requested quantity to MOQ multiple.
    2. Allocate maximum MOQ-aligned quantity from parent.
    3. Allocate remaining MOQ-aligned quantity from multiple alternatives.
    4. Do not use the same physical location more than once.
    5. Hold final remaining quantity at the parent RDC.
    """

    candidates = deduplicate_candidates_by_location(
        candidates=candidates,
    )

    original_quantity = order_line.requested_quantity

    moq_eligible_quantity = floor_to_moq(
        quantity=original_quantity,
        moq_qty=moq_qty,
    )

    moq_remainder_quantity = (
        original_quantity - moq_eligible_quantity
    )

    remaining_moq_quantity = moq_eligible_quantity

    allocations: list[SourceAllocation] = []
    reason_codes: list[ReasonCode] = []

    if moq_default_used:
        reason_codes.append(
            ReasonCode.MOQ_NOT_FOUND_DEFAULT_ONE_USED
        )

    if moq_remainder_quantity > Decimal("0"):
        reason_codes.extend(
            [
                ReasonCode.ORDER_QTY_PARTIALLY_MOQ_ALIGNED,
                ReasonCode.MOQ_REMAINDER_HELD_AT_PARENT,
            ]
        )

    if moq_eligible_quantity <= Decimal("0"):
        reason_codes.extend(
            [
                ReasonCode.INSUFFICIENT_MOQ_ALIGNED_STOCK,
                ReasonCode.REMAINING_QTY_HELD_AT_PARENT,
            ]
        )

        return MOQAllocationResult(
            original_requested_quantity=original_quantity,
            moq_qty=moq_qty,
            moq_default_used=moq_default_used,
            moq_eligible_quantity=Decimal("0"),
            moq_remainder_quantity=original_quantity,
            total_allocated_quantity=Decimal("0"),
            remaining_quantity=original_quantity,
            allocations=[],
            total_git_reserved_quantity=Decimal("0"),
            total_fulfilled_quantity=Decimal("0"),
            git_reservations=[],
            reason_codes=deduplicate_reason_codes(
                reason_codes
            ),
        )

    # ---------------------------------------------------------
    # Parent allocation
    # ---------------------------------------------------------
    parent_location: str | None = None

    parent_candidates = [
        candidate
        for candidate in candidates
        if candidate.source_type == SourceType.PARENT_RDC
        and candidate.eligible
        and candidate.eligible_quantity > Decimal("0")
    ]

    allocation_sequence = 1

    if parent_candidates:
        parent_candidate = sorted(
            parent_candidates,
            key=lambda candidate: (
                str(candidate.location).strip(),
            ),
        )[0]

        parent_location = str(
            parent_candidate.location
        ).strip()

        parent_allocation_quantity = (
            get_moq_aligned_available_quantity(
                candidate=parent_candidate,
                remaining_quantity=remaining_moq_quantity,
                moq_qty=moq_qty,
            )
        )

        if parent_allocation_quantity > Decimal("0"):
            parent_reason = (
                ReasonCode.PARENT_FULL_FILL
                if parent_allocation_quantity
                == remaining_moq_quantity
                else ReasonCode.PARENT_MOQ_PARTIAL_ALLOCATION
            )

            parent_allocation = allocate_from_candidate(
                order_line=order_line,
                candidate=parent_candidate,
                quantity=parent_allocation_quantity,
                allocation_sequence=allocation_sequence,
                inventory_state=inventory_state,
                decision_timestamp=decision_timestamp,
                reason_code=parent_reason,
            )

            allocations.append(parent_allocation)

            remaining_moq_quantity -= (
                parent_allocation_quantity
            )

            reason_codes.append(parent_reason)
            allocation_sequence += 1

    # ---------------------------------------------------------
    # Alternative candidates
    # ---------------------------------------------------------
    alternative_candidates = [
        candidate
        for candidate in candidates
        if candidate.source_type != SourceType.PARENT_RDC
        and candidate.eligible
        and candidate.eligible_quantity > Decimal("0")
        and (
            parent_location is None
            or str(candidate.location).strip()
            != parent_location
        )
    ]

    alternative_candidates = sorted(
        alternative_candidates,
        key=alternative_sort_key,
    )

    # Track every physical location already used for this order.
    allocated_location_keys = {
        (
            str(allocation.candidate.location).strip(),
            str(order_line.material_code).strip(),
        )
        for allocation in allocations
    }

    for candidate in alternative_candidates:
        if remaining_moq_quantity <= Decimal("0"):
            break

        candidate_location_key = (
            str(candidate.location).strip(),
            str(order_line.material_code).strip(),
        )

        # Do not allocate the same order-material from the same plant twice.
        if candidate_location_key in allocated_location_keys:
            continue

        allocation_quantity = (
            get_moq_aligned_available_quantity(
                candidate=candidate,
                remaining_quantity=remaining_moq_quantity,
                moq_qty=moq_qty,
            )
        )

        if allocation_quantity <= Decimal("0"):
            continue

        try:
            source_allocation = allocate_from_candidate(
                order_line=order_line,
                candidate=candidate,
                quantity=allocation_quantity,
                allocation_sequence=allocation_sequence,
                inventory_state=inventory_state,
                decision_timestamp=decision_timestamp,
                reason_code=(
                    ReasonCode.MULTI_SOURCE_MOQ_ALLOCATION
                ),
            )

        except DuplicateExecutionError as error:
            print(
                "Duplicate MOQ source skipped:",
                order_line.order_id,
                order_line.line_id,
                candidate.location,
                order_line.material_code,
                str(error),
            )
            continue

        except InventoryStateError as error:
            print(
                "Invalid MOQ source skipped:",
                order_line.order_id,
                order_line.line_id,
                candidate.location,
                order_line.material_code,
                str(error),
            )
            continue

        allocations.append(source_allocation)

        allocated_location_keys.add(
            candidate_location_key
        )

        remaining_moq_quantity -= allocation_quantity
        allocation_sequence += 1

    # ---------------------------------------------------------
    # Final result calculation
    # ---------------------------------------------------------
    total_allocated_quantity = sum(
        (
            allocation.allocated_quantity
            for allocation in allocations
        ),
        Decimal("0"),
    )

    final_remaining_quantity = (
        original_quantity - total_allocated_quantity
    )

    if len(allocations) > 1:
        reason_codes.append(
            ReasonCode.MULTI_SOURCE_MOQ_ALLOCATION
        )

    if total_allocated_quantity > Decimal("0"):
        reason_codes.append(
            ReasonCode.MAXIMUM_MOQ_ALIGNED_ALLOCATION
        )

    if remaining_moq_quantity > Decimal("0"):
        reason_codes.extend(
            [
                ReasonCode.INSUFFICIENT_MOQ_ALIGNED_STOCK,
                ReasonCode.REMAINING_QTY_HELD_AT_PARENT,
            ]
        )

    elif moq_remainder_quantity > Decimal("0"):
        reason_codes.append(
            ReasonCode.REMAINING_QTY_HELD_AT_PARENT
        )

    return MOQAllocationResult(
        original_requested_quantity=original_quantity,
        moq_qty=moq_qty,
        moq_default_used=moq_default_used,
        moq_eligible_quantity=moq_eligible_quantity,
        moq_remainder_quantity=moq_remainder_quantity,
        total_allocated_quantity=total_allocated_quantity,
        remaining_quantity=final_remaining_quantity,
        allocations=allocations,
        total_git_reserved_quantity=Decimal("0"),
        total_fulfilled_quantity=total_allocated_quantity,
        git_reservations=[],
        reason_codes=deduplicate_reason_codes(
            reason_codes
        ),
    )

# def allocate_replenishment_parent_then_gated_weighted_alternatives(
#     order_line: OrderLine,
#     candidates: list[CandidateSource],
#     moq_qty: Decimal,
#     moq_default_used: bool,
#     inventory_state: InventoryStateManager,
#     decision_timestamp: datetime,
#     scoring_config: dict,
# ) -> MOQAllocationResult:
#     """
#     Replenishment colour-code 16-20 allocation.

#     Flow:
#     1. Calculate MOQ-aligned requested quantity.
#     2. Allocate maximum MOQ-aligned quantity from parent.
#     3. Exclude parent from alternatives.
#     4. For every remaining allocation stage:
#        a. Use full-fill alternatives if available.
#        b. Otherwise use only maximum-partial alternatives.
#        c. Calculate normalized weighted scores within that pool.
#        d. Select highest-score candidate.
#        e. Allocate and repeat.
#     5. Hold final remaining quantity at parent.

#     Weighted factors:
#     - SLA: lower is better
#     - Ageing: higher is better
#     - RLT: lower is better
#     - Eligible quantity: higher is better
#     - Cost: lower is better
#     """

#     candidates = deduplicate_candidates_by_location(
#         candidates=candidates,
#     )

#     if moq_qty is None or moq_qty <= Decimal("0"):
#         moq_qty = Decimal("1")

#     original_quantity = order_line.requested_quantity

#     moq_eligible_quantity = floor_to_moq(
#         quantity=original_quantity,
#         moq_qty=moq_qty,
#     )

#     moq_remainder_quantity = (
#         original_quantity - moq_eligible_quantity
#     )

#     remaining_moq_quantity = moq_eligible_quantity

#     allocations: list[SourceAllocation] = []
#     reason_codes: list[ReasonCode] = []

#     if moq_default_used:
#         reason_codes.append(
#             ReasonCode.MOQ_NOT_FOUND_DEFAULT_ONE_USED
#         )

#     if moq_remainder_quantity > Decimal("0"):
#         reason_codes.extend(
#             [
#                 ReasonCode.ORDER_QTY_PARTIALLY_MOQ_ALIGNED,
#                 ReasonCode.MOQ_REMAINDER_HELD_AT_PARENT,
#             ]
#         )

#     if moq_eligible_quantity <= Decimal("0"):
#         reason_codes.extend(
#             [
#                 ReasonCode.INSUFFICIENT_MOQ_ALIGNED_STOCK,
#                 ReasonCode.REMAINING_QTY_HELD_AT_PARENT,
#             ]
#         )

#         return MOQAllocationResult(
#             original_requested_quantity=original_quantity,
#             moq_qty=moq_qty,
#             moq_default_used=moq_default_used,
#             moq_eligible_quantity=Decimal("0"),
#             moq_remainder_quantity=original_quantity,
#             total_allocated_quantity=Decimal("0"),
#             remaining_quantity=original_quantity,
#             allocations=[],
#             total_git_reserved_quantity=Decimal("0"),
#             total_fulfilled_quantity=Decimal("0"),
#             git_reservations=[],
#             reason_codes=deduplicate_reason_codes(
#                 reason_codes
#             ),
#         )

#     allocation_sequence = 1
#     parent_location: str | None = None

#     # ---------------------------------------------------------
#     # 1. Parent MOQ allocation
#     # ---------------------------------------------------------
#     parent_candidates = [
#         candidate
#         for candidate in candidates
#         if candidate.source_type == SourceType.PARENT_RDC
#         and candidate.eligible
#         and candidate.eligible_quantity > Decimal("0")
#     ]

#     if parent_candidates:
#         parent_candidate = sorted(
#             parent_candidates,
#             key=lambda candidate: (
#                 str(candidate.location).strip(),
#             ),
#         )[0]

#         parent_location = str(
#             parent_candidate.location
#         ).strip()

#         parent_allocation_quantity = (
#             get_moq_aligned_available_quantity(
#                 candidate=parent_candidate,
#                 remaining_quantity=remaining_moq_quantity,
#                 moq_qty=moq_qty,
#             )
#         )

#         if parent_allocation_quantity > Decimal("0"):
#             parent_reason = (
#                 ReasonCode.PARENT_FULL_FILL
#                 if parent_allocation_quantity
#                 == remaining_moq_quantity
#                 else ReasonCode.PARENT_MOQ_PARTIAL_ALLOCATION
#             )

#             parent_allocation = allocate_from_candidate(
#                 order_line=order_line,
#                 candidate=parent_candidate,
#                 quantity=parent_allocation_quantity,
#                 allocation_sequence=allocation_sequence,
#                 inventory_state=inventory_state,
#                 decision_timestamp=decision_timestamp,
#                 reason_code=parent_reason,
#             )

#             allocations.append(parent_allocation)

#             remaining_moq_quantity -= (
#                 parent_allocation_quantity
#             )

#             reason_codes.append(parent_reason)
#             allocation_sequence += 1

#     # Parent completed the aligned quantity.
#     if remaining_moq_quantity <= Decimal("0"):
#         total_allocated_quantity = sum(
#             (
#                 allocation.allocated_quantity
#                 for allocation in allocations
#             ),
#             Decimal("0"),
#         )

#         if moq_remainder_quantity > Decimal("0"):
#             reason_codes.append(
#                 ReasonCode.REMAINING_QTY_HELD_AT_PARENT
#             )

#         return MOQAllocationResult(
#             original_requested_quantity=original_quantity,
#             moq_qty=moq_qty,
#             moq_default_used=moq_default_used,
#             moq_eligible_quantity=moq_eligible_quantity,
#             moq_remainder_quantity=moq_remainder_quantity,
#             total_allocated_quantity=total_allocated_quantity,
#             remaining_quantity=(
#                 original_quantity
#                 - total_allocated_quantity
#             ),
#             allocations=allocations,
#             total_git_reserved_quantity=Decimal("0"),
#             total_fulfilled_quantity=total_allocated_quantity,
#             git_reservations=[],
#             reason_codes=deduplicate_reason_codes(
#                 reason_codes
#             ),
#         )

#     # ---------------------------------------------------------
#     # 2. Alternative candidates
#     # ---------------------------------------------------------
#     unused_alternatives = [
#         candidate
#         for candidate in candidates
#         if candidate.source_type != SourceType.PARENT_RDC
#         and candidate.eligible
#         and candidate.eligible_quantity > Decimal("0")
#         and (
#             parent_location is None
#             or str(candidate.location).strip()
#             != parent_location
#         )
#     ]

#     used_location_keys = {
#         (
#             str(allocation.candidate.location).strip(),
#             str(order_line.material_code).strip(),
#         )
#         for allocation in allocations
#     }

#     # ---------------------------------------------------------
#     # 3. Quantity gate, weighted score, allocate, repeat
#     # ---------------------------------------------------------
#     while (
#         remaining_moq_quantity > Decimal("0")
#         and unused_alternatives
#     ):
#         available_alternatives = [
#             candidate
#             for candidate in unused_alternatives
#             if (
#                 str(candidate.location).strip(),
#                 str(order_line.material_code).strip(),
#             )
#             not in used_location_keys
#         ]

#         (
#             candidate_pool,
#             is_full_fill_pool,
#             pool_allocation_quantity,
#         ) = build_quantity_gated_candidate_pool(
#             candidates=available_alternatives,
#             remaining_quantity=remaining_moq_quantity,
#             moq_qty=moq_qty,
#         )

#         if not candidate_pool:
#             break

#         # Scores are calculated only within the quantity-qualified pool.
#         weighted_sort_key, _ = (
#             build_replenishment_alternative_sort_key(
#                 candidates=candidate_pool,
#                 scoring_config=scoring_config,
#             )
#         )

#         selected_candidate = sorted(
#             candidate_pool,
#             key=weighted_sort_key,
#         )[0]

#         allocation_quantity = (
#             remaining_moq_quantity
#             if is_full_fill_pool
#             else pool_allocation_quantity
#         )

#         allocation_quantity = floor_to_moq(
#             quantity=allocation_quantity,
#             moq_qty=moq_qty,
#         )

#         if allocation_quantity <= Decimal("0"):
#             break

#         selected_location_key = (
#             str(selected_candidate.location).strip(),
#             str(order_line.material_code).strip(),
#         )

#         allocation_reason = (
#             ReasonCode.SINGLE_SOURCE_REROUTE
#             if is_full_fill_pool
#             else ReasonCode.MAXIMUM_PARTIAL_FILL
#         )

#         try:
#             source_allocation = allocate_from_candidate(
#                 order_line=order_line,
#                 candidate=selected_candidate,
#                 quantity=allocation_quantity,
#                 allocation_sequence=allocation_sequence,
#                 inventory_state=inventory_state,
#                 decision_timestamp=decision_timestamp,
#                 reason_code=allocation_reason,
#             )

#         except (
#             DuplicateExecutionError,
#             InventoryStateError,
#         ):
#             used_location_keys.add(
#                 selected_location_key
#             )

#             unused_alternatives = [
#                 candidate
#                 for candidate in unused_alternatives
#                 if (
#                     str(candidate.location).strip(),
#                     str(candidate.material_code).strip(),
#                 )
#                 != selected_location_key
#             ]

#             continue

#         allocations.append(source_allocation)

#         remaining_moq_quantity -= allocation_quantity

#         used_location_keys.add(
#             selected_location_key
#         )

#         unused_alternatives = [
#             candidate
#             for candidate in unused_alternatives
#             if (
#                 str(candidate.location).strip(),
#                 str(candidate.material_code).strip(),
#             )
#             != selected_location_key
#         ]

#         if is_full_fill_pool:
#             reason_codes.append(
#                 ReasonCode.SINGLE_SOURCE_REROUTE
#             )
#         else:
#             reason_codes.append(
#                 ReasonCode.MAXIMUM_PARTIAL_FILL
#             )

#         allocation_sequence += 1

#     # ---------------------------------------------------------
#     # 4. Final result
#     # ---------------------------------------------------------
#     total_allocated_quantity = sum(
#         (
#             allocation.allocated_quantity
#             for allocation in allocations
#         ),
#         Decimal("0"),
#     )

#     final_remaining_quantity = (
#         original_quantity - total_allocated_quantity
#     )

#     if len(allocations) > 1:
#         reason_codes.append(
#             ReasonCode.MULTI_SOURCE_MOQ_ALLOCATION
#         )

#     if total_allocated_quantity > Decimal("0"):
#         reason_codes.append(
#             ReasonCode.MAXIMUM_MOQ_ALIGNED_ALLOCATION
#         )

#     if remaining_moq_quantity > Decimal("0"):
#         reason_codes.extend(
#             [
#                 ReasonCode.INSUFFICIENT_MOQ_ALIGNED_STOCK,
#                 ReasonCode.REMAINING_QTY_HELD_AT_PARENT,
#             ]
#         )

#     elif moq_remainder_quantity > Decimal("0"):
#         reason_codes.append(
#             ReasonCode.REMAINING_QTY_HELD_AT_PARENT
#         )

#     return MOQAllocationResult(
#         original_requested_quantity=original_quantity,
#         moq_qty=moq_qty,
#         moq_default_used=moq_default_used,
#         moq_eligible_quantity=moq_eligible_quantity,
#         moq_remainder_quantity=moq_remainder_quantity,
#         total_allocated_quantity=total_allocated_quantity,
#         remaining_quantity=final_remaining_quantity,
#         allocations=allocations,
#         total_git_reserved_quantity=Decimal("0"),
#         total_fulfilled_quantity=total_allocated_quantity,
#         git_reservations=[],
#         reason_codes=deduplicate_reason_codes(
#             reason_codes
#         ),
#     )



def allocate_replenishment_parent_then_gated_weighted_alternatives(
    order_line: OrderLine,
    candidates: list[CandidateSource],
    moq_qty: Decimal,
    moq_default_used: bool,
    inventory_state: InventoryStateManager,
    git_state: GitStateManager,
    decision_timestamp: datetime,
    git_reference_timestamp: datetime,
    scoring_config: dict,
    execution_phase: Literal[
        "FULL",
        "PARENT_ONLY",
        "REMAINDER_ONLY",
    ] = "FULL",

    prior_result: MOQAllocationResult | None = None,
) -> MOQAllocationResult:
    """
    Replenishment colour-code 16-20 allocation.

    Flow:
    1. Calculate MOQ-aligned requested quantity.
    2. Allocate maximum MOQ-aligned quantity from parent.
    3. Exclude parent from alternatives.
    4. For every remaining allocation stage:
       a. Use full-fill alternatives if available.
       b. Otherwise use only maximum-partial alternatives.
       c. Calculate normalized weighted scores within that pool.
       d. Select highest-score candidate.
       e. Allocate and repeat.
    5. Hold final remaining quantity at parent.

    Weighted factors:
    - SLA: lower is better
    - Ageing: higher is better
    - RLT: lower is better
    - Eligible quantity: higher is better
    - Cost: lower is better
    """

    candidates = deduplicate_candidates_by_location(
        candidates=candidates,
    )

    if moq_qty is None or moq_qty <= Decimal("0"):
        moq_qty = Decimal("1")

    # ---------------------------------------------------------
    # Initialize allocation state
    # ---------------------------------------------------------

    candidate_score_lookup: dict[
        tuple[str, str],
        dict[
            str,
            Decimal | float | int | None,
        ],
    ]

    allocations: list[SourceAllocation]

    git_reservations: list[
        GitReservationMovement
    ]

    reason_codes: list[
        ReasonCode | str
    ]


    if prior_result is None:
        original_quantity = (
            order_line.requested_quantity
        )

        moq_eligible_quantity = floor_to_moq(
            quantity=original_quantity,
            moq_qty=moq_qty,
        )

        moq_remainder_quantity = (
            original_quantity
            - moq_eligible_quantity
        )

        remaining_moq_quantity = (
            moq_eligible_quantity
        )

        allocations = []

        git_reservations = []

        reason_codes = []

        candidate_score_lookup = {}

    else:
        original_quantity = (
            prior_result
            .original_requested_quantity
        )

        moq_eligible_quantity = (
            prior_result
            .moq_eligible_quantity
        )

        moq_remainder_quantity = (
            prior_result
            .moq_remainder_quantity
        )

        allocations = list(
            prior_result.allocations
        )

        git_reservations = list(
            getattr(
                prior_result,
                "git_reservations",
                [],
            )
        )

        reason_codes = list(
            prior_result.reason_codes
        )

        candidate_score_lookup = dict(
            getattr(
                prior_result,
                "candidate_score_lookup",
                {},
            )
        )

        prior_physical_quantity = (
            prior_result.total_allocated_quantity
        )

        prior_git_quantity = getattr(
            prior_result,
            "total_git_reserved_quantity",
            Decimal("0"),
        )

        remaining_moq_quantity = max(
            moq_eligible_quantity
            - prior_physical_quantity
            - prior_git_quantity,
            Decimal("0"),
        )

    # candidate_score_lookup: dict[
    #     tuple[str, str],
    #     dict[str, Decimal | float | int | None],
    # ] = {}

    if moq_default_used:
        reason_codes.append(
            ReasonCode.MOQ_NOT_FOUND_DEFAULT_ONE_USED
        )

    if moq_remainder_quantity > Decimal("0"):
        reason_codes.extend(
            [
                ReasonCode.ORDER_QTY_PARTIALLY_MOQ_ALIGNED,
                ReasonCode.MOQ_REMAINDER_HELD_AT_PARENT,
            ]
        )

    if moq_eligible_quantity <= Decimal("0"):
        reason_codes.extend(
            [
                ReasonCode.INSUFFICIENT_MOQ_ALIGNED_STOCK,
                ReasonCode.REMAINING_QTY_HELD_AT_PARENT,
            ]
        )

        return MOQAllocationResult(
            original_requested_quantity=original_quantity,
            moq_qty=moq_qty,
            moq_default_used=moq_default_used,
            moq_eligible_quantity=Decimal("0"),
            moq_remainder_quantity=original_quantity,
            total_allocated_quantity=Decimal("0"),
            remaining_quantity=original_quantity,
            allocations=[],
            total_git_reserved_quantity=Decimal("0"),
            total_fulfilled_quantity=Decimal("0"),
            git_reservations=[],
            reason_codes=deduplicate_reason_codes(
                reason_codes
            ),
        )

    allocation_sequence = 1
    parent_location: str | None = None

    # ---------------------------------------------------------
    # 1. Parent MOQ allocation
    # ---------------------------------------------------------
    # ---------------------------------------------------------
    # Step 1: Parent physical allocation
    # ---------------------------------------------------------
    if (
        execution_phase
        in {"FULL", "PARENT_ONLY"}
        and prior_result is None
    ):
        # Keep your existing parent-allocation code here.
        parent_candidates = [
            candidate
            for candidate in candidates
            if candidate.source_type == SourceType.PARENT_RDC
            and candidate.eligible
            and candidate.eligible_quantity > Decimal("0")
        ]

        if parent_candidates:
            parent_candidate = sorted(
                parent_candidates,
                key=lambda candidate: (
                    str(candidate.location).strip(),
                ),
            )[0]

            parent_location = str(
                parent_candidate.location
            ).strip()

            parent_allocation_quantity = (
                get_moq_aligned_available_quantity(
                    candidate=parent_candidate,
                    remaining_quantity=remaining_moq_quantity,
                    moq_qty=moq_qty,
                )
            )

            if parent_allocation_quantity > Decimal("0"):
                parent_reason = (
                    ReasonCode.PARENT_FULL_FILL
                    if parent_allocation_quantity
                    == remaining_moq_quantity
                    else ReasonCode.PARENT_MOQ_PARTIAL_ALLOCATION
                )

                parent_allocation = allocate_from_candidate(
                    order_line=order_line,
                    candidate=parent_candidate,
                    quantity=parent_allocation_quantity,
                    allocation_sequence=allocation_sequence,
                    inventory_state=inventory_state,
                    decision_timestamp=decision_timestamp,
                    reason_code=parent_reason,
                )

                allocations.append(parent_allocation)

                remaining_moq_quantity -= (
                    parent_allocation_quantity
                )

                reason_codes.append(parent_reason)
                allocation_sequence += 1

    # ---------------------------------------------------------
    # Stop after parent allocation during execution pass 1
    # ---------------------------------------------------------
    if execution_phase == "PARENT_ONLY":
        total_allocated_quantity = sum(
            (
                allocation.allocated_quantity
                for allocation in allocations
            ),
            Decimal("0"),
        )

        total_git_reserved_quantity = sum(
            (
                movement.reserved_quantity
                for movement in git_reservations
            ),
            Decimal("0"),
        )

        total_fulfilled_quantity = (
            total_allocated_quantity
            + total_git_reserved_quantity
        )

        final_remaining_quantity = max(
            original_quantity
            - total_fulfilled_quantity,
            Decimal("0"),
        )

        return MOQAllocationResult(
            original_requested_quantity=(
                original_quantity
            ),
            moq_qty=moq_qty,
            moq_default_used=moq_default_used,
            moq_eligible_quantity=(
                moq_eligible_quantity
            ),
            moq_remainder_quantity=(
                moq_remainder_quantity
            ),
            total_allocated_quantity=(
                total_allocated_quantity
            ),
            total_git_reserved_quantity=(
                total_git_reserved_quantity
            ),
            total_fulfilled_quantity=(
                total_fulfilled_quantity
            ),
            remaining_quantity=(
                final_remaining_quantity
            ),
            allocations=allocations,
            git_reservations=git_reservations,
            reason_codes=list(
                dict.fromkeys(reason_codes)
            ),
            candidate_score_lookup=(
                candidate_score_lookup
            ),
        )

    # ---------------------------------------------------------
    # Step 2: Priority parent GIT arriving within one day
    # ---------------------------------------------------------
    if (
        execution_phase
        in {"FULL", "REMAINDER_ONLY"}
        and remaining_moq_quantity
        > Decimal("0")
    ):
        # print(
        #     "\n[GIT DEBUG: BEFORE RESERVATION]",
        #     {
        #         "order_id": order_line.order_id,
        #         "line_id": order_line.line_id,
        #         "colour_code": order_line.colour_code,
        #         "parent_rdc": order_line.parent_rdc,
        #         "material_code": order_line.material_code,
        #         "moq_qty": moq_qty,
        #         "moq_eligible_quantity": (
        #             moq_eligible_quantity
        #         ),
        #         "remaining_after_parent": (
        #             remaining_moq_quantity
        #         ),
        #         "decision_timestamp": (
        #             decision_timestamp
        #         ),
        #         "git_reference_timestamp": (
        #             git_reference_timestamp
        #         ),
        #     },
        # )

        git_result = (
            allocate_priority_replenishment_git(
                order_line=order_line,
                git_state=git_state,
                remaining_quantity=(
                    remaining_moq_quantity
                ),
                moq_qty=moq_qty,
                git_reference_timestamp=(
                    git_reference_timestamp
                ),
                movement_timestamp=(
                    decision_timestamp
                ),
                maximum_arrival_days=1,
            )
        )

        # print(
        #     "[GIT DEBUG: RESERVATION RESULT]",
        #     {
        #         "reserved_quantity": (
        #             git_result.reserved_quantity
        #         ),
        #         "remaining_after_git": (
        #             git_result.remaining_quantity
        #         ),
        #         "movement_created": (
        #             git_result.movement is not None
        #         ),
        #         "reason_codes": (
        #             git_result.reason_codes
        #         ),
        #     },
        # )

        if (
            git_result.reserved_quantity
            > Decimal("0")
        ):
            remaining_moq_quantity = (
                git_result.remaining_quantity
            )

            if git_result.movement is not None:
                git_reservations.append(
                    git_result.movement
                )

            reason_codes.extend(
                git_result.reason_codes
            )


    # ---------------------------------------------------------
    # 2. Alternative candidates
    # ---------------------------------------------------------
    if (
        execution_phase
        in {"FULL", "REMAINDER_ONLY"}
        and remaining_moq_quantity
        > Decimal("0")
    ):
        # Build unused alternatives and continue
        # with your existing quantity-gating
        # and scoring logic.
        unused_alternatives = [
            candidate
            for candidate in candidates
            if candidate.source_type != SourceType.PARENT_RDC
            and candidate.eligible
            and candidate.eligible_quantity > Decimal("0")
            and (
                parent_location is None
                or str(candidate.location).strip()
                != parent_location
            )
        ]

        used_location_keys = {
            (
                str(allocation.candidate.location).strip(),
                str(order_line.material_code).strip(),
            )
            for allocation in allocations
        }

        # ---------------------------------------------------------
        # 3. Quantity gate, weighted score, allocate, repeat
        # ---------------------------------------------------------
        while (
            remaining_moq_quantity > Decimal("0")
            and unused_alternatives
        ):
            available_alternatives = [
                candidate
                for candidate in unused_alternatives
                if (
                    str(candidate.location).strip(),
                    str(order_line.material_code).strip(),
                )
                not in used_location_keys
            ]

            (
                candidate_pool,
                is_full_fill_pool,
                pool_allocation_quantity,
            ) = build_quantity_gated_candidate_pool(
                candidates=available_alternatives,
                remaining_quantity=remaining_moq_quantity,
                moq_qty=moq_qty,
            )

            if not candidate_pool:
                break

            (
                weighted_sort_key,
                iteration_score_lookup,
            ) = build_replenishment_alternative_sort_key(
                candidates=candidate_pool,
                scoring_config=scoring_config,
            )

            candidate_score_lookup.update(
                iteration_score_lookup
            )

            # # Scores are calculated only within the quantity-qualified pool.
            # weighted_sort_key, _ = (
            #     build_replenishment_alternative_sort_key(
            #         candidates=candidate_pool,
            #         scoring_config=scoring_config,
            #     )
            # )

            selected_candidate = sorted(
                candidate_pool,
                key=weighted_sort_key,
            )[0]

            allocation_quantity = (
                remaining_moq_quantity
                if is_full_fill_pool
                else pool_allocation_quantity
            )

            allocation_quantity = floor_to_moq(
                quantity=allocation_quantity,
                moq_qty=moq_qty,
            )

            if allocation_quantity <= Decimal("0"):
                break

            selected_location_key = (
                str(selected_candidate.location).strip(),
                str(order_line.material_code).strip(),
            )

            allocation_reason = (
                ReasonCode.SINGLE_SOURCE_REROUTE
                if is_full_fill_pool
                else ReasonCode.MAXIMUM_PARTIAL_FILL
            )

            try:
                source_allocation = allocate_from_candidate(
                    order_line=order_line,
                    candidate=selected_candidate,
                    quantity=allocation_quantity,
                    allocation_sequence=allocation_sequence,
                    inventory_state=inventory_state,
                    decision_timestamp=decision_timestamp,
                    reason_code=allocation_reason,
                )

            except (
                DuplicateExecutionError,
                InventoryStateError,
            ):
                used_location_keys.add(
                    selected_location_key
                )

                unused_alternatives = [
                    candidate
                    for candidate in unused_alternatives
                    if (
                        str(candidate.location).strip(),
                        str(candidate.material_code).strip(),
                    )
                    != selected_location_key
                ]

                continue

            allocations.append(source_allocation)

            remaining_moq_quantity -= allocation_quantity

            used_location_keys.add(
                selected_location_key
            )

            unused_alternatives = [
                candidate
                for candidate in unused_alternatives
                if (
                    str(candidate.location).strip(),
                    str(candidate.material_code).strip(),
                )
                != selected_location_key
            ]

            if is_full_fill_pool:
                reason_codes.append(
                    ReasonCode.SINGLE_SOURCE_REROUTE
                )
            else:
                reason_codes.append(
                    ReasonCode.MAXIMUM_PARTIAL_FILL
                )

            allocation_sequence += 1

    # ---------------------------------------------------------
    # 4. Final result
    # # ---------------------------------------------------------
    # total_allocated_quantity = sum(
    #     (
    #         allocation.allocated_quantity
    #         for allocation in allocations
    #     ),
    #     Decimal("0"),
    # )

    # final_remaining_quantity = (
    #     original_quantity - total_allocated_quantity
    # )

    # if len(allocations) > 1:
    #     reason_codes.append(
    #         ReasonCode.MULTI_SOURCE_MOQ_ALLOCATION
    #     )

    # if total_allocated_quantity > Decimal("0"):
    #     reason_codes.append(
    #         ReasonCode.MAXIMUM_MOQ_ALIGNED_ALLOCATION
    #     )

    # if remaining_moq_quantity > Decimal("0"):
    #     reason_codes.extend(
    #         [
    #             ReasonCode.INSUFFICIENT_MOQ_ALIGNED_STOCK,
    #             ReasonCode.REMAINING_QTY_HELD_AT_PARENT,
    #         ]
    #     )

    # elif moq_remainder_quantity > Decimal("0"):
    #     reason_codes.append(
    #         ReasonCode.REMAINING_QTY_HELD_AT_PARENT
    #     )

    # return MOQAllocationResult(
    #     original_requested_quantity=original_quantity,
    #     moq_qty=moq_qty,
    #     moq_default_used=moq_default_used,
    #     moq_eligible_quantity=moq_eligible_quantity,
    #     moq_remainder_quantity=moq_remainder_quantity,
    #     total_allocated_quantity=total_allocated_quantity,
    #     remaining_quantity=final_remaining_quantity,
    #     allocations=allocations,
    #     total_git_reserved_quantity=Decimal("0"),
    #     total_fulfilled_quantity=total_allocated_quantity,
    #     git_reservations=[],
    #     reason_codes=deduplicate_reason_codes(
    #         reason_codes
    #     ),
    # )
    # ---------------------------------------------------------
    # Step 5: Final result calculation
    # ---------------------------------------------------------
    total_allocated_quantity = sum(
        (
            allocation.allocated_quantity
            for allocation in allocations
        ),
        Decimal("0"),
    )

    total_git_reserved_quantity = sum(
        (
            movement.reserved_quantity
            for movement in git_reservations
        ),
        Decimal("0"),
    )

    total_fulfilled_quantity = (
        total_allocated_quantity
        + total_git_reserved_quantity
    )

    final_remaining_quantity = max(
        original_quantity
        - total_fulfilled_quantity,
        Decimal("0"),
    )

    # Number of physical and GIT contributions.
    contributing_source_count = (
        len(allocations)
        + len(git_reservations)
    )

    if contributing_source_count > 1:
        reason_codes.append(
            ReasonCode.MULTI_SOURCE_MOQ_ALLOCATION
        )

    # This reason applies when physical or GIT quantity
    # contributed to fulfilment.
    if total_fulfilled_quantity > Decimal("0"):
        reason_codes.append(
            ReasonCode.MAXIMUM_MOQ_ALIGNED_ALLOCATION
        )

    # remaining_moq_quantity tracks the aligned quantity that
    # remains after parent physical, GIT, and alternatives.
    if remaining_moq_quantity > Decimal("0"):
        reason_codes.extend(
            [
                ReasonCode.INSUFFICIENT_MOQ_ALIGNED_STOCK,
                ReasonCode.REMAINING_QTY_HELD_AT_PARENT,
            ]
        )

    # Aligned quantity was fulfilled, but the order still has
    # an unavoidable quantity below MOQ.
    elif moq_remainder_quantity > Decimal("0"):
        reason_codes.append(
            ReasonCode.REMAINING_QTY_HELD_AT_PARENT
        )

    # ---------------------------------------------------------
    # Step 6: Return final physical + GIT result
    # ---------------------------------------------------------
    return MOQAllocationResult(
        original_requested_quantity=(
            original_quantity
        ),
        moq_qty=moq_qty,
        moq_default_used=moq_default_used,
        moq_eligible_quantity=(
            moq_eligible_quantity
        ),
        moq_remainder_quantity=(
            moq_remainder_quantity
        ),
        total_allocated_quantity=(
            total_allocated_quantity
        ),
        total_git_reserved_quantity=(
            total_git_reserved_quantity
        ),
        total_fulfilled_quantity=(
            total_fulfilled_quantity
        ),
        remaining_quantity=(
            final_remaining_quantity
        ),
        allocations=allocations,
        git_reservations=git_reservations,
        reason_codes=deduplicate_reason_codes(
            reason_codes
        ),
        candidate_score_lookup=(
            candidate_score_lookup
        ),
    )

def _safe_decimal(
    value,
    default: Decimal = Decimal("0"),
) -> Decimal:
    if value is None:
        return default

    try:
        return Decimal(str(value))
    except Exception:
        return default


def _push_ageing_priority_key(
    candidate: CandidateSource,
) -> tuple:
    """
    Push ageing-source ranking.

    Ageing quantity is used only to determine whether the source can
    contribute ageing stock.

    Ranking:
    1. Minimum SLA
    2. Minimum RLT
    3. Maximum eligible quantity
    4. Lowest cost
    5. Location code
    """

    sla_days = (
        candidate.configured_sla_days
        if candidate.configured_sla_days is not None
        else 9999
    )

    rlt_days = (
        candidate.rlt_days
        if candidate.rlt_days is not None
        else 9999
    )

    eligible_quantity = _safe_decimal(
        candidate.eligible_quantity,
        Decimal("0"),
    )

    transport_cost = _safe_decimal(
        candidate.transport_cost,
        Decimal("999999999"),
    )

    return (
        sla_days,
        rlt_days,
        -eligible_quantity,
        transport_cost,
        str(candidate.location).strip(),
    )


def get_push_moq_aligned_ageing_quantity(
    candidate: CandidateSource,
    remaining_quantity: Decimal,
    moq_qty: Decimal,
) -> Decimal:
    """
    Returns current usable ageing quantity in complete MOQ multiples.

    Ageing allocation cannot exceed:
    - current ageing quantity
    - current eligible quantity
    - remaining order quantity
    """

    raw_ageing_allocatable = min(
        _safe_decimal(
            candidate.ageing_quantity,
            Decimal("0"),
        ),
        _safe_decimal(
            candidate.eligible_quantity,
            Decimal("0"),
        ),
        remaining_quantity,
    )

    return floor_to_moq(
        quantity=raw_ageing_allocatable,
        moq_qty=moq_qty,
    )


def allocate_push_parent_then_ageing_then_weighted(
    order_line: OrderLine,
    candidates: list[CandidateSource],
    moq_qty: Decimal,
    moq_default_used: bool,
    inventory_state: InventoryStateManager,
    decision_timestamp: datetime,
    scoring_config: dict,
) -> MOQAllocationResult:
    """
    MOQ-based Push allocation.

    Flow:
    1. Floor requested quantity to MOQ multiple.
    2. Allocate maximum MOQ-aligned quantity from parent once.
    3. For remaining aligned quantity:
       a. Single-source ageing full-fill.
       b. Multi-source ageing full-fill.
       c. Weighted-scoring fallback across alternatives.
    4. Do not use parent again after initial parent allocation.
    5. Hold final remaining quantity at parent.
    """

    candidates = deduplicate_candidates_by_location(
        candidates=candidates,
    )

    original_quantity = order_line.requested_quantity

    moq_eligible_quantity = floor_to_moq(
        quantity=original_quantity,
        moq_qty=moq_qty,
    )

    moq_remainder_quantity = (
        original_quantity - moq_eligible_quantity
    )

    remaining_moq_quantity = moq_eligible_quantity

    allocations: list[SourceAllocation] = []
    reason_codes: list[ReasonCode] = []
    candidate_score_lookup: dict[
        tuple[str, str],
        dict[str, Decimal | float | int | None],
    ] = {}

    if moq_default_used:
        reason_codes.append(
            ReasonCode.MOQ_NOT_FOUND_DEFAULT_ONE_USED
        )

    if moq_remainder_quantity > Decimal("0"):
        reason_codes.extend(
            [
                ReasonCode.ORDER_QTY_PARTIALLY_MOQ_ALIGNED,
                ReasonCode.MOQ_REMAINDER_HELD_AT_PARENT,
            ]
        )

    if moq_eligible_quantity <= Decimal("0"):
        reason_codes.extend(
            [
                ReasonCode.INSUFFICIENT_MOQ_ALIGNED_STOCK,
                ReasonCode.REMAINING_QTY_HELD_AT_PARENT,
            ]
        )

        return MOQAllocationResult(
            original_requested_quantity=original_quantity,
            moq_qty=moq_qty,
            moq_default_used=moq_default_used,
            moq_eligible_quantity=Decimal("0"),
            moq_remainder_quantity=original_quantity,
            total_allocated_quantity=Decimal("0"),
            remaining_quantity=original_quantity,
            allocations=[],
            total_git_reserved_quantity=Decimal("0"),
            total_fulfilled_quantity=Decimal("0"),
            git_reservations=[],
            reason_codes=deduplicate_reason_codes(
                reason_codes
            ),
        )

    allocation_sequence = 1
    parent_location: str | None = None

    # ---------------------------------------------------------
    # Step 1: Allocate maximum MOQ quantity from parent once
    # ---------------------------------------------------------
    parent_candidates = [
        candidate
        for candidate in candidates
        if candidate.source_type == SourceType.PARENT_RDC
        and candidate.eligible
        and candidate.eligible_quantity > Decimal("0")
    ]

    if parent_candidates:
        parent_candidate = sorted(
            parent_candidates,
            key=lambda candidate: (
                str(candidate.location).strip(),
            ),
        )[0]

        parent_location = str(
            parent_candidate.location
        ).strip()

        parent_allocation_quantity = (
            get_moq_aligned_available_quantity(
                candidate=parent_candidate,
                remaining_quantity=remaining_moq_quantity,
                moq_qty=moq_qty,
            )
        )

        if parent_allocation_quantity > Decimal("0"):
            parent_reason = (
                ReasonCode.PARENT_FULL_FILL
                if parent_allocation_quantity
                == remaining_moq_quantity
                else ReasonCode.PUSH_PARENT_MOQ_ALLOCATION
            )

            parent_allocation = allocate_from_candidate(
                order_line=order_line,
                candidate=parent_candidate,
                quantity=parent_allocation_quantity,
                allocation_sequence=allocation_sequence,
                inventory_state=inventory_state,
                decision_timestamp=decision_timestamp,
                reason_code=parent_reason,
            )

            allocations.append(parent_allocation)

            remaining_moq_quantity -= (
                parent_allocation_quantity
            )

            reason_codes.append(parent_reason)
            allocation_sequence += 1

    # Parent fulfilled all aligned quantity.
    if remaining_moq_quantity <= Decimal("0"):
        total_allocated_quantity = sum(
            (
                allocation.allocated_quantity
                for allocation in allocations
            ),
            Decimal("0"),
        )

        if moq_remainder_quantity > Decimal("0"):
            reason_codes.append(
                ReasonCode.REMAINING_QTY_HELD_AT_PARENT
            )

        return MOQAllocationResult(
            original_requested_quantity=original_quantity,
            moq_qty=moq_qty,
            moq_default_used=moq_default_used,
            moq_eligible_quantity=moq_eligible_quantity,
            moq_remainder_quantity=moq_remainder_quantity,
            total_allocated_quantity=total_allocated_quantity,
            remaining_quantity=(
                original_quantity
                - total_allocated_quantity
            ),
            allocations=allocations,
            total_git_reserved_quantity=Decimal("0"),
            total_fulfilled_quantity=total_allocated_quantity,
            git_reservations=[],
            reason_codes=deduplicate_reason_codes(
                reason_codes
            ),
        )

    # ---------------------------------------------------------
    # Alternative candidates only
    # Parent must not be checked again
    # ---------------------------------------------------------
    alternative_candidates = [
        candidate
        for candidate in candidates
        if candidate.source_type != SourceType.PARENT_RDC
        and candidate.eligible
        and candidate.eligible_quantity > Decimal("0")
        and (
            parent_location is None
            or str(candidate.location).strip()
            != parent_location
        )
    ]

    allocated_location_keys = {
        (
            str(allocation.candidate.location).strip(),
            str(order_line.material_code).strip(),
        )
        for allocation in allocations
    }

    # ---------------------------------------------------------
    # Step 2: Single-source ageing full-fill
    # ---------------------------------------------------------
    single_source_ageing_candidates = [
        candidate
        for candidate in alternative_candidates
        if get_push_moq_aligned_ageing_quantity(
            candidate=candidate,
            remaining_quantity=remaining_moq_quantity,
            moq_qty=moq_qty,
        )
        >= remaining_moq_quantity
    ]

    if single_source_ageing_candidates:
        selected_ageing_candidate = sorted(
            single_source_ageing_candidates,
            key=_push_ageing_priority_key,
        )[0]

        source_allocation = allocate_from_candidate(
            order_line=order_line,
            candidate=selected_ageing_candidate,
            quantity=remaining_moq_quantity,
            allocation_sequence=allocation_sequence,
            inventory_state=inventory_state,
            decision_timestamp=decision_timestamp,
            reason_code=(
                ReasonCode
                .PUSH_SINGLE_SOURCE_AGEING_ALLOCATION
            ),
        )

        allocations.append(source_allocation)

        allocated_location_keys.add(
            (
                str(
                    selected_ageing_candidate.location
                ).strip(),
                str(order_line.material_code).strip(),
            )
        )

        remaining_moq_quantity = Decimal("0")

        reason_codes.extend(
            [
                ReasonCode
                .PUSH_SINGLE_SOURCE_AGEING_ALLOCATION,
                ReasonCode.AGEING_STOCK_PREFERRED,
            ]
        )

    # ---------------------------------------------------------
    # Step 3: Multi-source ageing full-fill
    # ---------------------------------------------------------
    if remaining_moq_quantity > Decimal("0"):
        ageing_candidates = [
            candidate
            for candidate in alternative_candidates
            if get_push_moq_aligned_ageing_quantity(
                candidate=candidate,
                remaining_quantity=remaining_moq_quantity,
                moq_qty=moq_qty,
            )
            > Decimal("0")
            and (
                str(candidate.location).strip(),
                str(order_line.material_code).strip(),
            )
            not in allocated_location_keys
        ]

        ageing_candidates = sorted(
            ageing_candidates,
            key=_push_ageing_priority_key,
        )

        total_aligned_ageing_available = sum(
            (
                get_push_moq_aligned_ageing_quantity(
                    candidate=candidate,
                    remaining_quantity=remaining_moq_quantity,
                    moq_qty=moq_qty,
                )
                for candidate in ageing_candidates
            ),
            Decimal("0"),
        )

        if (
            total_aligned_ageing_available
            >= remaining_moq_quantity
        ):
            for candidate in ageing_candidates:
                if remaining_moq_quantity <= Decimal("0"):
                    break

                candidate_location_key = (
                    str(candidate.location).strip(),
                    str(order_line.material_code).strip(),
                )

                if (
                    candidate_location_key
                    in allocated_location_keys
                ):
                    continue

                ageing_allocation_quantity = (
                    get_push_moq_aligned_ageing_quantity(
                        candidate=candidate,
                        remaining_quantity=(
                            remaining_moq_quantity
                        ),
                        moq_qty=moq_qty,
                    )
                )

                if (
                    ageing_allocation_quantity
                    <= Decimal("0")
                ):
                    continue

                source_allocation = allocate_from_candidate(
                    order_line=order_line,
                    candidate=candidate,
                    quantity=ageing_allocation_quantity,
                    allocation_sequence=(
                        allocation_sequence
                    ),
                    inventory_state=inventory_state,
                    decision_timestamp=(
                        decision_timestamp
                    ),
                    reason_code=(
                        ReasonCode
                        .PUSH_MULTI_SOURCE_AGEING_ALLOCATION
                    ),
                )

                allocations.append(source_allocation)

                allocated_location_keys.add(
                    candidate_location_key
                )

                remaining_moq_quantity -= (
                    ageing_allocation_quantity
                )

                allocation_sequence += 1

            reason_codes.extend(
                [
                    ReasonCode
                    .PUSH_MULTI_SOURCE_AGEING_ALLOCATION,
                    ReasonCode.AGEING_STOCK_PREFERRED,
                ]
            )

    # # ---------------------------------------------------------
    # # Step 4: Weighted-scoring fallback
    # # ---------------------------------------------------------
    # if remaining_moq_quantity > Decimal("0"):
    #     weighted_candidates = [
    #         candidate
    #         for candidate in alternative_candidates
    #         if (
    #             str(candidate.location).strip(),
    #             str(order_line.material_code).strip(),
    #         )
    #         not in allocated_location_keys
    #     ]

    #     weighted_candidates = sorted(
    #         weighted_candidates,
    #         key=weighted_sort_key,
    #     )

    #     for candidate in weighted_candidates:
    #         if remaining_moq_quantity <= Decimal("0"):
    #             break

    #         candidate_location_key = (
    #             str(candidate.location).strip(),
    #             str(order_line.material_code).strip(),
    #         )

    #         if (
    #             candidate_location_key
    #             in allocated_location_keys
    #         ):
    #             continue

    #         allocation_quantity = (
    #             get_moq_aligned_available_quantity(
    #                 candidate=candidate,
    #                 remaining_quantity=(
    #                     remaining_moq_quantity
    #                 ),
    #                 moq_qty=moq_qty,
    #             )
    #         )

    #         if allocation_quantity <= Decimal("0"):
    #             continue

    #         try:
    #             source_allocation = (
    #                 allocate_from_candidate(
    #                     order_line=order_line,
    #                     candidate=candidate,
    #                     quantity=allocation_quantity,
    #                     allocation_sequence=(
    #                         allocation_sequence
    #                     ),
    #                     inventory_state=inventory_state,
    #                     decision_timestamp=(
    #                         decision_timestamp
    #                     ),
    #                     reason_code=(
    #                         ReasonCode
    #                         .PUSH_WEIGHTED_SCORE_FALLBACK
    #                     ),
    #                 )
    #             )

    #         except (
    #             DuplicateExecutionError,
    #             InventoryStateError,
    #         ):
    #             continue

    #         allocations.append(source_allocation)

    #         allocated_location_keys.add(
    #             candidate_location_key
    #         )

    #         remaining_moq_quantity -= (
    #             allocation_quantity
    #         )

    #         allocation_sequence += 1

    #     reason_codes.append(
    #         ReasonCode.PUSH_WEIGHTED_SCORE_FALLBACK
    #     )
    
    # ---------------------------------------------------------
    # Step 4: Quantity-gated weighted-scoring fallback
    # ---------------------------------------------------------
    weighted_allocation_made = False

    if remaining_moq_quantity > Decimal("0"):
        unused_weighted_candidates = [
            candidate
            for candidate in alternative_candidates
            if (
                str(candidate.location).strip(),
                str(order_line.material_code).strip(),
            )
            not in allocated_location_keys
        ]

        while (
            remaining_moq_quantity > Decimal("0")
            and unused_weighted_candidates
        ):
            available_weighted_candidates = [
                candidate
                for candidate in unused_weighted_candidates
                if (
                    str(candidate.location).strip(),
                    str(order_line.material_code).strip(),
                )
                not in allocated_location_keys
            ]

            # Quantity gate first.
            (
                weighted_candidate_pool,
                is_full_fill_pool,
                pool_allocation_quantity,
            ) = build_quantity_gated_candidate_pool(
                candidates=available_weighted_candidates,
                remaining_quantity=remaining_moq_quantity,
                moq_qty=moq_qty,
            )

            if not weighted_candidate_pool:
                break

            # Score only candidates in the qualified pool.
            # weighted_sort_key, _ = (
            #     build_replenishment_alternative_sort_key(
            #         candidates=weighted_candidate_pool,
            #         scoring_config=scoring_config,
            #     )
            # )
            (
                weighted_sort_key,
                iteration_score_lookup,
            ) = build_replenishment_alternative_sort_key(
                candidates=weighted_candidate_pool,
                scoring_config=scoring_config,
            )

            candidate_score_lookup.update(
                iteration_score_lookup
            )

            selected_candidate = sorted(
                weighted_candidate_pool,
                key=weighted_sort_key,
            )[0]

            allocation_quantity = (
                remaining_moq_quantity
                if is_full_fill_pool
                else pool_allocation_quantity
            )

            allocation_quantity = floor_to_moq(
                quantity=allocation_quantity,
                moq_qty=moq_qty,
            )

            if allocation_quantity <= Decimal("0"):
                break

            selected_location_key = (
                str(selected_candidate.location).strip(),
                str(order_line.material_code).strip(),
            )

            try:
                source_allocation = allocate_from_candidate(
                    order_line=order_line,
                    candidate=selected_candidate,
                    quantity=allocation_quantity,
                    allocation_sequence=allocation_sequence,
                    inventory_state=inventory_state,
                    decision_timestamp=decision_timestamp,
                    reason_code=(
                        ReasonCode.PUSH_WEIGHTED_SCORE_FALLBACK
                    ),
                )

            except (
                DuplicateExecutionError,
                InventoryStateError,
            ):
                allocated_location_keys.add(
                    selected_location_key
                )

                unused_weighted_candidates = [
                    candidate
                    for candidate in unused_weighted_candidates
                    if (
                        str(candidate.location).strip(),
                        str(candidate.material_code).strip(),
                    )
                    != selected_location_key
                ]

                continue

            allocations.append(source_allocation)

            allocated_location_keys.add(
                selected_location_key
            )

            remaining_moq_quantity -= (
                allocation_quantity
            )

            unused_weighted_candidates = [
                candidate
                for candidate in unused_weighted_candidates
                if (
                    str(candidate.location).strip(),
                    str(candidate.material_code).strip(),
                )
                != selected_location_key
            ]

            weighted_allocation_made = True
            allocation_sequence += 1

    if weighted_allocation_made:
        reason_codes.append(
            ReasonCode.PUSH_WEIGHTED_SCORE_FALLBACK
        )

    # ---------------------------------------------------------
    # Final result
    # ---------------------------------------------------------
    total_allocated_quantity = sum(
        (
            allocation.allocated_quantity
            for allocation in allocations
        ),
        Decimal("0"),
    )

    final_remaining_quantity = (
        original_quantity - total_allocated_quantity
    )

    if len(allocations) > 1:
        reason_codes.append(
            ReasonCode.MULTI_SOURCE_MOQ_ALLOCATION
        )

    if total_allocated_quantity > Decimal("0"):
        reason_codes.append(
            ReasonCode.MAXIMUM_MOQ_ALIGNED_ALLOCATION
        )

    if remaining_moq_quantity > Decimal("0"):
        reason_codes.extend(
            [
                ReasonCode.INSUFFICIENT_MOQ_ALIGNED_STOCK,
                ReasonCode.REMAINING_QTY_HELD_AT_PARENT,
            ]
        )

    elif moq_remainder_quantity > Decimal("0"):
        reason_codes.append(
            ReasonCode.REMAINING_QTY_HELD_AT_PARENT
        )

    return MOQAllocationResult(
        original_requested_quantity=original_quantity,
        moq_qty=moq_qty,
        moq_default_used=moq_default_used,
        moq_eligible_quantity=moq_eligible_quantity,
        moq_remainder_quantity=moq_remainder_quantity,
        total_allocated_quantity=total_allocated_quantity,
        remaining_quantity=final_remaining_quantity,
        allocations=allocations,
        total_git_reserved_quantity=Decimal("0"),
        total_fulfilled_quantity=total_allocated_quantity,
        git_reservations=[],
        reason_codes=deduplicate_reason_codes(
            reason_codes
        ),
        candidate_score_lookup=(
            candidate_score_lookup
        ),
    )




def _safe_candidate_decimal(
    value,
    default: Decimal = Decimal("0"),
) -> Decimal:
    """
    Safely converts a candidate field to Decimal.
    """

    if value is None:
        return default

    try:
        return Decimal(str(value))
    except Exception:
        return default


def _vor_acc_priority_key(
    candidate: CandidateSource,
) -> tuple:
    """
    Ranks candidates after the full-fill or maximum-partial pool
    has already been created.

    Ranking:
    1. Minimum SLA
    2. Maximum current ageing quantity
    3. Maximum current eligible quantity
    4. Minimum RLT
    5. Lowest cost
    6. Location code
    """

    sla_days = (
        candidate.configured_sla_days
        if candidate.configured_sla_days is not None
        else 9999
    )

    ageing_quantity = _safe_candidate_decimal(
        candidate.ageing_quantity,
        Decimal("0"),
    )

    eligible_quantity = _safe_candidate_decimal(
        candidate.eligible_quantity,
        Decimal("0"),
    )

    rlt_days = (
        candidate.rlt_days
        if candidate.rlt_days is not None
        else 9999
    )

    transport_cost = _safe_candidate_decimal(
        candidate.transport_cost,
        Decimal("999999999"),
    )

    return (
        sla_days,
        -ageing_quantity,
        -eligible_quantity,
        rlt_days,
        transport_cost,
        str(candidate.location).strip(),
    )


def _get_candidate_moq_capacity(
    candidate: CandidateSource,
    remaining_quantity: Decimal,
    moq_qty: Decimal,
) -> Decimal:
    """
    Returns the candidate's usable quantity in complete MOQ multiples.

    Capacity cannot exceed:
    - candidate eligible quantity
    - current remaining quantity
    """

    raw_capacity = min(
        _safe_candidate_decimal(
            candidate.eligible_quantity,
            Decimal("0"),
        ),
        remaining_quantity,
    )

    return floor_to_moq(
        quantity=raw_capacity,
        moq_qty=moq_qty,
    )


def _select_vor_acc_candidate_pool(
    candidates: list[CandidateSource],
    remaining_quantity: Decimal,
    moq_qty: Decimal,
) -> tuple[list[CandidateSource], bool, Decimal]:
    """
    Builds the next VOR/ACC candidate pool.

    Returns:
    - candidate pool
    - whether the pool is a full-fill pool
    - maximum partial quantity when full-fill is unavailable

    Logic:
    1. If one or more candidates can fully fulfil the remaining quantity,
       keep only those candidates.
    2. Otherwise calculate maximum MOQ-aligned partial quantity and keep
       only candidates tied at that quantity.
    """

    candidate_capacities: list[
        tuple[CandidateSource, Decimal]
    ] = []

    for candidate in candidates:
        if not candidate.eligible:
            continue

        if candidate.eligible_quantity <= Decimal("0"):
            continue

        moq_capacity = _get_candidate_moq_capacity(
            candidate=candidate,
            remaining_quantity=remaining_quantity,
            moq_qty=moq_qty,
        )

        if moq_capacity <= Decimal("0"):
            continue

        candidate_capacities.append(
            (
                candidate,
                moq_capacity,
            )
        )

    if not candidate_capacities:
        return [], False, Decimal("0")

    full_fill_candidates = [
        candidate
        for candidate, capacity in candidate_capacities
        if capacity >= remaining_quantity
    ]

    if full_fill_candidates:
        return (
            full_fill_candidates,
            True,
            remaining_quantity,
        )

    maximum_partial_quantity = max(
        capacity
        for _, capacity in candidate_capacities
    )

    maximum_partial_candidates = [
        candidate
        for candidate, capacity in candidate_capacities
        if capacity == maximum_partial_quantity
    ]

    return (
        maximum_partial_candidates,
        False,
        maximum_partial_quantity,
    )


def allocate_vor_acc_parent_then_ranked_alternatives(
    order_line: OrderLine,
    candidates: list[CandidateSource],
    moq_qty: Decimal,
    moq_default_used: bool,
    inventory_state: InventoryStateManager,
    decision_timestamp: datetime,
) -> MOQAllocationResult:
    """
    Performs MOQ-based VOR/ACC allocation.

    Flow:
    1. Floor effective requested quantity to MOQ multiple.
    2. Parent full-fill first.
    3. If parent cannot full-fill, allocate maximum MOQ partial from parent.
    4. For remaining quantity:
       - full-fill alternative pool first
       - otherwise maximum MOQ-partial pool
    5. Rank the selected pool by:
       - minimum SLA
       - maximum ageing quantity
       - maximum eligible quantity
       - minimum RLT
       - lowest cost
       - location
    6. Allocate from the winning candidate.
    7. Repeat using unused alternatives.
    8. Hold final remaining quantity at parent.
    """

    candidates = deduplicate_candidates_by_location(
        candidates=candidates,
    )

    original_quantity = order_line.requested_quantity

    moq_eligible_quantity = floor_to_moq(
        quantity=original_quantity,
        moq_qty=moq_qty,
    )

    moq_remainder_quantity = (
        original_quantity - moq_eligible_quantity
    )

    remaining_moq_quantity = moq_eligible_quantity

    allocations: list[SourceAllocation] = []
    reason_codes: list[ReasonCode] = []

    if moq_default_used:
        reason_codes.append(
            ReasonCode.MOQ_NOT_FOUND_DEFAULT_ONE_USED
        )

    if moq_remainder_quantity > Decimal("0"):
        reason_codes.extend(
            [
                ReasonCode.ORDER_QTY_PARTIALLY_MOQ_ALIGNED,
                ReasonCode.MOQ_REMAINDER_HELD_AT_PARENT,
            ]
        )

    if moq_eligible_quantity <= Decimal("0"):
        reason_codes.extend(
            [
                ReasonCode.INSUFFICIENT_MOQ_ALIGNED_STOCK,
                ReasonCode.REMAINING_QTY_HELD_AT_PARENT,
            ]
        )

        return MOQAllocationResult(
            original_requested_quantity=original_quantity,
            moq_qty=moq_qty,
            moq_default_used=moq_default_used,
            moq_eligible_quantity=Decimal("0"),
            moq_remainder_quantity=original_quantity,
            total_allocated_quantity=Decimal("0"),
            remaining_quantity=original_quantity,
            allocations=[],
            total_git_reserved_quantity=Decimal("0"),
            total_fulfilled_quantity=Decimal("0"),
            git_reservations=[],
            reason_codes=deduplicate_reason_codes(
                reason_codes
            ),
        )

    allocation_sequence = 1
    parent_location: str | None = None

    # ---------------------------------------------------------
    # Step 1: Parent allocation
    # ---------------------------------------------------------
    parent_candidates = [
        candidate
        for candidate in candidates
        if candidate.source_type == SourceType.PARENT_RDC
        and candidate.eligible
        and candidate.eligible_quantity > Decimal("0")
    ]

    if parent_candidates:
        parent_candidate = sorted(
            parent_candidates,
            key=lambda candidate: (
                str(candidate.location).strip(),
            ),
        )[0]

        parent_location = str(
            parent_candidate.location
        ).strip()

        parent_allocation_quantity = (
            _get_candidate_moq_capacity(
                candidate=parent_candidate,
                remaining_quantity=remaining_moq_quantity,
                moq_qty=moq_qty,
            )
        )

        if parent_allocation_quantity > Decimal("0"):
            parent_reason = (
                ReasonCode.PARENT_FULL_FILL
                if parent_allocation_quantity
                == remaining_moq_quantity
                else ReasonCode.PARENT_MOQ_PARTIAL_ALLOCATION
            )

            parent_allocation = allocate_from_candidate(
                order_line=order_line,
                candidate=parent_candidate,
                quantity=parent_allocation_quantity,
                allocation_sequence=allocation_sequence,
                inventory_state=inventory_state,
                decision_timestamp=decision_timestamp,
                reason_code=parent_reason,
            )

            allocations.append(parent_allocation)

            remaining_moq_quantity -= (
                parent_allocation_quantity
            )

            reason_codes.append(parent_reason)
            allocation_sequence += 1

    # Parent has completed the aligned quantity.
    if remaining_moq_quantity <= Decimal("0"):
        total_allocated_quantity = sum(
            (
                allocation.allocated_quantity
                for allocation in allocations
            ),
            Decimal("0"),
        )

        if moq_remainder_quantity > Decimal("0"):
            reason_codes.append(
                ReasonCode.REMAINING_QTY_HELD_AT_PARENT
            )

        return MOQAllocationResult(
            original_requested_quantity=original_quantity,
            moq_qty=moq_qty,
            moq_default_used=moq_default_used,
            moq_eligible_quantity=moq_eligible_quantity,
            moq_remainder_quantity=moq_remainder_quantity,
            total_allocated_quantity=total_allocated_quantity,
            remaining_quantity=(
                original_quantity
                - total_allocated_quantity
            ),
            allocations=allocations,
            total_git_reserved_quantity=Decimal("0"),
            total_fulfilled_quantity=total_allocated_quantity,
            git_reservations=[],
            reason_codes=deduplicate_reason_codes(
                reason_codes
            ),
        )

    # ---------------------------------------------------------
    # Step 2: Alternative candidates
    # ---------------------------------------------------------
    unused_alternatives = [
        candidate
        for candidate in candidates
        if candidate.source_type != SourceType.PARENT_RDC
        and candidate.eligible
        and candidate.eligible_quantity > Decimal("0")
        and (
            parent_location is None
            or str(candidate.location).strip()
            != parent_location
        )
    ]

    used_location_keys = {
        (
            str(allocation.candidate.location).strip(),
            str(order_line.material_code).strip(),
        )
        for allocation in allocations
    }

    # ---------------------------------------------------------
    # Step 3: Recalculate pool after every source allocation
    # ---------------------------------------------------------
    while (
        remaining_moq_quantity > Decimal("0")
        and unused_alternatives
    ):
        available_alternatives = [
            candidate
            for candidate in unused_alternatives
            if (
                str(candidate.location).strip(),
                str(order_line.material_code).strip(),
            )
            not in used_location_keys
        ]

        (
            candidate_pool,
            is_full_fill_pool,
            selected_pool_quantity,
        ) = _select_vor_acc_candidate_pool(
            candidates=available_alternatives,
            remaining_quantity=remaining_moq_quantity,
            moq_qty=moq_qty,
        )

        if not candidate_pool:
            break

        # Quantity has already been used to build the candidate pool.
        # The actual ranking now starts with minimum SLA.
        selected_candidate = sorted(
            candidate_pool,
            key=_vor_acc_priority_key,
        )[0]

        if is_full_fill_pool:
            allocation_quantity = remaining_moq_quantity
        else:
            allocation_quantity = selected_pool_quantity

        allocation_quantity = floor_to_moq(
            quantity=allocation_quantity,
            moq_qty=moq_qty,
        )

        if allocation_quantity <= Decimal("0"):
            break

        selected_location_key = (
            str(selected_candidate.location).strip(),
            str(order_line.material_code).strip(),
        )

        try:
            source_allocation = allocate_from_candidate(
                order_line=order_line,
                candidate=selected_candidate,
                quantity=allocation_quantity,
                allocation_sequence=allocation_sequence,
                inventory_state=inventory_state,
                decision_timestamp=decision_timestamp,
                reason_code=(
                    ReasonCode.MULTI_SOURCE_MOQ_ALLOCATION
                ),
            )

        except DuplicateExecutionError:
            used_location_keys.add(
                selected_location_key
            )

            unused_alternatives = [
                candidate
                for candidate in unused_alternatives
                if (
                    str(candidate.location).strip(),
                    str(candidate.material_code).strip(),
                )
                != selected_location_key
            ]

            continue

        except InventoryStateError:
            used_location_keys.add(
                selected_location_key
            )

            unused_alternatives = [
                candidate
                for candidate in unused_alternatives
                if (
                    str(candidate.location).strip(),
                    str(candidate.material_code).strip(),
                )
                != selected_location_key
            ]

            continue

        allocations.append(source_allocation)

        remaining_moq_quantity -= allocation_quantity

        used_location_keys.add(
            selected_location_key
        )

        unused_alternatives = [
            candidate
            for candidate in unused_alternatives
            if (
                str(candidate.location).strip(),
                str(candidate.material_code).strip(),
            )
            != selected_location_key
        ]

        if is_full_fill_pool:
            reason_codes.append(
                ReasonCode.SINGLE_SOURCE_REROUTE
            )
        else:
            reason_codes.append(
                ReasonCode.MAXIMUM_PARTIAL_FILL
            )

        allocation_sequence += 1

    # ---------------------------------------------------------
    # Final result
    # ---------------------------------------------------------
    total_allocated_quantity = sum(
        (
            allocation.allocated_quantity
            for allocation in allocations
        ),
        Decimal("0"),
    )

    final_remaining_quantity = (
        original_quantity - total_allocated_quantity
    )

    if len(allocations) > 1:
        reason_codes.append(
            ReasonCode.MULTI_SOURCE_MOQ_ALLOCATION
        )

    if total_allocated_quantity > Decimal("0"):
        reason_codes.append(
            ReasonCode.MAXIMUM_MOQ_ALIGNED_ALLOCATION
        )

    if remaining_moq_quantity > Decimal("0"):
        reason_codes.extend(
            [
                ReasonCode.INSUFFICIENT_MOQ_ALIGNED_STOCK,
                ReasonCode.REMAINING_QTY_HELD_AT_PARENT,
            ]
        )

    elif moq_remainder_quantity > Decimal("0"):
        reason_codes.append(
            ReasonCode.REMAINING_QTY_HELD_AT_PARENT
        )

    return MOQAllocationResult(
        original_requested_quantity=original_quantity,
        moq_qty=moq_qty,
        moq_default_used=moq_default_used,
        moq_eligible_quantity=moq_eligible_quantity,
        moq_remainder_quantity=moq_remainder_quantity,
        total_allocated_quantity=total_allocated_quantity,
        remaining_quantity=final_remaining_quantity,
        allocations=allocations,
        total_git_reserved_quantity=Decimal("0"),
        total_fulfilled_quantity=total_allocated_quantity,
        git_reservations=[],
        reason_codes=deduplicate_reason_codes(
            reason_codes
        ),
    )