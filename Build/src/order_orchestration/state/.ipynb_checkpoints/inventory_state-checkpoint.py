from __future__ import annotations
from datetime import datetime
from decimal import Decimal
from typing import Iterable

from order_orchestration.domain.enums import ReasonCode
from order_orchestration.domain.inventory import InventoryPosition
from order_orchestration.domain.inventory_movement import InventoryMovement
from order_orchestration.exceptions import (
    DuplicateExecutionError,
    InventoryStateError,
)


class InventoryStateManager:
    """
    Manages simulated inventory state during orchestration or historical replay.

    Tracks:
    - total available inventory
    - ageing available inventory

    Important:
    Multi-source Push ageing allocation requires one order line to allocate
    from more than one location. Therefore duplicate protection is done at:

        order_id + line_id + location + material_code

    not only at:

        order_id + line_id
    """

    def __init__(self, inventory_positions: Iterable[InventoryPosition]) -> None:
        self._inventory_balance: dict[tuple[str, str], Decimal] = {}
        self._ageing_balance: dict[tuple[str, str], Decimal] = {}
        self._movements: list[InventoryMovement] = []

        self._processed_order_keys: set[tuple[str, str]] = set()
        self._processed_allocation_keys: set[tuple[str, str, str, str]] = set()

        for position in inventory_positions:
            key = self._build_inventory_key(
                location=position.location,
                material_code=position.material_code,
            )

            available_quantity = (
                position.actual_stock
                - position.allocated_quantity
                - position.pending_so_quantity
            )

            if available_quantity < Decimal("0"):
                available_quantity = Decimal("0")

            ageing_quantity = position.ageing_quantity

            if ageing_quantity < Decimal("0"):
                ageing_quantity = Decimal("0")

            # Ageing cannot exceed available stock.
            ageing_quantity = min(ageing_quantity, available_quantity)

            self._inventory_balance[key] = available_quantity
            self._ageing_balance[key] = ageing_quantity

    @staticmethod
    def _build_inventory_key(
        location: str,
        material_code: str,
    ) -> tuple[str, str]:
        return (
            str(location).strip(),
            str(material_code).strip(),
        )

    @staticmethod
    def _build_order_key(
        order_id: str,
        line_id: str,
    ) -> tuple[str, str]:
        return (
            str(order_id).strip(),
            str(line_id).strip(),
        )

    @staticmethod
    def _build_allocation_key(
        order_id: str,
        line_id: str,
        location: str,
        material_code: str,
    ) -> tuple[str, str, str, str]:
        return (
            str(order_id).strip(),
            str(line_id).strip(),
            str(location).strip(),
            str(material_code).strip(),
        )

    def get_available_quantity(
        self,
        location: str,
        material_code: str,
    ) -> Decimal:
        key = self._build_inventory_key(
            location=location,
            material_code=material_code,
        )

        return self._inventory_balance.get(key, Decimal("0"))

    def get_available_ageing_quantity(
        self,
        location: str,
        material_code: str,
    ) -> Decimal:
        key = self._build_inventory_key(
            location=location,
            material_code=material_code,
        )

        return self._ageing_balance.get(key, Decimal("0"))

    def has_inventory_position(
        self,
        location: str,
        material_code: str,
    ) -> bool:
        key = self._build_inventory_key(
            location=location,
            material_code=material_code,
        )

        return key in self._inventory_balance

    def has_processed_order(
        self,
        order_id: str,
        line_id: str,
    ) -> bool:
        order_key = self._build_order_key(
            order_id=order_id,
            line_id=line_id,
        )

        return order_key in self._processed_order_keys

    def mark_order_processed(
        self,
        order_id: str,
        line_id: str,
    ) -> None:
        order_key = self._build_order_key(
            order_id=order_id,
            line_id=line_id,
        )

        self._processed_order_keys.add(order_key)

    def has_processed_allocation(
        self,
        order_id: str,
        line_id: str,
        location: str,
        material_code: str,
    ) -> bool:
        allocation_key = self._build_allocation_key(
            order_id=order_id,
            line_id=line_id,
            location=location,
            material_code=material_code,
        )

        return allocation_key in self._processed_allocation_keys

    def allocate(
        self,
        order_id: str,
        line_id: str,
        location: str,
        material_code: str,
        quantity: Decimal,
        movement_timestamp: datetime,
        reason_code: ReasonCode = ReasonCode.SINGLE_SOURCE_REROUTE,
        remarks: str | None = None,
    ) -> InventoryMovement:
        """
        Allocates inventory from one location-material position.

        Also reduces ageing stock if ageing stock is available.

        Ageing consumption logic:
            ageing_consumed = min(allocation_quantity, current_ageing_quantity)
        """

        if quantity <= Decimal("0"):
            raise InventoryStateError(
                "Allocation quantity must be greater than zero."
            )

        inventory_key = self._build_inventory_key(
            location=location,
            material_code=material_code,
        )

        allocation_key = self._build_allocation_key(
            order_id=order_id,
            line_id=line_id,
            location=location,
            material_code=material_code,
        )

        order_key = self._build_order_key(
            order_id=order_id,
            line_id=line_id,
        )

        if allocation_key in self._processed_allocation_keys:
            raise DuplicateExecutionError(
                f"Duplicate allocation prevented for "
                f"order_id={order_id}, line_id={line_id}, "
                f"location={location}, material_code={material_code}."
            )

        if inventory_key not in self._inventory_balance:
            raise InventoryStateError(
                f"Inventory position not found for location={location}, "
                f"material_code={material_code}."
            )

        inventory_before = self._inventory_balance[inventory_key]
        ageing_before = self._ageing_balance.get(inventory_key, Decimal("0"))

        inventory_after = inventory_before - quantity

        if inventory_after < Decimal("0"):
            raise InventoryStateError(
                "Negative inventory prevented. "
                f"Available={inventory_before}, requested allocation={quantity}."
            )

        ageing_consumed_quantity = min(
            quantity,
            ageing_before,
        )

        ageing_after = ageing_before - ageing_consumed_quantity

        if ageing_after < Decimal("0"):
            ageing_after = Decimal("0")

        self._inventory_balance[inventory_key] = inventory_after
        self._ageing_balance[inventory_key] = ageing_after

        self._processed_order_keys.add(order_key)
        self._processed_allocation_keys.add(allocation_key)

        movement = InventoryMovement.create(
            order_id=order_id,
            line_id=line_id,
            material_code=material_code,
            location=location,
            allocated_quantity=quantity,
            inventory_before=inventory_before,
            inventory_after=inventory_after,
            ageing_before=ageing_before,
            ageing_after=ageing_after,
            ageing_consumed_quantity=ageing_consumed_quantity,
            movement_timestamp=movement_timestamp,
            reason_code=reason_code,
            movement_type="ALLOCATION",
            remarks=remarks,
        )

        self._movements.append(movement)

        return movement

    def get_movements(self) -> list:
        return list(self._movements)

    def get_inventory_balance_snapshot(self) -> dict[tuple[str, str], Decimal]:
        return dict(self._inventory_balance)

    def get_ageing_balance_snapshot(self) -> dict[tuple[str, str], Decimal]:
        return dict(self._ageing_balance)

    def get_processed_order_keys_snapshot(self) -> set[tuple[str, str]]:
        return set(self._processed_order_keys)

    def get_processed_allocation_keys_snapshot(
        self,
    ) -> set[tuple[str, str, str, str]]:
        return set(self._processed_allocation_keys)



