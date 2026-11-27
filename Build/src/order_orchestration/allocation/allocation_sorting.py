from __future__ import annotations

from decimal import Decimal

from order_orchestration.domain.candidate import CandidateSource


def safe_sla(
    candidate: CandidateSource,
) -> int:
    return (
        int(candidate.configured_sla_days)
        if candidate.configured_sla_days is not None
        else 9999
    )


def safe_ageing(
    candidate: CandidateSource,
) -> Decimal:
    return Decimal(
        str(candidate.ageing_quantity or 0)
    )


def safe_eligible(
    candidate: CandidateSource,
) -> Decimal:
    return Decimal(
        str(candidate.eligible_quantity or 0)
    )


def safe_rlt(
    candidate: CandidateSource,
) -> int:
    return (
        int(candidate.rlt_days)
        if candidate.rlt_days is not None
        else 9999
    )


def safe_cost(
    candidate: CandidateSource,
) -> Decimal:
    return Decimal(
        str(
            candidate.transport_cost
            if candidate.transport_cost is not None
            else Decimal("999999999")
        )
    )


def vor_acc_alternative_sort_key(
    candidate: CandidateSource,
) -> tuple:
    """
    VOR/ACC alternative order:
    - Full-fill capability
    - Maximum quantity
    - Minimum SLA
    - Maximum ageing
    - Maximum stock
    - Minimum RLT
    - Lowest cost
    - Location
    """

    return (
        not candidate.full_fill_capable,
        -safe_eligible(candidate),
        safe_sla(candidate),
        -safe_ageing(candidate),
        -safe_eligible(candidate),
        safe_rlt(candidate),
        safe_cost(candidate),
        str(candidate.location).strip(),
    )


#Replenishment 


def _to_decimal(
    value,
    default: Decimal = Decimal("0"),
) -> Decimal:
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
    minimum_value: Decimal,
    maximum_value: Decimal,
) -> Decimal:
    """
    Normalizes a higher-is-better value between 0 and 1.

    If all candidates have the same value, every candidate gets 1.
    """

    if maximum_value == minimum_value:
        return Decimal("1")

    return (
        value - minimum_value
    ) / (
        maximum_value - minimum_value
    )


def _normalize_lower_is_better(
    value: Decimal,
    minimum_value: Decimal,
    maximum_value: Decimal,
) -> Decimal:
    """
    Normalizes a lower-is-better value between 0 and 1.

    Lowest value gets 1.
    Highest value gets 0.

    If all candidates have the same value, every candidate gets 1.
    """

    if maximum_value == minimum_value:
        return Decimal("1")

    return (
        maximum_value - value
    ) / (
        maximum_value - minimum_value
    )


