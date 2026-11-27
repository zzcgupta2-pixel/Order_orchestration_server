from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from order_orchestration.domain.candidate import CandidateSource
from order_orchestration.domain.enums import DecisionType, ReasonCode, SourceType
from order_orchestration.selection.source_selection import SourceSelectionResult


@dataclass(frozen=True)
class CandidateScoreBreakdown:
    """
    Score details for one candidate.

    Quantity and full-fill are used as selection gates before scoring.
    The weighted score itself uses business quality factors:
    - ageing
    - SLA
    - RLT
    - cost
    - source priority
    """

    candidate_location: str
    candidate_source_type: SourceType
    final_score: Decimal
    ageing_component: Decimal
    sla_component: Decimal
    rlt_component: Decimal
    cost_component: Decimal
    source_priority_component: Decimal
    weighted_components: dict[str, Decimal] = field(default_factory=dict)
    scoring_pool: str = ""


def _safe_decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    """
    Safely converts a value to Decimal.
    """

    if value is None:
        return default

    try:
        return Decimal(str(value))
    except Exception:
        return default


def _normalize_higher_is_better(
    value: Decimal,
    min_value: Decimal,
    max_value: Decimal,
) -> Decimal:
    """
    Normalizes a value between 0 and 1 where higher is better.
    """

    if max_value == min_value:
        return Decimal("1")

    return (value - min_value) / (max_value - min_value)


def _normalize_lower_is_better(
    value: Decimal,
    min_value: Decimal,
    max_value: Decimal,
) -> Decimal:
    """
    Normalizes a value between 0 and 1 where lower is better.
    """

    if max_value == min_value:
        return Decimal("1")

    return (max_value - value) / (max_value - min_value)


def _get_rlt_value(
    candidate: CandidateSource,
    scoring_config: dict,
) -> Decimal:
    """
    Returns RLT value for scoring.

    Business rule:
    - RLT is RDC-level lead time from VEPDC to RDC.
    - VEPDC itself should not be penalized for missing RLT.
    - If candidate is VEPDC and RLT is missing, use VEPDC default, normally 0.
    - If non-VEPDC RLT is missing, use missing_rlt default, normally 9999.
    """

    rlt_defaults = scoring_config.get("rlt_defaults", {})

    vepdc_default = Decimal(str(rlt_defaults.get("VEPDC", 0)))
    missing_rlt_default = Decimal(str(rlt_defaults.get("missing_rlt", 9999)))

    if candidate.rlt_days is not None:
        return _safe_decimal(candidate.rlt_days, missing_rlt_default)

    if candidate.source_type == SourceType.VEPDC:
        return vepdc_default

    return missing_rlt_default


def _get_cost_value(
    candidate: CandidateSource,
) -> Decimal:
    """
    Returns cost value for scoring.

    Missing cost is pushed to the end by using a very high value.
    """

    return _safe_decimal(candidate.transport_cost, Decimal("999999999"))


def _get_candidate_metric_ranges(
    candidates: list[CandidateSource],
    scoring_config: dict,
) -> dict[str, tuple[Decimal, Decimal]]:
    """
    Builds min and max ranges for candidate normalization.

    Only business quality factors are normalized here.
    Quantity is intentionally not included because quantity is handled
    before scoring.
    """

    ageing_values = [
        _safe_decimal(candidate.ageing_quantity)
        for candidate in candidates
    ]

    sla_values = [
        _safe_decimal(candidate.configured_sla_days, Decimal("9999"))
        for candidate in candidates
    ]

    rlt_values = [
        _get_rlt_value(candidate, scoring_config)
        for candidate in candidates
    ]

    cost_values = [
        _get_cost_value(candidate)
        for candidate in candidates
    ]

    return {
        "ageing": (min(ageing_values), max(ageing_values)),
        "sla": (min(sla_values), max(sla_values)),
        "rlt": (min(rlt_values), max(rlt_values)),
        "cost": (min(cost_values), max(cost_values)),
    }