# from datetime import datetime
# from decimal import Decimal
# from typing import Iterable

# from order_orchestration.domain.enums import ReasonCode
# from order_orchestration.domain.inventory import InventoryPosition
# from order_orchestration.domain.inventory_movement import InventoryMovement
# from order_orchestration.exceptions import (
#     DuplicateExecutionError,
#     InventoryStateError,
# )


# class InventoryStateManager:
#     """
#     Manages simulated inventory state during orchestration or historical replay.

#     Responsibilities:
#     - Store current inventory by location and material.
#     - Return available inventory.
#     - Allocate inventory safely.
#     - Prevent negative inventory.
#     - Prevent duplicate allocation from the same order-line, location, and material.
#     - Record inventory movement audit logs.

#     Important:
#     Multi-source Push ageing allocation requires one order line to allocate
#     from more than one location. Therefore duplicate protection should not
#     block the same order_id and line_id across different locations.

#     Duplicate allocation is blocked only for:
#         order_id + line_id + location + material_code
#     """

#     def __init__(self, inventory_positions: Iterable[InventoryPosition]) -> None:
#         self._inventory_balance: dict[tuple[str, str], Decimal] = {}
#         self._movements: list[InventoryMovement] = []

#         # Old order-line level tracking is kept for optional external checks.
#         # It should not be used to block multi-source allocation.
#         self._processed_order_keys: set[tuple[str, str]] = set()

