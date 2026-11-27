from __future__ import annotations

import pandas as pd


def _normalize_rlt_code(
    value,
) -> str:
    normalized = str(value).strip().upper()

    if normalized.endswith(".0"):
        normalized = normalized[:-2]

    return normalized


def build_rlt_lookup(
    rlt_df: pd.DataFrame | None,
) -> dict:
    """
    Builds RLT lookup keys for:

    1. Exact location-material-supplier resolution:
       ("EXACT", location, material, supplier)

    2. RDC-level fallback:
       ("RDC_LEVEL", location)

    3. Existing workflow's VEPDC material resolution:
       ("VEPDC", "1110", material)
    """

    if rlt_df is None or rlt_df.empty:
        return {}

    required_columns = [
        "location",
        "material_code",
        "supplier_code",
        "rlt_days",
    ]

    missing_columns = [
        column
        for column in required_columns
        if column not in rlt_df.columns
    ]

    if missing_columns:
        raise ValueError(
            "RLT dataframe is missing required columns: "
            f"{missing_columns}. "
            f"Available columns: "
            f"{rlt_df.columns.tolist()}"
        )

    working_df = rlt_df.copy()

    for column in [
        "location",
        "material_code",
        "supplier_code",
    ]:
        working_df[column] = (
            working_df[column]
            .map(_normalize_rlt_code)
        )

    working_df["rlt_days"] = pd.to_numeric(
        working_df["rlt_days"],
        errors="coerce",
    )

    working_df = working_df.dropna(
        subset=["rlt_days"]
    ).copy()

    working_df = working_df[
        working_df["rlt_days"] > 0
    ].copy()

    if "rlt_type" not in working_df.columns:
        working_df["rlt_type"] = (
            "COMPLETE_RLT_MASTER"
        )

    working_df["rlt_type"] = (
        working_df["rlt_type"]
        .astype(str)
        .str.strip()
        .str.upper()
    )

    rlt_lookup: dict = {}

    vepdc_material_values: dict[
        tuple[str, str],
        list[int],
    ] = {}

    for _, row in working_df.iterrows():
        location = _normalize_rlt_code(
            row["location"]
        )

        material_code = _normalize_rlt_code(
            row["material_code"]
        )

        supplier_code = _normalize_rlt_code(
            row["supplier_code"]
        )

        rlt_days = int(
            row["rlt_days"]
        )

        rlt_type = str(
            row["rlt_type"]
        ).strip().upper()

        is_rdc_level = (
            rlt_type == "RDC_LEVEL"
            or (
                material_code == "ALL"
                and supplier_code == "ALL"
            )
        )

        if is_rdc_level:
            rlt_lookup[
                (
                    "RDC_LEVEL",
                    location,
                )
            ] = {
                "rlt_days": rlt_days,
                "rlt_type": "RDC_LEVEL",
                "matched_material_code": "ALL",
                "matched_supplier_code": "ALL",
            }

            continue

        # Exact RLT for GIT and supplier-specific resolution.
        rlt_lookup[
            (
                "EXACT",
                location,
                material_code,
                supplier_code,
            )
        ] = {
            "rlt_days": rlt_days,
            "rlt_type": rlt_type,
            "matched_material_code": (
                material_code
            ),
            "matched_supplier_code": (
                supplier_code
            ),
        }

        # Existing physical VEPDC candidate resolution does not
        # supply a supplier code, so collect candidate values by
        # VEPDC location and material.
        if location == "1110":
            vepdc_key = (
                location,
                material_code,
            )

            vepdc_material_values.setdefault(
                vepdc_key,
                [],
            ).append(
                rlt_days
            )

    # Add one material-level key for VEPDC candidate evaluation.
    for (
        location,
        material_code,
    ), rlt_values in vepdc_material_values.items():
        selected_rlt_days = min(
            rlt_values
        )

        rlt_lookup[
            (
                "VEPDC",
                location,
                material_code,
            )
        ] = {
            "rlt_days": selected_rlt_days,
            "rlt_type": (
                "VEPDC_MATERIAL_LEVEL"
            ),
            "matched_material_code": (
                material_code
            ),
            "matched_supplier_code": (
                "MULTIPLE_OR_UNSPECIFIED"
            ),
        }

    return rlt_lookup

# def build_rlt_lookup(
#     rlt_df: pd.DataFrame,
# ) -> dict:
#     """
#     Builds RLT lookup from final RLT master.

#     Supported rows:
#     - RDC_LEVEL:
#         key = ("RDC", location)

