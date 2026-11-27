from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import numpy as np
import yaml
import logging

logger = logging.getLogger(__name__)

def normalize_mapping_code(
    series: pd.Series,
) -> pd.Series:
    """
    Normalizes dealer and material codes before dataframe mapping.
    """

    return (
        series
        .astype("string")
        .str.strip()
        .str.upper()
        .str.replace(
            r"\.0$",
            "",
            regex=True,
        )
        .str.replace(
            r"\s+",
            "",
            regex=True,
        )
    )

def load_yaml_config(config_path: str | Path) -> dict:
    config_path = Path(config_path)

    with config_path.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file)


# def get_excel_engine(path: str | Path) -> str:
#     path = str(path).lower()

#     if path.endswith(".xlsb"):
#         return "pyxlsb"

#     return "openpyxl"


# def read_excel_from_config(section_config: dict) -> pd.DataFrame:
#     """
#     Reads source file using top-level section config.

#     Supports:
#     - Excel files
#     - CSV files
#     """

#     input_path = section_config["input_path"]
#     sheet_name = section_config.get("sheet_name", 0)
#     header = section_config.get("header", 0)

#     input_path_lower = str(input_path).lower()

#     if input_path_lower.endswith(".csv"):
#         return pd.read_csv(
#             input_path,
#             header=header,
#             encoding=section_config.get("encoding", "utf-8-sig"),
#         )

#     engine = section_config.get("engine", get_excel_engine(input_path))

#     return pd.read_excel(
#         input_path,
#         sheet_name=sheet_name,
#         header=header,
#         engine=engine,
#     )

 

def get_excel_engine(
    path: str | Path,
) -> str:
    """
    Returns the appropriate pandas engine based on
    the source-file extension.
    """

    extension = Path(
        path
    ).suffix.lower()

    if extension == ".xlsb":
        return "pyxlsb"

    if extension == ".xls":
        return "xlrd"

    if extension in {
        ".xlsx",
        ".xlsm",
    }:
        return "openpyxl"

    raise ValueError(
        "Unsupported Excel file extension: "
        f"{extension}. File: {path}"
    )


def read_excel_from_config(
    section_config: dict,
) -> pd.DataFrame:
    """
    Reads a source file using the top-level section config.

    Supported formats:
    - CSV
    - XLSX
    - XLSM
    - XLS
    - XLSB
    """

    if "input_path" not in section_config:
        raise ValueError(
            "Configuration must contain 'input_path'. "
            f"Available keys: "
            f"{list(section_config.keys())}"
        )

    input_path = Path(
        section_config["input_path"]
    )

    if not input_path.exists():
        raise FileNotFoundError(
            f"Input file not found: {input_path}"
        )

    sheet_name = section_config.get(
        "sheet_name",
        0,
    )

    header = section_config.get(
        "header",
        0,
    )

    input_path_lower = str(
        input_path
    ).lower()

    # -----------------------------------------------------
    # CSV input
    # -----------------------------------------------------
    if input_path_lower.endswith(".csv"):
        return pd.read_csv(
            input_path,
            header=header,
            encoding=section_config.get(
                "encoding",
                "utf-8-sig",
            ),

            # Preserve dealer/material/location identifiers.
            dtype=str,

            low_memory=False,
        )

    # -----------------------------------------------------
    # Excel input
    # -----------------------------------------------------
    engine = section_config.get(
        "engine",
        get_excel_engine(
            input_path
        ),
    )

    return pd.read_excel(
        input_path,
        sheet_name=sheet_name,
        header=header,
        engine=engine,

        # Preserve codes such as dealer, material and plant
        # without converting them to floats.
        dtype=str,
    )


def ensure_output_dir(output_dir: str | Path) -> Path:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    return output_path


def make_datetimes_excel_safe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Converts timezone-aware datetime values to timezone-naive values
    before writing to Excel.

    Excel does not support timezone-aware datetimes.
    """

    output_df = df.copy()

    for column in output_df.columns:
        # Handles pandas datetime64 columns with timezone
        # if pd.api.types.is_datetime64tz_dtype(output_df[column]):
        if isinstance(output_df[column].dtype, pd.DatetimeTZDtype):
            output_df[column] = output_df[column].dt.tz_localize(None)

        # Handles object columns containing Python datetime values
        else:
            output_df[column] = output_df[column].apply(
                lambda value: value.replace(tzinfo=None)
                if hasattr(value, "tzinfo") and value.tzinfo is not None
                else value
            )

    return output_df


def save_if_required(
    df: pd.DataFrame,
    output_dir: str | Path,
    output_file: str,
    save_outputs: bool,
) -> None:
    if not save_outputs:
        return

    output_path = ensure_output_dir(output_dir)

    excel_safe_df = make_datetimes_excel_safe(df)

    excel_safe_df.to_excel(
        output_path / output_file,
        index=False,
        engine="openpyxl",
    )


def clean_text_series(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip()


def remove_invalid_key_rows(
    df: pd.DataFrame,
    key_column: str,
) -> pd.DataFrame:
    return df[
        ~df[key_column].astype(str).str.strip().str.lower().isin(
            ["", "nan", "none"]
        )
    ].copy()

def classify_order_category(
    raw_order_type: str,
    ean_upc: float | int | str,
) -> str:
    """
    Classifies order category using SalesDocumentType and EAN/UPC.

    Logic:
    - ZROP -> VOR
    - ZACC -> ACC
    - ZEOR / ZROH -> Push
    - ZMSO / ZFMO with EAN/UPC = 01 -> Push
    - ZMSO / ZFMO with EAN/UPC between 11 and 20 -> Replenishment
    - Else -> No Priority
    """

    order_type = str(raw_order_type).strip().upper()

    try:
        ean_value = int(float(str(ean_upc).strip()))
    except Exception:
        ean_value = None

    if order_type == "ZROP":
        return "VOR"

    if order_type == "ZACC":
        return "ACC"

    if order_type in ["ZEOR", "ZROH"]:
        return "Push"

    if order_type in ["ZMSO", "ZFMO"]:
        if ean_value == 1:
            return "Push"

        if ean_value is not None and 11 <= ean_value <= 20:
            return "Replenishment"

    return "No Priority"

def clean_open_order(
    raw_df: pd.DataFrame,
    section_config: dict,
) -> pd.DataFrame:
    important_cols = [
        "CustomerStatus",
        # "CB",
        # "Date",
        "Date      ",
        "Time    ",
        # "SalesDocumentType",
        "SaTy",
        # "Plant",
        "Plnt",
        # "Plnt",
        # "Material",
        "Material   ",
        # "MaterialDescription",
        "Material Description                    ",
        # "OpenOrderQty.",
        "Open Order Qty.",
        "Customer",
        # "Name1",
        # "Name 1       
        "Name 1                        ",              
        # "DocumentDate",
        "Doc. Date ",
        # "Time.1",
        "Time    .1",
        # "CustomerType",
        "Cust Type", 
        # "TYPE",
        "EAN/UPC",
    ]

    df = raw_df[important_cols].copy()

    df = df.rename(
        columns={
            "CustomerStatus": "credit_block",
            # "CB": "credit_block",
            "Date      ": "today_date",
            "Time    ": "today_time",
            "SaTy": "raw_order_type",
            # "SaTy": "raw_order_type",
            "Plnt": "ordered_plant",
            # "Plnt": "ordered_plant",
            "Material   ": "material_code",
            "Material Description                    ": "material_description",
            "Open Order Qty.": "open_order_qty",
            "Customer": "customer_code",
            "Name 1                        ": "customer_name",
            "Doc. Date ": "order_create_date",
            "Time    .1": "order_create_time",
            "Cust Type": "customer_type",
            # "TYPE": "customer_type",
            "EAN/UPC": "ean_upc",

            # # "CB": "credit_block",
            # "CustomerStatus": "credit_block",
            # "Date": "today_date",
            # "Time": "today_time",
            # "SalesDocumentType": "raw_order_type",
            # # "SaTy": "raw_order_type",
            # "Plant": "ordered_plant",
            # # "Plnt": "ordered_plant",
            # "Material": "material_code",
            # "MaterialDescription": "material_description",
            # "OpenOrderQty.": "open_order_qty",
            # "Customer": "customer_code",
            # "Name1": "customer_name",
            # "DocumentDate": "order_create_date",
            # "Time.1": "order_create_time",
            # "CustomerType": "customer_type",
            # # "TYPE": "customer_type",
            # "EAN/UPC": "ean_upc",
        }
    )

    text_cols = [
        "credit_block",
        "raw_order_type",
        "ordered_plant",
        "material_code",
        "material_description",
        "customer_code",
        "customer_name",
        "customer_type",
    ]

    for col in text_cols:
        df[col] = clean_text_series(df[col])

    df["ean_upc"] = pd.to_numeric(
        df["ean_upc"],
        errors="coerce",
    ).fillna(-1)

    # =========================================================
    # TODAY DATE AND TIME
    # =========================================================
    df["today_date"] = pd.to_datetime(
        df["today_date"],
        format="%d.%m.%Y",
        errors="coerce",
    ).dt.date

    df["today_time"] = pd.to_datetime(
        df["today_time"].astype("string"),
        format="%H:%M:%S",
        errors="coerce",
    ).dt.time

    df["today_datetime"] = pd.to_datetime(
        df["today_date"].astype("string")
        + " "
        + df["today_time"].astype("string"),
        errors="coerce",
    )

    print(
        "Raw order_create_date sample:"
    )

    print(
        df["order_create_date"].head(20)
    )

    print(
        "Raw order_create_time sample:"
    )

    print(
        df["order_create_time"].head(20)
    )

    # =========================================================
    # ORDER CREATION DATETIME
    # =========================================================

    # Preserve raw values for debugging.
    raw_order_create_date = (
        df["order_create_date"]
        .astype("string")
        .str.strip()
    )

    raw_order_create_time = (
        df["order_create_time"]
        .astype("string")
        .str.strip()
    )


    # ---------------------------------------------------------
    # Parse order creation date
    # ---------------------------------------------------------
    # Source values currently look like:
    # 2024-11-14 00:00:00
    # 2022-10-10 00:00:00
    parsed_order_create_date = pd.to_datetime(
        raw_order_create_date,
        format="%Y-%m-%d %H:%M:%S",
        errors="coerce",
    )


    # ---------------------------------------------------------
    # Parse order creation time
    # ---------------------------------------------------------
    # Source values currently look like:
    # 11:52:31
    # 12:38:09
    parsed_order_create_time = pd.to_datetime(
        raw_order_create_time,
        format="%H:%M:%S",
        errors="coerce",
    )


    # ---------------------------------------------------------
    # Combine parsed date and time
    # ---------------------------------------------------------
    normalized_order_date = (
        parsed_order_create_date
        .dt.strftime("%Y-%m-%d")
    )

    normalized_order_time = (
        parsed_order_create_time
        .dt.strftime("%H:%M:%S")
    )

    df["order_create_datetime"] = pd.to_datetime(
        normalized_order_date
        + " "
        + normalized_order_time,
        format="%Y-%m-%d %H:%M:%S",
        errors="coerce",
    )


    # ---------------------------------------------------------
    # Derive final date and time columns
    # ---------------------------------------------------------
    df["order_create_date"] = (
        df["order_create_datetime"]
        .dt.date
    )

    df["order_create_time"] = (
        df["order_create_datetime"]
        .dt.time
    )


    # ---------------------------------------------------------
    # Validate the result
    # ---------------------------------------------------------
    invalid_order_datetime_mask = (
        df["order_create_datetime"].isna()
    )

    print(
        "Valid order_create_datetime rows:",
        int(
            (
                ~invalid_order_datetime_mask
            ).sum()
        ),
    )

    print(
        "Invalid order_create_datetime rows:",
        int(
            invalid_order_datetime_mask.sum()
        ),
    )

    print()
    print(
        df[
            [
                "order_create_datetime",
                "order_create_date",
                "order_create_time",
            ]
        ].head(10)
    )


    if invalid_order_datetime_mask.any():
        print()
        print(
            "Raw values that could not be parsed:"
        )

        invalid_datetime_debug_df = pd.DataFrame(
            {
                "raw_order_create_date": (
                    raw_order_create_date.loc[
                        invalid_order_datetime_mask
                    ]
                ),
                "raw_order_create_time": (
                    raw_order_create_time.loc[
                        invalid_order_datetime_mask
                    ]
                ),
            }
        )

        print(
            invalid_datetime_debug_df.head(20)
        )

    invalid_order_datetime_mask = (
        df["order_create_datetime"].isna()
    )

    invalid_order_datetime_df = (
        df.loc[
            invalid_order_datetime_mask
        ]
        .copy()
    )

    if not invalid_order_datetime_df.empty:
        invalid_order_datetime_df[
            "cleaning_rejection_reason"
        ] = "MISSING_OR_INVALID_ORDER_CREATE_DATETIME"

        print(
            "Open-order rows removed due to invalid "
            "order creation datetime:",
            len(invalid_order_datetime_df),
        )

        print(
            invalid_order_datetime_df[
                [
                    column
                    for column in [
                        "raw_order_type",
                        "material_code",
                        "customer_code",
                        "order_create_date",
                        "order_create_time",
                        "cleaning_rejection_reason",
                    ]
                    if column
                    in invalid_order_datetime_df.columns
                ]
            ].head(20)
        )

    # Remove invalid datetime rows from the cleaned open orders.
    df = (
        df.loc[
            ~invalid_order_datetime_mask
        ]
        .copy()
        .reset_index(drop=True)
    )
    # df["today_date"] = pd.to_datetime(
    #     df["today_date"],
    #     errors="coerce",
    # ).dt.date
    # df["today_date"] = pd.to_datetime(
    #     df["today_date"],
    #     format="%d.%m.%Y",
    #     errors="coerce",
    # ).dt.date

    # # print(df["order_create_date"].head(10))
    # # df["order_create_date"] = pd.to_datetime(
    # #     df["order_create_date"],
    # #     errors="coerce",
    # # ).dt.date
    # df["order_create_date"] = pd.to_datetime(
    #     df["order_create_date"],
    #     format="%d.%m.%Y",
    #     errors="coerce",
    # ).dt.date

    # df["today_time"] = pd.to_datetime(
    #     df["today_time"].astype(str),
    #     errors="coerce",
    # ).dt.time

    
    # print(df["order_create_time"].head(10)) 
    # df["order_create_time"] = pd.to_datetime(
    #     df["order_create_time"].astype(str),
    #     errors="coerce",
    # ).dt.time
    # # df["order_create_time"] = pd.to_timedelta(
    # #     pd.to_numeric(
    # #         df["order_create_time"],
    # #         errors="coerce",
    # #     ),
    # #     unit="D",
    # # )

    # df["today_datetime"] = pd.to_datetime(
    #     df["today_date"].astype(str)
    #     + " "
    #     + df["today_time"].astype(str),
    #     errors="coerce",
    # )

    # print("order_create_date nulls:", df["order_create_date"].isna().sum())
    # print("order_create_time nulls:", df["order_create_time"].isna().sum())

    # print(df["order_create_time"].head(10))

    # df["order_create_datetime"] = pd.to_datetime(
    #     df["order_create_date"].astype(str)
    #     + " "
    #     + df["order_create_time"].astype(str),
    #     errors="coerce",
    # ) 

    df["open_order_qty"] = pd.to_numeric(
        df["open_order_qty"],
        errors="coerce",
    ).fillna(0)

    df = remove_invalid_key_rows(df, "material_code")

    df = df[df["open_order_qty"] > 0].copy()

    df["order_age_days"] = (
        df["today_datetime"] - df["order_create_datetime"]
    ).dt.days

    priority_rank_mapping = section_config.get(
        "priority_rank_mapping",
        {
            "VOR": 1,
            "ACC": 2,
            "Replenishment": 3,
            "Push": 4,
        },
    )

    df["raw_order_type_upper"] = df["raw_order_type"].str.upper()

    df["order_category"] = df.apply(
        lambda row: classify_order_category(
            raw_order_type=row["raw_order_type_upper"],
            ean_upc=row["ean_upc"],
        ),
        axis=1,
    )

    df = df[df["order_category"] != "No Priority"].copy()

    df["priority_rank"] = df["order_category"].map(priority_rank_mapping)

    # df["is_credit_blocked"] = np.where(
    #     df["credit_block"].str.upper().isin(["CB"]),
    #     1,
    #     0,
    # )
    df["is_credit_blocked"] = df["credit_block"]

    df = df.sort_values(
        by="order_create_datetime",
        ascending=True,
    )

    print(df["order_create_datetime"].head(10))


    final_cols = [
        "is_credit_blocked",
        "order_category",
        "priority_rank",
        "raw_order_type",
        "ean_upc",
        "ordered_plant",
        "material_code",
        "material_description",
        "customer_code",
        "customer_name",
        "order_create_datetime",
        "open_order_qty",
    ]

    return df[final_cols].copy()


def clean_vepdc_inventory(
    raw_df: pd.DataFrame,
    section_config: dict,
) -> pd.DataFrame:
    important_cols = [
        "Plant",
        "Material",
        "Stor. Loc.",
        "Val. stock",
    ]

    df = raw_df[important_cols].copy()

    df = df.rename(
        columns={
            "Plant": "plant",
            "Material": "material_code",
            "Stor. Loc.": "storage_location",
            "Val. stock": "saleable_inventory_qty",
        }
    )

    for col in ["plant", "material_code", "storage_location"]:
        df[col] = clean_text_series(df[col])

    df["saleable_inventory_qty"] = pd.to_numeric(
        df["saleable_inventory_qty"],
        errors="coerce",
    ).fillna(0)

    saleable_locations = [
        str(value).upper()
        for value in section_config.get("saleable_storage_locations", [])
    ]

    df = df[
        df["storage_location"].str.upper().isin(saleable_locations)
    ].copy()

    df = remove_invalid_key_rows(df, "material_code")

    df = df[df["saleable_inventory_qty"] > 0].copy()

    return df


def clean_rdc_inventory(
    raw_df: pd.DataFrame,
    section_config: dict,
) -> pd.DataFrame:
    important_cols = [
        "Plant",
        "Material",
        "Stor. Loc.",
        "Val. stock",
    ]

    df = raw_df[important_cols].copy()

    df = df.rename(
        columns={
            "Plant": "plant",
            "Material": "material_code",
            "Stor. Loc.": "storage_location",
            "Val. stock": "saleable_inventory_qty",
        }
    )

    for col in ["plant", "material_code", "storage_location"]:
        df[col] = clean_text_series(df[col])

    df["saleable_inventory_qty"] = pd.to_numeric(
        df["saleable_inventory_qty"],
        errors="coerce",
    ).fillna(0)

    suffixes = [
        str(value)
        for value in section_config.get("allowed_storage_suffixes", [])
    ]

    df = df[
        df["storage_location"].str[-2:].isin(suffixes)
    ].copy()

    df = remove_invalid_key_rows(df, "material_code")

    df = df[df["saleable_inventory_qty"] > 0].copy()

    return df


def clean_ageing_inventory(
    raw_df: pd.DataFrame,
    section_config: dict,
) -> pd.DataFrame:
    # df = raw_df.copy()

    # df.columns = df.iloc[0]
    # df = df.iloc[1:].copy()
    # df = df.reset_index(drop=True)

    # df.columns = (
    #     df.columns.astype(str)
    #     .str.strip()
    #     .str.replace("\n", " ", regex=False)
    #     .str.replace("  ", " ", regex=False)
    # )

    # # print(df.columns.tolist())

    # # df[">1 Qty"] = (
    # #     df[["> 1", "> 2", "> 3"]]
    # #     .apply(pd.to_numeric, errors="coerce")
    # #     .fillna(0)
    # #     .sum(axis=1)
    # # )

    # important_cols = [
    #     "Plant",
    #     "Material Code",
    #     "Plant Stock",
    #     ">1 Qty"
    # ]

    # available_cols = [
    #     col for col in important_cols
    #     if col in df.columns
    # ]

    # df = df[available_cols].copy()

    # df = df.rename(
    #     columns={
    #         "Plant": "plant",
    #         "Material Code": "material_code",
    #         "Plant Stock": "ageing_stock_qty",
    #         ">1 Qty": "ageing_stock_gt_1yr",
    #     }
    # )

    # df["material_code"] = clean_text_series(df["material_code"])

    # for col in ["plant", "ageing_stock_qty", "ageing_stock_gt_1yr"]:
    #     if col in df.columns:
    #         df[col] = pd.to_numeric(
    #             df[col],
    #             errors="coerce",
    #         ).fillna(0)

    # df = remove_invalid_key_rows(df, "material_code")

    # df = df[
    #     (df["ageing_stock_qty"] > 0)
    #     | (df["ageing_stock_gt_1yr"] > 0)
    # ].copy()

    # df_agg = (
    #     df.groupby(
    #         ["plant", "material_code"],
    #         as_index=False,
    #     )
    #     .agg(
    #         {
    #             "ageing_stock_qty": "sum",
    #             "ageing_stock_gt_1yr": "sum",
    #         }
    #     )
    # )

    # df_agg["is_ageing_stock_available"] = np.where(
    #     df_agg["ageing_stock_gt_1yr"] > 0,
    #     1,
    #     0,
    # )

    df_agg = pd.read_excel("/home/VECVNET/zzasom/jupyter/01_Developement_work_QA/Chakshu_G/order_orchestration/order_orchestration_mannual/Build/data/cleaned/cleaned_ageing_plant_material_level.xlsx",
    engine="openpyxl")

    return df_agg


def make_unique_columns(columns: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    new_columns: list[str] = []

    for col in columns:
        col = str(col).strip()

        if col not in seen:
            seen[col] = 0
            new_columns.append(col)
        else:
            seen[col] += 1
            new_columns.append(f"{col}_{seen[col]}")

    return new_columns


def clean_logistics(
    raw_df: pd.DataFrame,
    section_config: dict,
) -> pd.DataFrame:
    df = raw_df.copy()

    header_row_0 = df.iloc[0].copy()
    header_row_1 = df.iloc[1].copy()

    header_row_0_ffill = header_row_0.ffill()

    base_cols = [
        "Dealer",
        "Dealer Name",
        "Category",
        "Dealer City",
        "Pin Code",
        "Zone",
        "Source Loc",
        "Parent Plant",
    ]

    new_cols = []

    for i in range(len(df.columns)):
        top_header = str(header_row_0_ffill.iloc[i]).strip()
        second_header = str(header_row_1.iloc[i]).strip()

        if i < len(base_cols):
            new_cols.append(base_cols[i])
        elif top_header and second_header and second_header.lower() != "nan":
            new_cols.append(f"{top_header}_{second_header}")
        elif top_header and top_header.lower() != "nan":
            new_cols.append(top_header)
        else:
            new_cols.append(str(df.columns[i]))

    df.columns = make_unique_columns(new_cols)

    df = df.iloc[2:].copy()
    df = df.reset_index(drop=True)

    df.columns = (
        df.columns.astype(str)
        .str.strip()
        .str.replace("\n", " ", regex=False)
        .str.replace("  ", " ", regex=False)
    )

    rename_map = {
        "Dealer": "dealer_code",
        "Dealer Name": "dealer_name",
        "Category": "dealer_category",
        "Dealer City": "dealer_city",
        "Pin Code": "dealer_pin_code",
        "Zone": "zone",
        "Source Loc": "source_location",
        "Parent Plant": "parent_plant",
        "Pin Code_1": "parent_pin_code",
        "State": "dealer_state",
    }

    df = df.rename(columns=rename_map)

    base_text_cols = [
        "dealer_code",
        "dealer_name",
        "dealer_category",
        "dealer_city",
        "dealer_pin_code",
        "zone",
        "source_location",
        "parent_plant",
        "parent_pin_code",
        "dealer_state",
    ]

    for col in base_text_cols:
        if col in df.columns:
            df[col] = clean_text_series(df[col])

    df = remove_invalid_key_rows(df, "dealer_code")

    rename_col = {
        "TAT From Parent Plant - VEPDC & 9 RDC_Surface": "milk_run_surface",
        # "Surface": "open_truck_from_vepdc_surface",
        # "AIR": "vepdc_air",
        # "Surface_1": "vepdc_surface",
        # "AIR Rate": "vepdc_air_rate",
        # "Surface Rate": "vepdc_surface_rate",

        "TAT From VEPDC to Pan India_Surface": "open_truck_from_vepdc_surface",
        "VEPDC_AIR": "vepdc_air",
        "VEPDC_Surface": "vepdc_surface",
        "VEPDC_AIR Rate": "vepdc_air_rate",
        "VEPDC_Surface Rate": "vepdc_surface_rate",

        # # fallback mappings if file format changes later
        # "Surface": "open_truck_from_vepdc_surface",
        # "AIR": "vepdc_air",
        # "Surface_1": "vepdc_surface",
        # "AIR Rate": "vepdc_air_rate",
        # "Surface Rate": "vepdc_surface_rate",
        "Bang RDC_AIR": "bangalore_air",
        "Bang RDC_Surface": "bangalore_surface",
        "Bang RDC_AIR Rate": "bangalore_air_rate",
        "Bang RDC_Surface Rate": "bangalore_surface_rate",
        "Jhajjer RDC_AIR": "jhajjer_air",
        "Jhajjer RDC_Surface": "jhajjer_surface",
        "Jhajjer RDC_AIR Rate": "jhajjer_air_rate",
        "Jhajjer RDC_Surface Rate": "jhajjer_surface_rate",
        "Kol RDC_AIR": "kolkata_air",
        "Kol RDC_Surface": "kolkata_surface",
        "Kol RDC_AIR Rate": "kolkata_air_rate",
        "Kol RDC_Surface Rate": "kolkata_surface_rate",
        "Ludhiana RDC_AIR": "ludhiana_air",
        "Ludhiana RDC_Surface": "ludhiana_surface",
        "Ludhiana RDC_Air Rate": "ludhiana_air_rate",
        "Ludhiana RDC_Surface Rate": "ludhiana_surface_rate",
        "Lucknow RDC_AIR": "lucknow_air",
        "Lucknow RDC_Surface": "lucknow_surface",
        "Lucknow RDC_Air Rate": "lucknow_air_rate",
        "Lucknow RDC_Surface Rate": "lucknow_surface_rate",
        "Hyd RDC_AIR": "hyderabad_air",
        "Hyd RDC_Surface": "hyderabad_surface",
        "Hyd RDC_Air Rate": "hyderabad_air_rate",
        "Hyd RDC_Surface Rate": "hyderabad_surface_rate",
        "Coimb RDC_AIR": "coimbatore_air",
        "Coimb RDC_Surface": "coimbatore_surface",
        "Coimb RDC_Air Rate": "coimbatore_air_rate",
        "Coimb RDC_Surface Rate": "coimbatore_surface_rate",
        "Raipur RDC_AIR": "raipur_air",
        "Raipur RDC_Surface": "raipur_surface",
        "Raipur RDC_Air Rate": "raipur_air_rate",
        "Raipur RDC_Surface Rate": "raipur_surface_rate",
        "Guwahati RDC_AIR": "guwahati_air",
        "Guwahati RDC_Surface": "guwahati_surface",
        "Guwahati RDC_Air Rate": "guwahati_air_rate",
        "Guwahati RDC_Surface Rate": "guwahati_surface_rate",
    }

    df = df.rename(columns=rename_col)

    numeric_candidates = [
        col for col in df.columns
        if (
            col.endswith("_air")
            or col.endswith("_surface")
            or col.endswith("_air_rate")
            or col.endswith("_surface_rate")
            or col in ["milk_run_surface", "open_truck_from_vepdc_surface"]
        )
    ]

    for col in numeric_candidates:
        df[col] = pd.to_numeric(
            df[col],
            errors="coerce",
        ).fillna(0)

    return df

def enrich_open_order_with_actual_parent_plant(
    open_order_df: pd.DataFrame,
    logistics_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Adds actual parent RDC to cleaned open order using logistics master.

    Business rule:
    - ordered_plant = Plant from open order file
    - plant = actual parent RDC from logistics parent_plant
    - Join key:
        open_order.customer_code = logistics.dealer_code

    If logistics parent plant is missing, fallback to ordered_plant.
    """

    enriched_df = open_order_df.copy()
    logistics_parent_df = logistics_df.copy()

    required_open_order_cols = [
        "customer_code",
        "ordered_plant",
    ]

    required_logistics_cols = [
        "dealer_code",
        "parent_plant",
    ]

    missing_open_order_cols = [
        column
        for column in required_open_order_cols
        if column not in enriched_df.columns
    ]

    missing_logistics_cols = [
        column
        for column in required_logistics_cols
        if column not in logistics_parent_df.columns
    ]

    if missing_open_order_cols:
        raise ValueError(
            f"Open order dataframe missing columns: {missing_open_order_cols}"
        )

    if missing_logistics_cols:
        raise ValueError(
            f"Logistics dataframe missing columns: {missing_logistics_cols}"
        )

    enriched_df["customer_code"] = (
        enriched_df["customer_code"].astype(str).str.strip()
    )

    enriched_df["ordered_plant"] = (
        enriched_df["ordered_plant"].astype(str).str.strip()
    )

    logistics_parent_df["dealer_code"] = (
        logistics_parent_df["dealer_code"].astype(str).str.strip()
    )

    logistics_parent_df["parent_plant"] = (
        logistics_parent_df["parent_plant"].astype(str).str.strip()
    )

    logistics_parent_df = logistics_parent_df[
        [
            "dealer_code",
            "parent_plant",
        ]
    ].drop_duplicates(
        subset=["dealer_code"],
        keep="first",
    )

    enriched_df = enriched_df.merge(
        logistics_parent_df,
        left_on="customer_code",
        right_on="dealer_code",
        how="left",
    )

    enriched_df["plant"] = enriched_df["parent_plant"]

    enriched_df["plant"] = enriched_df["plant"].replace(
        {
            "": pd.NA,
            "nan": pd.NA,
            "None": pd.NA,
        } # type: ignore
    )

    enriched_df["plant"] = enriched_df["plant"].fillna(
        enriched_df["ordered_plant"]
    )

    enriched_df = enriched_df.drop(
        columns=[
            "dealer_code",
            "parent_plant",
        ],
        errors="ignore",
    )

    final_cols = [
        "is_credit_blocked",
        "order_category",
        "priority_rank",
        "raw_order_type",
        "ean_upc",
        "ordered_plant",
        "plant",
        "material_code",
        "material_description",
        "customer_code",
        "customer_name",
        "order_create_datetime",
        "open_order_qty",
    ]

    available_final_cols = [
        column
        for column in final_cols
        if column in enriched_df.columns
    ]

    return enriched_df[available_final_cols].copy()

