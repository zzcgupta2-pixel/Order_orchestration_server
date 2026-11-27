from __future__ import annotations
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from order_orchestration.domain.candidate import CandidateSource
from order_orchestration.domain.enums import DecisionType, ReasonCode, SourceType


@dataclass(frozen=True)
class SourceSelectionResult:
    """
    Structured result of source selection for one order line.

    This object only represents source selection.
    It does not update inventory state.
    """

    decision: DecisionType
    selected_candidate: Optional[CandidateSource]
    allocated_quantity: Decimal
    remaining_quantity: Decimal
    reason_codes: list[ReasonCode] = field(default_factory=list)

DEFAULT_TIE_BREAK_ORDER = [
    "full_fill",
    "maximum_quantity",
    "shortest_sla",
    "ageing_quantity",
    "shortest_rlt",
    "source_priority",
    "lowest_cost",
]


DEFAULT_SOURCE_PRIORITY = {
    SourceType.PARENT_RDC.value: 1,
    SourceType.PARENT_GIT.value: 2,
    SourceType.CLUSTER_RDC.value: 3,
    SourceType.PAN_INDIA_RDC.value: 4,
    SourceType.VEPDC.value: 5,
}


def filter_selectable_candidates(
    candidates: list[CandidateSource],
) -> list:
    """
    Returns candidates that can be considered for source selection.

    A candidate is selectable when:
    - candidate.eligible is True
    - candidate.eligible_quantity is greater than zero

    Rejected candidates remain in the audit outside this function.
    """

    return [
        candidate
        for candidate in candidates
        if candidate.eligible and candidate.eligible_quantity > Decimal("0")
    ]


def get_full_fill_candidates(
    candidates: list[CandidateSource],
) -> list:
    """
    Returns candidates that can fully fulfil the requested quantity.
    """

    return [
        candidate
        for candidate in candidates
        if candidate.full_fill_capable
    ]


def get_maximum_quantity_candidates(
    candidates: list[CandidateSource],
) -> list:
    """
    Returns candidates having the maximum eligible quantity.

    This is used when no candidate can fully fulfil the order.
    """

    if not candidates:
        return []

    maximum_quantity = max(
        candidate.eligible_quantity
        for candidate in candidates
    )

    return [
        candidate
        for candidate in candidates
        if candidate.eligible_quantity == maximum_quantity
    ]


def _get_source_priority_value(
    candidate: CandidateSource,
    source_priority: dict[str, int],
) -> int:
    """
    Returns configured source priority for a candidate.

    Lower value means higher priority.
    """

    return source_priority.get(candidate.source_type.value, 9999)

def _get_rlt_sort_value(candidate: CandidateSource) -> int:
    """
    Returns RLT sort value.

    Missing RLT is pushed to the end.
    Lower RLT days is better.
    """

    if candidate.rlt_days is None:
        return 9999

    return candidate.rlt_days

def _get_sla_sort_value(candidate: CandidateSource) -> int:
    """
    Returns SLA sort value.

    Missing SLA is pushed to the end.
    """

    if candidate.configured_sla_days is None:
        return 9999

    return candidate.configured_sla_days


def _get_cost_sort_value(candidate: CandidateSource) -> Decimal:
    """
    Returns cost sort value.

    Missing cost is pushed to the end.
    """

    if candidate.transport_cost is None:
        return Decimal("999999999")

    return candidate.transport_cost


def build_candidate_sort_key(
    candidate: CandidateSource,
    tie_break_order: list[str],
    source_priority: dict[str, int],
) -> tuple:
    """
    Builds deterministic sort key based on configured tie-break order.

    Supported tie-break keys:
    - full_fill
    - maximum_quantity
    - shortest_sla
    - source_priority
    - ageing_quantity
    - lowest_cost

    For deterministic final tie-break, location is always appended.
    """

    sort_values = []

    for tie_break in tie_break_order:
        if tie_break == "full_fill":
            sort_values.append(0 if candidate.full_fill_capable else 1)

        elif tie_break == "maximum_quantity":
            sort_values.append(-candidate.eligible_quantity)

        elif tie_break == "shortest_sla":
            sort_values.append(_get_sla_sort_value(candidate))

        elif tie_break == "source_priority":
            sort_values.append(
                _get_source_priority_value(
                    candidate=candidate,
                    source_priority=source_priority,
                )
            )

        elif tie_break == "ageing_quantity":
            sort_values.append(-candidate.ageing_quantity)

        elif tie_break == "shortest_rlt":
            sort_values.append(_get_rlt_sort_value(candidate))

        elif tie_break == "lowest_cost":
            sort_values.append(_get_cost_sort_value(candidate))

        else:
            # Unknown tie-breaks are ignored to keep logic configurable.
            # Config validation can flag unsupported tie-breaks later.
            continue

    # Final deterministic tie-breaker
    sort_values.append(str(candidate.location).strip())

    return tuple(sort_values)


