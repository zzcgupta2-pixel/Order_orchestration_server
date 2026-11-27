from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Iterable, Optional
import pandas as pd
from order_orchestration.calendar.delivery_calculator import (
    calculate_route_delivery_result_for_location,
)
from order_orchestration.domain.candidate import CandidateSource
from order_orchestration.domain.enums import OrderType, ReasonCode, TransportMode, SourceType
from order_orchestration.domain.route import Route
from order_orchestration.eligibility.transport_eligibility import (
    evaluate_transport_eligibility,
)  
import pandas as pd

def build_route_list_lookup(
    routes: Iterable[Route],
) -> dict[tuple[str, str], list[Route]]:
    """
    Builds route lookup allowing multiple modes for same source-destination.
    """

    route_lookup: dict[tuple[str, str], list[Route]] = {}

    for route in routes:
        key = (
            str(route.source_location).strip(),
            str(route.destination_location).strip(),
        )

        route_lookup.setdefault(key, []).append(route)

    return route_lookup


def get_routes_for_candidate(
    candidate: CandidateSource,
    destination_location: str,
    route_lookup: dict[tuple[str, str], list[Route]],
) -> list:
    key = (
        str(candidate.location).strip(),
        str(destination_location).strip(),
    )

    return route_lookup.get(key, [])


def _evaluate_valid_route_options(
    routes: list[Route],
    order_type: OrderType,
    decision_datetime: datetime,
    allowed_transport_modes_config: dict[str, list[str]],
    calendar_rules: dict,
) -> list[tuple[Route, datetime, datetime]]:
    """
    Returns valid route options with expected dispatch and delivery.
    """

    valid_options: list[tuple[Route, datetime, datetime]] = []

    for route in routes:
        transport_result = evaluate_transport_eligibility(
            route=route,
            order_type=order_type,
            decision_datetime=decision_datetime,
            allowed_transport_modes_config=allowed_transport_modes_config,
        )

        if not transport_result.eligible:
            continue

        delivery_result = calculate_route_delivery_result_for_location(
            route=route,
            order_type=order_type,
            decision_datetime=decision_datetime,
            calendar_rules=calendar_rules,
            adjust_final_delivery_to_working_time=True,
        )

        valid_options.append(
            (
                route,
                delivery_result.expected_dispatch,
                delivery_result.expected_delivery,
            )
        )

    return valid_options


def _choose_shortest_sla_route(
    valid_options: list[tuple[Route, datetime, datetime]],
) -> tuple[Optional[Route], Optional[datetime], Optional[datetime]]:
    """
    Chooses route by expected delivery, SLA, cost.
    """

    if not valid_options:
        return None, None, None

    selected_route, expected_dispatch, expected_delivery = sorted(
        valid_options,
        key=lambda item: (
            item[2],
            item[0].standard_sla_days,
            item[0].transport_cost,
        ),
    )[0]

    return selected_route, expected_dispatch, expected_delivery