def clean_allowable_max_qty(
    raw_df: pd.DataFrame,
    section_config: dict,
) -> pd.DataFrame:
    df = raw_df.copy()
    df.columns = df.columns.astype(str).str.strip()

    important_cols = [
        "Material",
        "Dlv.Qty",
    ]

    df = df[important_cols].copy()

    df = df.rename(
        columns={
            "Material": "material_code",
            "Dlv.Qty": "max_delivery_qty",
        }
    )

    df["material_code"] = clean_text_series(df["material_code"])

    df["max_delivery_qty"] = pd.to_numeric(
        df["max_delivery_qty"],
        errors="coerce",
    ).fillna(0)

    df = remove_invalid_key_rows(df, "material_code")

    df = df[df["max_delivery_qty"] > 0].copy()

    df = df.drop_duplicates(
        subset=["material_code"],
        keep="first",
    )

    return df[
        [
            "material_code",
            "max_delivery_qty",
        ]
    ].copy()

def clean_moq_master(
    raw_df: pd.DataFrame,
    section_config: dict,
) -> pd.DataFrame:
    """
    Cleans the material-level MOQ master.

    Final output columns:
    - material_code
    - moq_qty

    Supported duplicate rules:
    - MAX_MOQ
    - MIN_MOQ
    - FIRST
    - LAST
    """

    df = raw_df.copy()

    # Standardize source column names
    df.columns = (
        df.columns.astype(str)
        .str.strip()
        .str.replace("\n", " ", regex=False)
        .str.replace(r"\s+", " ", regex=True)
    )

    configured_mapping = section_config.get(
        "column_mapping",
        {},
    )

    # Normalize mapping keys to match cleaned source headers
    column_mapping = {
        str(source_column)
        .strip()
        .replace("\n", " "): target_column
        for source_column, target_column
        in configured_mapping.items()
    }

    df = df.rename(columns=column_mapping)

    required_columns = [
        "material_code",
        "moq_qty",
    ]

    missing_columns = [
        column
        for column in required_columns
        if column not in df.columns
    ]

    if missing_columns:
        raise ValueError(
            "MOQ file is missing required columns after mapping: "
            f"{missing_columns}. "
            f"Available columns: {df.columns.tolist()}"
        )

    # Keep only required fields
    df = df[
        [
            "material_code",
            "moq_qty",
        ]
    ].copy()

    # Standardize material code
    df["material_code"] = (
        df["material_code"]
        .astype(str)
        .str.strip()
    )

    # Convert MOQ to numeric
    df["moq_qty"] = pd.to_numeric(
        df["moq_qty"],
        errors="coerce",
    ).fillna(0)

    # Remove invalid material codes
    df = df[
        ~df["material_code"]
        .str.lower()
        .isin(
            [
                "",
                "nan",
                "none",
                "null",
            ]
        )
    ].copy()

    # Keep only positive MOQ values
    df = df[
        df["moq_qty"] > 0
    ].copy()

    duplicate_rule = str(
        section_config.get(
            "duplicate_rule",
            "MAX_MOQ",
        )
    ).strip().upper()

    if duplicate_rule == "MAX_MOQ":
        df = (
            df.groupby(
                "material_code",
                as_index=False,
            )
            .agg(
                moq_qty=("moq_qty", "max")
            )
        )

    elif duplicate_rule == "MIN_MOQ":
        df = (
            df.groupby(
                "material_code",
                as_index=False,
            )
            .agg(
                moq_qty=("moq_qty", "min")
            )
        )

    elif duplicate_rule == "FIRST":
        df = df.drop_duplicates(
            subset=["material_code"],
            keep="first",
        )

    elif duplicate_rule == "LAST":
        df = df.drop_duplicates(
            subset=["material_code"],
            keep="last",
        )

    else:
        raise ValueError(
            "Unsupported MOQ duplicate rule: "
            f"{duplicate_rule}. "
            "Supported values are MAX_MOQ, MIN_MOQ, FIRST, LAST."
        )

    # Keep whole numbers as integers when possible
    if (
        not df.empty
        and (df["moq_qty"] % 1 == 0).all()
    ):
        df["moq_qty"] = df["moq_qty"].astype(int)

    df = df.sort_values(
        by="material_code",
        ascending=True,
    ).reset_index(drop=True)

    return df[
        [
            "material_code",
            "moq_qty",
        ]
    ].copy()

