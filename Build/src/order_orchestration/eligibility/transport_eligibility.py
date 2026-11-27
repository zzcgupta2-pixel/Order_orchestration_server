from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from order_orchestration.domain.enums import OrderType, ReasonCode, TransportMode
from order_orchestration.domain.route import Route


@dataclass(frozen=True)
class TransportEligibilityResult:
    """
    Represents the result of transport eligibility evaluation.

    Attributes:
        eligible:
            True if the route can be used for the order.
        reason_codes:
            Reason codes explaining why the route was accepted or rejected.
    """

    eligible: bool
    reason_codes: list[ReasonCode] = field(default_factory=list)


def get_allowed_transport_modes_for_order_type(
    order_type: OrderType,
    allowed_transport_modes_config: dict[str, list[str]],
) -> set[TransportMode]:
    """
    Returns configured allowed transport modes for an order type.

    Example config:
        {
            "VOR": ["AIR", "COURIER_EXPRESS", "SURFACE"],
            "REPLENISHMENT": ["MILK_RUN", "SURFACE", "PART_TRUCK_LOAD"],
            "PUSH": ["SURFACE", "PART_TRUCK_LOAD", "FULL_TRUCK_LOAD"]
        }
    """

    configured_modes = allowed_transport_modes_config.get(order_type.value, [])

    return {
        TransportMode(mode)
        for mode in configured_modes
    }


def is_transport_mode_allowed(
    route: Route,
    order_type: OrderType,
    allowed_transport_modes_config: dict[str, list[str]],
) -> bool:
    """
    Checks whether the route transport mode is allowed for the order type.

    This check is based on transport_rules.yaml or another supplied config.
    """

    allowed_modes = get_allowed_transport_modes_for_order_type(
        order_type=order_type,
        allowed_transport_modes_config=allowed_transport_modes_config,
    )

    return route.transport_mode in allowed_modes


def evaluate_transport_eligibility(
    route: Optional[Route],
    order_type: OrderType,
    decision_datetime: datetime,
    allowed_transport_modes_config: dict[str, list[str]],
) -> TransportEligibilityResult:
    """
    Evaluates whether a route is eligible for an order.

    Checks performed:
        1. Route exists.
        2. Route is effective on decision datetime.
        3. Transport connectivity is available.
        4. Route is applicable for the order type.
        5. Transport mode is allowed by configuration.
        6. SLA and buffers are valid.
        7. Transport cost is valid.

    The function is deterministic and returns all rejection reason codes.
    """

    reason_codes: list[ReasonCode] = []

    if route is None:
        return TransportEligibilityResult(
            eligible=False,
            reason_codes=[ReasonCode.MISSING_MASTER_DATA],
        )

    if not route.is_effective_on(decision_datetime):
        reason_codes.append(ReasonCode.ROUTE_NOT_EFFECTIVE)

    if not route.connectivity_available:
        reason_codes.append(ReasonCode.NO_TRANSPORT_CONNECTIVITY)

    if not route.is_applicable_for_order_type(order_type):
        reason_codes.append(ReasonCode.INVALID_ORDER_TYPE)

    if not is_transport_mode_allowed(
        route=route,
        order_type=order_type,
        allowed_transport_modes_config=allowed_transport_modes_config,
    ):
        reason_codes.append(ReasonCode.TRANSPORT_MODE_NOT_ALLOWED)

    if not route.has_valid_sla():
        reason_codes.append(ReasonCode.INVALID_ROUTE_SLA)

    if not route.has_valid_cost():
        reason_codes.append(ReasonCode.INVALID_TRANSPORT_COST)

    if reason_codes:
        return TransportEligibilityResult(
            eligible=False,
            reason_codes=reason_codes,
        )

    return TransportEligibilityResult(
        eligible=True,
        reason_codes=[ReasonCode.SLA_SATISFIED],
    )