from decimal import Decimal
from typing import Iterable, Optional

from order_orchestration.candidates.classifier import classify_source_type
from order_orchestration.domain.candidate import CandidateSource
from order_orchestration.domain.enums import SourceType
from order_orchestration.domain.git import GitShipment
from order_orchestration.domain.inventory import InventoryPosition
from order_orchestration.domain.order import OrderLine


def generate_physical_source_candidates(
    order_line: OrderLine,
    inventory_positions: Iterable[InventoryPosition],
    location_cluster_map: dict[str, str],
    vepdc_location_code: str,
    allowed_source_types: Optional[set[SourceType]] = None,
) -> list:
    """
    Generates physical inventory source candidates for an order line.
    """

    candidates: list[CandidateSource] = []

    for position in inventory_positions:
        if position.material_code != order_line.material_code:
            continue

        source_type = classify_source_type(
            source_location=position.location,
            parent_rdc=order_line.parent_rdc,
            location_cluster_map=location_cluster_map,
            vepdc_location_code=vepdc_location_code,
        )

        if allowed_source_types is not None and source_type not in allowed_source_types:
            continue

        candidate = CandidateSource(
            location=position.location,
            source_type=source_type,
            material_code=position.material_code,
            requested_quantity=order_line.remaining_quantity,
            available_quantity=position.actual_stock,
            safety_stock=position.safety_stock,
            eligible_quantity=Decimal("0"),
            full_fill_capable=False,
            ageing_quantity=position.ageing_quantity_gt_1yr,
            cluster=location_cluster_map.get(position.location),
            region=None,
            route_available=False,
            eligible=False,
            rejection_reason_codes=[],
        )

        candidates.append(candidate)

    return candidates


def generate_parent_git_candidates(
    order_line: OrderLine,
    git_shipments: Iterable[GitShipment],
) -> list:
    """
    Generates Parent-bound GIT candidates for an order line.
    """

    candidates: list[CandidateSource] = []

    for shipment in git_shipments:
        if shipment.material_code != order_line.material_code:
            continue

        if shipment.destination_location != order_line.parent_rdc:
            continue

        candidate = CandidateSource(
            location=shipment.destination_location,
            source_type=SourceType.PARENT_GIT,
            material_code=shipment.material_code,
            requested_quantity=order_line.remaining_quantity,
            available_quantity=shipment.git_quantity,
            safety_stock=Decimal("0"),
            eligible_quantity=shipment.git_quantity,
            full_fill_capable=shipment.git_quantity >= order_line.remaining_quantity,
            ageing_quantity=Decimal("0"),
            cluster=None,
            region=None,
            route_available=True,
            eligible=True,
            rejection_reason_codes=[],
        )

        candidates.append(candidate)

    return candidates


def generate_all_source_candidates(
    order_line: OrderLine,
    inventory_positions: Iterable[InventoryPosition],
    git_shipments: Iterable[GitShipment],
    location_cluster_map: dict[str, str],
    vepdc_location_code: str,
    allowed_source_types: Optional[set[SourceType]] = None,
    include_parent_git: bool = True,
) -> list:
    """
    Generates all source candidates for an order line.
    """

    candidates = generate_physical_source_candidates(
        order_line=order_line,
        inventory_positions=inventory_positions,
        location_cluster_map=location_cluster_map,
        vepdc_location_code=vepdc_location_code,
        allowed_source_types=allowed_source_types,
    )

    if include_parent_git:
        candidates.extend(
            generate_parent_git_candidates(
                order_line=order_line,
                git_shipments=git_shipments,
            )
        )

    return candidates