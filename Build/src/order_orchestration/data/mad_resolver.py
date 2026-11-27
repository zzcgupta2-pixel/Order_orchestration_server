from __future__ import annotations

from decimal import Decimal, InvalidOperation

import pandas as pd


def _safe_decimal(
    value,
    default: Decimal = Decimal("1"),
) -> Decimal:
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


def build_mad_lookup(
    mad_df: pd.DataFrame | None,
) -> dict[tuple[str, str], Decimal]:
    """
    Builds plant-material MAD lookup.

    Expected columns:
    - location or plant
    - material_code
    - mad

    If mad_df is None or empty, an empty lookup is returned.
    The resolver will then use default MAD = 1.
    """

    if mad_df is None or mad_df.empty:
        return {}

    mad_data = mad_df.copy()

    mad_data.columns = (
        mad_data.columns.astype(str)
        .str.strip()
        .str.lower()
        .str.replace(" ", "_", regex=False)
    )

    rename_map = {
        "plant": "location",
        "plant_code": "location",
        "location_code": "location",
        "material": "material_code",
        "sku_code": "material_code",
        "mad": "mad",
        "monthly_average_demand": "mad",
    }

    mad_data = mad_data.rename(columns=rename_map)

    required_columns = [
        "location",
        "material_code",
        "mad",
    ]

    missing_columns = [
        column
        for column in required_columns
        if column not in mad_data.columns
    ]

    if missing_columns:
        raise ValueError(
            "MAD dataframe is missing required columns after normalization: "
            f"{missing_columns}. Available columns: "
            f"{mad_data.columns.tolist()}"
        )

    mad_data["location"] = (
        mad_data["location"]
        .astype(str)
        .str.strip()
    )

    mad_data["material_code"] = (
        mad_data["material_code"]
        .astype(str)
        .str.strip()
    )

    mad_data["mad"] = pd.to_numeric(
        mad_data["mad"],
        errors="coerce",
    )

    mad_data = mad_data[
        ~mad_data["location"].str.lower().isin(
            ["", "nan", "none"]
        )
    ].copy()

    mad_data = mad_data[
        ~mad_data["material_code"].str.lower().isin(
            ["", "nan", "none"]
        )
    ].copy()

    # If duplicate plant-material rows exist, take the latest/last record.
    mad_data = mad_data.drop_duplicates(
        subset=["location", "material_code"],
        keep="last",
    )

    lookup: dict[tuple[str, str], Decimal] = {}

    for _, row in mad_data.iterrows():
        key = (
            str(row["location"]).strip(),
            str(row["material_code"]).strip(),
        )

        mad_value = _safe_decimal(
            row["mad"],
            default=Decimal("1"),
        )

        if mad_value < Decimal("0"):
            mad_value = Decimal("1")

        lookup[key] = mad_value

    return lookup


def resolve_mad(
    location: str,
    material_code: str,
    mad_lookup: dict[tuple[str, str], Decimal],
    missing_combinations: set[tuple[str, str]] | None = None,
    default_mad: Decimal = Decimal("1"),
) -> tuple[Decimal, bool]:
    """
    Resolves MAD for one plant-material combination.

    Returns:
    - MAD value
    - True if default MAD was used

    If the combination is missing, it is added to missing_combinations.
    """

    location_key = str(location).strip()
    material_key = str(material_code).strip()

    lookup_key = (
        location_key,
        material_key,
    )

    if lookup_key in mad_lookup:
        mad_value = mad_lookup[lookup_key]

        if mad_value >= Decimal("0"):
            return mad_value, False

    if missing_combinations is not None:
        missing_combinations.add(lookup_key)

    return default_mad, True


def build_missing_mad_report(
    missing_combinations: set[tuple[str, str]],
    default_mad: Decimal = Decimal("1"),
) -> pd.DataFrame:
    """
    Builds a unique plant-material missing-MAD report.
    """

    rows = [
        {
            "location": location,
            "material_code": material_code,
            "default_mad_used": default_mad,
            "reason": "PLANT_MATERIAL_MAD_NOT_FOUND",
        }
        for location, material_code in sorted(missing_combinations)
    ]

    return pd.DataFrame(
        rows,
        columns=[
            "location",
            "material_code",
            "default_mad_used",
            "reason",
        ],
    )