def clean_zfmo_dealer_material_master(
    raw_df: pd.DataFrame,
    section_config: dict,
) -> pd.DataFrame:
    """
    Cleans the ZFMO dealer-material mapping master.

    Business meaning:
        Every valid dealer-material combination in this master
        identifies an order that must be classified as ZFMO.

    Mapping key:
        dealer_code + material_code

    Final output:
        dealer_code
        material_code
        mapped_raw_order_type
        zfmo_mapping_source

    The cleaner:
    - Standardizes source column names.
    - Applies configured column mapping.
    - Cleans dealer and material codes.
    - Removes blank and invalid values.
    - Keeps only valid dealer codes starting with 1S.
    - Removes export dealers starting with 1XS.
    - Removes duplicate dealer-material combinations.
    """

    df = raw_df.copy()

    input_row_count = len(df)

    # ---------------------------------------------------------
    # 1. Standardize source column names
    # ---------------------------------------------------------
    df.columns = (
        df.columns
        .astype(str)
        .str.strip()
        .str.lower()
        .str.replace("\n", " ", regex=False)
        .str.replace(".", "", regex=False)
        .str.replace("/", "_", regex=False)
        .str.replace("-", "_", regex=False)
        .str.replace(r"\s+", "_", regex=True)
        .str.replace(r"_+", "_", regex=True)
        .str.strip("_")
    )

    # ---------------------------------------------------------
    # 2. Apply configured column mapping
    # ---------------------------------------------------------
    default_column_mapping = {
        "material": "material_code",
        "material_code": "material_code",
        "material_number": "material_code",
        "part_number": "material_code",
        "part_no": "material_code",

        "dealer": "dealer_code",
        "dealer_code": "dealer_code",
        "customer": "dealer_code",
        "customer_code": "dealer_code",
        "sold_to_party": "dealer_code",
    }

    configured_column_mapping = section_config.get(
        "column_mapping",
        {},
    )

    normalized_configured_mapping = {
        str(source_column)
        .strip()
        .lower()
        .replace("\n", " ")
        .replace(".", "")
        .replace("/", "_")
        .replace("-", "_")
        .replace(" ", "_"): target_column
        for source_column, target_column
        in configured_column_mapping.items()
    }

    column_mapping = {
        **default_column_mapping,
        **normalized_configured_mapping,
    }

    df = df.rename(
        columns=column_mapping
    )

    # ---------------------------------------------------------
    # 3. Validate required columns
    # ---------------------------------------------------------
    required_columns = [
        "dealer_code",
        "material_code",
    ]

    missing_columns = [
        column
        for column in required_columns
        if column not in df.columns
    ]

    if missing_columns:
        raise ValueError(
            "ZFMO dealer-material master is missing required "
            f"columns after mapping: {missing_columns}. "
            f"Available columns: {df.columns.tolist()}"
        )

    # Retain only fields required for the mapping.
    df = df[
        required_columns
    ].copy()

    # ---------------------------------------------------------
    # 4. Preserve missing-value status before string conversion
    # ---------------------------------------------------------
    missing_dealer_mask = (
        df["dealer_code"].isna()
    )

    missing_material_mask = (
        df["material_code"].isna()
    )

    # ---------------------------------------------------------
    # 5. Clean dealer code
    # ---------------------------------------------------------
    df["dealer_code"] = (
        df["dealer_code"]
        .astype(str)
        .str.strip()
        .str.upper()
        .str.replace(r"\.0$", "", regex=True)
        .str.replace(r"\s+", "", regex=True)
    )

    # ---------------------------------------------------------
    # 6. Clean material code
    # ---------------------------------------------------------
    df["material_code"] = (
        df["material_code"]
        .astype(str)
        .str.strip()
        .str.upper()
        .str.replace(r"\.0$", "", regex=True)
        .str.replace(r"\s+", "", regex=True)
    )

    # ---------------------------------------------------------
    # 7. Identify invalid identifiers
    # ---------------------------------------------------------
    invalid_text_values = {
        "",
        "NAN",
        "NONE",
        "NULL",
        "<NA>",
        "NAT",
        "NA",
        "N/A",
    }

    invalid_dealer_mask = (
        missing_dealer_mask
        | df["dealer_code"].isin(
            invalid_text_values
        )
    )

    invalid_material_mask = (
        missing_material_mask
        | df["material_code"].isin(
            invalid_text_values
        )
    )

    # ---------------------------------------------------------
    # 8. Apply dealer eligibility rules
    # ---------------------------------------------------------
    export_dealer_mask = (
        df["dealer_code"]
        .str.startswith(
            "1XS",
            na=False,
        )
    )

    non_auto_dealer_mask = (
        df["dealer_code"]
        .str.startswith(
            "1E",
            na=False,
        )
    )

    numeric_dealer_mask = (
        df["dealer_code"]
        .str.fullmatch(
            r"\d+",
            na=False,
        )
    )

    valid_dealer_prefix_mask = (
        df["dealer_code"]
        .str.startswith(
            "1S",
            na=False,
        )
    )

    valid_row_mask = (
        ~invalid_dealer_mask
        & ~invalid_material_mask
        & ~export_dealer_mask
        & ~non_auto_dealer_mask
        & ~numeric_dealer_mask
        & valid_dealer_prefix_mask
    )

    invalid_rows_df = df[
        ~valid_row_mask
    ].copy()

    # ---------------------------------------------------------
    # 9. Add removal reasons for audit
    # ---------------------------------------------------------
    if not invalid_rows_df.empty:
        invalid_rows_df["reason"] = (
            "INVALID_ZFMO_MAPPING_ROW"
        )

        invalid_rows_df.loc[
            invalid_dealer_mask.loc[
                invalid_rows_df.index
            ],
            "reason",
        ] = "MISSING_OR_INVALID_DEALER_CODE"

        invalid_rows_df.loc[
            invalid_material_mask.loc[
                invalid_rows_df.index
            ],
            "reason",
        ] = "MISSING_OR_INVALID_MATERIAL_CODE"

        invalid_rows_df.loc[
            export_dealer_mask.loc[
                invalid_rows_df.index
            ],
            "reason",
        ] = "EXPORT_DEALER_EXCLUDED"

        invalid_rows_df.loc[
            non_auto_dealer_mask.loc[
                invalid_rows_df.index
            ],
            "reason",
        ] = "NON_AUTO_DEALER_EXCLUDED"

        invalid_rows_df.loc[
            numeric_dealer_mask.loc[
                invalid_rows_df.index
            ],
            "reason",
        ] = "NUMERIC_DEALER_EXCLUDED"

        invalid_prefix_mask = (
            ~valid_dealer_prefix_mask
            & ~invalid_dealer_mask
            & ~export_dealer_mask
            & ~non_auto_dealer_mask
            & ~numeric_dealer_mask
        )

        invalid_rows_df.loc[
            invalid_prefix_mask.loc[
                invalid_rows_df.index
            ],
            "reason",
        ] = "INVALID_DEALER_PREFIX"

    df = df[
        valid_row_mask
    ].copy()

    invalid_row_count = (
        input_row_count - len(df)
    )

    # ---------------------------------------------------------
    # 10. Remove duplicate dealer-material combinations
    # ---------------------------------------------------------
    duplicate_mask = df.duplicated(
        subset=[
            "dealer_code",
            "material_code",
        ],
        keep=False,
    )

    duplicate_rows_df = (
        df.loc[
            duplicate_mask,
            [
                "dealer_code",
                "material_code",
            ],
        ]
        .sort_values(
            by=[
                "dealer_code",
                "material_code",
            ]
        )
        .copy()
    )

    duplicate_count = int(
        df.duplicated(
            subset=[
                "dealer_code",
                "material_code",
            ],
            keep="first",
        ).sum()
    )

    df = df.drop_duplicates(
        subset=[
            "dealer_code",
            "material_code",
        ],
        keep="first",
    ).copy()

    # ---------------------------------------------------------
    # 12. Set final column order
    # ---------------------------------------------------------
    final_columns = [
        "dealer_code",
        "material_code"
    ]

    df = (
        df[
            final_columns
        ]
        .sort_values(
            by=[
                "dealer_code",
                "material_code",
            ],
            ascending=[
                True,
                True,
            ],
        )
        .reset_index(drop=True)
    )

    # ---------------------------------------------------------
    # 13. Attach audit reports
    # ---------------------------------------------------------
    df.attrs[
        "invalid_zfmo_mapping_rows"
    ] = invalid_rows_df.reset_index(
        drop=True
    )

    df.attrs[
        "duplicate_zfmo_mapping_rows"
    ] = duplicate_rows_df.reset_index(
        drop=True
    )

    # ---------------------------------------------------------
    # 14. Print cleaning summary
    # ---------------------------------------------------------
    print(
        "ZFMO mapping input rows:",
        input_row_count,
    )

    print(
        "ZFMO mapping invalid rows removed:",
        invalid_row_count,
    )

    print(
        "ZFMO mapping duplicate rows removed:",
        duplicate_count,
    )

    print(
        "ZFMO mapping unique dealer-material combinations:",
        len(df),
    )

    return df

def clean_norms_master(
    raw_df: pd.DataFrame,
    section_config: dict,
) -> pd.DataFrame:
    """
    Cleans the plant-material norms master.

    Final output:
    - location
    - material_code
    - norms

    Business use:
    Plant-material combinations where norms < 3 will not have
    safety stock calculated or applied.
    """

    df = raw_df.copy()

    # ---------------------------------------------------------
    # 1. Standardize source column names
    # ---------------------------------------------------------
    df.columns = (
        df.columns
        .astype(str)
        .str.strip()
        .str.replace("\n", " ", regex=False)
        .str.replace(r"\s+", " ", regex=True)
    )

    # ---------------------------------------------------------
    # 2. Apply configured column mapping
    # ---------------------------------------------------------
    configured_mapping = section_config.get(
        "column_mapping",
        {},
    )

    normalized_mapping = {
        str(source_column)
        .strip()
        .replace("\n", " "): target_column
        for source_column, target_column
        in configured_mapping.items()
    }

    df = df.rename(
        columns=normalized_mapping
    )

    # ---------------------------------------------------------
    # 3. Validate required fields
    # ---------------------------------------------------------
    required_columns = [
        "location",
        "material_code",
        "norms",
    ]

    missing_columns = [
        column
        for column in required_columns
        if column not in df.columns
    ]

    if missing_columns:
        raise ValueError(
            "Norms file is missing required columns "
            f"after column mapping: {missing_columns}. "
            f"Available columns: {df.columns.tolist()}"
        )

    # ---------------------------------------------------------
    # 4. Keep only required columns
    # ---------------------------------------------------------
    df = df[
        [
            "location",
            "material_code",
            "norms",
        ]
    ].copy() 

    # ---------------------------------------------------------
    # 5. Clean, normalize, and filter location
    # ---------------------------------------------------------
    df["location"] = (
        df["location"]
        .astype(str)
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
    )

    # Normalize plant values before filtering.
    # This is case-insensitive, so values such as:
    # 1110_FG, 1110_fg, 1110_Kit, and 1110_KIT
    # will all become 1110.
    location_upper = df["location"].str.upper()

    df["location"] = location_upper.replace(
        {
            "1110_FG": "1110",
            "1110_KIT": "1110",
        }
    )

    # Keep only the approved plants.
    allowed_locations = {
        "1110",
        "1159",
        "1153",
        "1156",
        "1157",
        "1155",
        "1158",
        "1161",
        "1152",
        "1141",
    }

    df = df[
        df["location"].isin(allowed_locations)
    ].copy()

    # ---------------------------------------------------------
    # 6. Clean material code
    # ---------------------------------------------------------
    df["material_code"] = (
        df["material_code"]
        .astype(str)
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
    )

    # ---------------------------------------------------------
    # 7. Convert norms to numeric
    # ---------------------------------------------------------
    df["norms"] = pd.to_numeric(
        df["norms"],
        errors="coerce",
    )

    validation_config = section_config.get(
        "validation",
        {},
    )

    invalid_text_values = {
        "",
        "nan",
        "none",
        "null",
        "<na>",
    }

    # ---------------------------------------------------------
    # 8. Remove missing location
    # ---------------------------------------------------------
    if validation_config.get(
        "remove_missing_location",
        True,
    ):
        valid_location_mask = ~(
            df["location"]
            .str.lower()
            .isin(invalid_text_values)
        )

        df = df[
            valid_location_mask
        ].copy()

    # ---------------------------------------------------------
    # 9. Remove missing material
    # ---------------------------------------------------------
    if validation_config.get(
        "remove_missing_material",
        True,
    ):
        valid_material_mask = ~(
            df["material_code"]
            .str.lower()
            .isin(invalid_text_values)
        )

        df = df[
            valid_material_mask
        ].copy()

    # ---------------------------------------------------------
    # 10. Remove blank or non-numeric norms
    # ---------------------------------------------------------
    if validation_config.get(
        "remove_missing_norms",
        True,
    ):
        df = df.dropna(
            subset=["norms"]
        )

    # ---------------------------------------------------------
    # 11. Remove negative norms
    # ---------------------------------------------------------
    if validation_config.get(
        "remove_negative_norms",
        True,
    ):
        df = df[
            df["norms"] >= 0
        ].copy()

    # ---------------------------------------------------------
    # 12. Handle duplicate plant-material combinations
    # ---------------------------------------------------------
    duplicate_rule = str(
        section_config.get(
            "duplicate_rule",
            "LAST",
        )
    ).strip().upper()

    if duplicate_rule == "LAST":
        df = df.drop_duplicates(
            subset=[
                "location",
                "material_code",
            ],
            keep="last",
        )

    elif duplicate_rule == "FIRST":
        df = df.drop_duplicates(
            subset=[
                "location",
                "material_code",
            ],
            keep="first",
        )

    elif duplicate_rule == "MAX":
        df = (
            df.groupby(
                [
                    "location",
                    "material_code",
                ],
                as_index=False,
            )
            .agg(
                norms=("norms", "max")
            )
        )

    elif duplicate_rule == "MIN":
        df = (
            df.groupby(
                [
                    "location",
                    "material_code",
                ],
                as_index=False,
            )
            .agg(
                norms=("norms", "min")
            )
        )

    else:
        raise ValueError(
            "Unsupported norms duplicate rule: "
            f"{duplicate_rule}. "
            "Supported rules are LAST, FIRST, MAX, and MIN."
        )

    # ---------------------------------------------------------
    # 13. Convert whole-number norms to integer
    # ---------------------------------------------------------
    if (
        not df.empty
        and (df["norms"] % 1 == 0).all()
    ):
        df["norms"] = (
            df["norms"]
            .astype("int64")
        )

    # ---------------------------------------------------------
    # 14. Final sorting
    # ---------------------------------------------------------
    df = df.sort_values(
        by=[
            "location",
            "material_code",
        ],
        ascending=[
            True,
            True,
        ],
    ).reset_index(drop=True)

    return df[
        [
            "location",
            "material_code",
            "norms",
        ]
    ].copy()

