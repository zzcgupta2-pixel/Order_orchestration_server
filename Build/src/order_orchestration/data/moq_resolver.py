from __future__ import annotations

from decimal import Decimal, InvalidOperation

import pandas as pd


def safe_decimal(
    value,
    default: Decimal = Decimal("0"),
) -> Decimal:
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


def build_moq_lookup(
    moq_df: pd.DataFrame | None,
) -> dict[str, Decimal]:
    """
    Builds material-level MOQ lookup.

    Expected columns:
    - material_code
    - moq_qty
    """

    if moq_df is None or moq_df.empty:
        return {}

    moq_data = moq_df.copy()

    moq_data.columns = (
        moq_data.columns.astype(str)
        .str.strip()
        .str.lower()
        .str.replace(" ", "_", regex=False)
    )

    rename_map = {
        "material": "material_code",
        "material_code": "material_code",
        "sku_code": "material_code",
        "moq": "moq_qty",
        "moq_quantity": "moq_qty",
        "minimum_order_quantity": "moq_qty",
    }

    moq_data = moq_data.rename(columns=rename_map)

    required_columns = [
        "material_code",
        "moq_qty",
    ]

    missing_columns = [
        column
        for column in required_columns
        if column not in moq_data.columns
    ]

    if missing_columns:
        raise ValueError(
            "MOQ dataframe is missing required columns: "
            f"{missing_columns}. Available columns: "
            f"{moq_data.columns.tolist()}"
        )

    moq_data["material_code"] = (
        moq_data["material_code"]
        .astype(str)
        .str.strip()
    )

    moq_data["moq_qty"] = pd.to_numeric(
        moq_data["moq_qty"],
        errors="coerce",
    )

    moq_data = moq_data[
        ~moq_data["material_code"]
        .str.lower()
        .isin(["", "nan", "none"])
    ].copy()

    moq_data = moq_data[
        moq_data["moq_qty"] > 0
    ].copy()

    moq_data = moq_data.drop_duplicates(
        subset=["material_code"],
        keep="last",
    )

    lookup: dict[str, Decimal] = {}

    for _, row in moq_data.iterrows():
        material_code = str(
            row["material_code"]
        ).strip()

        moq_qty = safe_decimal(
            row["moq_qty"],
            Decimal("1"),
        )

        if moq_qty <= Decimal("0"):
            moq_qty = Decimal("1")

        lookup[material_code] = moq_qty

    return lookup


def resolve_moq(
    material_code: str,
    moq_lookup: dict[str, Decimal],
    missing_materials: set[str] | None = None,
    default_moq: Decimal = Decimal("1"),
) -> tuple[Decimal, bool]:
    """
    Returns:
    - MOQ quantity
    - Whether default MOQ was used
    """

    material_key = str(material_code).strip()

    if material_key in moq_lookup:
        moq_qty = moq_lookup[material_key]

        if moq_qty > Decimal("0"):
            return moq_qty, False

    if missing_materials is not None:
        missing_materials.add(material_key)

    return default_moq, True


def floor_to_moq(
    quantity: Decimal,
    moq_qty: Decimal,
) -> Decimal:
    """
    Floors quantity to the nearest valid MOQ multiple.

    Examples:
        quantity=23, MOQ=5 -> 20
        quantity=20, MOQ=5 -> 20
        quantity=4, MOQ=5  -> 0
    """

    if quantity <= Decimal("0"):
        return Decimal("0")

    if moq_qty <= Decimal("0"):
        moq_qty = Decimal("1")

    number_of_blocks = quantity // moq_qty

    return number_of_blocks * moq_qty


def build_missing_moq_report(
    missing_materials: set[str],
    default_moq: Decimal = Decimal("1"),
) -> pd.DataFrame:
    rows = [
        {
            "material_code": material_code,
            "default_moq_used": default_moq,
            "reason": "MOQ_NOT_FOUND_DEFAULT_ONE_USED",
        }
        for material_code in sorted(missing_materials)
    ]

    return pd.DataFrame(
        rows,
        columns=[
            "material_code",
            "default_moq_used",
            "reason",
        ],
    )