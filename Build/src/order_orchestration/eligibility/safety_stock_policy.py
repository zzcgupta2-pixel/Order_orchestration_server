from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING

from order_orchestration.data.mad_resolver import resolve_mad
from order_orchestration.data.rlt_resolver import resolve_rlt_days
from order_orchestration.domain.candidate import CandidateSource
from order_orchestration.domain.enums import OrderType, SourceType
from order_orchestration.domain.order import OrderLine

from order_orchestration.data.norms_resolver import (
    resolve_norms,
)


@dataclass(frozen=True)
class SafetyStockEvaluation:
    """
    Dynamic safety-stock result for one order candidate.
    """

    norms: Decimal | None
    norms_found: bool
    safety_stock_exempt_due_to_norms: bool

    mad: Decimal
    mad_default_used: bool
    rlt_days: Decimal

    calculated_safety_stock: Decimal
    applied_safety_stock: Decimal

    safety_stock_protected: bool
    safety_stock_policy: str

# @dataclass(frozen=True)
# class SafetyStockEvaluation:
#     """
#     Dynamic safety-stock result for one order candidate.
#     """

#     mad: Decimal
#     mad_default_used: bool
#     rlt_days: Decimal
#     calculated_safety_stock: Decimal
#     applied_safety_stock: Decimal
#     safety_stock_protected: bool
#     safety_stock_policy: str


def calculate_dynamic_safety_stock(
    mad: Decimal,
    rlt_days: Decimal,
    round_up_to_whole_unit: bool = True,
) -> Decimal:
    """
    Calculates dynamic safety stock.

    Formula:
        Safety Stock = (MAD / 30) * RLT

    Safety stock is always rounded upward to a whole unit.

    Examples:
        0.01 -> 1
        0.10 -> 1
        0.50 -> 1
        0.60 -> 1
        1.00 -> 1
        1.10 -> 2
        2.20 -> 3
    """

    if mad < Decimal("0"):
        mad = Decimal("0")

    if rlt_days < Decimal("0"):
        rlt_days = Decimal("0")

    calculated_value = (
        mad / Decimal("30")
    ) * rlt_days

    if calculated_value <= Decimal("0"):
        return Decimal("0")
    
    return calculated_value.quantize(
        Decimal("1"),
        rounding=ROUND_CEILING,
    ) 


def is_non_auto_customer(
    dealer_code: str,
) -> bool:
    """
    Current Non-Auto identification rule.
    """

    dealer_code = str(dealer_code).strip().upper()

    return (
        dealer_code.startswith("1E")
        or dealer_code == "1341596"
    )


def should_protect_safety_stock(
    order_line: OrderLine,
    candidate: CandidateSource,
) -> tuple[bool, str]:
    """
    Determines whether safety stock must be deducted for a candidate.

    Rules:

    VOR:
        May consume at parent and alternatives.
        Safety stock is not deducted.

    ACC:
        May consume at parent and alternatives.
        Safety stock is not deducted.

    Replenishment:
        May consume at parent.
        Protect at alternatives.

    Push:
        Protect at parent and all alternatives.

    Non-Auto:
        VEPDC rule is pending.
        Temporary policy: protect safety stock.
    """

    # if is_non_auto_customer(order_line.dealer_code):
    #     return True, "NON_AUTO_VEPDC_SAFETY_STOCK_PROTECTED"

    if order_line.order_type in {
        OrderType.VOR,
        OrderType.ACC,
    }:
        return False, "SAFETY_STOCK_NOT_APPLIED"

    if order_line.order_type == OrderType.REPLENISHMENT:
        if candidate.source_type == SourceType.PARENT_RDC:
            return False, "PARENT_SAFETY_STOCK_NOT_APPLIED"

        return True, "ALTERNATIVE_SAFETY_STOCK_PROTECTED"

    if order_line.order_type == OrderType.PUSH:
        return True, "PUSH_SAFETY_STOCK_PROTECTED"

    return True, "DEFAULT_SAFETY_STOCK_PROTECTED"


