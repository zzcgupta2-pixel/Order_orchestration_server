from order_orchestration.candidates.classifier import (
    classify_source_type,
    is_location_in_same_cluster,
    is_vepdc_location,
)
from order_orchestration.domain.enums import SourceType


def test_classifies_parent_rdc():
    location_cluster_map = {
        "1158": "NORTH",
        "1157": "NORTH",
        "1141": "SOUTH",
        "1110": "VEPDC",
    }

    source_type = classify_source_type(
        source_location="1158",
        parent_rdc="1158",
        location_cluster_map=location_cluster_map,
        vepdc_location_code="1110",
    )

    assert source_type == SourceType.PARENT_RDC


def test_classifies_cluster_rdc():
    location_cluster_map = {
        "1158": "NORTH",
        "1157": "NORTH",
        "1141": "SOUTH",
        "1110": "VEPDC",
    }

    source_type = classify_source_type(
        source_location="1157",
        parent_rdc="1158",
        location_cluster_map=location_cluster_map,
        vepdc_location_code="1110",
    )

    assert source_type == SourceType.CLUSTER_RDC


def test_classifies_pan_india_rdc():
    location_cluster_map = {
        "1158": "NORTH",
        "1157": "NORTH",
        "1141": "SOUTH",
        "1110": "VEPDC",
    }

    source_type = classify_source_type(
        source_location="1141",
        parent_rdc="1158",
        location_cluster_map=location_cluster_map,
        vepdc_location_code="1110",
    )

    assert source_type == SourceType.PAN_INDIA_RDC


def test_classifies_vepdc():
    location_cluster_map = {
        "1158": "NORTH",
        "1157": "NORTH",
        "1141": "SOUTH",
        "1110": "VEPDC",
    }

    source_type = classify_source_type(
        source_location="1110",
        parent_rdc="1158",
        location_cluster_map=location_cluster_map,
        vepdc_location_code="1110",
    )

    assert source_type == SourceType.VEPDC


def test_same_cluster_true():
    location_cluster_map = {
        "1158": "NORTH",
        "1157": "NORTH",
    }

    assert (
        is_location_in_same_cluster(
            source_location="1157",
            parent_rdc="1158",
            location_cluster_map=location_cluster_map,
        )
        is True
    )


def test_same_cluster_false():
    location_cluster_map = {
        "1158": "NORTH",
        "1141": "SOUTH",
    }

    assert (
        is_location_in_same_cluster(
            source_location="1141",
            parent_rdc="1158",
            location_cluster_map=location_cluster_map,
        )
        is False
    )


def test_is_vepdc_location_true():
    assert is_vepdc_location(
        source_location="1110",
        vepdc_location_code="1110",
    ) is True


def test_is_vepdc_location_false():
    assert is_vepdc_location(
        source_location="1158",
        vepdc_location_code="1110",
    ) is False