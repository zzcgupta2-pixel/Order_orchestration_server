from decimal import Decimal

from order_orchestration.domain.enums import OrderType
from order_orchestration.domain.inventory import InventoryPosition


def should_protect_safety_stock(
    order_type: OrderType,
    safety_stock_config: dict[str, bool],
) -> bool:
    """
    Returns whether safety stock should be protected for the given order type.

    The rule is configurable because business may allow different safety-stock
    behavior for VOR, Replenishment, and Push orders.
    """

    return bool(safety_stock_config.get(order_type.value, True))


def calculate_eligible_quantity(
    inventory_position: InventoryPosition,
    order_type: OrderType,
    safety_stock_config: dict[str, bool],
) -> Decimal:
    """
    Calculates eligible inventory quantity for a material-location position.

    Standard formula:

        eligible_quantity =
            actual_stock
            - allocated_quantity
            - pending_so_quantity
            - safety_stock, if safety stock protection is enabled

    If safety stock protection is disabled for an order type, safety stock
    is not deducted.

    Eligible quantity is never allowed to go below zero.
    """

    safety_stock_to_deduct = (
        inventory_position.safety_stock
        if should_protect_safety_stock(order_type, safety_stock_config)
        else Decimal("0")
    )

    eligible_quantity = (
        inventory_position.actual_stock
        - inventory_position.allocated_quantity
        - inventory_position.pending_so_quantity
        - safety_stock_to_deduct
    )

    return max(Decimal("0"), eligible_quantity)


def is_full_fill_capable(
    eligible_quantity: Decimal,
    requested_quantity: Decimal,
) -> bool:
    """
    Returns True if eligible quantity can fully satisfy requested quantity.
    """

    if requested_quantity <= 0:
        return False

    return eligible_quantity >= requested_quantity


def is_partial_fill_possible(
    eligible_quantity: Decimal,
    requested_quantity: Decimal,
) -> bool:
    """
    Returns True if some positive quantity can be allocated but full fill is not possible.
    """

    if requested_quantity <= 0:
        return False

    return Decimal("0") < eligible_quantity < requested_quantity