#     - VEPDC_MATERIAL_SUPPLIER:
#         key = ("VEPDC", location, material_code)
#     """

#     lookup = {}

#     if rlt_df.empty:
#         return lookup

#     rlt_data = rlt_df.copy()

#     rlt_data["location"] = rlt_data["location"].astype(str).str.strip()
#     rlt_data["material_code"] = rlt_data["material_code"].astype(str).str.strip()
#     rlt_data["rlt_type"] = rlt_data["rlt_type"].astype(str).str.strip()

#     rlt_data["rlt_days"] = pd.to_numeric(
#         rlt_data["rlt_days"],
#         errors="coerce",
#     ).fillna(9999).astype(int)

#     for _, row in rlt_data.iterrows():
#         location = row["location"]
#         material_code = row["material_code"]
#         rlt_type = row["rlt_type"]
#         rlt_days = int(row["rlt_days"])

#         if rlt_type == "RDC_LEVEL":
#             lookup[("RDC", location)] = rlt_days

#         elif rlt_type == "VEPDC_MATERIAL_SUPPLIER":
#             lookup[("VEPDC", location, material_code)] = rlt_days

#     return lookup

def resolve_rlt_with_fallback(
    location: str,
    material_code: str,
    supplier_code: str,
    rlt_lookup: dict,
) -> dict | None:
    """
    Resolves RLT using this hierarchy:

    1. Exact:
       location + material + supplier

    2. RDC-level fallback:
       location + ALL + ALL

       This fallback is permitted only when the requested
       supplier/source is VEPDC 1110.

    3. None if neither match exists.
    """

    normalized_location = (
        _normalize_rlt_code(location)
    )

    normalized_material = (
        _normalize_rlt_code(material_code)
    )

    normalized_supplier = (
        _normalize_rlt_code(supplier_code)
    )

    exact_key = (
        "EXACT",
        normalized_location,
        normalized_material,
        normalized_supplier,
    )

    exact_result = rlt_lookup.get(
        exact_key
    )

    if exact_result is not None:
        return {
            **exact_result,
            "rlt_fallback_used": False,
            "requested_location": (
                normalized_location
            ),
            "requested_material_code": (
                normalized_material
            ),
            "requested_supplier_code": (
                normalized_supplier
            ),
        }

    # RDC-level fallback applies only when the requested
    # source/supplier is VEPDC 1110.
    if normalized_supplier == "1110":
        rdc_level_key = (
            "RDC_LEVEL",
            normalized_location,
        )

        rdc_level_result = rlt_lookup.get(
            rdc_level_key
        )

        if rdc_level_result is not None:
            return {
                **rdc_level_result,
                "rlt_fallback_used": True,
                "requested_location": (
                    normalized_location
                ),
                "requested_material_code": (
                    normalized_material
                ),
                "requested_supplier_code": (
                    normalized_supplier
                ),
            }

    return None

def resolve_rlt_days_with_fallback(
    location: str,
    material_code: str,
    supplier_code: str,
    rlt_lookup: dict,
    missing_rlt_days: int = 0,
) -> int:
    """
    Resolves exact or RDC-level fallback RLT and returns days only.
    """

    result = resolve_rlt_with_fallback(
        location=location,
        material_code=material_code,
        supplier_code=supplier_code,
        rlt_lookup=rlt_lookup,
    )

    if result is None:
        return missing_rlt_days

    return int(
        result["rlt_days"]
    )

# def resolve_rlt_days(
#     location: str,
#     material_code: str,
#     rlt_lookup: dict,
#     vepdc_location_code: str = "1110",
#     missing_rdc_rlt: int = 9999,
#     missing_vepdc_rlt: int = 9999,
# ) -> int:
#     """
#     Resolves RLT for a candidate.

#     Logic:
#     - If candidate location is VEPDC, use material-specific supplier RLT.
#     - Otherwise, use RDC-level RLT.
#     """

#     location = str(location).strip()
#     material_code = str(material_code).strip()

#     if location == str(vepdc_location_code).strip():
#         return rlt_lookup.get(
#             ("VEPDC", location, material_code),
#             missing_vepdc_rlt,
#         )

#     return rlt_lookup.get(
#         ("RDC", location),
#         missing_rdc_rlt,
#     )

from dataclasses import replace

from order_orchestration.domain.candidate import CandidateSource


