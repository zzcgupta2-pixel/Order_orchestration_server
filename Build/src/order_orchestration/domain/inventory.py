from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass
class InventoryPosition:
    """
    Represents inventory for one material at one location.

    Current available data supports:
    - actual_stock
    - allocated_quantity
    - pending_so_quantity
    - safety_stock

    Blocked stock and quality-hold stock are not included yet because
    those fields are not currently available in the cleaned input data.
    """

    snapshot_timestamp: datetime
    location: str
    material_code: str
    actual_stock: Decimal
    allocated_quantity: Decimal
    pending_so_quantity: Decimal
    safety_stock: Decimal
    ageing_quantity: Decimal = Decimal("0")
    ageing_quantity_gt_1yr: Decimal = Decimal("0")
    
# from dataclasses import dataclass
# from datetime import datetime
# from decimal import Decimal


# @dataclass
# class InventoryPosition:
#     snapshot_timestamp: datetime
#     location: str
#     material_code: str
#     unrestricted_stock: Decimal
#     allocated_quantity: Decimal
#     pending_so_quantity: Decimal
#     blocked_quantity: Decimal
#     quality_hold_quantity: Decimal
#     safety_stock: Decimal
#     ageing_quantity: Decimal = Decimal("0")
#     ageing_quantity_gt_1yr: Decimal = Decimal("0")

#     @property
#     def eligible_quantity(self) -> Decimal:
#         eligible = (
#             self.unrestricted_stock
#             - self.allocated_quantity
#             - self.pending_so_quantity
#             - self.blocked_quantity
#             - self.quality_hold_quantity
#             - self.safety_stock
#         )
#         return max(Decimal("0"), eligible)