def build_replenishment_weighted_score_lookup(
    candidates: list[CandidateSource],
    scoring_config: dict,
) -> dict[tuple[str, str], dict]:
    """
    Calculates Replenishment weighted scores for alternative candidates.

    Factors:
    - Lower SLA is better.
    - Higher current ageing quantity is better.
    - Lower RLT is better.
    - Higher current eligible quantity is better.
    - Lower transport cost is better.

    Returns:
        {
            (location, material_code): {
                "total_score": Decimal,
                "sla_score": Decimal,
                "ageing_score": Decimal,
                "rlt_score": Decimal,
                "eligible_quantity_score": Decimal,
                "cost_score": Decimal,
            }
        }
    """

    eligible_candidates = [
        candidate
        for candidate in candidates
        if candidate.eligible
        and candidate.eligible_quantity > Decimal("0")
    ]

    if not eligible_candidates:
        return {}

    weights_config = scoring_config.get("weights", {})

    sla_weight = _to_decimal(
        weights_config.get("sla", 0.30)
    )

    ageing_weight = _to_decimal(
        weights_config.get("ageing", 0.25)
    )

    rlt_weight = _to_decimal(
        weights_config.get("rlt", 0.20)
    )

    eligible_quantity_weight = _to_decimal(
        weights_config.get("eligible_quantity", 0.15)
    )

    cost_weight = _to_decimal(
        weights_config.get("cost", 0.10)
    )

    total_weight = (
        sla_weight
        + ageing_weight
        + rlt_weight
        + eligible_quantity_weight
        + cost_weight
    )

    if total_weight <= Decimal("0"):
        raise ValueError(
            "Replenishment MOQ scoring weights must total "
            "to a value greater than zero."
        )

    # Normalize weights in case config does not total exactly to 1.
    sla_weight = sla_weight / total_weight
    ageing_weight = ageing_weight / total_weight
    rlt_weight = rlt_weight / total_weight
    eligible_quantity_weight = (
        eligible_quantity_weight / total_weight
    )
    cost_weight = cost_weight / total_weight

    missing_values = scoring_config.get(
        "missing_values",
        {},
    )

    missing_sla = _to_decimal(
        missing_values.get("sla", 9999)
    )

    missing_rlt = _to_decimal(
        missing_values.get("rlt", 9999)
    )

    missing_cost = _to_decimal(
        missing_values.get("cost", 999999999)
    )

    candidate_values: list[dict] = []

    for candidate in eligible_candidates:
        candidate_values.append(
            {
                "candidate": candidate,
                "sla": _to_decimal(
                    candidate.configured_sla_days,
                    missing_sla,
                ),
                "ageing": _to_decimal(
                    candidate.ageing_quantity,
                    Decimal("0"),
                ),
                "rlt": _to_decimal(
                    getattr(candidate, "rlt_days", None),
                    missing_rlt,
                ),
                "eligible_quantity": _to_decimal(
                    candidate.eligible_quantity,
                    Decimal("0"),
                ),
                "cost": _to_decimal(
                    candidate.transport_cost,
                    missing_cost,
                ),
            }
        )

    sla_values = [
        item["sla"]
        for item in candidate_values
    ]

    ageing_values = [
        item["ageing"]
        for item in candidate_values
    ]

    rlt_values = [
        item["rlt"]
        for item in candidate_values
    ]

    eligible_quantity_values = [
        item["eligible_quantity"]
        for item in candidate_values
    ]

    cost_values = [
        item["cost"]
        for item in candidate_values
    ]

    min_sla = min(sla_values)
    max_sla = max(sla_values)

    min_ageing = min(ageing_values)
    max_ageing = max(ageing_values)

    min_rlt = min(rlt_values)
    max_rlt = max(rlt_values)

    min_eligible_quantity = min(
        eligible_quantity_values
    )
    max_eligible_quantity = max(
        eligible_quantity_values
    )

    min_cost = min(cost_values)
    max_cost = max(cost_values)

    score_lookup: dict[
        tuple[str, str],
        dict,
    ] = {}

    for item in candidate_values:
        candidate = item["candidate"]

        sla_score = _normalize_lower_is_better(
            value=item["sla"],
            minimum_value=min_sla,
            maximum_value=max_sla,
        )

        ageing_score = _normalize_higher_is_better(
            value=item["ageing"],
            minimum_value=min_ageing,
            maximum_value=max_ageing,
        )

        rlt_score = _normalize_lower_is_better(
            value=item["rlt"],
            minimum_value=min_rlt,
            maximum_value=max_rlt,
        )

        eligible_quantity_score = (
            _normalize_higher_is_better(
                value=item["eligible_quantity"],
                minimum_value=min_eligible_quantity,
                maximum_value=max_eligible_quantity,
            )
        )

        cost_score = _normalize_lower_is_better(
            value=item["cost"],
            minimum_value=min_cost,
            maximum_value=max_cost,
        )

        total_score = (
            sla_weight * sla_score
            + ageing_weight * ageing_score
            + rlt_weight * rlt_score
            + eligible_quantity_weight
            * eligible_quantity_score
            + cost_weight * cost_score
        )

        # lookup_key = (
        #     str(candidate.location).strip(),
        #     str(candidate.material_code).strip(),
        # )

        lookup_key = (
            str(candidate.location)
            .strip()
            .upper()
            .removesuffix(".0"),
            str(candidate.material_code)
            .strip()
            .upper()
            .removesuffix(".0"),
        )


        score_lookup[lookup_key] = {
            "total_score": total_score,
            "sla_score": sla_score,
            "ageing_score": ageing_score,
            "rlt_score": rlt_score,
            "eligible_quantity_score": (
                eligible_quantity_score
            ),
            "cost_score": cost_score,
        }

    return score_lookup


def build_replenishment_alternative_sort_key(
    candidates: list[CandidateSource],
    scoring_config: dict,
):
    """
    Builds a sorting function for Replenishment alternatives.

    Alternatives are sorted by:
    1. Highest total weighted score.
    2. Higher current eligible quantity.
    3. Lower SLA.
    4. Lower RLT.
    5. Lower cost.
    6. Location code.

    The first criterion is the actual weighted score.
    Remaining criteria provide deterministic tie-breaking.
    """

    score_lookup = (
        build_replenishment_weighted_score_lookup(
            candidates=candidates,
            scoring_config=scoring_config,
        )
    )

    def sort_key(
        candidate: CandidateSource,
    ) -> tuple:
        # lookup_key = (
        #     str(candidate.location).strip(),
        #     str(candidate.material_code).strip(),
        # )
        lookup_key = (
            str(candidate.location)
            .strip()
            .upper()
            .removesuffix(".0"),
            str(candidate.material_code)
            .strip()
            .upper()
            .removesuffix(".0"),
        )


        score_data = score_lookup.get(
            lookup_key,
            {},
        )

        total_score = _to_decimal(
            score_data.get("total_score", 0)
        )

        eligible_quantity = _to_decimal(
            candidate.eligible_quantity,
            Decimal("0"),
        )

        sla_days = _to_decimal(
            candidate.configured_sla_days,
            Decimal("9999"),
        )

        rlt_days = _to_decimal(
            getattr(candidate, "rlt_days", None),
            Decimal("9999"),
        )

        transport_cost = _to_decimal(
            candidate.transport_cost,
            Decimal("999999999"),
        )

        return (
            -total_score,
            -eligible_quantity,
            sla_days,
            rlt_days,
            transport_cost,
            str(candidate.location).strip(),
        )

    return sort_key, score_lookup


def push_alternative_sort_key(
    candidate: CandidateSource,
) -> tuple:
    """
    Push alternatives prefer ageing availability.
    """

    ageing_available = (
        safe_ageing(candidate) > Decimal("0")
    )

    return (
        not ageing_available,
        -safe_ageing(candidate),
        not candidate.full_fill_capable,
        -safe_eligible(candidate),
        safe_sla(candidate),
        safe_rlt(candidate),
        safe_cost(candidate),
        str(candidate.location).strip(),
    )