#         # New allocation-level duplicate protection.
#         # This allows same order-line to allocate from multiple locations,
#         # but prevents duplicate allocation from the same location-material.
#         self._processed_allocation_keys: set[tuple[str, str, str, str]] = set()

#         for position in inventory_positions:
#             key = self._build_inventory_key(
#                 location=position.location,
#                 material_code=position.material_code,
#             )

#             available_quantity = (
#                 position.actual_stock
#                 - position.allocated_quantity
#                 - position.pending_so_quantity
#                 - position.safety_stock
#             )

#             if available_quantity < Decimal("0"):
#                 available_quantity = Decimal("0")

#             self._inventory_balance[key] = available_quantity

#     @staticmethod
#     def _build_inventory_key(
#         location: str,
#         material_code: str,
#     ) -> tuple[str, str]:
#         """
#         Builds inventory state key.
#         """

#         return (
#             str(location).strip(),
#             str(material_code).strip(),
#         )

#     @staticmethod
#     def _build_order_key(
#         order_id: str,
#         line_id: str,
#     ) -> tuple[str, str]:
#         """
#         Builds order-line key.

#         This is used only to identify whether an order line has been touched
#         at least once. It should not block Push multi-source ageing allocation.
#         """

#         return (
#             str(order_id).strip(),
#             str(line_id).strip(),
#         )

#     @staticmethod
#     def _build_allocation_key(
#         order_id: str,
#         line_id: str,
#         location: str,
#         material_code: str,
#     ) -> tuple[str, str, str, str]:
#         """
#         Builds allocation-level duplicate key.

#         This key allows:
#             same order_id + same line_id + different location

#         But blocks:
#             same order_id + same line_id + same location + same material
#         """

#         return (
#             str(order_id).strip(),
#             str(line_id).strip(),
#             str(location).strip(),
#             str(material_code).strip(),
#         )

#     def get_available_quantity(
#         self,
#         location: str,
#         material_code: str,
#     ) -> Decimal:
#         """
#         Returns current simulated available quantity for a location-material pair.

#         If no inventory position exists, returns Decimal('0').
#         """

#         key = self._build_inventory_key(
#             location=location,
#             material_code=material_code,
#         )

#         return self._inventory_balance.get(key, Decimal("0"))

#     def has_inventory_position(
#         self,
#         location: str,
#         material_code: str,
#     ) -> bool:
#         """
#         Returns True if inventory state contains the location-material pair.
#         """

#         key = self._build_inventory_key(
#             location=location,
#             material_code=material_code,
#         )

#         return key in self._inventory_balance

#     def has_processed_order(
#         self,
#         order_id: str,
#         line_id: str,
#     ) -> bool:
#         """
#         Returns True if the order line has been processed at least once.

#         Note:
#         For Push multi-source ageing allocation, the same order line can have
#         multiple allocation movements from different locations.
#         """

#         order_key = self._build_order_key(
#             order_id=order_id,
#             line_id=line_id,
#         )

#         return order_key in self._processed_order_keys

#     def mark_order_processed(
#         self,
#         order_id: str,
#         line_id: str,
#     ) -> None:
#         """
#         Marks an order line as processed at order-line level.

#         This method is kept for compatibility with existing workflow checks.
#         """

#         order_key = self._build_order_key(
#             order_id=order_id,
#             line_id=line_id,
#         )