def apply_rlt_defaults(
    candidates: list[CandidateSource],
    default_rlt_days: int = 5,
) -> list[CandidateSource]:
    """
    Uses the configured default RLT when candidate RLT is
    missing, invalid, negative, or equal to the 9999 sentinel.
    """

    enriched_candidates: list[
        CandidateSource
    ] = []

    invalid_rlt_values = {
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
        raw_rlt = candidate.rlt_days

        parsed_rlt_days: int | None = None

        if raw_rlt is not None:
            normalized_rlt = (
                str(raw_rlt)
                .strip()
                .upper()
            )

            if (
                normalized_rlt
                not in invalid_rlt_values
            ):
                try:
                    numeric_rlt = float(
                        normalized_rlt
                    )

                    if (
                        0 <= numeric_rlt < 9999
                    ):
                        parsed_rlt_days = int(
                            numeric_rlt
                        )

                except (
                    TypeError,
                    ValueError,
                    OverflowError,
                ):
                    parsed_rlt_days = None

        rlt_default_used = (
            parsed_rlt_days is None
        )

        final_rlt_days: int = (
            int(default_rlt_days)
            if rlt_default_used
            else (
                parsed_rlt_days
                if parsed_rlt_days is not None
                else int(default_rlt_days)
            )
        )

        enriched_candidates.append(
            replace(
                candidate,
                rlt_days=final_rlt_days,
                rlt_default_used=(
                    rlt_default_used
                ),
                # master_data_default_used=(
                #     rlt_default_used
                #     or candidate.route_default_used
                #     or candidate.sla_default_used
                # ),
 
                master_data_default_used=(
                    rlt_default_used
                    or bool(
                        getattr(
                            candidate,
                            "route_default_used",
                            False,
                        )
                    )
                    or bool(
                        getattr(
                            candidate,
                            "sla_default_used",
                            False,
                        )
                    )
                ),
            )
        )

    return enriched_candidates


def enrich_candidates_with_rlt(
    candidates: list[CandidateSource],
    rlt_lookup: dict,
    vepdc_location_code: str,
    missing_rdc_rlt: int = 9999,
    missing_vepdc_rlt: int = 9999,
) -> list:
    """
    Adds RLT days to candidates.

    Logic:
    - RDC candidates use RDC-level RLT.
    - VEPDC candidates use material/supplier-level RLT.
    """

    enriched_candidates: list[CandidateSource] = []

    for candidate in candidates:
        rlt_days = resolve_rlt_days(
            location=candidate.location,
            material_code=candidate.material_code,
            rlt_lookup=rlt_lookup,
            vepdc_location_code=vepdc_location_code,
            missing_rdc_rlt=missing_rdc_rlt,
            missing_vepdc_rlt=missing_vepdc_rlt,
        )

        enriched_candidates.append(
            replace(
                candidate,
                rlt_days=rlt_days,
            )
        )

    return enriched_candidates

def resolve_rlt_days(
    location: str,
    material_code: str,
    rlt_lookup: dict,
    vepdc_location_code: str = "1110",
    missing_rdc_rlt: int = 9999,
    missing_vepdc_rlt: int = 9999,
) -> int:
    """
    Resolves RLT for a physical inventory candidate.

    For VEPDC candidate 1110:
        Uses material-level VEPDC RLT stored under the
        compatibility key:
            ("VEPDC", "1110", material_code)

    For another RDC candidate:
        Uses the configured VEPDC-to-RDC fallback:
            ("RDC_LEVEL", destination_location)

    Returns the configured missing value if no match exists.
    """

    normalized_location = _normalize_rlt_code(
        location
    )

    normalized_material = _normalize_rlt_code(
        material_code
    )

    normalized_vepdc = _normalize_rlt_code(
        vepdc_location_code
    )

    # ---------------------------------------------------------
    # VEPDC candidate
    # ---------------------------------------------------------
    if normalized_location == normalized_vepdc:
        vepdc_result = rlt_lookup.get(
            (
                "VEPDC",
                normalized_location,
                normalized_material,
            )
        )

        if vepdc_result is None:
            return missing_vepdc_rlt

        if isinstance(vepdc_result, dict):
            return int(
                vepdc_result["rlt_days"]
            )

        return int(vepdc_result)

    # ---------------------------------------------------------
    # RDC candidate
    # ---------------------------------------------------------
    rdc_result = rlt_lookup.get(
        (
            "RDC_LEVEL",
            normalized_location,
        )
    )

    if rdc_result is None:
        return missing_rdc_rlt

    if isinstance(rdc_result, dict):
        return int(
            rdc_result["rlt_days"]
        )

    return int(rdc_result)