from datetime import datetime, timezone
from decimal import Decimal

import pandas as pd
import pytest

from order_orchestration.data.adapters import (
    git_dataframe_to_shipments,
    logistics_dataframe_to_routes,
)
from order_orchestration.domain.enums import OrderType, TransportMode


def test_git_dataframe_to_shipments_with_expected_arrival_column():
    git_df = pd.DataFrame(
        {
            "material_code": ["MAT-001"],
            "from_location": ["1110"],
            "to_plant": ["1158"],
            "git_qty": [20],
            "expected_arrival_datetime": ["2026-07-25 10:00:00+00:00"],
            "status": ["IN_TRANSIT"],
        }
    )

    shipments = git_dataframe_to_shipments(
        git_df=git_df,
        expected_arrival_column="expected_arrival_datetime",
        status_column="status",
    )

    assert len(shipments) == 1

    shipment = shipments[0]

    assert shipment.material_code == "MAT-001"
    assert shipment.source_location == "1110"
    assert shipment.destination_location == "1158"
    assert shipment.git_quantity == Decimal("20")
    assert shipment.status == "IN_TRANSIT"
    assert shipment.expected_arrival_datetime.tzinfo is not None


def test_git_dataframe_to_shipments_with_default_expected_arrival():
    git_df = pd.DataFrame(
        {
            "material_code": ["MAT-001"],
            "from_location": ["1110"],
            "to_plant": ["1158"],
            "git_qty": [20],
        }
    )

    shipments = git_dataframe_to_shipments(
        git_df=git_df,
        default_expected_arrival_datetime=datetime(
            2026,
            7,
            25,
            10,
            0,
            tzinfo=timezone.utc,
        ),
    )

    assert len(shipments) == 1
    assert shipments[0].expected_arrival_datetime.tzinfo is not None
    assert shipments[0].status == "IN_TRANSIT"


def test_git_dataframe_to_shipments_missing_expected_arrival_raises_error():
    git_df = pd.DataFrame(
        {
            "material_code": ["MAT-001"],
            "from_location": ["1110"],
            "to_plant": ["1158"],
            "git_qty": [20],
        }
    )

    with pytest.raises(ValueError):
        git_dataframe_to_shipments(git_df=git_df)


def test_git_dataframe_to_shipments_missing_required_column_raises_error():
    git_df = pd.DataFrame(
        {
            "material_code": ["MAT-001"],
            "to_plant": ["1158"],
            "git_qty": [20],
        }
    )

    with pytest.raises(ValueError):
        git_dataframe_to_shipments(
            git_df=git_df,
            default_expected_arrival_datetime=datetime(
                2026,
                7,
                25,
                10,
                0,
                tzinfo=timezone.utc,
            ),
        )


def test_logistics_dataframe_to_routes_creates_routes():
    logistics_df = pd.DataFrame(
        {
            "dealer_code": ["DEALER-001"],
            "vepdc_air": [1],
            "vepdc_surface": [5],
            "vepdc_air_rate": [1000],
            "vepdc_surface_rate": [500],
            "lucknow_air": [2],
            "lucknow_surface": [3],
            "lucknow_air_rate": [900],
            "lucknow_surface_rate": [400],
        }
    )

    rdc_source_mapping = {
        "vepdc": "1110",
        "lucknow": "1158",
    }

    routes = logistics_dataframe_to_routes(
        logistics_df=logistics_df,
        rdc_source_mapping=rdc_source_mapping,
        effective_start_datetime=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )

    assert len(routes) == 4

    route_keys = {
        (route.source_location, route.destination_location, route.transport_mode)
        for route in routes
    }

    assert ("1110", "DEALER-001", TransportMode.AIR) in route_keys
    assert ("1110", "DEALER-001", TransportMode.SURFACE) in route_keys
    assert ("1158", "DEALER-001", TransportMode.AIR) in route_keys
    assert ("1158", "DEALER-001", TransportMode.SURFACE) in route_keys


def test_logistics_dataframe_to_routes_maps_sla_days_and_cost():
    logistics_df = pd.DataFrame(
        {
            "dealer_code": ["DEALER-001"],
            "lucknow_surface": [3],
            "lucknow_surface_rate": [400],
        }
    )

    rdc_source_mapping = {
        "lucknow": "1158",
    }

    routes = logistics_dataframe_to_routes(
        logistics_df=logistics_df,
        rdc_source_mapping=rdc_source_mapping,
        effective_start_datetime=datetime(2026, 7, 1, tzinfo=timezone.utc),
        mode_names=("surface",),
    )

    assert len(routes) == 1

    route = routes[0]

    assert route.source_location == "1158"
    assert route.destination_location == "DEALER-001"
    assert route.transport_mode == TransportMode.SURFACE
    assert route.standard_sla_days == 3
    assert route.transport_cost == Decimal("400")
    assert route.pickup_buffer_hours == 4
    assert route.drop_buffer_hours == 4
    assert route.connectivity_available is True


def test_logistics_dataframe_to_routes_skips_zero_sla():
    logistics_df = pd.DataFrame(
        {
            "dealer_code": ["DEALER-001"],
            "lucknow_surface": [0],
            "lucknow_surface_rate": [400],
        }
    )

    rdc_source_mapping = {
        "lucknow": "1158",
    }

    routes = logistics_dataframe_to_routes(
        logistics_df=logistics_df,
        rdc_source_mapping=rdc_source_mapping,
        effective_start_datetime=datetime(2026, 7, 1, tzinfo=timezone.utc),
        mode_names=("surface",),
    )

    assert len(routes) == 0


def test_logistics_dataframe_to_routes_missing_dealer_column_raises_error():
    logistics_df = pd.DataFrame(
        {
            "lucknow_surface": [3],
            "lucknow_surface_rate": [400],
        }
    )

    rdc_source_mapping = {
        "lucknow": "1158",
    }

    with pytest.raises(ValueError):
        logistics_dataframe_to_routes(
            logistics_df=logistics_df,
            rdc_source_mapping=rdc_source_mapping,
            effective_start_datetime=datetime(2026, 7, 1, tzinfo=timezone.utc),
            mode_names=("surface",),
        )


def test_logistics_dataframe_to_routes_custom_applicable_order_types():
    logistics_df = pd.DataFrame(
        {
            "dealer_code": ["DEALER-001"],
            "lucknow_surface": [3],
            "lucknow_surface_rate": [400],
        }
    )

    rdc_source_mapping = {
        "lucknow": "1158",
    }

    routes = logistics_dataframe_to_routes(
        logistics_df=logistics_df,
        rdc_source_mapping=rdc_source_mapping,
        effective_start_datetime=datetime(2026, 7, 1, tzinfo=timezone.utc),
        mode_names=("surface",),
        applicable_order_types_by_mode={
            "SURFACE": (OrderType.REPLENISHMENT, OrderType.PUSH),
        },
    )

    assert len(routes) == 1
    assert routes[0].applicable_order_types == (
        OrderType.REPLENISHMENT,
        OrderType.PUSH,
    )