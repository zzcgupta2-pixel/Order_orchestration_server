from __future__ import annotations

from decimal import Decimal

import pandas as pd


def build_git_rlt_lookup(
    git_rlt_df: pd.DataFrame | None,
) -> dict[tuple[str, str, str], int]:
    """
    Builds inbound GIT RLT lookup.

    Lookup key:
        destination_location
        material_code
        source_location/vendor

    Expected columns:
    - destination_location or plant
    - material_code
    - source_location or vendor_code
    - inbound_rlt_days or rlt_days
    """

    if git_rlt_df is None or git_rlt_df.empty:
        return {}

    df = git_rlt_df.copy()

    df.columns = (
        df.columns
        .astype(str)
        .str.strip()
        .str.lower()
        .str.replace("\n", " ", regex=False)
        .str.replace(r"\s+", "_", regex=True)
    )

    df = df.rename(
        columns={
            "plant": "destination_location",
            "destination_plant": "destination_location",
            "vendor": "source_location",
            "vendor_code": "source_location",
            "source_vendor": "source_location",
            "material": "material_code",
            "rlt": "inbound_rlt_days",
            "rlt_days": "inbound_rlt_days",
            "git_rlt": "inbound_rlt_days",
        }
    )

    required_columns = [
        "destination_location",
        "material_code",
        "source_location",
        "inbound_rlt_days",
    ]

    missing_columns = [
        column
        for column in required_columns
        if column not in df.columns
    ]

    if missing_columns:
        raise ValueError(
            "GIT RLT dataframe is missing columns: "
            f"{missing_columns}"
        )

    for column in [
        "destination_location",
        "material_code",
        "source_location",
    ]:
        df[column] = (
            df[column]
            .astype(str)
            .str.strip()
            .str.replace(r"\.0$", "", regex=True)
        )

    df["inbound_rlt_days"] = pd.to_numeric(
        df["inbound_rlt_days"],
        errors="coerce",
    )

    df = df.dropna(
        subset=["inbound_rlt_days"]
    )

    df = df[
        df["inbound_rlt_days"] >= 0
    ].copy()

    df = df.drop_duplicates(
        subset=[
            "destination_location",
            "material_code",
            "source_location",
        ],
        keep="last",
    )

    return {
        (
            str(row["destination_location"]).strip(),
            str(row["material_code"]).strip(),
            str(row["source_location"]).strip(),
        ): int(row["inbound_rlt_days"])
        for _, row in df.iterrows()
    }


def resolve_git_inbound_rlt(
    destination_location: str,
    material_code: str,
    source_location: str,
    git_rlt_lookup: dict[
        tuple[str, str, str],
        int,
    ],
) -> int | None:
    key = (
        str(destination_location).strip(),
        str(material_code).strip(),
        str(source_location).strip(),
    )

    return git_rlt_lookup.get(key)