#         self._processed_order_keys.add(order_key)

#     def has_processed_allocation(
#         self,
#         order_id: str,
#         line_id: str,
#         location: str,
#         material_code: str,
#     ) -> bool:
#         """
#         Returns True if the same order-line has already allocated from the same
#         location-material pair.
#         """

#         allocation_key = self._build_allocation_key(
#             order_id=order_id,
#             line_id=line_id,
#             location=location,
#             material_code=material_code,
#         )

#         return allocation_key in self._processed_allocation_keys

#     def allocate(
#         self,
#         order_id: str,
#         line_id: str,
#         location: str,
#         material_code: str,
#         quantity: Decimal,
#         movement_timestamp: datetime,
#         reason_code: ReasonCode = ReasonCode.SINGLE_SOURCE_REROUTE,
#         remarks: str | None = None,
#     ) -> InventoryMovement:
#         """
#         Allocates inventory from one location-material position.

#         Rules:
#         - Quantity must be positive.
#         - Inventory position must exist.
#         - Same order-line cannot allocate twice from same location-material.
#         - Same order-line can allocate from different locations.
#         - Inventory must not become negative.
#         - Allocation movement must be recorded.
#         - Inventory balance is reduced immediately after allocation.
#         """

#         if quantity <= Decimal("0"):
#             raise InventoryStateError(
#                 "Allocation quantity must be greater than zero."
#             )

#         inventory_key = self._build_inventory_key(
#             location=location,
#             material_code=material_code,
#         )

#         allocation_key = self._build_allocation_key(
#             order_id=order_id,
#             line_id=line_id,
#             location=location,
#             material_code=material_code,
#         )

#         order_key = self._build_order_key(
#             order_id=order_id,
#             line_id=line_id,
#         )

#         if allocation_key in self._processed_allocation_keys:
#             raise DuplicateExecutionError(
#                 f"Duplicate allocation prevented for "
#                 f"order_id={order_id}, line_id={line_id}, "
#                 f"location={location}, material_code={material_code}."
#             )

#         if inventory_key not in self._inventory_balance:
#             raise InventoryStateError(
#                 f"Inventory position not found for location={location}, "
#                 f"material_code={material_code}."
#             )

#         inventory_before = self._inventory_balance[inventory_key]
#         inventory_after = inventory_before - quantity

#         if inventory_after < Decimal("0"):
#             raise InventoryStateError(
#                 "Negative inventory prevented. "
#                 f"Available={inventory_before}, requested allocation={quantity}."
#             )

#         self._inventory_balance[inventory_key] = inventory_after

#         # Mark both:
#         # 1. order-line touched at least once
#         # 2. specific allocation source used
#         self._processed_order_keys.add(order_key)
#         self._processed_allocation_keys.add(allocation_key)

#         movement = InventoryMovement.create(
#             order_id=order_id,
#             line_id=line_id,
#             material_code=material_code,
#             location=location,
#             allocated_quantity=quantity,
#             inventory_before=inventory_before,
#             inventory_after=inventory_after,
#             movement_timestamp=movement_timestamp,
#             reason_code=reason_code,
#             movement_type="ALLOCATION",
#             remarks=remarks,
#         )

#         self._movements.append(movement)

#         return movement

#     def get_movements(self) -> list:
#         """
#         Returns inventory movement audit log.
#         """

#         return list(self._movements)

#     def get_inventory_balance_snapshot(self) -> dict[tuple[str, str], Decimal]:
#         """
#         Returns a copy of current inventory balance state.
#         """

#         return dict(self._inventory_balance)

#     def get_processed_order_keys_snapshot(self) -> set[tuple[str, str]]:
#         """
#         Returns processed order-line keys.

#         Useful for debugging.
#         """

#         return set(self._processed_order_keys)

#     def get_processed_allocation_keys_snapshot(
#         self,
#     ) -> set[tuple[str, str, str, str]]:
#         """
#         Returns processed allocation-level keys.

#         Useful for debugging Push multi-source allocation.
#         """

#         return set(self._processed_allocation_keys)