def clean_git_type_1(
    raw_df: pd.DataFrame,
    rlt_master_df: pd.DataFrame,
    section_config: dict,
) -> pd.DataFrame:
    """
    Cleans and enriches GIT source file Type 1.

    GIT source mapping:
    - Material           -> material_code
    - To Plant           -> destination_location
    - From Plant/Vendor  -> source_location
    - Quantity           -> git_quantity
    - Delv.Status        -> delivery_status
    - ASN No.            -> asn_number
    - Delv.Date          -> dispatch_datetime

    RLT matching:
    - GIT destination_location = RLT location
    - GIT material_code = RLT material_code
    - GIT source_location = RLT supplier_code

    Expected arrival:
        dispatch_datetime + inbound_rlt_days

    Final columns:
    - material_code
    - destination_location
    - source_location
    - git_quantity
    - delivery_status
    - asn_number
    - dispatch_datetime
    - inbound_rlt_days
    - expected_arrival_datetime
    - rlt_found

    Important:
    - Expected arrival represents arrival at the destination/parent plant.
    - The one-day buffer and parent-to-dealer delivery time are added later
      during order orchestration.
    - Missing-RLT rows remain in the cleaned GIT output for audit.
    """

    git_df = raw_df.copy()
    rlt_df = rlt_master_df.copy()

    # ---------------------------------------------------------
    # Constants
    # ---------------------------------------------------------
    allowed_destination_locations = {
        "1110",
        "1159",
        "1153",
        "1156",
        "1157",
        "1155",
        "1158",
        "1161",
        "1152",
        "1141",
    }

    invalid_text_values = {
        "",
        "NAN",
        "NONE",
        "NULL",
        "<NA>",
        "NAT",
    }

    # =========================================================
    # GIT DATA PREPARATION
    # =========================================================

    # ---------------------------------------------------------
    # 1. Standardize GIT column names
    # ---------------------------------------------------------
    git_df.columns = (
        git_df.columns
        .astype(str)
        .str.strip()
        .str.replace("\n", " ", regex=False)
        .str.replace(r"\s+", " ", regex=True)
    )

    # ---------------------------------------------------------
    # 2. Rename GIT columns
    # ---------------------------------------------------------
    default_git_mapping = {
        "Material": "material_code",
        "To Plant": "destination_location",
        "From Plant/Vendor": "source_location",
        "Quantity": "git_quantity",
        "Delv.Status": "delivery_status",
        "ASN No.": "asn_number",
        "Delv.Date": "dispatch_datetime",
        "Unit": "unit",
    }

    configured_git_mapping = section_config.get(
        "column_mapping",
        {},
    )

    git_column_mapping = {
        **default_git_mapping,
        **configured_git_mapping,
    }

    normalized_git_mapping = {
        str(source_column)
        .strip()
        .replace("\n", " "): target_column
        for source_column, target_column
        in git_column_mapping.items()
    }

    git_df = git_df.rename(
        columns=normalized_git_mapping
    )

    # Backward compatibility with older YAML configuration.
    if (
        "dispatch_date" in git_df.columns
        and "dispatch_datetime" not in git_df.columns
    ):
        git_df = git_df.rename(
            columns={
                "dispatch_date": "dispatch_datetime",
            }
        )

    # ---------------------------------------------------------
    # 3. Validate required GIT columns
    # ---------------------------------------------------------
    required_git_columns = [
        "material_code",
        "destination_location",
        "source_location",
        "git_quantity",
        "delivery_status",
        "asn_number",
        "dispatch_datetime",
    ]

    missing_git_columns = [
        column
        for column in required_git_columns
        if column not in git_df.columns
    ]

    if missing_git_columns:
        raise ValueError(
            "GIT Type 1 file is missing required columns "
            f"after mapping: {missing_git_columns}. "
            f"Available columns: {git_df.columns.tolist()}"
        )

    git_df = git_df[
        required_git_columns
    ].copy()

    # ---------------------------------------------------------
    # 4. Clean material code
    # ---------------------------------------------------------
    git_df["material_code"] = (
        git_df["material_code"]
        .astype(str)
        .str.strip()
        .str.upper()
        .str.replace(r"\.0$", "", regex=True)
    )

    # ---------------------------------------------------------
    # 5. Clean and filter destination plant
    # ---------------------------------------------------------
    git_df["destination_location"] = (
        git_df["destination_location"]
        .astype(str)
        .str.strip()
        .str.upper()
        .str.replace(r"\.0$", "", regex=True)
    )

    rows_before_plant_filter = len(git_df)

    git_df = git_df[
        git_df["destination_location"].isin(
            allowed_destination_locations
        )
    ].copy()

    rows_removed_by_plant_filter = (
        rows_before_plant_filter - len(git_df)
    )

    # -------------------------
    # Vendor -> Plant mapping
    # -------------------------
    vendor_to_plant = {
        "139151": "1110",
        "139317": "1141",
        "139271": "1152",
        "139273": "1153",
        "142991": "1155",
        "139331": "1156",
        "139332": "1157",
        "139227": "1158",
        "139334": "1159",
        "139345": "1161",
        # "1000 ETB": "1010",
        # "1110_Kit": "1110",
        # "1110_FG": "1110",
        # "1110_KIT":"1110"
    }

    git_df["source_location"] = git_df["source_location"].replace(vendor_to_plant)

    # ---------------------------------------------------------
    # 6. Clean source plant/vendor
    # ---------------------------------------------------------
    # Preserve the source code as text for audit.
    git_df["source_location"] = (
        git_df["source_location"]
        .astype(str)
        .str.strip()
        .str.upper()
        .str.replace(r"\.0$", "", regex=True)
    )

    # Matching key handles leading-zero differences.
    #
    # 0000113033 -> 113033
    # 113033      -> 113033
    git_df["_source_location_key"] = (
        git_df["source_location"]
        .str.lstrip("0")
        .replace("", "0")
    )

    # ---------------------------------------------------------
    # 7. Clean and filter delivery status
    # ---------------------------------------------------------
    git_df["delivery_status"] = pd.to_numeric(
        git_df["delivery_status"],
        errors="coerce",
    )

    rows_before_status_filter = len(git_df)

    git_df = git_df[
        git_df["delivery_status"].isin(
            [1, 2, 3]
        )
    ].copy()

    rows_removed_by_status_filter = (
        rows_before_status_filter - len(git_df)
    )

    git_df["delivery_status"] = (
        git_df["delivery_status"]
        .astype("int64")
    )

    # ---------------------------------------------------------
    # 8. Clean and filter GIT quantity
    # ---------------------------------------------------------
    git_df["git_quantity"] = (
        git_df["git_quantity"]
        .astype(str)
        .str.strip()
        .str.replace(",", "", regex=False)
    )

    git_df["git_quantity"] = pd.to_numeric(
        git_df["git_quantity"],
        errors="coerce",
    )

    rows_before_quantity_filter = len(git_df)

    git_df = git_df[
        git_df["git_quantity"].notna()
        & (git_df["git_quantity"] > 0)
    ].copy()

    rows_removed_by_quantity_filter = (
        rows_before_quantity_filter - len(git_df)
    )

    if (
        not git_df.empty
        and (git_df["git_quantity"] % 1 == 0).all()
    ):
        git_df["git_quantity"] = (
            git_df["git_quantity"]
            .astype("int64")
        )

    # ---------------------------------------------------------
    # 9. Clean ASN number
    # ---------------------------------------------------------
    git_df["asn_number"] = (
        git_df["asn_number"]
        .astype(str)
        .str.strip()
        .str.upper()
        .str.replace(r"\.0$", "", regex=True)
    )

    # ---------------------------------------------------------
    # 10. Parse dispatch date
    # ---------------------------------------------------------
    original_dispatch_values = (
        git_df["dispatch_datetime"].copy()
    )

    raw_dispatch_date = (
        original_dispatch_values
        .astype(str)
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
    )

    parsed_dispatch_date = pd.Series(
        pd.NaT,
        index=git_df.index,
        dtype="datetime64[ns]",
    )

    # Format such as 20260908.
    yyyymmdd_mask = (
        raw_dispatch_date.str.fullmatch(
            r"\d{8}",
            na=False,
        )
    )

    parsed_dispatch_date.loc[yyyymmdd_mask] = (
        pd.to_datetime(
            raw_dispatch_date.loc[
                yyyymmdd_mask
            ],
            format="%Y%m%d",
            errors="coerce",
        )
    )

    # Other Excel or text date formats.
    remaining_date_mask = ~yyyymmdd_mask

    parsed_dispatch_date.loc[
        remaining_date_mask
    ] = pd.to_datetime(
        original_dispatch_values.loc[
            remaining_date_mask
        ],
        errors="coerce",
        dayfirst=True,
    )

    git_df["dispatch_datetime"] = (
        parsed_dispatch_date
    )

    invalid_dispatch_date_count = int(
        git_df["dispatch_datetime"]
        .isna()
        .sum()
    )

    git_df = git_df.dropna(
        subset=["dispatch_datetime"]
    ).copy()

    # ---------------------------------------------------------
    # 11. Remove invalid GIT identifiers
    # ---------------------------------------------------------
    valid_identifier_mask = (
        ~git_df["material_code"]
        .str.upper()
        .isin(invalid_text_values)
        & ~git_df["destination_location"]
        .str.upper()
        .isin(invalid_text_values)
        & ~git_df["source_location"]
        .str.upper()
        .isin(invalid_text_values)
        & ~git_df["asn_number"]
        .str.upper()
        .isin(invalid_text_values)
    )

    rows_before_identifier_filter = len(
        git_df
    )

    git_df = git_df[
        valid_identifier_mask
    ].copy()

    rows_removed_by_identifier_filter = (
        rows_before_identifier_filter
        - len(git_df)
    )

    # =========================================================
    # RLT MASTER PREPARATION
    # =========================================================

    # ---------------------------------------------------------
    # 12. Standardize RLT master columns
    # ---------------------------------------------------------
    rlt_df.columns = (
        rlt_df.columns
        .astype(str)
        .str.strip()
        .str.lower()
        .str.replace("\n", " ", regex=False)
        .str.replace(r"\s+", "_", regex=True)
        .str.replace(".", "", regex=False)
    )

    default_rlt_mapping = {
        "plant": "location",
        "plant_code": "location",
        "destination_location": "location",
        "destination_plant": "location",
        "material": "material_code",
        "material_number": "material_code",
        "vendor": "supplier_code",
        "vendor_code": "supplier_code",
        "source_location": "supplier_code",
        "source_vendor": "supplier_code",
        "supplier": "supplier_code",
        "rlt": "inbound_rlt_days",
        "rlt_days": "inbound_rlt_days",
        "replenishment_lead_time": "inbound_rlt_days",
        "lead_time": "inbound_rlt_days",
    }

    configured_rlt_mapping = section_config.get(
        "rlt_column_mapping",
        {},
    )

    normalized_configured_rlt_mapping = {
        str(source_column)
        .strip()
        .lower()
        .replace("\n", " ")
        .replace(" ", "_")
        .replace(".", ""): target_column
        for source_column, target_column
        in configured_rlt_mapping.items()
    }

    rlt_column_mapping = {
        **default_rlt_mapping,
        **normalized_configured_rlt_mapping,
    }

    rlt_df = rlt_df.rename(
        columns=rlt_column_mapping
    )

    # ---------------------------------------------------------
    # 13. Validate required RLT columns
    # ---------------------------------------------------------
    required_rlt_columns = [
        "location",
        "material_code",
        "supplier_code",
        "inbound_rlt_days",
    ]

    missing_rlt_columns = [
        column
        for column in required_rlt_columns
        if column not in rlt_df.columns
    ]

    if missing_rlt_columns:
        raise ValueError(
            "RLT master is missing columns required for "
            f"GIT enrichment: {missing_rlt_columns}. "
            f"Available columns: {rlt_df.columns.tolist()}"
        )

    rlt_df = rlt_df[
        required_rlt_columns
    ].copy()

    # ---------------------------------------------------------
    # 14. Clean RLT location
    # ---------------------------------------------------------
    rlt_df["location"] = (
        rlt_df["location"]
        .astype(str)
        .str.strip()
        .str.upper()
        .str.replace(r"\.0$", "", regex=True)
    )

    rlt_df = rlt_df[
        rlt_df["location"].isin(
            allowed_destination_locations
        )
    ].copy()

    # ---------------------------------------------------------
    # 15. Clean RLT material code
    # ---------------------------------------------------------
    rlt_df["material_code"] = (
        rlt_df["material_code"]
        .astype(str)
        .str.strip()
        .str.upper()
        .str.replace(r"\.0$", "", regex=True)
    )

    # ---------------------------------------------------------
    # 16. Clean RLT supplier code
    # ---------------------------------------------------------
    rlt_df["supplier_code"] = (
        rlt_df["supplier_code"]
        .astype(str)
        .str.strip()
        .str.upper()
        .str.replace(r"\.0$", "", regex=True)
    )

    rlt_df["_supplier_code_key"] = (
        rlt_df["supplier_code"]
        .str.lstrip("0")
        .replace("", "0")
    )

    # ---------------------------------------------------------
    # 17. Clean inbound RLT days
    # ---------------------------------------------------------
    rlt_df["inbound_rlt_days"] = pd.to_numeric(
        rlt_df["inbound_rlt_days"],
        errors="coerce",
    )

    rlt_df = rlt_df.dropna(
        subset=["inbound_rlt_days"]
    ).copy()

    rlt_df = rlt_df[
        rlt_df["inbound_rlt_days"] >= 0
    ].copy()

    rlt_valid_identifier_mask = (
        ~rlt_df["location"]
        .str.upper()
        .isin(invalid_text_values)
        & ~rlt_df["material_code"]
        .str.upper()
        .isin(invalid_text_values)
        & ~rlt_df["supplier_code"]
        .str.upper()
        .isin(invalid_text_values)
    )

    rlt_df = rlt_df[
        rlt_valid_identifier_mask
    ].copy()

    # ---------------------------------------------------------
    # 18. Handle duplicate plant-material-supplier RLT rows
    # ---------------------------------------------------------
    # Minimum RLT is retained for an exact duplicate key.
    # If your business rule requires the latest master row instead,
    # replace this aggregation with drop_duplicates(keep="last").
    rlt_lookup_df = (
        rlt_df.groupby(
            [
                "location",
                "material_code",
                "_supplier_code_key",
            ],
            as_index=False,
        )
        .agg(
            inbound_rlt_days=(
                "inbound_rlt_days",
                "min",
            )
        )
    )

    # Use nullable integer when every RLT is a whole number.
    if (
        not rlt_lookup_df.empty
        and (
            rlt_lookup_df["inbound_rlt_days"]
            % 1
            == 0
        ).all()
    ):
        rlt_lookup_df["inbound_rlt_days"] = (
            rlt_lookup_df["inbound_rlt_days"]
            .astype("int64")
        )

    # =========================================================
    # GIT AND RLT MERGE
    # =========================================================

    # ---------------------------------------------------------
    # 19. Merge GIT rows with RLT master
    # ---------------------------------------------------------
    git_df = git_df.merge(
        rlt_lookup_df,
        left_on=[
            "destination_location",
            "material_code",
            "_source_location_key",
        ],
        right_on=[
            "location",
            "material_code",
            "_supplier_code_key",
        ],
        how="left",
        validate="many_to_one",
    )

    git_df["inbound_rlt_days"] = pd.to_numeric(
        git_df["inbound_rlt_days"],
        errors="coerce",
    )

    git_df["rlt_found"] = (
        git_df["inbound_rlt_days"].notna()
    )

    # ---------------------------------------------------------
    # 20. Calculate effective dispatch and expected arrival
    # ---------------------------------------------------------

    # Preserve the original source/vendor dispatch date.
    git_df["dispatch_datetime"] = pd.to_datetime(
        git_df["dispatch_datetime"],
        errors="coerce",
    )

    # Fixed source-dispatch processing buffer.
    git_df["source_dispatch_buffer_days"] = 1

    # Effective dispatch date used for inbound-arrival calculation.
    #
    # Formula:
    # effective dispatch datetime
    # = original source dispatch datetime + 1 buffer day
    git_df["effective_dispatch_datetime"] = (
        git_df["dispatch_datetime"]
        + pd.to_timedelta(
            git_df["source_dispatch_buffer_days"],
            unit="D",
        )
    )

    # Initialize expected arrival as blank.
    git_df["expected_arrival_datetime"] = pd.NaT

    rlt_found_mask = (
        git_df["rlt_found"]
        & git_df["effective_dispatch_datetime"].notna()
        & git_df["inbound_rlt_days"].notna()
    )

    # Formula:
    # expected arrival at parent RDC
    # = original dispatch date
    # + 1 source-dispatch buffer day
    # + inbound RLT
    git_df.loc[
        rlt_found_mask,
        "expected_arrival_datetime",
    ] = (
        git_df.loc[
            rlt_found_mask,
            "effective_dispatch_datetime",
        ]
        + pd.to_timedelta(
            git_df.loc[
                rlt_found_mask,
                "inbound_rlt_days",
            ],
            unit="D",
        )
    )

    git_df["effective_dispatch_datetime"] = (
        pd.to_datetime(
            git_df["effective_dispatch_datetime"],
            errors="coerce",
        )
    )

    git_df["expected_arrival_datetime"] = (
        pd.to_datetime(
            git_df["expected_arrival_datetime"],
            errors="coerce",
        )
    )

    git_df["expected_arrival_datetime"] = (
        pd.to_datetime(
            git_df[
                "expected_arrival_datetime"
            ],
            errors="coerce",
        )
    )

    # ---------------------------------------------------------
    # 21. Build missing GIT RLT audit report
    # ---------------------------------------------------------
    missing_rlt_df = (
        git_df[
            ~git_df["rlt_found"]
        ][
            [
                "destination_location",
                "material_code",
                "source_location",
            ]
        ]
        .drop_duplicates()
        .sort_values(
            by=[
                "destination_location",
                "material_code",
                "source_location",
            ],
            ascending=[
                True,
                True,
                True,
            ],
        )
        .reset_index(drop=True)
    )

    if not missing_rlt_df.empty:
        missing_rlt_df["reason"] = (
            "GIT_INBOUND_RLT_NOT_FOUND"
        )

    # ---------------------------------------------------------
    # 22. Remove temporary merge fields
    # ---------------------------------------------------------
    git_df = git_df.drop(
        columns=[
            "_source_location_key",
            "location",
            "_supplier_code_key",
        ],
        errors="ignore",
    )
 

    # ---------------------------------------------------------
    # 23. Set final output columns
    # ---------------------------------------------------------
    final_columns = [
        "material_code",
        "destination_location",
        "source_location",
        "git_quantity",
        "delivery_status",
        "asn_number",
        "dispatch_datetime",

        # New source-dispatch buffer fields
        "source_dispatch_buffer_days",
        "effective_dispatch_datetime",

        "inbound_rlt_days",
        "expected_arrival_datetime",
        "rlt_found",
    ]

    # ---------------------------------------------------------
    # 24. Remove exact duplicate rows
    # ---------------------------------------------------------
    duplicate_count = int(
        git_df.duplicated(
            subset=final_columns,
            keep="last",
        ).sum()
    )

    git_df = git_df.drop_duplicates(
        subset=final_columns,
        keep="last",
    ).copy()

    # ---------------------------------------------------------
    # 25. Sort final output
    # ---------------------------------------------------------
    git_df = git_df.sort_values(
        by=[
            "rlt_found",
            "expected_arrival_datetime",
            "destination_location",
            "material_code",
            "asn_number",
        ],
        ascending=[
            False,
            True,
            True,
            True,
            True,
        ],
        na_position="last",
    ).reset_index(drop=True)

    # ---------------------------------------------------------
    # 26. Attach missing RLT report
    # ---------------------------------------------------------
    # This is retrieved by the pipeline before saving the dataframe.
    git_df.attrs[
        "missing_git_rlt_report"
    ] = missing_rlt_df

    # ---------------------------------------------------------
    # 27. Print cleaning summary
    # ---------------------------------------------------------
    print(
        "GIT Type 1 rows removed due to excluded plants:",
        rows_removed_by_plant_filter,
    )

    print(
        "GIT Type 1 rows removed due to delivery status:",
        rows_removed_by_status_filter,
    )

    print(
        "GIT Type 1 rows removed due to invalid quantity:",
        rows_removed_by_quantity_filter,
    )

    print(
        "GIT Type 1 rows removed due to invalid dispatch date:",
        invalid_dispatch_date_count,
    )

    print(
        "GIT Type 1 rows removed due to invalid identifiers:",
        rows_removed_by_identifier_filter,
    )

    print(
        "GIT Type 1 exact duplicate rows removed:",
        duplicate_count,
    )

    print(
        "GIT Type 1 rows with inbound RLT:",
        int(git_df["rlt_found"].sum()),
    )

    print(
        "GIT Type 1 rows without inbound RLT:",
        int((~git_df["rlt_found"]).sum()),
    )

    print(
        "GIT Type 1 missing RLT combinations:",
        len(missing_rlt_df),
    )

    print(
        "GIT Type 1 final row count:",
        len(git_df),
    )

    return git_df[final_columns].copy()
     
def read_git_workbook_from_config(
    section_config: dict,
) -> pd.DataFrame | dict[str, pd.DataFrame]:
    """
    Reads one sheet or all sheets from a GIT workbook.

    Config:
        sheet_name: "ALL"
            Returns a dictionary of all sheets.

        sheet_name: 0 or a sheet name
            Returns one DataFrame.
    """

    input_path = section_config["input_path"]

    sheet_name = section_config.get(
        "sheet_name",
        0,
    )

    header = section_config.get(
        "header",
        0,
    )

    if (
        isinstance(sheet_name, str)
        and sheet_name.strip().upper() == "ALL"
    ):
        return pd.read_excel(
            input_path,
            sheet_name=None,
            header=header,
            engine="openpyxl",
        )

    return pd.read_excel(
        input_path,
        sheet_name=sheet_name,
        header=header,
        engine="openpyxl",
    )

