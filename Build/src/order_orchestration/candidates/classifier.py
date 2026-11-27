from order_orchestration.domain.enums import SourceType


def classify_source_type(
    source_location: str,
    parent_rdc: str,
    location_cluster_map: dict[str, str],
    vepdc_location_code: str,
) -> SourceType:
    """
    Classifies a physical source location for an order.

    Classification rules:
        - If source equals VEPDC location code, classify as VEPDC.
        - If source equals dealer parent RDC, classify as PARENT_RDC.
        - If source is in same cluster as parent RDC, classify as CLUSTER_RDC.
        - Otherwise classify as PAN_INDIA_RDC.

    Cluster mapping and VEPDC code must be provided through configuration
    or master data. Nothing is hard-coded.
    """

    source_location = str(source_location).strip()
    parent_rdc = str(parent_rdc).strip()
    vepdc_location_code = str(vepdc_location_code).strip()

    if source_location == parent_rdc:
        return SourceType.PARENT_RDC

    if source_location == vepdc_location_code:
            return SourceType.VEPDC

    source_cluster = location_cluster_map.get(source_location)
    parent_cluster = location_cluster_map.get(parent_rdc)

    if (
        source_cluster is not None
        and parent_cluster is not None
        and source_cluster == parent_cluster
    ):
        return SourceType.CLUSTER_RDC

    return SourceType.PAN_INDIA_RDC


def is_location_in_same_cluster(
    source_location: str,
    parent_rdc: str,
    location_cluster_map: dict[str, str],
) -> bool:
    """
    Returns True if source location and parent RDC belong to the same cluster.
    """

    source_location = str(source_location).strip()
    parent_rdc = str(parent_rdc).strip()

    source_cluster = location_cluster_map.get(source_location)
    parent_cluster = location_cluster_map.get(parent_rdc)

    return (
        source_cluster is not None
        and parent_cluster is not None
        and source_cluster == parent_cluster
    )


def is_vepdc_location(
    source_location: str,
    vepdc_location_code: str,
) -> bool:
    """
    Returns True if source location is VEPDC.
    """

    return str(source_location).strip() == str(vepdc_location_code).strip()