def _get_source_priority_score(
    candidate: CandidateSource,
    source_priority: dict[str, int],
) -> Decimal:
    """
    Converts source priority into a normalized-like score.

    Lower source priority number is better.
    Example:
        priority 1 gives score 1
        priority 2 gives score 0.5
        priority 3 gives score 0.333...
    """

    priority_value = source_priority.get(candidate.source_type.value, 9999)

    if priority_value <= 0:
        return Decimal("1")

    return Decimal("1") / Decimal(str(priority_value))


def filter_scoreable_candidates(
    candidates: list[CandidateSource],
) -> list:
    """
    Returns candidates eligible for scoring.

    A candidate can be scored only when:
    - candidate.eligible is True
    - candidate.eligible_quantity is positive
    """

    return [
        candidate
        for candidate in candidates
        if candidate.eligible and candidate.eligible_quantity > Decimal("0")
    ]


def get_scoring_pool(
    candidates: list[CandidateSource],
) -> tuple[list[CandidateSource], str]:
    """
    Determines which candidates should enter weighted scoring.

    Business rule:
    1. If one or more candidates can fully fulfil, score only full-fill candidates.
    2. If no full-fill candidate exists, find maximum eligible quantity.
       Score only candidates with that maximum quantity.

    This ensures quantity is handled as a gate, not as a normal scoring weight.
    """

    full_fill_candidates = [
        candidate
        for candidate in candidates
        if candidate.full_fill_capable
    ]

    if full_fill_candidates:
        return full_fill_candidates, "FULL_FILL_POOL"

    maximum_quantity = max(
        candidate.eligible_quantity
        for candidate in candidates
    )

    max_quantity_candidates = [
        candidate
        for candidate in candidates
        if candidate.eligible_quantity == maximum_quantity
    ]

    return max_quantity_candidates, "MAX_QUANTITY_PARTIAL_POOL"


def calculate_candidate_score(
    candidate: CandidateSource,
    candidates: list[CandidateSource],
    scoring_config: dict,
    scoring_pool: str,
) -> CandidateScoreBreakdown:
    """
    Calculates weighted score for one candidate.

    Quantity and full-fill are already handled before this function.
    This function scores only:
    - ageing
    - SLA
    - RLT
    - cost
    - source priority
    """

    weights = scoring_config.get("weights", {})
    source_priority = scoring_config.get("source_priority", {})
    round_digits = int(scoring_config.get("score_round_digits", 6))

    ranges = _get_candidate_metric_ranges(
        candidates=candidates,
        scoring_config=scoring_config,
    )

    ageing_min, ageing_max = ranges["ageing"]
    ageing_component = _normalize_higher_is_better(
        _safe_decimal(candidate.ageing_quantity),
        ageing_min,
        ageing_max,
    )

    sla_min, sla_max = ranges["sla"]
    sla_component = _normalize_lower_is_better(
        _safe_decimal(candidate.configured_sla_days, Decimal("9999")),
        sla_min,
        sla_max,
    )

    rlt_min, rlt_max = ranges["rlt"]
    rlt_component = _normalize_lower_is_better(
        _get_rlt_value(candidate, scoring_config),
        rlt_min,
        rlt_max,
    )

    cost_min, cost_max = ranges["cost"]
    cost_component = _normalize_lower_is_better(
        _get_cost_value(candidate),
        cost_min,
        cost_max,
    )

    source_priority_component = _get_source_priority_score(
        candidate=candidate,
        source_priority=source_priority,
    )

    weighted_components = {
        "ageing": Decimal(str(weights.get("ageing", 0))) * ageing_component,
        "sla": Decimal(str(weights.get("sla", 0))) * sla_component,
        "rlt": Decimal(str(weights.get("rlt", 0))) * rlt_component,
        "cost": Decimal(str(weights.get("cost", 0))) * cost_component,
        "source_priority": Decimal(str(weights.get("source_priority", 0)))
        * source_priority_component,
    }

    final_score = sum(weighted_components.values(), Decimal("0"))
    final_score = final_score.quantize(Decimal("1." + "0" * round_digits))

    return CandidateScoreBreakdown(
        candidate_location=candidate.location,
        candidate_source_type=candidate.source_type,
        final_score=final_score,
        ageing_component=ageing_component,
        sla_component=sla_component,
        rlt_component=rlt_component,
        cost_component=cost_component,
        source_priority_component=source_priority_component,
        weighted_components=weighted_components,
        scoring_pool=scoring_pool,
    )