def select_best_route_by_business_policy(
    candidate: CandidateSource,
    routes: list[Route],
    order_type: OrderType,
    decision_datetime: datetime,
    allowed_transport_modes_config: dict[str, list[str]],
    calendar_rules: dict,
    vepdc_location_code: str,
) -> tuple[Optional[Route], Optional[datetime], Optional[datetime], list[ReasonCode]]:
    """
    Central route policy.

    Rules:

    VOR / ACC:
        Any source:
            Milk Run if available.
            Else compare AIR and SURFACE/PTL by shortest SLA.

    Replenishment / Push:
        RDC source:
            Milk Run if available.
            Else SURFACE/PTL.
        VEPDC source:
            SURFACE/PTL only.

    Note:
        In current logistics data, SURFACE is business equivalent of
        PART_TRUCK_LOAD.
    """

    reason_codes: list[ReasonCode] = []

    source_location = str(candidate.location).strip()
    is_vepdc_source = source_location == str(vepdc_location_code).strip()

    valid_options = _evaluate_valid_route_options(
        routes=routes,
        order_type=order_type,
        decision_datetime=decision_datetime,
        allowed_transport_modes_config=allowed_transport_modes_config,
        calendar_rules=calendar_rules,
    )

    if not valid_options:
        return None, None, None, [ReasonCode.SLA_DATA_NOT_FOUND]

    milk_run_options = [
        option
        for option in valid_options
        if option[0].transport_mode == TransportMode.MILK_RUN
    ]

    air_surface_options = [
        option
        for option in valid_options
        if option[0].transport_mode in [TransportMode.AIR, TransportMode.SURFACE]
    ]

    surface_options = [
        option
        for option in valid_options
        if option[0].transport_mode == TransportMode.SURFACE
    ]

    if order_type in [OrderType.VOR, OrderType.ACC]:
        if milk_run_options:
            selected_route, expected_dispatch, expected_delivery = (
                _choose_shortest_sla_route(milk_run_options)
            )

            return (
                selected_route,
                expected_dispatch,
                expected_delivery,
                [ReasonCode.MILK_RUN_SELECTED],
            )

        selected_route, expected_dispatch, expected_delivery = (
            _choose_shortest_sla_route(air_surface_options)
        )

        if selected_route is None:
            return None, None, None, [ReasonCode.SLA_DATA_NOT_FOUND]

        if selected_route.transport_mode == TransportMode.AIR:
            reason_codes.append(ReasonCode.AIR_SELECTED_FOR_FASTEST_SLA)
        else:
            reason_codes.append(ReasonCode.SURFACE_SELECTED_AS_PART_TRUCK_LOAD)

        return selected_route, expected_dispatch, expected_delivery, reason_codes

    # Replenishment / Push
    # if not is_vepdc_source and milk_run_options:
    #     selected_route, expected_dispatch, expected_delivery = (
    #         _choose_shortest_sla_route(milk_run_options)
    #     )

    #     return (
    #         selected_route,
    #         expected_dispatch,
    #         expected_delivery,
    #         [ReasonCode.MILK_RUN_SELECTED],
    #     )
    # ---------------------------------------------------------
    # Replenishment / Push
    # ---------------------------------------------------------
    # Business rule:
    # If the candidate source is the order's parent source and Milk Run is
    # available, use Milk Run.
    #
    # For non-emergency Replenishment/Push:
    # - Milk Run if available for RDC-to-dealer
    # - Else Surface, which represents Part Truck Load in current logistics
    #
    # VEPDC non-parent Replenishment/Push uses Surface/PTL.
    # But if VEPDC is classified as PARENT_RDC for that dealer and Milk Run exists,
    # Milk Run should be allowed.
    if milk_run_options and candidate.source_type == SourceType.PARENT_RDC:
        selected_route, expected_dispatch, expected_delivery = (
            _choose_shortest_sla_route(milk_run_options)
        )

        return (
            selected_route,
            expected_dispatch,
            expected_delivery,
            [ReasonCode.MILK_RUN_SELECTED],
        )

    if not is_vepdc_source and milk_run_options:
        selected_route, expected_dispatch, expected_delivery = (
            _choose_shortest_sla_route(milk_run_options)
        )

        return (
            selected_route,
            expected_dispatch,
            expected_delivery,
            [ReasonCode.MILK_RUN_SELECTED],
        )

    selected_route, expected_dispatch, expected_delivery = (
        _choose_shortest_sla_route(surface_options)
    )

    if selected_route is None:
        return None, None, None, [ReasonCode.SLA_DATA_NOT_FOUND]

    return (
        selected_route,
        expected_dispatch,
        expected_delivery,
        [ReasonCode.SURFACE_SELECTED_AS_PART_TRUCK_LOAD],
    )



def enrich_candidates_with_route_policy(
    candidates: list[CandidateSource],
    routes: Iterable[Route],
    order_type: OrderType,
    decision_datetime: datetime,
    destination_location: str,
    allowed_transport_modes_config: dict[str, list[str]],
    calendar_rules: dict,
    vepdc_location_code: str,
) -> list:
    """
    Applies common route/mode policy to all candidates.
    """

    route_lookup = build_route_list_lookup(routes)
    enriched_candidates: list[CandidateSource] = []

    for candidate in candidates:
        candidate_routes = get_routes_for_candidate(
            candidate=candidate,
            destination_location=destination_location,
            route_lookup=route_lookup,
        )

        selected_route, expected_dispatch, expected_delivery, route_reason_codes = (
            select_best_route_by_business_policy(
                candidate=candidate,
                routes=candidate_routes,
                order_type=order_type,
                decision_datetime=decision_datetime,
                allowed_transport_modes_config=allowed_transport_modes_config,
                calendar_rules=calendar_rules,
                vepdc_location_code=vepdc_location_code,
            )
        )

        merged_reason_codes = list(candidate.rejection_reason_codes)
        merged_reason_codes.extend(route_reason_codes)

        if selected_route is None:
            enriched_candidates.append(
                replace(
                    candidate,
                    route_available=False,
                    eligible=False,
                    rejection_reason_codes=merged_reason_codes,
                )
            )
            continue

        enriched_candidates.append(
            replace(
                candidate,
                route_available=True,
                selected_transport_mode=selected_route.transport_mode,
                configured_sla_days=selected_route.standard_sla_days,
                transport_cost=selected_route.transport_cost,
                expected_dispatch=expected_dispatch,
                expected_delivery=expected_delivery,
                eligible=candidate.eligible,
                rejection_reason_codes=merged_reason_codes,
            )
        )

    return enriched_candidates


