from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class GitShipment:
    material_code: str
    source_location: str
    destination_location: str
    git_quantity: Decimal
    expected_arrival_datetime: datetime
    status: str