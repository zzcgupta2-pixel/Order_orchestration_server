from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from order_orchestration.domain.enums import OrderType


@dataclass(frozen=True)
class OrderLine:
    order_id: str
    line_id: str
    order_creation_timestamp: datetime
    order_type: OrderType
    material_code: str
    dealer_code: str
    parent_rdc: str
    requested_quantity: Decimal
    remaining_quantity: Decimal
    is_credit_blocked: bool = False

    colour_code: int | None = None
    raw_order_type: str | None = None
    dealer_norms: Decimal | None = None