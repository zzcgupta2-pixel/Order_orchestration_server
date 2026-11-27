from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from order_orchestration.domain.enums import ReasonCode


@dataclass(frozen=True)
class InventoryMovement:
    """
    Inventory movement audit record.

    Tracks both total inventory movement and ageing inventory consumption.
    """

    movement_id: str
    order_id: str
    line_id: str
    material_code: str
    location: str
    allocated_quantity: Decimal
    inventory_before: Decimal
    inventory_after: Decimal
    ageing_before: Decimal
    ageing_after: Decimal
    ageing_consumed_quantity: Decimal
    movement_timestamp: datetime
    reason_code: ReasonCode
    movement_type: str
    remarks: str | None = None

    @classmethod
    def create(
        cls,
        order_id: str,
        line_id: str,
        material_code: str,
        location: str,
        allocated_quantity: Decimal,
        inventory_before: Decimal,
        inventory_after: Decimal,
        movement_timestamp: datetime,
        reason_code: ReasonCode,
        movement_type: str = "ALLOCATION",
        remarks: str | None = None,
        ageing_before: Decimal = Decimal("0"),
        ageing_after: Decimal = Decimal("0"),
        ageing_consumed_quantity: Decimal = Decimal("0"),
    ) -> "InventoryMovement":
        return cls(
            movement_id=str(uuid4()),
            order_id=str(order_id),
            line_id=str(line_id),
            material_code=str(material_code),
            location=str(location),
            allocated_quantity=allocated_quantity,
            inventory_before=inventory_before,
            inventory_after=inventory_after,
            ageing_before=ageing_before,
            ageing_after=ageing_after,
            ageing_consumed_quantity=ageing_consumed_quantity,
            movement_timestamp=movement_timestamp,
            reason_code=reason_code,
            movement_type=movement_type,
            remarks=remarks,
        )