def clean_git_type_2(
    raw_df: pd.DataFrame | dict[str, pd.DataFrame],
    section_config: dict,
) -> pd.DataFrame:
    """
    Cleans GIT source file Type 2.

    Input may be:
    - A single pandas DataFrame
    - A dictionary of DataFrames returned by:
      pd.read_excel(..., sheet_name=None)

    Expected source fields:
    - Plant
    - IBD Date
    - Challan No.
    - Material
    - Vendor
    - Qty
    - Delivery Status

    Final common GIT format:
    - material_code
    - destination_location
    - source_location
    - git_quantity
    - delivery_status
    - asn_number
    - dispatch_datetime

    Business rules:
    - Combine all non-empty sheets.
    - Keep only approved destination plants.
    - Keep delivery statuses 1, 2, and 3.
    - Keep only positive quantities.
    - Treat IBD Date as dispatch date.
    - Keep only records from the last configured number of days.
    """

    final_columns = [
        "material_code",
        "destination_location",
        "source_location",
        "git_quantity",
        "delivery_status",
        "asn_number",
        "dispatch_datetime",
    ]

    # ---------------------------------------------------------
    # 1. Combine multiple sheets, if supplied
    # ---------------------------------------------------------
    if isinstance(raw_df, dict):
        non_empty_sheets: list[pd.DataFrame] = []

        for sheet_name, sheet_df in raw_df.items():
            if sheet_df is None or sheet_df.empty:
                continue

            current_sheet_df = sheet_df.copy()

            # Temporary field for debugging.
            # It is excluded from the final output.
            current_sheet_df["_source_sheet"] = str(
                sheet_name
            ).strip()

            non_empty_sheets.append(current_sheet_df)

        if not non_empty_sheets:
            return pd.DataFrame(columns=final_columns)

        df = pd.concat(
            non_empty_sheets,
            ignore_index=True,
            sort=False,
        )

    else:
        if raw_df is None or raw_df.empty:
            return pd.DataFrame(columns=final_columns)

        df = raw_df.copy()

    # ---------------------------------------------------------
    # 2. Standardize source column names
    # ---------------------------------------------------------
    df.columns = (
        df.columns
        .astype(str)
        .str.strip()
        .str.replace("\n", " ", regex=False)
        .str.replace(r"\s+", " ", regex=True)
    )

    # ---------------------------------------------------------
    # 3. Apply source-to-target column mapping
    # ---------------------------------------------------------
    default_column_mapping = {
        "Plant": "destination_location",
        "IBD Date": "dispatch_datetime",
        "IBD Date.": "dispatch_datetime",
        "Challan No.": "asn_number",
        "Challan No": "asn_number",
        "Material": "material_code",
        "Vendor": "source_location",
        "Qty": "git_quantity",
        "Quantity": "git_quantity",
        "Delivery Status": "delivery_status",
    }

    configured_mapping = section_config.get(
        "column_mapping",
        {},
    )

    column_mapping = {
        **default_column_mapping,
        **configured_mapping,
    }

    normalized_mapping = {
        str(source_column)
        .strip()
        .replace("\n", " "): target_column
        for source_column, target_column
        in column_mapping.items()
    }

    df = df.rename(columns=normalized_mapping)

        # ---------------------------------------------------------
    # 3A. Combine duplicate columns created during renaming
    # ---------------------------------------------------------
    duplicate_column_names = (
        df.columns[
            df.columns.duplicated(keep=False)
        ]
        .unique()
        .tolist()
    )

    if duplicate_column_names:
        print(
            "GIT Type 2 duplicate columns after mapping:",
            duplicate_column_names,
        )

        duplicate_free_df = pd.DataFrame(
            index=df.index
        )

        for column_name in df.columns.unique():
            matching_columns = df.loc[
                :,
                df.columns == column_name,
            ]

            if matching_columns.shape[1] == 1:
                duplicate_free_df[column_name] = (
                    matching_columns.iloc[:, 0]
                )
            else:
                # Take the first non-blank value across duplicate
                # columns, working from left to right.
                cleaned_matching_columns = (
                    matching_columns.replace(
                        {
                            "": pd.NA,
                            " ": pd.NA,
                            "nan": pd.NA,
                            "NaN": pd.NA,
                            "None": pd.NA,
                            "NULL": pd.NA,
                        }
                    )
                )

                duplicate_free_df[column_name] = (
                    cleaned_matching_columns
                    .bfill(axis=1)
                    .iloc[:, 0]
                )

        df = duplicate_free_df
    # ---------------------------------------------------------
    # 4. Validate required columns
    # ---------------------------------------------------------
    missing_columns = [
        column
        for column in final_columns
        if column not in df.columns
    ]

    if missing_columns:
        raise ValueError(
            "GIT Type 2 file is missing required columns "
            f"after mapping: {missing_columns}. "
            f"Available columns: {df.columns.tolist()}"
        )

    # ---------------------------------------------------------
    # 5. Keep only workflow-required columns
    # ---------------------------------------------------------
    df = df[final_columns].copy()

    # ---------------------------------------------------------
    # 6. Clean material code
    # ---------------------------------------------------------
    df["material_code"] = (
        df["material_code"]
        .astype(str)
        .str.strip()
        .str.upper()
        .str.replace(r"\.0$", "", regex=True)
    )

    # ---------------------------------------------------------
    # 7. Clean and filter destination plant
    # ---------------------------------------------------------
    df["destination_location"] = (
        df["destination_location"]
        .astype(str)
        .str.strip()
        .str.upper()
        .str.replace(r"\.0$", "", regex=True)
    )

    allowed_destination_locations = {
        "1110",
        "1159",
        "1153",
        "1156",
        "1157",
        "1155",
        "1158",
        "1161",
        "1152",
        "1141",
    }

    df = df[
        df["destination_location"].isin(
            allowed_destination_locations
        )
    ].copy()

    # ---------------------------------------------------------
    # 8. Clean vendor/source code
    # ---------------------------------------------------------
    df["source_location"] = (
        df["source_location"]
        .astype(str)
        .str.strip()
        .str.upper()
        .str.replace(r"\.0$", "", regex=True)
    )

    # ---------------------------------------------------------
    # 9. Clean GIT quantity
    # ---------------------------------------------------------
    df["git_quantity"] = (
        df["git_quantity"]
        .astype(str)
        .str.strip()
        .str.replace(",", "", regex=False)
    )

    df["git_quantity"] = pd.to_numeric(
        df["git_quantity"],
        errors="coerce",
    )

    df = df[
        df["git_quantity"].notna()
        & (df["git_quantity"] > 0)
    ].copy()

    if (
        not df.empty
        and (df["git_quantity"] % 1 == 0).all()
    ):
        df["git_quantity"] = (
            df["git_quantity"].astype("int64")
        )

    # ---------------------------------------------------------
    # 10. Clean and filter delivery status
    # ---------------------------------------------------------
    # Handles 01, 02, 03, 1, 2, 3, 1.0, 2.0, and 3.0.
    df["delivery_status"] = pd.to_numeric(
        df["delivery_status"],
        errors="coerce",
    )

    df = df[
        df["delivery_status"].isin([1, 2, 3])
    ].copy()

    df["delivery_status"] = (
        df["delivery_status"].astype("int64")
    )

    # ---------------------------------------------------------
    # 11. Clean ASN/Challan number
    # ---------------------------------------------------------
    df["asn_number"] = (
        df["asn_number"]
        .astype(str)
        .str.strip()
        .str.upper()
        .str.replace(r"\.0$", "", regex=True)
    )

    # ---------------------------------------------------------
    # 12. Parse IBD Date as dispatch_datetime
    # ---------------------------------------------------------
    original_dispatch_values = df[
        "dispatch_datetime"
    ].copy()

    raw_dispatch_date = (
        original_dispatch_values
        .astype(str)
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
    )

    parsed_dispatch_date = pd.Series(
        pd.NaT,
        index=df.index,
        dtype="datetime64[ns]",
    )

    # Format: 20260908
    yyyymmdd_mask = raw_dispatch_date.str.fullmatch(
        r"\d{8}",
        na=False,
    )

    parsed_dispatch_date.loc[yyyymmdd_mask] = (
        pd.to_datetime(
            raw_dispatch_date.loc[yyyymmdd_mask],
            format="%Y%m%d",
            errors="coerce",
        )
    )

    # Format: 07/09/2023
    slash_date_mask = (
        raw_dispatch_date.str.fullmatch(
            r"\d{1,2}/\d{1,2}/\d{4}",
            na=False,
        )
        & ~yyyymmdd_mask
    )

    parsed_dispatch_date.loc[slash_date_mask] = (
        pd.to_datetime(
            raw_dispatch_date.loc[slash_date_mask],
            format="%d/%m/%Y",
            errors="coerce",
        )
    )

    # Other Excel/Python date representations
    remaining_date_mask = (
        ~yyyymmdd_mask
        & ~slash_date_mask
    )

    parsed_dispatch_date.loc[remaining_date_mask] = (
        pd.to_datetime(
            original_dispatch_values.loc[
                remaining_date_mask
            ],
            errors="coerce",
            dayfirst=True,
        )
    )

    df["dispatch_datetime"] = parsed_dispatch_date

    # Remove rows with invalid IBD Date.
    invalid_date_count = int(
        df["dispatch_datetime"].isna().sum()
    )

    df = df.dropna(
        subset=["dispatch_datetime"]
    ).copy()

    # ---------------------------------------------------------
    # 13. Apply last-N-days IBD date filter
    # ---------------------------------------------------------
    lookback_days = int(
        section_config.get(
            "lookback_days",
            90,
        )
    )

    if lookback_days <= 0:
        raise ValueError(
            "git_type_2.lookback_days must be greater than zero."
        )

    configured_reference_date = section_config.get(
        "reference_date"
    )

    if (
        isinstance(configured_reference_date, str)
        and configured_reference_date.strip().upper()
        == "MAX_IBD_DATE"
    ):
        if df.empty:
            return pd.DataFrame(columns=final_columns)

        reference_date = pd.Timestamp(
            df["dispatch_datetime"].max()
        ).normalize()

    elif configured_reference_date in {
        None,
        "",
    }:
        reference_date = (
            pd.Timestamp.today().normalize()
        )

    else:
        if configured_reference_date is None:
            reference_date = pd.NaT
        else:
            reference_date = pd.to_datetime(
                configured_reference_date,
                errors="coerce",
            )

        if pd.isna(reference_date):
            raise ValueError(
                "Invalid git_type_2 reference_date: "
                f"{configured_reference_date}"
            )

        reference_date = pd.Timestamp(
            reference_date
        ).normalize()

    # Inclusive N-day window:
    # reference date counts as one of the N days.
    cutoff_date = (
        reference_date
        - pd.Timedelta(days=lookback_days - 1)
    )

    rows_before_date_filter = len(df)

    normalized_dispatch_date = (
        df["dispatch_datetime"].dt.normalize()
    )

    df = df[
        normalized_dispatch_date.between(
            cutoff_date,
            reference_date,
            inclusive="both",
        )
    ].copy()

    rows_removed_by_date_filter = (
        rows_before_date_filter - len(df)
    )

    # ---------------------------------------------------------
    # 14. Remove invalid identifier values
    # ---------------------------------------------------------
    invalid_text_values = {
        "",
        "NAN",
        "NONE",
        "NULL",
        "<NA>",
        "NAT",
    }

    valid_identifier_mask = (
        ~df["material_code"]
        .str.upper()
        .isin(invalid_text_values)
        & ~df["destination_location"]
        .str.upper()
        .isin(invalid_text_values)
        & ~df["source_location"]
        .str.upper()
        .isin(invalid_text_values)
        & ~df["asn_number"]
        .str.upper()
        .isin(invalid_text_values)
    )

    df = df[valid_identifier_mask].copy()

    # ---------------------------------------------------------
    # 15. Remove exact duplicate records
    # ---------------------------------------------------------
    # Exact duplicates are removed, but different materials within
    # the same challan/ASN are retained.
    duplicate_count = int(
        df.duplicated(keep="last").sum()
    )

    df = df.drop_duplicates(
        keep="last"
    ).copy()

    # ---------------------------------------------------------
    # 16. Sort final output
    # ---------------------------------------------------------
    df = df.sort_values(
        by=[
            "dispatch_datetime",
            "destination_location",
            "material_code",
            "asn_number",
        ],
        ascending=[
            True,
            True,
            True,
            True,
        ],
    ).reset_index(drop=True)

    # ---------------------------------------------------------
    # 17. Cleaning summary
    # ---------------------------------------------------------
    print(
        "GIT Type 2 invalid dispatch dates removed:",
        invalid_date_count,
    )

    print(
        "GIT Type 2 reference date:",
        reference_date.date(),
    )

    print(
        "GIT Type 2 cutoff date:",
        cutoff_date.date(),
    )

    print(
        f"GIT Type 2 rows removed outside "
        f"the last {lookback_days} days:",
        rows_removed_by_date_filter,
    )

    print(
        "GIT Type 2 duplicate rows removed:",
        duplicate_count,
    )

    print(
        "GIT Type 2 final row count:",
        len(df),
    )

    # ---------------------------------------------------------
    # 18. Enforce final common column order
    # ---------------------------------------------------------
    return df[final_columns].copy()

def clean_git_quantity(
    raw_df: pd.DataFrame,
    section_config: dict,
) -> pd.DataFrame:
    important_cols = [
        "SKUCode",
        "WHCode",
        "GIT/ Pending",
        "SourceLocation",
        "Parent Location Name",
    ]

    df = raw_df[important_cols].copy()

    df = df.rename(
        columns={
            "SKUCode": "material_code",
            "WHCode": "to_plant",
            "GIT/ Pending": "git_qty",
            "SourceLocation": "from_location",
            "Parent Location Name": "from_location_name",
        }
    )

    for col in [
        "material_code",
        "to_plant",
        "from_location",
        "from_location_name",
    ]:
        df[col] = clean_text_series(df[col])

    df["to_plant_raw"] = df["to_plant"]
    df["to_plant_key"] = df["to_plant"].str.upper()

    required_to_plants = [
        str(value).upper()
        for value in section_config.get("required_to_plants", [])
    ]

    to_plant_mapping = {
        str(key).upper(): str(value)
        for key, value in section_config.get("to_plant_mapping", {}).items()
    }

    df = df[df["to_plant_key"].isin(required_to_plants)].copy()

    df["to_plant"] = df["to_plant_key"].map(to_plant_mapping)

    df["git_qty"] = pd.to_numeric(
        df["git_qty"],
        errors="coerce",
    ).fillna(0)

    df = remove_invalid_key_rows(df, "material_code")
    df = df[df["git_qty"] > 0].copy()

    df_agg = (
        df.groupby(
            [
                "to_plant",
                "material_code",
                "from_location",
                "from_location_name",
            ],
            as_index=False,
        )
        .agg({"git_qty": "sum"})
    )

    return df_agg


def read_excel_from_file_config(file_config: dict) -> pd.DataFrame:
    """
    Reads source file using nested file config.

    Supports:
    - .xlsx / .xlsm via openpyxl
    - .xls via xlrd
    - .xlsb via pyxlsb
    - .csv via pandas read_csv
    """

    input_path = file_config["input_path"]
    sheet_name = file_config.get("sheet_name", 0)
    header = file_config.get("header", 0)

    input_path_lower = str(input_path).lower()

    if input_path_lower.endswith(".csv"):
        return pd.read_csv(
            input_path,
            header=header,
            encoding=file_config.get("encoding", "utf-8-sig"),
        )

    engine = file_config.get("engine", get_excel_engine(input_path))

    return pd.read_excel(
        input_path,
        sheet_name=sheet_name,
        header=header,
        engine=engine,
    )


def clean_rdc_rlt(
    raw_df: pd.DataFrame,
    rdc_rlt_config: dict,
) -> pd.DataFrame:
    """
    Cleans RDC-level RLT.

    Output:
    - location
    - material_code = ALL
    - supplier_code = ALL
    - rlt_days
    - rlt_type = RDC_LEVEL
    """

    df = raw_df.copy()

    df.columns = (
        df.columns.astype(str)
        .str.strip()
        .str.lower()
        .str.replace(" ", "_", regex=False)
    )

    column_mapping = rdc_rlt_config.get("column_mapping", {})

    df = df.rename(columns=column_mapping)

    required_columns = ["location", "rlt_days"]

    missing_columns = [
        column for column in required_columns
        if column not in df.columns
    ]

    if missing_columns:
        raise ValueError(
            f"RDC RLT file missing columns after mapping: {missing_columns}. "
            f"Available columns: {df.columns.tolist()}"
        )

    df["location"] = df["location"].astype(str).str.strip()

    df["rlt_days"] = pd.to_numeric(
        df["rlt_days"],
        errors="coerce",
    ).fillna(9999).astype(int)

    df = df[df["location"] != ""].copy()

    df = (
        df.groupby("location", as_index=False)
        .agg({"rlt_days": "min"})
    )

    df["material_code"] = "ALL"
    df["supplier_code"] = "ALL"
    df["supplier_name"] = "ALL"
    df["rlt_type"] = "RDC_LEVEL"

    return df[
        [
            "location",
            "material_code",
            "supplier_code",
            "supplier_name",
            "rlt_days",
            "rlt_type",
        ]
    ].copy()


def clean_vepdc_supplier_rlt(
    raw_df: pd.DataFrame,
    supplier_rlt_config: dict,
    vepdc_location: str,
) -> pd.DataFrame:
    """
    Cleans VEPDC material/supplier-level RLT.

    Expected source file columns after normalization:
    - SKU Code
    - SKU Name
    - Location Code
    - Location Name
    - Parent Loc code
    - Parent Loc Name
    - RLT

    Business rule:
    - Keep only rows where Location Name is VEPDC or VEPDC - KIT FG.
    - Treat both as VEPDC location 1110.
    - SKU Code becomes material_code.
    - Parent Loc code becomes supplier_code.
    - Parent Loc Name becomes supplier_name.
    - RLT becomes rlt_days.
    - If multiple suppliers exist for same material, keep minimum RLT.
    """

    df = raw_df.copy()

    # Standardize source column names
    df.columns = (
        df.columns.astype(str)
        .str.strip()
        .str.lower()
        .str.replace(".", "", regex=False)
        .str.replace("/", "_", regex=False)
        .str.replace("-", "_", regex=False)
        .str.replace(" ", "_", regex=False)
    )

    column_mapping = supplier_rlt_config.get("column_mapping", {})

    # Also normalize config keys because YAML keys may use readable names
    normalized_column_mapping = {
        str(key)
        .strip()
        .lower()
        .replace(".", "")
        .replace("/", "_")
        .replace("-", "_")
        .replace(" ", "_"): value
        for key, value in column_mapping.items()
    }

    df = df.rename(columns=normalized_column_mapping)

    required_columns = [
        "material_code",
        "location_name",
        "supplier_code",
        "supplier_name",
        "rlt_days",
    ]

    missing_columns = [
        column
        for column in required_columns
        if column not in df.columns
    ]

    if missing_columns:
        raise ValueError(
            "VEPDC supplier RLT file missing columns after mapping: "
            f"{missing_columns}. Available columns: {df.columns.tolist()}"
        )

    # Clean text fields
    df["material_code"] = df["material_code"].astype(str).str.strip()
    df["location_name"] = df["location_name"].astype(str).str.strip()
    df["supplier_code"] = df["supplier_code"].astype(str).str.strip()
    df["supplier_name"] = df["supplier_name"].astype(str).str.strip()

    # Filter only VEPDC related rows
    allowed_location_names = supplier_rlt_config.get(
        "allowed_location_names",
        ["VEPDC", "VEPDC - KIT FG"],
    )

    allowed_location_names_normalized = {
        str(value).strip().upper()
        for value in allowed_location_names
    }

    df = df[
        df["location_name"].str.upper().isin(allowed_location_names_normalized)
    ].copy()

    # Convert RLT
    df["rlt_days"] = pd.to_numeric(
        df["rlt_days"],
        errors="coerce",
    ).fillna(9999).astype(int)

    # Remove invalid material rows
    df = remove_invalid_key_rows(df, "material_code")

    # Remove invalid or zero/negative RLT if needed
    df = df[df["rlt_days"] > 0].copy()

    # Force VEPDC location as 1110
    df["location"] = str(
        supplier_rlt_config.get("vepdc_location_code", vepdc_location)
    ).strip()

    df["rlt_type"] = "VEPDC_MATERIAL_SUPPLIER"

    # Multiple supplier rule
    multiple_supplier_rule = supplier_rlt_config.get(
        "multiple_supplier_rule",
        "MIN_RLT",
    )

    if multiple_supplier_rule == "MIN_RLT":
        df = (
            df.sort_values(
                by=["material_code", "rlt_days"],
                ascending=[True, True],
            )
            .drop_duplicates(
                subset=["material_code"],
                keep="first",
            )
        )
    else:
        df = df.drop_duplicates(
            subset=["material_code"],
            keep="first",
        )

    final_columns = [
        "location",
        "material_code",
        "supplier_code",
        "supplier_name",
        "rlt_days",
        "rlt_type",
    ]

    return df[final_columns].copy()


