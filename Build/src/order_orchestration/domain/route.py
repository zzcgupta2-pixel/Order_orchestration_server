from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional

from order_orchestration.domain.enums import OrderType, TransportMode


@dataclass(frozen=True)
class Route:
    """
    Represents one configured transportation route between a source location
    and a destination location.

    A route defines whether transportation is possible, which mode is used,
    the configured SLA in days, cost, buffers, and the effective validity period.

    Important:
    - standard_sla_days represents fixed logistics transit time in days.
    - pickup_buffer_hours and drop_buffer_hours are separate from SLA.
    - Delivery date calculation is handled separately in the delivery calculator.
    """

    source_location: str
    destination_location: str
    transport_mode: TransportMode
    standard_sla_days: int
    pickup_buffer_hours: int
    drop_buffer_hours: int
    transport_cost: Decimal
    connectivity_available: bool
    applicable_order_types: tuple[OrderType, ...]
    effective_start_datetime: datetime
    effective_end_datetime: Optional[datetime] = None
    route_type: Optional[str] = None

    def is_effective_on(self, decision_datetime: datetime) -> bool:
        """
        Returns True if the route is effective on the given decision datetime.

        A route is effective when:
        - decision_datetime is greater than or equal to effective_start_datetime
        - and either effective_end_datetime is not maintained
        - or decision_datetime is less than or equal to effective_end_datetime
        """

        if decision_datetime < self.effective_start_datetime:
            return False

        if self.effective_end_datetime is not None:
            if decision_datetime > self.effective_end_datetime:
                return False

        return True

    def is_applicable_for_order_type(self, order_type: OrderType) -> bool:
        """
        Returns True if the route is applicable for the given order type.
        """

        return order_type in self.applicable_order_types

    def has_valid_sla(self) -> bool:
        """
        Returns True if the configured SLA days and buffers are non-negative.

        Here, SLA is measured in days because the logistics master provides
        SLA as number of transit days.
        """

        return (
            self.standard_sla_days >= 0
            and self.pickup_buffer_hours >= 0
            and self.drop_buffer_hours >= 0
        )

    def has_valid_cost(self) -> bool:
        """
        Returns True if transportation cost is non-negative.
        """

        return self.transport_cost >= Decimal("0")