def evaluate_dynamic_safety_stock(
    order_line: OrderLine,
    candidate: CandidateSource,
    mad_lookup: dict,
    rlt_lookup: dict,
    norms_lookup: dict,
    missing_mad_combinations: (
        set[tuple[str, str]] | None
    ),
    missing_norms_combinations: (
        set[tuple[str, str]] | None
    ),
    vepdc_location_code: str,
    default_mad: Decimal = Decimal("1"),
    missing_rdc_rlt: int = 0,
    missing_vepdc_rlt: int = 0,
    round_up_to_whole_unit: bool = True,
) -> SafetyStockEvaluation:
    """
    Evaluates dynamic safety stock.

    Global norms rule:
        norms < 3:
            calculated safety stock = 0
            applied safety stock = 0

    Missing norms rule:
        Continue normal MAD-RLT safety-stock calculation.
    """

    norms, norms_found = resolve_norms(
        location=candidate.location,
        material_code=candidate.material_code,
        norms_lookup=norms_lookup,
        missing_combinations=(
            missing_norms_combinations
        ),
    )

    # ---------------------------------------------------------
    # Global safety-stock exemption
    # ---------------------------------------------------------
    if (
        norms_found
        and norms is not None
        and norms < Decimal("3")
    ):
        return SafetyStockEvaluation(
            norms=norms,
            norms_found=True,
            safety_stock_exempt_due_to_norms=True,
            mad=Decimal("0"),
            mad_default_used=False,
            rlt_days=Decimal("0"),
            calculated_safety_stock=Decimal("0"),
            applied_safety_stock=Decimal("0"),
            safety_stock_protected=False,
            safety_stock_policy=(
                "NORMS_BELOW_3_NO_SAFETY_STOCK"
            ),
        )

    # ---------------------------------------------------------
    # Resolve MAD
    # ---------------------------------------------------------
    mad, mad_default_used = resolve_mad(
        location=candidate.location,
        material_code=candidate.material_code,
        mad_lookup=mad_lookup,
        missing_combinations=(
            missing_mad_combinations
        ),
        default_mad=default_mad,
    )

    # ---------------------------------------------------------
    # Resolve RLT
    # ---------------------------------------------------------
    resolved_rlt_days = resolve_rlt_days(
        location=candidate.location,
        material_code=candidate.material_code,
        rlt_lookup=rlt_lookup,
        vepdc_location_code=(
            vepdc_location_code
        ),
        missing_rdc_rlt=missing_rdc_rlt,
        missing_vepdc_rlt=(
            missing_vepdc_rlt
        ),
    )

    rlt_days = Decimal(
        str(resolved_rlt_days)
    )

    # ---------------------------------------------------------
    # Calculate dynamic safety stock
    # ---------------------------------------------------------
    calculated_safety_stock = (
        calculate_dynamic_safety_stock(
            mad=mad,
            rlt_days=rlt_days,
            round_up_to_whole_unit=(
                round_up_to_whole_unit
            ),
        )
    )

    # ---------------------------------------------------------
    # Apply order-source safety-stock policy
    # ---------------------------------------------------------
    (
        protect_safety_stock,
        safety_stock_policy,
    ) = should_protect_safety_stock(
        order_line=order_line,
        candidate=candidate,
    )

    applied_safety_stock = (
        calculated_safety_stock
        if protect_safety_stock
        else Decimal("0")
    )

    # Make missing norms visible in the policy.
    if not norms_found:
        safety_stock_policy = (
            "NORMS_MISSING_"
            + safety_stock_policy
        )

    return SafetyStockEvaluation(
        norms=norms,
        norms_found=norms_found,
        safety_stock_exempt_due_to_norms=False,
        mad=mad,
        mad_default_used=mad_default_used,
        rlt_days=rlt_days,
        calculated_safety_stock=(
            calculated_safety_stock
        ),
        applied_safety_stock=(
            applied_safety_stock
        ),
        safety_stock_protected=(
            protect_safety_stock
        ),
        safety_stock_policy=(
            safety_stock_policy
        ),
    )
# def evaluate_dynamic_safety_stock(
#     order_line: OrderLine,
#     candidate: CandidateSource,
#     mad_lookup: dict,
#     rlt_lookup: dict,
#     missing_mad_combinations: set[tuple[str, str]] | None,
#     vepdc_location_code: str,
#     default_mad: Decimal = Decimal("1"),
#     missing_rdc_rlt: int = 0,
#     missing_vepdc_rlt: int = 0,
#     round_up_to_whole_unit: bool = True,
# ) -> SafetyStockEvaluation:
#     """
#     Calculates dynamic safety stock and determines whether it applies
#     to the current order-source combination.

#     Missing RLT defaults to 0 here, not 9999, because 9999 would create
#     an unrealistic safety-stock calculation.
#     """

#     mad, mad_default_used = resolve_mad(
#         location=candidate.location,
#         material_code=candidate.material_code,
#         mad_lookup=mad_lookup,
#         missing_combinations=missing_mad_combinations,
#         default_mad=default_mad,
#     )

#     resolved_rlt_days = resolve_rlt_days(
#         location=candidate.location,
#         material_code=candidate.material_code,
#         rlt_lookup=rlt_lookup,
#         vepdc_location_code=vepdc_location_code,
#         missing_rdc_rlt=missing_rdc_rlt,
#         missing_vepdc_rlt=missing_vepdc_rlt,
#     )

#     rlt_days = Decimal(str(resolved_rlt_days))

#     calculated_safety_stock = calculate_dynamic_safety_stock(
#         mad=mad,
#         rlt_days=rlt_days,
#         round_up_to_whole_unit=round_up_to_whole_unit,
#     )

#     protect_safety_stock, policy = should_protect_safety_stock(
#         order_line=order_line,
#         candidate=candidate,
#     )

#     applied_safety_stock = (
#         calculated_safety_stock
#         if protect_safety_stock
#         else Decimal("0")
#     )

#     return SafetyStockEvaluation(
#         mad=mad,
#         mad_default_used=mad_default_used,
#         rlt_days=rlt_days,
#         calculated_safety_stock=calculated_safety_stock,
#         applied_safety_stock=applied_safety_stock,
#         safety_stock_protected=protect_safety_stock,
#         safety_stock_policy=policy,
#     )