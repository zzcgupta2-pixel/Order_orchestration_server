from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional

from order_orchestration.domain.candidate import CandidateSource
from order_orchestration.domain.enums import DecisionType, SourceType, TransportMode, ReasonCode
from order_orchestration.selection.source_selection import SourceSelectionResult

@dataclass
class Decision:
    order_id: str
    line_id: str
    order_type: str
    material_code: str
    dealer_code: str
    parent_rdc: str
    decision_timestamp: datetime
    decision: DecisionType
    requested_quantity: Decimal
    allocated_quantity: Decimal
    remaining_quantity: Decimal
    selected_source: Optional[str] = None
    selected_source_type: Optional[SourceType] = None
    transport_mode: Optional[TransportMode] = None
    expected_dispatch: Optional[datetime] = None
    expected_delivery: Optional[datetime] = None
    configured_sla_hours: Optional[int] = None
    transport_cost: Optional[Decimal] = None
    first_fill_rate: Decimal = Decimal("0")
    reason_codes: list[ReasonCode] = field(default_factory=list)
    business_explanation: str = ""
    candidate_evaluations: list[CandidateSource] = field(default_factory=list)
    rule_version: str = "1.0"
    configuration_version: str = "1.0"