def build_weighted_selection_reason_codes(
    selected_candidate: CandidateSource,
    allocated_quantity: Decimal,
    requested_quantity: Decimal,
    scoring_pool: str,
) -> list:
    """
    Builds reason codes for weighted scoring selection.
    """

    reason_codes = [ReasonCode.WEIGHTED_SCORE_SELECTED]

    if selected_candidate.full_fill_capable:
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

    if scoring_pool == "MAX_QUANTITY_PARTIAL_POOL":
        if ReasonCode.MAXIMUM_PARTIAL_FILL not in reason_codes:
            reason_codes.append(ReasonCode.MAXIMUM_PARTIAL_FILL)

    if selected_candidate.ageing_quantity > Decimal("0"):
        reason_codes.append(ReasonCode.AGEING_STOCK_PREFERRED)

    return reason_codes


def select_best_source_by_weighted_score(
    candidates: list[CandidateSource],
    requested_quantity: Decimal,
    scoring_config: dict,
) -> tuple[SourceSelectionResult, list[CandidateScoreBreakdown]]:
    """
    Selects the best candidate using quantity-gated weighted scoring.

    Selection logic:
    1. Keep only eligible candidates with positive stock.
    2. If full-fill candidates exist, score only full-fill candidates.
    3. If no full-fill candidates exist, keep only max-quantity candidates.
    4. Score the selected pool using ageing, SLA, RLT, cost, and source priority.
    5. Highest score wins.
    """

    scoreable_candidates = filter_scoreable_candidates(candidates)

    if not scoreable_candidates:
        return (
            SourceSelectionResult(
                decision=DecisionType.NO_ELIGIBLE_STOCK,
                selected_candidate=None,
                allocated_quantity=Decimal("0"),
                remaining_quantity=requested_quantity,
                reason_codes=[ReasonCode.NO_ELIGIBLE_STOCK],
            ),
            [],
        )

    scoring_candidates, scoring_pool = get_scoring_pool(scoreable_candidates)

    score_breakdowns = [
        calculate_candidate_score(
            candidate=candidate,
            candidates=scoring_candidates,
            scoring_config=scoring_config,
            scoring_pool=scoring_pool,
        )
        for candidate in scoring_candidates
    ]

    score_by_location = {
        breakdown.candidate_location: breakdown.final_score
        for breakdown in score_breakdowns
    }

    sorted_candidates = sorted(
        scoring_candidates,
        key=lambda candidate: (
            -score_by_location[candidate.location],
            str(candidate.location).strip(),
        ),
    )

    selected_candidate = sorted_candidates[0]

    allocated_quantity = min(
        selected_candidate.eligible_quantity,
        requested_quantity,
    )

    remaining_quantity = requested_quantity - allocated_quantity

    reason_codes = build_weighted_selection_reason_codes(
        selected_candidate=selected_candidate,
        allocated_quantity=allocated_quantity,
        requested_quantity=requested_quantity,
        scoring_pool=scoring_pool,
    )

    return (
        SourceSelectionResult(
            decision=DecisionType.ALLOCATE,
            selected_candidate=selected_candidate,
            allocated_quantity=allocated_quantity,
            remaining_quantity=remaining_quantity,
            reason_codes=reason_codes,
        ),
        score_breakdowns,
    )