def build_rlt_master(
    config: dict,
) -> pd.DataFrame:
    """
    Builds final RLT master.

    Logic:
    - RDC RLT is location-level.
    - VEPDC RLT is material/supplier-level.
    """

    rlt_config = config.get("rlt", {})
    defaults = rlt_config.get("defaults", {})
    vepdc_location = str(defaults.get("vepdc_location", "1110"))

    rlt_frames: list[pd.DataFrame] = []

    rdc_rlt_config = rlt_config.get("rdc_rlt", {})

    if rdc_rlt_config.get("enabled", False):
        raw_rdc_rlt = read_excel_from_file_config(rdc_rlt_config)

        cleaned_rdc_rlt = clean_rdc_rlt(
            raw_df=raw_rdc_rlt,
            rdc_rlt_config=rdc_rlt_config,
        )

        rlt_frames.append(cleaned_rdc_rlt)

    supplier_rlt_config = rlt_config.get("vepdc_supplier_rlt", {})

    if supplier_rlt_config.get("enabled", False):
        raw_supplier_rlt = read_excel_from_file_config(supplier_rlt_config)

        # cleaned_supplier_rlt = clean_vepdc_supplier_rlt(
        #     raw_df=raw_supplier_rlt,
        #     supplier_rlt_config=supplier_rlt_config,
        #     vepdc_location=vepdc_location,
        # )

        cleaned_supplier_rlt = clean_complete_rlt_master(
            raw_df=raw_supplier_rlt,
            rlt_config=supplier_rlt_config,
        )

        rlt_frames.append(cleaned_supplier_rlt)

    if not rlt_frames:
        return pd.DataFrame(
            columns=[
                "location",
                "material_code",
                "supplier_code",
                "supplier_name",
                "rlt_days",
                "rlt_type",
            ]
        )

    rlt_master_df = pd.concat(
        rlt_frames,
        ignore_index=True,
    )

    return rlt_master_df[
        [
            "location",
            "material_code",
            "supplier_code",
            "supplier_name",
            "rlt_days",
            "rlt_type",
        ]
    ].copy()

def clean_complete_rlt_master(
    raw_df: pd.DataFrame,
    rlt_config: dict,
) -> pd.DataFrame:
    """
    Cleans complete RLT master file.

    Output:
    - location
    - material_code
    - supplier_code
    - supplier_name
    - rlt_days
    - rlt_type
    """
 
    duplicate_analysis_file = rlt_config.get(
        "duplicate_analysis_file",
        "rlt_duplicate_analysis.xlsx",
    )

    duplicate_summary_file = rlt_config.get(
        "duplicate_summary_file",
        "rlt_duplicate_summary.xlsx",
    )

    df = raw_df.copy()

    # -------------------------
    # Standardize columns
    # -------------------------
    df.columns = (
        df.columns.astype(str)
        .str.strip()
        .str.lower()
        .str.replace(".", "", regex=False)
        .str.replace("/", "_", regex=False)
        .str.replace("-", "_", regex=False)
        .str.replace(" ", "_", regex=False)
    )

    column_mapping = rlt_config.get("column_mapping", {})

    normalized_column_mapping = {
        str(key)
        .strip()
        .lower()
        .replace(".", "")
        .replace("/", "_")
        .replace("-", "_")
        .replace(" ", "_"): value
        for key, value in column_mapping.items()
    }

    df = df.rename(columns=normalized_column_mapping)

    required_columns = [
        "material_code",
        "location_code",
        "supplier_code",
        "supplier_name",
        "rlt_days",
    ]

    missing_columns = [
        col
        for col in required_columns
        if col not in df.columns
    ]

    if missing_columns:
        raise ValueError(
            f"Missing columns: {missing_columns}. "
            f"Available columns: {df.columns.tolist()}"
        )

    # -------------------------
    # Clean fields
    # -------------------------
    for col in [
        "material_code",
        "location_code",
        "supplier_code",
        "supplier_name",
    ]:
        df[col] = df[col].astype(str).str.strip()

    # -------------------------
    # Remove unwanted locations
    # -------------------------
    df = df[
        ~df["location_code"]
        .str.upper()
        .eq("1110_VMI")
    ].copy()

    df = df[
            ~df["location_code"]
            .str.upper()
            .eq("1154")
        ].copy()

    # -------------------------
    # Remove unwanted suppliers
    # -------------------------
    invalid_parent_codes = {
        "MULTI",
        "PHASEOUT",
        "PHASE OUT",
        "TBD",
        # "1110_VMI",
    }

    df = df[
        ~df["supplier_code"]
        .str.upper()
        .isin(invalid_parent_codes)
    ].copy()

    # -------------------------
    # Merge KIT & FG into 1110
    # -------------------------
    df["location_code"] = df["location_code"].replace(
        {
            "1110_KIT": "1110",
            "1110_Kit":"1110",
            "1110_FG": "1110",
        }
    )

    # -------------------------
    # Vendor -> Plant mapping
    # -------------------------
    vendor_to_plant = {
        "139151": "1110",
        "139317": "1141",
        "139271": "1152",
        "139273": "1153",
        "142991": "1155",
        "139331": "1156",
        "139332": "1157",
        "139227": "1158",
        "139334": "1159",
        "139345": "1161",
        "1000 ETB": "1000",
        "1110_Kit": "1110",
        "1110_FG": "1110",
        "1110_KIT":"1110",
        "1110_VMI":"1110"
    }

    df["supplier_code"] = df["supplier_code"].replace(vendor_to_plant)

    # -------------------------
    # RLT conversion
    # -------------------------
    df["rlt_days"] = (
        pd.to_numeric(
            df["rlt_days"],
            errors="coerce",
        )
        .fillna(9999)
        .astype(int)
    )

    df = df[df["rlt_days"] > 0].copy()

    # -------------------------
    # Duplicate analysis
    # -------------------------
    duplicate_mask = df.duplicated(
        subset=[
            "location_code",
            "material_code",
            "supplier_code",
        ],
        keep=False,
    )

    duplicate_analysis_df = (
        df.loc[duplicate_mask]
        .sort_values(
            [
                "location_code",
                "material_code",
                "supplier_code",
                "rlt_days",
            ]
        )
        .copy()
    )

    logger.info(
        "Duplicate RLT rows after vendor-to-plant mapping: %s",
        len(duplicate_analysis_df),
    )

    logger.info(
        "Duplicate combinations: %s",
        duplicate_analysis_df[
            ["location_code", "material_code", "supplier_code"]
        ]
        .drop_duplicates()
        .shape[0],
    )

    # -------------------------
    # Remove invalid materials
    # -------------------------
    df = remove_invalid_key_rows(
        df,
        "material_code",
    )

    # -------------------------
    # Prepare detailed RLT output
    # -------------------------
    df["location"] = (
        df["location_code"]
        .astype(str)
        .str.strip()
        .str.upper()
    )

    df["material_code"] = (
        df["material_code"]
        .astype(str)
        .str.strip()
        .str.upper()
    )

    df["supplier_code"] = (
        df["supplier_code"]
        .astype(str)
        .str.strip()
        .str.upper()
    )

    df["supplier_name"] = (
        df["supplier_name"]
        .astype(str)
        .str.strip()
    )

    df["rlt_type"] = "COMPLETE_RLT_MASTER"

    detailed_rlt_df = df[
        [
            "location",
            "material_code",
            "supplier_code",
            "supplier_name",
            "rlt_days",
            "rlt_type",
        ]
    ].copy()

    # -------------------------
    # Remove any existing generic RDC-level rows
    # -------------------------
    # The configured fallback rows below are authoritative.
    existing_generic_mask = (
        detailed_rlt_df["material_code"].eq("ALL")
        & detailed_rlt_df["supplier_code"].eq("ALL")
    )

    detailed_rlt_df = detailed_rlt_df[
        ~existing_generic_mask
    ].copy()

    # -------------------------
    # Add VEPDC-to-RDC fallback RLT rows
    # -------------------------
    # These rows represent the fallback movement:
    #
    #     source VEPDC 1110 -> destination RDC
    #
    # The supplier_code is stored as ALL because these are generic
    # destination-level fallback rows. The resolver must only use them
    # when the requested source is 1110.
    rdc_level_rlt_map = {
        "1141": 7,
        "1152": 6,
        "1153": 3,
        "1155": 2,
        "1156": 4,
        "1157": 2,
        "1158": 2,
        "1159": 2,
        "1161": 3,
    }

    rdc_level_rows = [
        {
            "location": location,
            "material_code": "ALL",
            "supplier_code": "ALL",
            "supplier_name": "ALL",
            "rlt_days": rlt_days,
            "rlt_type": "RDC_LEVEL",
        }
        for location, rlt_days
        in rdc_level_rlt_map.items()
    ]

    rdc_level_df = pd.DataFrame(
        rdc_level_rows,
        columns=[
            "location",
            "material_code",
            "supplier_code",
            "supplier_name",
            "rlt_days",
            "rlt_type",
        ],
    )

    # -------------------------
    # Combine detailed and fallback rows
    # -------------------------
    final_rlt_df = pd.concat(
        [
            detailed_rlt_df,
            rdc_level_df,
        ],
        ignore_index=True,
        sort=False,
    )

    # Defensive duplicate check.
    final_rlt_df = final_rlt_df.drop_duplicates(
        subset=[
            "location",
            "material_code",
            "supplier_code",
            "rlt_type",
        ],
        keep="last",
    )

    final_rlt_df = final_rlt_df.sort_values(
        by=[
            "location",
            "rlt_type",
            "material_code",
            "supplier_code",
        ],
        ascending=[
            True,
            True,
            True,
            True,
        ],
    ).reset_index(drop=True)

    logger.info(
        "Detailed RLT rows retained: %s",
        len(detailed_rlt_df),
    )

    logger.info(
        "RDC-level fallback rows added: %s",
        len(rdc_level_df),
    )

    logger.info(
        "Final combined RLT rows: %s",
        len(final_rlt_df),
    )

    # # -------------------------
    # # Rename output columns
    # # -------------------------
    # df["location"] = df["location_code"]
    # df["rlt_type"] = "COMPLETE_RLT_MASTER"

    duplicate_summary_df = (
    duplicate_analysis_df
        .groupby(
            [
                "location_code",
                "material_code",
                "supplier_code",
            ],
            as_index=False,
        )
        .agg(
            duplicate_count=("rlt_days", "size"),
            min_rlt=("rlt_days", "min"),
            max_rlt=("rlt_days", "max"),
        )
        .sort_values(
            ["duplicate_count", "max_rlt"],
            ascending=[False, False],
        )
    )
 
    duplicate_analysis_df.to_excel(
        rf"C:\Order Orchestration code\order_orchestration\data\cleaned\{duplicate_analysis_file}",
        index=False,
    )

    duplicate_summary_df.to_excel(
        rf"C:\Order Orchestration code\order_orchestration\data\cleaned\{duplicate_summary_file}",
        index=False,
    )

    return final_rlt_df.copy()
    # return df[
    #     [
    #         "location",
    #         "material_code",
    #         "supplier_code",
    #         "supplier_name",
    #         "rlt_days",
    #         "rlt_type",
    #     ]
    # ].copy()

def build_inventory_master(
    inventory_df: pd.DataFrame,
    snapshot_timestamp: str,
) -> pd.DataFrame:
    """
    Builds engine-ready inventory master dataframe.

    Expected input columns:
    - plant
    - material_code
    - ageing_stock_qty
    - ageing_stock_gt_1yr

    Business meaning:
    - ageing_stock_qty means total available inventory quantity.
    - ageing_stock_gt_1yr means quantity older than 1 year.

    Output columns:
    - snapshot_timestamp
    - location
    - material_code
    - actual_stock
    - allocated_quantity
    - pending_so_quantity
    - safety_stock
    - ageing_quantity
    - ageing_quantity_gt_1yr
    """

    inventory_master_df = inventory_df.copy()

    required_columns = [
        "plant",
        "material_code",
        "ageing_stock_qty",
        "ageing_stock_gt_1yr",
    ]

    missing_columns = [
        column
        for column in required_columns
        if column not in inventory_master_df.columns
    ]

    if missing_columns:
        raise ValueError(
            f"Inventory master source missing columns: {missing_columns}"
        )

    # Standardize text columns
    inventory_master_df["plant"] = (
        inventory_master_df["plant"]
        .astype(str)
        .str.strip()
    )

    inventory_master_df["material_code"] = (
        inventory_master_df["material_code"]
        .astype(str)
        .str.strip()
    )

    # Convert numeric columns
    inventory_master_df["ageing_stock_qty"] = pd.to_numeric(
        inventory_master_df["ageing_stock_qty"],
        errors="coerce",
    ).fillna(0)

    inventory_master_df["ageing_stock_gt_1yr"] = pd.to_numeric(
        inventory_master_df["ageing_stock_gt_1yr"],
        errors="coerce",
    ).fillna(0)

    # Rename columns into engine format
    inventory_master_df = inventory_master_df.rename(
        columns={
            "plant": "location",
            "ageing_stock_qty": "actual_stock",
            "ageing_stock_gt_1yr": "ageing_quantity_gt_1yr",
        }
    )

    # If separate total ageing quantity is not available,
    # use ageing_quantity_gt_1yr as ageing_quantity for now
    inventory_master_df["ageing_quantity"] = (
        inventory_master_df["ageing_quantity_gt_1yr"]
    )

    # Add required engine fields
    inventory_master_df["allocated_quantity"] = 0
    inventory_master_df["pending_so_quantity"] = 0
    inventory_master_df["safety_stock"] = 0

    # Add snapshot timestamp
    inventory_master_df["snapshot_timestamp"] = pd.Timestamp(
        snapshot_timestamp
    )

    # Aggregate at location-material level
    inventory_master_df = (
        inventory_master_df
        .groupby(
            [
                "snapshot_timestamp",
                "location",
                "material_code",
            ],
            as_index=False,
        )
        .agg(
            {
                "actual_stock": "sum",
                "allocated_quantity": "sum",
                "pending_so_quantity": "sum",
                "safety_stock": "max",
                "ageing_quantity": "sum",
                "ageing_quantity_gt_1yr": "sum",
            }
        )
    )

    # Final engine-ready inventory structure
    inventory_master_df = inventory_master_df[
        [
            "snapshot_timestamp",
            "location",
            "material_code",
            "actual_stock",
            "allocated_quantity",
            "pending_so_quantity",
            "safety_stock", 
            "ageing_quantity",
            "ageing_quantity_gt_1yr",
        ]
    ]

    return inventory_master_df

def clean_dealer_norms_master(
    raw_df: pd.DataFrame,
    section_config: dict,
) -> pd.DataFrame:
    """
    Cleans the complete dealer-material norms master in memory.

    Final columns:
        dealer_code
        material_code
        dealer_norms

    The cleaned dataframe is not saved separately. It is used
    to enrich the cleaned open-order dataframe.
    """

    df = raw_df.copy()

    input_row_count = len(df)

    # ---------------------------------------------------------
    # 1. Standardize source column names
    # ---------------------------------------------------------
    df.columns = (
        df.columns
        .astype(str)
        .str.strip()
        .str.lower()
        .str.replace("\n", " ", regex=False)
        .str.replace(".", "", regex=False)
        .str.replace("/", "_", regex=False)
        .str.replace("-", "_", regex=False)
        .str.replace(r"\s+", "_", regex=True)
        .str.replace(r"_+", "_", regex=True)
        .str.strip("_")
    )

    # ---------------------------------------------------------
    # 2. Apply configured column mapping
    # ---------------------------------------------------------
    column_mapping = section_config.get(
        "column_mapping",
        {},
    )

    normalized_column_mapping = {
        str(source_column)
        .strip()
        .lower()
        .replace("\n", " ")
        .replace(".", "")
        .replace("/", "_")
        .replace("-", "_")
        .replace(" ", "_"): target_column
        for source_column, target_column
        in column_mapping.items()
    }

    df = df.rename(
        columns=normalized_column_mapping
    )

    # ---------------------------------------------------------
    # 3. Validate required columns
    # ---------------------------------------------------------
    required_columns = [
        "dealer_code",
        "material_code",
        "dealer_norms",
    ]

    missing_columns = [
        column
        for column in required_columns
        if column not in df.columns
    ]

    if missing_columns:
        raise ValueError(
            "Dealer norms file is missing required columns: "
            f"{missing_columns}. "
            f"Available columns: {df.columns.tolist()}"
        )

    df = df[
        required_columns
    ].copy()

    # ---------------------------------------------------------
    # 4. Normalize dealer and material codes
    # ---------------------------------------------------------
    for column in [
        "dealer_code",
        "material_code",
    ]:
        df[column] = (
            df[column]
            .astype("string")
            .str.strip()
            .str.upper()
            .str.replace(
                r"\.0$",
                "",
                regex=True,
            )
            .str.replace(
                r"\s+",
                "",
                regex=True,
            )
        )

    # ---------------------------------------------------------
    # 5. Convert norms to numeric
    # ---------------------------------------------------------
    df["dealer_norms"] = pd.to_numeric(
        df["dealer_norms"],
        errors="coerce",
    )

    # ---------------------------------------------------------
    # 6. Remove invalid dealer/material/norm rows
    # ---------------------------------------------------------
    invalid_text_values = {
        "",
        "NAN",
        "NONE",
        "NULL",
        "<NA>",
        "NAT",
        "NA",
        "N/A",
    }

    valid_mask = (
        df["dealer_code"].notna()
        & df["material_code"].notna()
        & ~df["dealer_code"].isin(
            invalid_text_values
        )
        & ~df["material_code"].isin(
            invalid_text_values
        )
        & df["dealer_norms"].notna()
        & df["dealer_norms"].ge(0)
    )

    invalid_rows_removed = int(
        (~valid_mask).sum()
    )

    df = df[
        valid_mask
    ].copy()

    # ---------------------------------------------------------
    # 7. Retain valid dealer orders only
    # ---------------------------------------------------------
    # Valid dealer starts with 1S, but export dealer 1XS
    # must not be included.
    valid_dealer_mask = (
        df["dealer_code"]
        .str.startswith(
            "1S",
            na=False,
        )
        & ~df["dealer_code"]
        .str.startswith(
            "1XS",
            na=False,
        )
    )

    invalid_dealers_removed = int(
        (~valid_dealer_mask).sum()
    )

    df = df[
        valid_dealer_mask
    ].copy()

    # ---------------------------------------------------------
    # 8. Analyze and resolve duplicate combinations
    # ---------------------------------------------------------
    duplicate_mask = df.duplicated(
        subset=[
            "dealer_code",
            "material_code",
        ],
        keep=False,
    )

    duplicate_rows = int(
        duplicate_mask.sum()
    )

    duplicate_combinations = int(
        df.loc[
            duplicate_mask,
            [
                "dealer_code",
                "material_code",
            ],
        ]
        .drop_duplicates()
        .shape[0]
    )

    # Use the maximum dealer norm when a dealer-material
    # combination has multiple norm values.
    #
    # Replace "max" with "min" or "last" if the business
    # duplicate-resolution rule is different.
    df = (
        df.groupby(
            [
                "dealer_code",
                "material_code",
            ],
            as_index=False,
        )
        .agg(
            dealer_norms=(
                "dealer_norms",
                "max",
            )
        )
    )

    # ---------------------------------------------------------
    # 9. Sort final dealer norms master
    # ---------------------------------------------------------
    df = (
        df.sort_values(
            by=[
                "dealer_code",
                "material_code",
            ]
        )
        .reset_index(drop=True)
    )

    print()
    print("Dealer norms cleaning summary")
    print("-" * 45)
    print(
        "Input dealer norms rows              :",
        f"{input_row_count:,}",
    )
    print(
        "Invalid rows removed                 :",
        f"{invalid_rows_removed:,}",
    )
    print(
        "Invalid dealer rows removed          :",
        f"{invalid_dealers_removed:,}",
    )
    print(
        "Duplicate rows identified            :",
        f"{duplicate_rows:,}",
    )
    print(
        "Duplicate dealer-material combinations:",
        f"{duplicate_combinations:,}",
    )
    print(
        "Final unique dealer-material norms   :",
        f"{len(df):,}",
    )

    return df

