from __future__ import annotations

from decimal import Decimal, InvalidOperation

import pandas as pd


def _safe_decimal(
    value,
    default: Decimal | None = None,
) -> Decimal | None:
    """
    Safely converts a value to Decimal.
    """

    if value is None:
        return default

    try:
        if pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass

    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, TypeError, ValueError):
        return default


def build_norms_lookup(
    norms_df: pd.DataFrame | None,
) -> dict[tuple[str, str], Decimal]:
    """
    Builds a plant-material norms lookup.

    Expected logical columns:
    - location or plant
    - material_code
    - norms

    Duplicate plant-material rows:
    - Last valid row is retained.
    """

    if norms_df is None or norms_df.empty:
        return {}

    norms_data = norms_df.copy()

    norms_data.columns = (
        norms_data.columns.astype(str)
        .str.strip()
        .str.lower()
        .str.replace("\n", " ", regex=False)
        .str.replace(r"\s+", "_", regex=True)
    )

    rename_map = {
        "plant": "location",
        "plant_code": "location",
        "location_code": "location",
        "material": "material_code",
        "material_number": "material_code",
        "sku_code": "material_code",
        "norm": "norms",
        "norm_qty": "norms",
        "norms_qty": "norms",
    }

    norms_data = norms_data.rename(
        columns=rename_map
    )

    required_columns = [
        "location",
        "material_code",
        "norms",
    ]

    missing_columns = [
        column
        for column in required_columns
        if column not in norms_data.columns
    ]

    if missing_columns:
        raise ValueError(
            "Norms dataframe is missing required columns: "
            f"{missing_columns}. Available columns: "
            f"{norms_data.columns.tolist()}"
        )

    norms_data = norms_data[
        [
            "location",
            "material_code",
            "norms",
        ]
    ].copy()

    norms_data["location"] = (
        norms_data["location"]
        .astype(str)
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
    )

    norms_data["material_code"] = (
        norms_data["material_code"]
        .astype(str)
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
    )

    norms_data["norms"] = pd.to_numeric(
        norms_data["norms"],
        errors="coerce",
    )

    invalid_text_values = [
        "",
        "nan",
        "none",
        "null",
        "<na>",
    ]

    norms_data = norms_data[
        ~norms_data["location"]
        .str.lower()
        .isin(invalid_text_values)
    ].copy()

    norms_data = norms_data[
        ~norms_data["material_code"]
        .str.lower()
        .isin(invalid_text_values)
    ].copy()

    norms_data = norms_data.dropna(
        subset=["norms"]
    )

    norms_data = norms_data[
        norms_data["norms"] >= 0
    ].copy()

    norms_data = norms_data.drop_duplicates(
        subset=[
            "location",
            "material_code",
        ],
        keep="last",
    )

    norms_lookup: dict[
        tuple[str, str],
        Decimal,
    ] = {}

    for _, row in norms_data.iterrows():
        lookup_key = (
            str(row["location"]).strip(),
            str(row["material_code"]).strip(),
        )

        norms_value = _safe_decimal(
            row["norms"]
        )

        if norms_value is not None:
            norms_lookup[lookup_key] = (
                norms_value
            )

    return norms_lookup


def resolve_norms(
    location: str,
    material_code: str,
    norms_lookup: dict[
        tuple[str, str],
        Decimal,
    ],
    missing_combinations: (
        set[tuple[str, str]] | None
    ) = None,
) -> tuple[Decimal | None, bool]:
    """
    Resolves norms for one plant-material.

    Returns:
    - norms value
    - norms_found flag

    Missing norms policy:
    - Return None.
    - Record the missing combination.
    - Normal safety-stock calculation will continue.
    """

    lookup_key = (
        str(location)
        .strip()
        .replace(".0", ""),
        str(material_code)
        .strip()
        .replace(".0", ""),
    )

    if lookup_key in norms_lookup:
        return norms_lookup[lookup_key], True

    if missing_combinations is not None:
        missing_combinations.add(lookup_key)

    return None, False


def build_missing_norms_report(
    missing_combinations: set[
        tuple[str, str]
    ],
) -> pd.DataFrame:
    """
    Creates a unique missing norms report.
    """

    rows = [
        {
            "location": location,
            "material_code": material_code,
            "reason": (
                "PLANT_MATERIAL_NORMS_NOT_FOUND"
            ),
            "fallback_policy": (
                "NORMAL_SAFETY_STOCK_CALCULATION"
            ),
        }
        for location, material_code
        in sorted(missing_combinations)
    ]

    return pd.DataFrame(
        rows,
        columns=[
            "location",
            "material_code",
            "reason",
            "fallback_policy",
        ],
    )


def merge_norms_into_inventory_master(
    inventory_master_df: pd.DataFrame,
    norms_df: pd.DataFrame | None,
) -> pd.DataFrame:
    """
    Adds norms to the inventory master using:

        location + material_code

    Missing norms remain blank. They are not treated as zero.
    """

    inventory_data = (
        inventory_master_df.copy()
    )

    if norms_df is None or norms_df.empty:
        inventory_data["norms"] = pd.NA
        inventory_data["norms_found"] = False

        return inventory_data

    inventory_data["location"] = (
        inventory_data["location"]
        .astype(str)
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
    )

    inventory_data["material_code"] = (
        inventory_data["material_code"]
        .astype(str)
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
    )

    norms_lookup = build_norms_lookup(
        norms_df=norms_df
    )

    norms_records = [
        {
            "location": location,
            "material_code": material_code,
            "norms": norms,
        }
        for (
            location,
            material_code,
        ), norms in norms_lookup.items()
    ]

    normalized_norms_df = pd.DataFrame(
        norms_records,
        columns=[
            "location",
            "material_code",
            "norms",
        ],
    )

    inventory_data = inventory_data.drop(
        columns=[
            "norms",
            "norms_found",
        ],
        errors="ignore",
    )

    inventory_data = inventory_data.merge(
        normalized_norms_df,
        on=[
            "location",
            "material_code",
        ],
        how="left",
        validate="many_to_one",
    )

    inventory_data["norms_found"] = (
        inventory_data["norms"].notna()
    )

    return inventory_data