def select_candidate_by_tie_breaks(
    candidates: list[CandidateSource],
    tie_break_order: list[str] | None = None,
    source_priority: dict[str, int] | None = None,
) -> Optional[CandidateSource]:
    """
    Selects one candidate deterministically using configured tie-breaks.
    """

    if not candidates:
        return None

    if tie_break_order is None:
        tie_break_order = DEFAULT_TIE_BREAK_ORDER

    if source_priority is None:
        source_priority = DEFAULT_SOURCE_PRIORITY

    sorted_candidates = sorted(
        candidates,
        key=lambda candidate: build_candidate_sort_key(
            candidate=candidate,
            tie_break_order=tie_break_order,
            source_priority=source_priority,
        ),
    )

    return sorted_candidates[0]


def build_selection_reason_codes(
    selected_candidate: CandidateSource,
    requested_quantity: Decimal,
    allocated_quantity: Decimal,
    full_fill_selected: bool,
) -> list:
    """
    Builds reason codes for source selection.
    """

    reason_codes: list[ReasonCode] = []

    if full_fill_selected:
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
    else:
        reason_codes.append(ReasonCode.MAXIMUM_PARTIAL_FILL)

    if selected_candidate.source_type != SourceType.PARENT_RDC:
        reason_codes.append(ReasonCode.SINGLE_SOURCE_REROUTE)

    if selected_candidate.configured_sla_days is not None:
        reason_codes.append(ReasonCode.SHORTEST_SLA_SELECTED)

    if selected_candidate.rlt_days is not None:
        reason_codes.append(ReasonCode.RLT_TIE_BREAK_SELECTED)

    if selected_candidate.transport_cost is not None:
        reason_codes.append(ReasonCode.LOWEST_COST_SELECTED)

    if selected_candidate.ageing_quantity > Decimal("0"):
        reason_codes.append(ReasonCode.AGEING_STOCK_PREFERRED)

    if allocated_quantity < requested_quantity:
        reason_codes.append(ReasonCode.MAXIMUM_PARTIAL_FILL)

    return reason_codes


def select_best_source(
    candidates: list[CandidateSource],
    requested_quantity: Decimal,
    tie_break_order: list[str] | None = None,
    source_priority: dict[str, int] | None = None,
) -> SourceSelectionResult:
    """
    Selects the best source candidate for an order line.

    Business rules:
    1. Use only eligible candidates.
    2. Prefer complete fulfilment from one source.
    3. If no full-fill source exists, select one source with maximum eligible quantity.
    4. Do not split across locations.
    5. Use configured tie-breaks for deterministic selection.
    """

    selectable_candidates = filter_selectable_candidates(candidates)

    if not selectable_candidates:
        return SourceSelectionResult(
            decision=DecisionType.NO_ELIGIBLE_STOCK,
            selected_candidate=None,
            allocated_quantity=Decimal("0"),
            remaining_quantity=requested_quantity,
            reason_codes=[ReasonCode.NO_ELIGIBLE_STOCK],
        )

    full_fill_candidates = get_full_fill_candidates(selectable_candidates)

    if full_fill_candidates:
        selected_candidate = select_candidate_by_tie_breaks(
            candidates=full_fill_candidates,
            tie_break_order=tie_break_order,
            source_priority=source_priority,
        )

        if selected_candidate is None:
            return SourceSelectionResult(
                decision=DecisionType.NO_ELIGIBLE_STOCK,
                selected_candidate=None,
                allocated_quantity=Decimal("0"),
                remaining_quantity=requested_quantity,
                reason_codes=[ReasonCode.NO_ELIGIBLE_STOCK],
            )

        allocated_quantity = requested_quantity
        remaining_quantity = Decimal("0")

        reason_codes = build_selection_reason_codes(
            selected_candidate=selected_candidate,
            requested_quantity=requested_quantity,
            allocated_quantity=allocated_quantity,
            full_fill_selected=True,
        )

        return SourceSelectionResult(
            decision=DecisionType.ALLOCATE,
            selected_candidate=selected_candidate,
            allocated_quantity=allocated_quantity,
            remaining_quantity=remaining_quantity,
            reason_codes=reason_codes,
        )

    maximum_quantity_candidates = get_maximum_quantity_candidates(
        selectable_candidates
    )

    selected_candidate = select_candidate_by_tie_breaks(
        candidates=maximum_quantity_candidates,
        tie_break_order=tie_break_order,
        source_priority=source_priority,
    )

    if selected_candidate is None:
        return SourceSelectionResult(
            decision=DecisionType.NO_ELIGIBLE_STOCK,
            selected_candidate=None,
            allocated_quantity=Decimal("0"),
            remaining_quantity=requested_quantity,
            reason_codes=[ReasonCode.NO_ELIGIBLE_STOCK],
        )

    allocated_quantity = min(
        selected_candidate.eligible_quantity,
        requested_quantity,
    )

    remaining_quantity = requested_quantity - allocated_quantity

    reason_codes = build_selection_reason_codes(
        selected_candidate=selected_candidate,
        requested_quantity=requested_quantity,
        allocated_quantity=allocated_quantity,
        full_fill_selected=False,
    )

    return SourceSelectionResult(
        decision=DecisionType.ALLOCATE,
        selected_candidate=selected_candidate,
        allocated_quantity=allocated_quantity,
        remaining_quantity=remaining_quantity,
        reason_codes=reason_codes,
    )