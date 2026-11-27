from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from order_orchestration.data.moq_resolver import (
    floor_to_moq,
)
from order_orchestration.domain.order import OrderLine
from order_orchestration.state.git_state import (
    AvailableGitShipment,
    GitReservationMovement,
    GitStateManager,
)


@dataclass(frozen=True)
class ReplenishmentGitCandidate:
    """
    Earliest eligible GIT ASN for one Replenishment order.
    """

    shipment: AvailableGitShipment

    arrival_days_from_decision: int
    eligible_quantity: Decimal
    moq_aligned_capacity: Decimal

    full_fill_capable: bool


@dataclass(frozen=True)
class ReplenishmentGitAllocationResult:
    """
    Result of the priority GIT step.
    """

    candidate: (
        ReplenishmentGitCandidate | None
    )

    reserved_quantity: Decimal
    remaining_quantity: Decimal

    movement: GitReservationMovement | None
    reason_codes: list[str]


# def expected_arrival_days(
#     decision_timestamp: datetime,
#     expected_arrival_datetime: datetime,
# ) -> int:
#     """
#     Returns calendar days until arrival.

#     Past expected-arrival dates are treated as zero days.
#     """

#     difference = (
#         expected_arrival_datetime.date()
#         - decision_timestamp.date()
#     ).days

#     return max(difference, 0)


def select_earliest_replenishment_git(
    order_line: OrderLine,
    git_state: GitStateManager,
    remaining_quantity: Decimal,
    moq_qty: Decimal,
    decision_timestamp: datetime,
    maximum_arrival_days: int = 1,
) -> ReplenishmentGitCandidate | None:
    """
    Chooses the earliest parent GIT ASN satisfying:

    - Destination equals order parent RDC
    - Material equals order material
    - Available quantity is positive
    - Expected arrival is today or within one day
    - ASN has at least one MOQ-aligned block

    Only one ASN is selected.
    """

    if remaining_quantity <= Decimal("0"):
        return None

    matching_shipments = (
        git_state.get_matching_shipments(
            destination_location=(
                order_line.parent_rdc
            ),
            material_code=(
                order_line.material_code
            ),
        )
    )

    eligible_candidates: list[
        ReplenishmentGitCandidate
    ] = []

    for shipment in matching_shipments:
        arrival_days_from_decision = (
            _arrival_days(
                decision_timestamp=(
                    decision_timestamp
                ),
                expected_arrival_datetime=(
                    shipment
                    .expected_arrival_datetime
                ),
            )
        )

        # GIT is eligible only when it is expected to arrive
        # today or within the configured number of future days.
        #
        # With maximum_arrival_days=1:
        # 0 = today
        # 1 = tomorrow
        #
        # Negative values are overdue and must not be allocated.
        if not (
            0
            <= arrival_days_from_decision
            <= maximum_arrival_days
        ):
            continue

        # if (
        #     arrival_days_from_decision
        #     > maximum_arrival_days
        # ):
        #     continue

        moq_aligned_capacity = (
            floor_to_moq(
                quantity=min(
                    shipment.available_quantity,
                    remaining_quantity,
                ),
                moq_qty=moq_qty,
            )
        )

        if (
            moq_aligned_capacity
            <= Decimal("0")
        ):
            continue

        eligible_candidates.append(
            ReplenishmentGitCandidate(
                shipment=shipment,
                arrival_days_from_decision=(
                    arrival_days_from_decision
                ),
                eligible_quantity=(
                    shipment.available_quantity
                ),
                moq_aligned_capacity=(
                    moq_aligned_capacity
                ),
                full_fill_capable=(
                    moq_aligned_capacity
                    >= remaining_quantity
                ),
            )
        )

    if not eligible_candidates:
        return None

    return sorted(
        eligible_candidates,
        key=lambda candidate: (
            candidate.shipment
            .expected_arrival_datetime,
            candidate
            .arrival_days_from_decision,
            candidate.shipment
            .inbound_rlt_days,
            candidate.shipment
            .dispatch_datetime,
            str(
                candidate.shipment.asn_number
            ).strip(),
            str(
                candidate.shipment
                .source_location
            ).strip(),
        ),
    )[0]

def _arrival_days(
    decision_timestamp: datetime,
    expected_arrival_datetime: datetime,
) -> int:
    return (
        expected_arrival_datetime.date()
        - decision_timestamp.date()
    ).days

def allocate_priority_replenishment_git(
    order_line: OrderLine,
    git_state: GitStateManager,
    remaining_quantity: Decimal,
    moq_qty: Decimal,
    git_reference_timestamp: datetime,
    movement_timestamp: datetime,   
    # decision_timestamp: datetime,
    maximum_arrival_days: int = 1,
) -> ReplenishmentGitAllocationResult:
    """
    Reserves the earliest GIT ASN before physical alternatives.

    This function is intended only for Replenishment colour
    codes 16-20.

    Replenishment colour codes 11-15 must never call it.
    """

    selected_candidate = (
        select_earliest_replenishment_git(
            order_line=order_line,
            git_state=git_state,
            remaining_quantity=(
                remaining_quantity
            ),
            moq_qty=moq_qty,
            decision_timestamp=(
                git_reference_timestamp
            ),
            maximum_arrival_days=(
                maximum_arrival_days
            ),
        )
    )

    if selected_candidate is None:
        return ReplenishmentGitAllocationResult(
            candidate=None,
            reserved_quantity=Decimal("0"),
            remaining_quantity=(
                remaining_quantity
            ),
            movement=None,
            reason_codes=[
                "NO_ELIGIBLE_PARENT_GIT_WITHIN_ONE_DAY",
            ],
        )

    # Defensive validation: overdue or late GIT must never
    # reach the reservation stage.
    if not (
        0
        <= selected_candidate.arrival_days_from_decision
        <= maximum_arrival_days
    ):
        raise ValueError(
            "Invalid GIT reservation attempt. "
            f"Order={order_line.order_id}, "
            f"line={order_line.line_id}, "
            f"ASN={selected_candidate.shipment.asn_number}, "
            f"arrival_days="
            f"{selected_candidate.arrival_days_from_decision}. "
            "Only GIT arriving between 0 and "
            f"{maximum_arrival_days} day(s) is eligible."
        )

    reservation_quantity = (
        selected_candidate
        .moq_aligned_capacity
    )

    movement = git_state.reserve(
        order_id=order_line.order_id,
        line_id=order_line.line_id,
        order_category=(
            order_line.order_type.value
        ),
        shipment=(
            selected_candidate.shipment
        ),
        quantity=reservation_quantity,
        arrival_days_from_decision=(
            selected_candidate
            .arrival_days_from_decision
        ),
        movement_timestamp=(
            movement_timestamp
        ),
        reason_code=(
            "REPLENISHMENT_PARENT_GIT_"
            "WITHIN_ONE_DAY"
        ),
    )

    remaining_after_git = max(
        remaining_quantity
        - reservation_quantity,
        Decimal("0"),
    )

    reason_codes = [
        "REPLENISHMENT_PARENT_GIT_WITHIN_ONE_DAY",
        "GIT_DEFERRED_ALLOCATION",
    ]

    if (
        reservation_quantity
        >= remaining_quantity
    ):
        reason_codes.append(
            "PARENT_GIT_FULL_FILL"
        )
    else:
        reason_codes.append(
            "PARENT_GIT_PARTIAL_FILL"
        )

    return ReplenishmentGitAllocationResult(
        candidate=selected_candidate,
        reserved_quantity=(
            reservation_quantity
        ),
        remaining_quantity=(
            remaining_after_git
        ),
        movement=movement,
        reason_codes=reason_codes,
    )