def add_dealer_norms_to_open_orders(
    open_order_df: pd.DataFrame,
    dealer_norms_df: pd.DataFrame,
    open_order_dealer_column: str,
    open_order_material_column: str,
) -> pd.DataFrame:
    """
    Adds dealer_norms to every open-order row using:

        dealer_code + material_code

    Missing dealer-material matches remain blank.
    """

    orders_df = open_order_df.copy()
    norms_df = dealer_norms_df.copy()

    # ---------------------------------------------------------
    # 1. Validate open-order columns
    # ---------------------------------------------------------
    required_open_order_columns = [
        open_order_dealer_column,
        open_order_material_column,
    ]

    missing_open_order_columns = [
        column
        for column in required_open_order_columns
        if column not in orders_df.columns
    ]

    if missing_open_order_columns:
        raise ValueError(
            "Open-order dataframe is missing dealer-norm "
            f"mapping columns: {missing_open_order_columns}. "
            f"Available columns: {orders_df.columns.tolist()}"
        )

    # ---------------------------------------------------------
    # 2. Validate dealer-norm columns
    # ---------------------------------------------------------
    required_norm_columns = [
        "dealer_code",
        "material_code",
        "dealer_norms",
    ]

    missing_norm_columns = [
        column
        for column in required_norm_columns
        if column not in norms_df.columns
    ]

    if missing_norm_columns:
        raise ValueError(
            "Cleaned dealer norms dataframe is missing columns: "
            f"{missing_norm_columns}"
        )

    # ---------------------------------------------------------
    # 3. Preserve original open-order columns
    # ---------------------------------------------------------
    orders_df["_dealer_norm_key"] = (
        normalize_mapping_code(
            orders_df[
                open_order_dealer_column
            ]
        )
    )

    orders_df["_material_norm_key"] = (
        normalize_mapping_code(
            orders_df[
                open_order_material_column
            ]
        )
    )

    norms_df["_dealer_norm_key"] = (
        normalize_mapping_code(
            norms_df["dealer_code"]
        )
    )

    norms_df["_material_norm_key"] = (
        normalize_mapping_code(
            norms_df["material_code"]
        )
    )

    # ---------------------------------------------------------
    # 4. Keep unique lookup combinations
    # ---------------------------------------------------------
    norms_lookup_df = (
        norms_df[
            [
                "_dealer_norm_key",
                "_material_norm_key",
                "dealer_norms",
            ]
        ]
        .drop_duplicates(
            subset=[
                "_dealer_norm_key",
                "_material_norm_key",
            ],
            keep="last",
        )
        .copy()
    )

    # ---------------------------------------------------------
    # 5. Remove an old norms column before merging
    # ---------------------------------------------------------
    orders_df = orders_df.drop(
        columns=["dealer_norms"],
        errors="ignore",
    )

    # ---------------------------------------------------------
    # 6. Merge dealer norms into every open-order row
    # ---------------------------------------------------------
    orders_df = orders_df.merge(
        norms_lookup_df,
        on=[
            "_dealer_norm_key",
            "_material_norm_key",
        ],
        how="left",
        validate="many_to_one",
    )

    # ---------------------------------------------------------
    # 7. Remove temporary matching columns
    # ---------------------------------------------------------
    orders_df = orders_df.drop(
        columns=[
            "_dealer_norm_key",
            "_material_norm_key",
        ],
        errors="ignore",
    )

    # ---------------------------------------------------------
    # 8. Print enrichment summary
    # ---------------------------------------------------------
    dealer_norms_found = int(
        orders_df["dealer_norms"]
        .notna()
        .sum()
    )

    dealer_norms_missing = int(
        orders_df["dealer_norms"]
        .isna()
        .sum()
    )

    print()
    print("Open-order dealer norms enrichment")
    print("-" * 45)
    print(
        "Total open-order rows               :",
        f"{len(orders_df):,}",
    )
    print(
        "Rows with dealer norms found        :",
        f"{dealer_norms_found:,}",
    )
    print(
        "Rows with dealer norms missing      :",
        f"{dealer_norms_missing:,}",
    )

    return orders_df

def clean_dealer_parent_mapping(
    raw_df: pd.DataFrame,
    section_config: dict,
) -> pd.DataFrame:
    """
    Cleans the dealer-to-parent-plant mapping.

    Final columns:
        dealer_code
        parent_plant

    Each dealer must map to exactly one parent plant.
    """

    df = raw_df.copy()

    input_row_count = len(df)

    # ---------------------------------------------------------
    # Standardize source column names
    # ---------------------------------------------------------
    df.columns = (
        df.columns
        .astype(str)
        .str.strip()
        .str.lower()
        .str.replace("\n", " ", regex=False)
        .str.replace(".", "", regex=False)
        .str.replace("/", "_", regex=False)
        .str.replace("-", "_", regex=False)
        .str.replace(r"\s+", "_", regex=True)
        .str.replace(r"_+", "_", regex=True)
        .str.strip("_")
    )

    # ---------------------------------------------------------
    # Normalize configured source column names
    # ---------------------------------------------------------
    configured_mapping = section_config.get(
        "column_mapping",
        {},
    )

    normalized_mapping = {
        (
            str(source_column)
            .strip()
            .lower()
            .replace("\n", " ")
            .replace(".", "")
            .replace("/", "_")
            .replace("-", "_")
            .replace(" ", "_")
        ): target_column
        for source_column, target_column
        in configured_mapping.items()
    }

    df = df.rename(
        columns=normalized_mapping
    )

    # ---------------------------------------------------------
    # Validate required columns
    # ---------------------------------------------------------
    required_columns = [
        "dealer_code",
        "parent_plant",
    ]

    missing_columns = [
        column
        for column in required_columns
        if column not in df.columns
    ]

    if missing_columns:
        raise ValueError(
            "Dealer-parent mapping is missing required "
            f"columns: {missing_columns}. "
            f"Available columns: {df.columns.tolist()}"
        )

    df = df[
        required_columns
    ].copy()

    # ---------------------------------------------------------
    # Normalize dealer and parent plant
    # ---------------------------------------------------------
    for column in [
        "dealer_code",
        "parent_plant",
    ]:
        df[column] = (
            df[column]
            .astype("string")
            .str.strip()
            .str.upper()
            .str.replace(
                r"\.0$",
                "",
                regex=True,
            )
            .str.replace(
                r"\s+",
                "",
                regex=True,
            )
        )

    # ---------------------------------------------------------
    # Remove invalid values
    # ---------------------------------------------------------
    invalid_values = {
        "",
        "NAN",
        "NONE",
        "NULL",
        "<NA>",
        "NAT",
        "NA",
        "N/A",
    }

    valid_mask = (
        df["dealer_code"].notna()
        & df["parent_plant"].notna()
        & ~df["dealer_code"].isin(
            invalid_values
        )
        & ~df["parent_plant"].isin(
            invalid_values
        )
    )

    invalid_rows_removed = int(
        (~valid_mask).sum()
    )

    df = df[
        valid_mask
    ].copy()

    # ---------------------------------------------------------
    # Retain valid dealer codes only
    # ---------------------------------------------------------
    valid_dealer_mask = (
        df["dealer_code"]
        .str.startswith(
            "1S",
            na=False,
        )
        & ~df["dealer_code"]
        .str.startswith(
            "1XS",
            na=False,
        )
    )

    invalid_dealers_removed = int(
        (~valid_dealer_mask).sum()
    )

    df = df[
        valid_dealer_mask
    ].copy()

    # ---------------------------------------------------------
    # Remove exact duplicate rows
    # ---------------------------------------------------------
    exact_duplicate_count = int(
        df.duplicated(
            subset=[
                "dealer_code",
                "parent_plant",
            ],
            keep="first",
        ).sum()
    )

    df = df.drop_duplicates(
        subset=[
            "dealer_code",
            "parent_plant",
        ],
        keep="first",
    ).copy()

    # ---------------------------------------------------------
    # Validate one parent plant per dealer
    # ---------------------------------------------------------
    dealer_parent_counts = (
        df.groupby(
            "dealer_code",
            as_index=False,
        )
        .agg(
            parent_plant_count=(
                "parent_plant",
                "nunique",
            )
        )
    )

    conflicting_dealers = (
        dealer_parent_counts[
            dealer_parent_counts[
                "parent_plant_count"
            ] > 1
        ]
    )

    if not conflicting_dealers.empty:
        conflicting_rows = (
            df.merge(
                conflicting_dealers[
                    ["dealer_code"]
                ],
                on="dealer_code",
                how="inner",
            )
            .sort_values(
                [
                    "dealer_code",
                    "parent_plant",
                ]
            )
        )

        raise ValueError(
            "Some dealers are mapped to more than one "
            "parent plant. Correct the mapping file before "
            "running open-order cleaning.\n"
            f"{conflicting_rows.head(30).to_string(index=False)}"
        )

    # One row per dealer.
    df = df.drop_duplicates(
        subset=["dealer_code"],
        keep="first",
    )

    df = (
        df.sort_values(
            "dealer_code"
        )
        .reset_index(drop=True)
    )

    print()
    print("Dealer-parent mapping cleaning summary")
    print("-" * 48)
    print(
        "Input mapping rows                 :",
        f"{input_row_count:,}",
    )
    print(
        "Invalid rows removed               :",
        f"{invalid_rows_removed:,}",
    )
    print(
        "Invalid dealer rows removed        :",
        f"{invalid_dealers_removed:,}",
    )
    print(
        "Exact duplicate rows removed       :",
        f"{exact_duplicate_count:,}",
    )
    print(
        "Final unique dealer mappings       :",
        f"{len(df):,}",
    )

    return df

def add_parent_plant_to_open_orders(
    open_order_df: pd.DataFrame,
    dealer_parent_df: pd.DataFrame,
    open_order_dealer_column: str,
    fail_on_missing_mapping: bool = True,
) -> pd.DataFrame:
    """
    Maps the authoritative parent plant to every open-order row.

    Mapping:
        open-order dealer code
        -> dealer-parent mapping dealer code

    The dedicated mapping file replaces the logistics-derived
    parent plant.

    If fail_on_missing_mapping is True:
        Raise an error when any open-order dealer has no mapping.

    If fail_on_missing_mapping is False:
        Keep parent_plant blank for unmatched dealers.
    """

    orders_df = open_order_df.copy()
    mapping_df = dealer_parent_df.copy()

    # ---------------------------------------------------------
    # 1. Validate open-order dealer column
    # ---------------------------------------------------------
    if (
        open_order_dealer_column
        not in orders_df.columns
    ):
        raise ValueError(
            "Open-order dataframe is missing dealer column "
            f"'{open_order_dealer_column}'. "
            f"Available columns: "
            f"{orders_df.columns.tolist()}"
        )

    # ---------------------------------------------------------
    # 2. Validate dealer-parent mapping columns
    # ---------------------------------------------------------
    required_mapping_columns = {
        "dealer_code",
        "parent_plant",
    }

    missing_mapping_columns = (
        required_mapping_columns
        - set(mapping_df.columns)
    )

    if missing_mapping_columns:
        raise ValueError(
            "Dealer-parent dataframe is missing columns: "
            f"{sorted(missing_mapping_columns)}"
        )

    # ---------------------------------------------------------
    # 3. Normalize open-order dealer key
    # ---------------------------------------------------------
    orders_df["_dealer_parent_key"] = (
        orders_df[
            open_order_dealer_column
        ]
        .astype("string")
        .str.strip()
        .str.upper()
        .str.replace(
            r"\.0$",
            "",
            regex=True,
        )
        .str.replace(
            r"\s+",
            "",
            regex=True,
        )
    )

    # ---------------------------------------------------------
    # 4. Normalize mapping dealer key
    # ---------------------------------------------------------
    mapping_df["_dealer_parent_key"] = (
        mapping_df["dealer_code"]
        .astype("string")
        .str.strip()
        .str.upper()
        .str.replace(
            r"\.0$",
            "",
            regex=True,
        )
        .str.replace(
            r"\s+",
            "",
            regex=True,
        )
    )

    # ---------------------------------------------------------
    # 5. Normalize mapped parent plant
    # ---------------------------------------------------------
    mapping_df["parent_plant"] = (
        mapping_df["parent_plant"]
        .astype("string")
        .str.strip()
        .str.upper()
        .str.replace(
            r"\.0$",
            "",
            regex=True,
        )
        .str.replace(
            r"\s+",
            "",
            regex=True,
        )
    )

    # ---------------------------------------------------------
    # 6. Remove invalid mapping keys
    # ---------------------------------------------------------
    invalid_values = {
        "",
        "NAN",
        "NONE",
        "NULL",
        "<NA>",
        "NAT",
        "NA",
        "N/A",
    }

    valid_mapping_mask = (
        mapping_df[
            "_dealer_parent_key"
        ].notna()
        & mapping_df[
            "parent_plant"
        ].notna()
        & ~mapping_df[
            "_dealer_parent_key"
        ].isin(invalid_values)
        & ~mapping_df[
            "parent_plant"
        ].isin(invalid_values)
    )

    mapping_df = mapping_df[
        valid_mapping_mask
    ].copy()

    # ---------------------------------------------------------
    # 7. Verify one parent plant per dealer
    # ---------------------------------------------------------
    parent_count_by_dealer = (
        mapping_df.groupby(
            "_dealer_parent_key",
            as_index=False,
        )
        .agg(
            parent_plant_count=(
                "parent_plant",
                "nunique",
            )
        )
    )

    conflicting_dealers = (
        parent_count_by_dealer[
            parent_count_by_dealer[
                "parent_plant_count"
            ] > 1
        ]
    )

    if not conflicting_dealers.empty:
        conflict_rows = (
            mapping_df.merge(
                conflicting_dealers[
                    ["_dealer_parent_key"]
                ],
                on="_dealer_parent_key",
                how="inner",
            )
            [
                [
                    "dealer_code",
                    "parent_plant",
                ]
            ]
            .drop_duplicates()
            .sort_values(
                [
                    "dealer_code",
                    "parent_plant",
                ]
            )
        )

        raise ValueError(
            "Some dealers are mapped to more than one "
            "parent plant. Correct the mapping file.\n"
            f"{conflict_rows.head(50).to_string(index=False)}"
        )

    # ---------------------------------------------------------
    # 8. Create one unique mapping per dealer
    # ---------------------------------------------------------
    mapping_lookup_df = (
        mapping_df[
            [
                "_dealer_parent_key",
                "parent_plant",
            ]
        ]
        .drop_duplicates(
            subset=[
                "_dealer_parent_key",
            ],
            keep="first",
        )
        .copy()
    )

    # ---------------------------------------------------------
    # 9. Remove previous parent columns
    # ---------------------------------------------------------
    # This ensures the dedicated mapping file is authoritative.
    orders_df = orders_df.drop(
        columns=[
            "parent_plant",
            "parent_rdc",
        ],
        errors="ignore",
    )

    row_count_before = len(
        orders_df
    )

    # ---------------------------------------------------------
    # 10. Merge authoritative parent plant
    # ---------------------------------------------------------
    orders_df = orders_df.merge(
        mapping_lookup_df,
        on="_dealer_parent_key",
        how="left",
        validate="many_to_one",
        sort=False,
    )

    # ---------------------------------------------------------
    # 11. Confirm row count did not change
    # ---------------------------------------------------------
    if len(orders_df) != row_count_before:
        raise ValueError(
            "Dealer-parent enrichment changed the number "
            "of open-order rows. "
            f"Before={row_count_before}, "
            f"after={len(orders_df)}."
        )

    # ---------------------------------------------------------
    # 12. Identify missing parent mappings
    # ---------------------------------------------------------
    normalized_parent = (
        orders_df["parent_plant"]
        .astype("string")
        .str.strip()
        .str.upper()
    )

    missing_parent_mask = (
        orders_df["parent_plant"].isna()
        | normalized_parent.isna()
        | normalized_parent.isin(
            invalid_values
        )
    )

    missing_mapping_count = int(
        missing_parent_mask.sum()
    )

    missing_dealers = (
        orders_df.loc[
            missing_parent_mask,
            [
                open_order_dealer_column,
            ],
        ]
        .drop_duplicates()
        .sort_values(
            open_order_dealer_column
        )
        .reset_index(drop=True)
    )

    # ---------------------------------------------------------
    # 13. Stop execution when mappings are missing
    # ---------------------------------------------------------
    if (
        fail_on_missing_mapping
        and missing_mapping_count > 0
    ):
        raise ValueError(
            "Parent plant mapping is missing for "
            f"{missing_mapping_count:,} open-order rows "
            f"across {len(missing_dealers):,} unique "
            "dealer(s).\n\n"
            "First missing dealers:\n"
            f"{missing_dealers.head(50).to_string(index=False)}"
        )

    # ---------------------------------------------------------
    # 14. Remove temporary matching key
    # ---------------------------------------------------------
    orders_df = orders_df.drop(
        columns=[
            "_dealer_parent_key",
        ],
        errors="ignore",
    )

    # ---------------------------------------------------------
    # 15. Print mapping summary
    # ---------------------------------------------------------
    print()
    print("Open-order parent-plant enrichment")
    print("-" * 50)
    print(
        "Total open-order rows              :",
        f"{len(orders_df):,}",
    )
    print(
        "Rows with parent mapping           :",
        f"{len(orders_df) - missing_mapping_count:,}",
    )
    print(
        "Rows missing parent mapping        :",
        f"{missing_mapping_count:,}",
    )
    print(
        "Unique dealers missing mapping     :",
        f"{len(missing_dealers):,}",
    )

    # ---------------------------------------------------------
    # 16. Return enriched open orders
    # ---------------------------------------------------------
    return orders_df
         
