from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional

from order_orchestration.domain.enums import SourceType, TransportMode, ReasonCode


@dataclass
class CandidateSource:
    """
    Represents one possible fulfilment source for an order line.

    A candidate can be:
    - Parent RDC
    - Parent-bound GIT
    - Cluster RDC
    - PAN-India RDC
    - VEPDC

    Every candidate should be retained in the audit, whether selected,
    eligible, partially eligible, or rejected.

    Notes:
    - configured_sla_days is used because logistics SLA is available as
      fixed transit days in the logistics master.
    - pickup and drop buffers are part of Route, not stored separately here.
    """

    location: str
    source_type: SourceType
    material_code: str
    requested_quantity: Decimal
    available_quantity: Decimal
    safety_stock: Decimal
    eligible_quantity: Decimal
    full_fill_capable: bool

    ageing_quantity: Decimal = Decimal("0")
    cluster: Optional[str] = None
    region: Optional[str] = None

    route_available: bool = False
    allowed_transport_modes: list[TransportMode] = field(default_factory=list)
    selected_transport_mode: Optional[TransportMode] = None

    configured_sla_days: Optional[int] = None
    rlt_days: Optional[int] = None
    transport_cost: Optional[Decimal] = None
    expected_dispatch: Optional[datetime] = None
    expected_delivery: Optional[datetime] = None

    eligible: bool = False
    rejection_reason_codes: list[ReasonCode] = field(default_factory=list)

    norms: Decimal | None = None
    norms_found: bool = False
    safety_stock_exempt_due_to_norms: bool = False

    mad: Decimal = Decimal("1")
    mad_default_used: bool = False
    calculated_safety_stock: Decimal = Decimal("0")
    safety_stock_protected: bool = False
    safety_stock_policy: str = ""

    route_default_used: bool = False
    sla_default_used: bool = False
    rlt_default_used: bool = False

    master_data_default_used: bool = False