def apply_route_and_sla_defaults(
    candidates: list[CandidateSource],
    decision_datetime: datetime,
    default_sla_days: int = 5,
    default_transport_mode: TransportMode = (
        TransportMode.SURFACE
    ),
    default_transport_cost: Decimal = Decimal(
        "999999999"
    ),
) -> list[CandidateSource]:
    """
    Makes a candidate usable when route or SLA data is missing.

    Missing route:
        route_available = True
        transport mode = configured default
        SLA = configured default
        cost = configured default

    Existing route with missing SLA:
        Retain existing mode
        SLA = configured default

    Candidate eligibility remains dependent on positive
    eligible physical inventory.
    """

    enriched_candidates: list[
        CandidateSource
    ] = []

    invalid_numeric_values = {
        "",
        "NAN",
        "NONE",
        "NULL",
        "<NA>",
        "NAT",
        "NA",
        "N/A",
    }

    for candidate in candidates:
        route_available = bool(
            candidate.route_available
        )

        selected_mode = (
            candidate.selected_transport_mode
        )

        raw_sla = (
            candidate.configured_sla_days
        )

        raw_cost = (
            candidate.transport_cost
        )

        # -----------------------------------------------------
        # Parse SLA
        # -----------------------------------------------------
        parsed_sla_days: int | None = None

        if raw_sla is not None:
            normalized_sla = (
                str(raw_sla)
                .strip()
                .upper()
            )

            if (
                normalized_sla
                not in invalid_numeric_values
            ):
                try:
                    numeric_sla = float(
                        normalized_sla
                    )

                    if (
                        0 <= numeric_sla < 9999
                    ):
                        parsed_sla_days = int(
                            numeric_sla
                        )

                except (
                    TypeError,
                    ValueError,
                    OverflowError,
                ):
                    parsed_sla_days = None

        sla_is_missing = (
            parsed_sla_days is None
        )

        route_is_missing = (
            not route_available
            or selected_mode is None
        )

        route_default_used = (
            route_is_missing
        )

        sla_default_used = (
            route_is_missing
            or sla_is_missing
        )

        final_sla_days: int = (
            int(default_sla_days)
            if sla_default_used
            else (
                parsed_sla_days
                if parsed_sla_days is not None
                else int(default_sla_days)
            )
        )

        # -----------------------------------------------------
        # Resolve transport mode
        # -----------------------------------------------------
        final_transport_mode: TransportMode = (
            selected_mode
            if selected_mode is not None
            and not route_is_missing
            else default_transport_mode
        )

        # -----------------------------------------------------
        # Parse transport cost
        # -----------------------------------------------------
        parsed_transport_cost: Decimal | None = None

        if raw_cost is not None:
            normalized_cost = (
                str(raw_cost)
                .strip()
                .upper()
            )

            if (
                normalized_cost
                not in invalid_numeric_values
            ):
                try:
                    parsed_transport_cost = Decimal(
                        normalized_cost
                    )

                except (
                    TypeError,
                    ValueError,
                    ArithmeticError,
                ):
                    parsed_transport_cost = None

        final_transport_cost: Decimal = (
            default_transport_cost
            if (
                route_is_missing
                or parsed_transport_cost is None
            )
            else parsed_transport_cost
        )

        # -----------------------------------------------------
        # Resolve expected dates
        # -----------------------------------------------------
        expected_dispatch = (
            candidate.expected_dispatch
        )

        if expected_dispatch is None:
            expected_dispatch = (
                decision_datetime
            )

        expected_delivery = (
            expected_dispatch
            + timedelta(
                days=final_sla_days
            )
        )

        # -----------------------------------------------------
        # Inventory eligibility
        # -----------------------------------------------------
        eligible_quantity = (
            candidate.eligible_quantity
        )

        inventory_eligible = (
            eligible_quantity
            > Decimal("0")
        )

        enriched_candidates.append(
            replace(
                candidate,
                route_available=True,
                selected_transport_mode=(
                    final_transport_mode
                ),
                configured_sla_days=(
                    final_sla_days
                ),
                transport_cost=(
                    final_transport_cost
                ),
                expected_dispatch=(
                    expected_dispatch
                ),
                expected_delivery=(
                    expected_delivery
                ),
                eligible=(
                    inventory_eligible
                ),
                route_default_used=(
                    route_default_used
                ),
                sla_default_used=(
                    sla_default_used
                ),
                master_data_default_used=(
                    route_default_used
                    or sla_default_used
                    or bool(
                        getattr(
                            candidate,
                            "rlt_default_used",
                            False,
                        )
                    )
                ),
            )
        )

    return enriched_candidates