# def run_cleaning_pipeline(
#     config: dict,
#     only_steps: list[str] | None = None,
# ) -> dict[str, pd.DataFrame]:
def run_cleaning_pipeline(
    config: dict,
    path_config: dict,
) -> dict[str, pd.DataFrame]:
    pipeline_config = config.get(
        "pipeline",
        {},
    )

    output_dir_config = pipeline_config.get(
        "output_dir",
        "data/cleaned",
    )

    save_outputs = bool(
        pipeline_config.get(
            "save_outputs",
            True,
        )
    )

    build_dir = (
        Path(__file__)
        .resolve()
        .parents[3]
    )

    output_dir = Path(
        output_dir_config
    ).expanduser()

    if not output_dir.is_absolute():
        output_dir = (
            build_dir
            / output_dir
        ).resolve()

    if save_outputs:
        output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

    outputs: dict[str, pd.DataFrame] = {}

    def should_run(
        step_name: str,
    ) -> bool:
        return bool(
            config
            .get(step_name, {})
            .get("enabled", False)
        )
    # pipeline_config = config.get("pipeline", {})
    # output_dir = pipeline_config.get("output_dir", "data/cleaned")
    # save_outputs = bool(pipeline_config.get("save_outputs", True))

    # outputs: dict[str, pd.DataFrame] = {}

    # def should_run(step_name: str) -> bool:
    #     if only_steps is not None and step_name not in only_steps:
    #         return False

    #     return bool(config.get(step_name, {}).get("enabled", False))
    def get_section_config(
        section_name: str,
    ) -> dict:
        """
        Return a copy of a YAML section with its physical
        input path injected from OO_manual.json.
        """

        section = config.get(
            section_name,
            {},
        ).copy()

        if not section:
            raise KeyError(
                "Missing configuration section in "
                "data_cleaning.yaml: "
                f"{section_name}"
            )

        configured_path = path_config.get(
            section_name
        )

        if not configured_path:
            raise KeyError(
                "Missing file path in OO_manual.json "
                f"for '{section_name}'. "
                "Available path keys: "
                f"{list(path_config.keys())}"
            )

        input_path = Path(
            configured_path
        ).expanduser()

        # Relative JSON paths are resolved from the
        # deployment root, one level above Build.
        if not input_path.is_absolute():
            input_path = (
                build_dir.parent
                / input_path
            ).resolve()

        if not input_path.is_file():
            raise FileNotFoundError(
                "Configured input file was not found.\n"
                f"Section: {section_name}\n"
                f"Path: {input_path}"
            )

        section["input_path"] = str(
            input_path
        )

        return section

        
    if should_run("open_order"):
        # =====================================================
        # 1. READ AND CLEAN OPEN ORDERS
        # =====================================================
        section = get_section_config("open_order")

        raw_df = read_excel_from_config(
            section
        )

        cleaned_df = clean_open_order(
            raw_df,
            section,
        )

        initial_open_order_row_count = len(
            cleaned_df
        )

        # =====================================================
        # 2. DEALER-TO-PARENT-PLANT ENRICHMENT
        # =====================================================
        parent_mapping_settings = config.get(
            "dealer_parent_mapping",
            {},
        )
        
        if not parent_mapping_settings.get(
            "enabled",
            False,
        ):
            raise ValueError(
                "dealer_parent_mapping is disabled. "
                "It is required for open-order cleaning."
            )
        
        parent_mapping_config = get_section_config(
            "dealer_parent_mapping"
        )
        # parent_mapping_config = config.get(
        #     "dealer_parent_mapping",
        #     {},
        # )

        # if not parent_mapping_config.get(
        #     "enabled",
        #     False,
        # ):
        #     raise ValueError(
        #         "dealer_parent_mapping is disabled. "
        #         "The dedicated dealer-parent mapping file "
        #         "is required for open-order cleaning."
        #     )

        # -----------------------------------------------------
        # Read dealer-parent mapping
        # -----------------------------------------------------
        raw_parent_mapping_df = (
            read_excel_from_config(
                parent_mapping_config
            )
        )

        # -----------------------------------------------------
        # Clean dealer-parent mapping in memory
        # -----------------------------------------------------
        cleaned_parent_mapping_df = (
            clean_dealer_parent_mapping(
                raw_df=raw_parent_mapping_df,
                section_config=(
                    parent_mapping_config
                ),
            )
        )

        # -----------------------------------------------------
        # Replace the old/logistics-derived parent plant
        # with the dedicated dealer-parent mapping
        # -----------------------------------------------------
        cleaned_df = (
            add_parent_plant_to_open_orders(
                open_order_df=cleaned_df,
                dealer_parent_df=(
                    cleaned_parent_mapping_df
                ),
                open_order_dealer_column=(
                    parent_mapping_config.get(
                        "open_order_dealer_column",
                        "customer_code",
                    )
                ),
                fail_on_missing_mapping=(
                    parent_mapping_config.get(
                        "fail_on_missing_mapping",
                        True,
                    )
                ),
            )
        )

        if (
            len(cleaned_df)
            != initial_open_order_row_count
        ):
            raise ValueError(
                "Parent-plant enrichment changed the "
                "open-order row count. "
                f"Before={initial_open_order_row_count}, "
                f"after={len(cleaned_df)}."
            )

        # =====================================================
        # 3. DEALER-MATERIAL NORMS ENRICHMENT
        # =====================================================
        dealer_norms_config = config.get(
            "dealer_norms",
            {},
        )

        if dealer_norms_config.get(
            "enabled",
            False,
        ):
            # if (
            #     "input_path"
            #     not in dealer_norms_config
            # ):
            #     raise ValueError(
            #         "dealer_norms configuration must "
            #         "contain 'input_path'. "
            #         f"Available keys: "
            #         f"{list(dealer_norms_config.keys())}"
            #    )
            
            dealer_norms_config = (
                get_section_config(
                    "dealer_norms"
                )
            )

            rows_before_norms_mapping = len(
                cleaned_df
            )

            # -------------------------------------------------
            # Read raw dealer norms
            # -------------------------------------------------
            raw_dealer_norms_df = (
                read_excel_from_config(
                    dealer_norms_config
                )
            )

            # -------------------------------------------------
            # Clean complete dealer norms in memory
            # -------------------------------------------------
            cleaned_dealer_norms_df = (
                clean_dealer_norms_master(
                    raw_df=raw_dealer_norms_df,
                    section_config=(
                        dealer_norms_config
                    ),
                )
            )

            # -------------------------------------------------
            # Match dealer + material and add dealer_norms
            # -------------------------------------------------
            cleaned_df = (
                add_dealer_norms_to_open_orders(
                    open_order_df=cleaned_df,
                    dealer_norms_df=(
                        cleaned_dealer_norms_df
                    ),
                    open_order_dealer_column=(
                        dealer_norms_config.get(
                            "open_order_dealer_column",
                            "customer_code",
                        )
                    ),
                    open_order_material_column=(
                        dealer_norms_config.get(
                            "open_order_material_column",
                            "material_code",
                        )
                    ),
                )
            )

            # Dealer norms mapping must not multiply
            # or remove open-order rows.
            if (
                len(cleaned_df)
                != rows_before_norms_mapping
            ):
                raise ValueError(
                    "Dealer norms enrichment changed the "
                    "open-order row count. "
                    f"Before={rows_before_norms_mapping}, "
                    f"after={len(cleaned_df)}."
                )

        else:
            # Keep the output schema consistent.
            cleaned_df["dealer_norms"] = pd.NA

            print(
                "Dealer norms enrichment is disabled. "
                "dealer_norms will remain blank."
            )

        # =====================================================
        # 4. FINAL VALIDATION
        # =====================================================
        if (
            len(cleaned_df)
            != initial_open_order_row_count
        ):
            raise ValueError(
                "Open-order enrichment changed the final "
                "row count. "
                f"Initial={initial_open_order_row_count}, "
                f"final={len(cleaned_df)}."
            )

        if "parent_plant" not in cleaned_df.columns:
            raise ValueError(
                "parent_plant was not added to the "
                "cleaned open-order dataframe."
            )

        cleaned_df["plant"] = cleaned_df["parent_plant"]

        if "dealer_norms" not in cleaned_df.columns:
            raise ValueError(
                "dealer_norms was not added to the "
                "cleaned open-order dataframe."
            )

        # =====================================================
        # 5. PRINT FINAL ENRICHMENT SUMMARY
        # =====================================================
        parent_mapping_found_count = int(
            cleaned_df["parent_plant"]
            .notna()
            .sum()
        )

        parent_mapping_missing_count = int(
            cleaned_df["parent_plant"]
            .isna()
            .sum()
        )

        dealer_norms_found_count = int(
            cleaned_df["dealer_norms"]
            .notna()
            .sum()
        )

        dealer_norms_missing_count = int(
            cleaned_df["dealer_norms"]
            .isna()
            .sum()
        )

        print()
        print("Final open-order enrichment summary")
        print("-" * 50)

        print(
            "Total cleaned open-order rows       :",
            f"{len(cleaned_df):,}",
        )

        print(
            "Rows with parent plant mapping      :",
            f"{parent_mapping_found_count:,}",
        )

        print(
            "Rows missing parent plant mapping   :",
            f"{parent_mapping_missing_count:,}",
        )

        print(
            "Rows with dealer norms              :",
            f"{dealer_norms_found_count:,}",
        )

        print(
            "Rows missing dealer norms           :",
            f"{dealer_norms_missing_count:,}",
        ) 
        outputs["open_order"] = cleaned_df
 
        save_if_required(
            cleaned_df,
            output_dir,
            section.get("output_file", "cleaned_open_order.xlsx"),
            save_outputs,
        )


    # if should_run("vepdc_inventory"):
    #     section = get_section_config["vepdc_inventory"]
    #     raw_df = read_excel_from_config(section)
    #     cleaned_df = clean_vepdc_inventory(raw_df, section)
    #     outputs["vepdc_inventory"] = cleaned_df
    #     save_if_required(
    #         cleaned_df,
    #         output_dir,
    #         section.get("output_file", "cleaned_vepdc_inventory.xlsx"),
    #         save_outputs,
    #     )

    # if should_run("rdc_inventory"):
    #     section = get_section_config["rdc_inventory"]
    #     raw_df = read_excel_from_config(section)
    #     cleaned_df = clean_rdc_inventory(raw_df, section)
    #     outputs["rdc_inventory"] = cleaned_df
    #     save_if_required(
    #         cleaned_df,
    #         output_dir,
    #         section.get("output_file", "cleaned_rdc_inventory.xlsx"),
    #         save_outputs,
    #     )

    if should_run("ageing_inventory"):
        section = get_section_config("ageing_inventory")
        raw_df = read_excel_from_config(section)
        cleaned_df = clean_ageing_inventory(raw_df, section)
        outputs["ageing_inventory"] = cleaned_df
        save_if_required(
            cleaned_df,
            output_dir,
            section.get("output_file", "cleaned_ageing_inventory.xlsx"),
            save_outputs,
        )

    if should_run("logistics"):
        section = get_section_config("logistics")
        raw_df = read_excel_from_config(section)
        cleaned_df = clean_logistics(raw_df, section)
        outputs["logistics"] = cleaned_df
        save_if_required(
            cleaned_df,
            output_dir,
            section.get("output_file", "cleaned_logistics_wide.xlsx"),
            save_outputs,
        )

    # if "open_order" in outputs:
    #     open_order_section = config.get("open_order", {})

    #     if "logistics" in outputs:
    #         outputs["open_order"] = enrich_open_order_with_actual_parent_plant(
    #             open_order_df=outputs["open_order"],
    #             logistics_df=outputs["logistics"],
    #         )
    #     else:
    #         # If logistics is not enabled, fallback:
    #         # use ordered_plant as plant so downstream workflow still works.
    #         fallback_open_order_df = outputs["open_order"].copy()
    #         fallback_open_order_df["plant"] = fallback_open_order_df["ordered_plant"]
    #         outputs["open_order"] = fallback_open_order_df

    #     save_if_required(
    #         outputs["open_order"],
    #         output_dir,
    #         open_order_section.get("output_file", "cleaned_open_order.xlsx"),
    #         save_outputs,
    #     )

    if should_run("allowable_qty"):
        section = get_section_config("allowable_qty")
        # print("\nReading file:")
        # print(input_path)
        # print("Section:", section_config.get("name"))
        # print(
        #      f"Reading file: {section_config['input_path']}"
        # )
        raw_df = read_excel_from_config(section)
        cleaned_df = clean_allowable_max_qty(raw_df, section)
        outputs["allowable_qty"] = cleaned_df
        save_if_required(
            cleaned_df,
            output_dir,
            section.get("output_file", "cleaned_allowable_max_qty.xlsx"),
            save_outputs,
        )

    if should_run("moq"):
        section = get_section_config("moq")
        print("\nMOQ section:")
        print(section)
        print("\nMOQ input path:")
        print(section["input_path"])
        raw_df = read_excel_from_config(section)
        
        cleaned_df = clean_moq_master(
            raw_df=raw_df,
            section_config=section,
        )

        outputs["moq"] = cleaned_df

        save_if_required(
            cleaned_df,
            output_dir,
            section.get(
                "output_file",
                "cleaned_moq_master.xlsx",
            ),
            save_outputs,
        )

    if should_run("zfmo_dealer_material"):
        section = get_section_config(
            "zfmo_dealer_material"
        )

        raw_df = read_excel_from_file_config(
            section
        )

        cleaned_df = (
            clean_zfmo_dealer_material_master(
                raw_df=raw_df,
                section_config=section,
            )
        )

        # invalid_zfmo_rows_df = (
        #     cleaned_df.attrs.get(
        #         "invalid_zfmo_mapping_rows",
        #         pd.DataFrame(),
        #     )
        # )

        # duplicate_zfmo_rows_df = (
        #     cleaned_df.attrs.get(
        #         "duplicate_zfmo_mapping_rows",
        #         pd.DataFrame(),
        #     )
        # )

        outputs[
            "zfmo_dealer_material"
        ] = cleaned_df

        if save_outputs:
            cleaned_df.to_excel(
                Path(output_dir)
                / section.get(
                    "output_file",
                    (
                        "cleaned_zfmo_"
                        "dealer_material.xlsx"
                    ),
                ),
                index=False,
                engine="openpyxl",
            )

            # if not invalid_zfmo_rows_df.empty:
            #     invalid_zfmo_rows_df.to_excel(
            #         Path(output_dir)
            #         / section.get(
            #             "invalid_rows_output_file",
            #             (
            #                 "invalid_zfmo_"
            #                 "mapping_rows.xlsx"
            #             ),
            #         ),
            #         index=False,
            #         engine="openpyxl",
            #     )

            # if not duplicate_zfmo_rows_df.empty:
            #     duplicate_zfmo_rows_df.to_excel(
            #         Path(output_dir)
            #         / section.get(
            #             "duplicate_rows_output_file",
            #             (
            #                 "duplicate_zfmo_"
            #                 "mapping_rows.xlsx"
            #             ),
            #         ),
            #         index=False,
            #         engine="openpyxl",
            #     )

    if should_run("norms"):
        section = get_section_config("norms")

        raw_df = read_excel_from_config(
            section
        )

        cleaned_df = clean_norms_master(
            raw_df=raw_df,
            section_config=section,
        )

        outputs["norms"] = cleaned_df

        save_if_required(
            cleaned_df,
            output_dir,
            section.get(
                "output_file",
                "cleaned_norms_master.xlsx",
            ),
            save_outputs,
        )
 
    # if should_run("git_type_2"):
    #     section = get_section_config["git_type_2"]

    #     raw_git_type_2 = (
    #         read_git_workbook_from_config(
    #             section_config=section,
    #         )
    #     )

    #     cleaned_git_type_2 = clean_git_type_2(
    #         raw_df=raw_git_type_2,
    #         section_config=section,
    #     )

    #     outputs["git_type_2"] = (
    #         cleaned_git_type_2
    #     )

    #     save_if_required(
    #         cleaned_git_type_2,
    #         output_dir,
    #         section.get(
    #             "output_file",
    #             "cleaned_git_type_2.xlsx",
    #         ),
    #         save_outputs,
    #     )

    # if should_run("git"):
    #     section = get_section_config["git"]
    #     raw_df = read_excel_from_config(section)
    #     cleaned_df = clean_git_quantity(raw_df, section)
    #     outputs["git"] = cleaned_df
    #     save_if_required(
    #         cleaned_df,
    #         output_dir,
    #         section.get("output_file", "cleaned_git_qty.xlsx"),
    #         save_outputs,
    #     )

    if should_run("rlt"):
        section = get_section_config("rlt")

        cleaned_df = build_rlt_master(
            config=config,
        )

        outputs["rlt"] = cleaned_df

        save_if_required(
            cleaned_df,
            output_dir,
            section.get("output_file", "cleaned_rlt_master.xlsx"),
            save_outputs,
        )

    if should_run("git_type_1"):
        section = get_section_config("git_type_1")

        raw_df = read_excel_from_config(
            section
        )

        cleaned_df = clean_git_type_1(
            raw_df=raw_df,
            rlt_master_df=outputs["rlt"],
            section_config=section,
        )

        missing_git_rlt_df = (
            cleaned_df.attrs.get(
                "missing_git_rlt_report",
                pd.DataFrame(),
            )
        )

        outputs["git_type_1"] = cleaned_df

        if not missing_git_rlt_df.empty:
            missing_git_rlt_output_path = (
                Path(output_dir)
                / section.get(
                    "missing_rlt_output_file",
                    "missing_git_rlt_combinations.xlsx",
                )
            )

            missing_git_rlt_df.to_excel(
                missing_git_rlt_output_path,
                index=False,
                engine="openpyxl",
            )

            print(
                "Saved missing GIT RLT report:",
                missing_git_rlt_output_path,
            )

        save_if_required(
            cleaned_df,
            output_dir,
            section.get(
                "output_file",
                "cleaned_git_type_1.xlsx",
            ),
            save_outputs,
        )

    if should_run("inventory_master"):
        if "ageing_inventory" not in outputs:
            raise ValueError(
                "inventory_master requires ageing_inventory output. "
                "Enable ageing_inventory or include it in --only."
            )

        section = config["inventory_master"]

        cleaned_df = build_inventory_master(
            inventory_df=outputs["ageing_inventory"],
            snapshot_timestamp=pipeline_config.get(
                "snapshot_timestamp",
                "2026-01-01 00:00:00+00:00",
            ),
        )

        outputs["inventory_master"] = cleaned_df

        save_if_required(
            cleaned_df,
            output_dir,
            section.get("output_file", "inventory_master.xlsx"),
            save_outputs,
        )

    return outputs