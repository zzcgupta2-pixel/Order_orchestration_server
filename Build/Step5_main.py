# %%
from __future__ import annotations

import pandas as pd 
import numpy as np
import os 
import json
from datetime import datetime
# %%
# pip install openpyxl

execution_datetime = datetime(
    2026,
    11,
    13,
    9,
    0,
    0,
)

output_dir = "/home/VECVNET/zzasom/jupyter/01_Developement_work_QA/Chakshu_G/order_orchestration/order_orchestration_mannual/Output"

# %%
open_order_df = pd.read_excel(r"/home/VECVNET/zzasom/jupyter/01_Developement_work_QA/Chakshu_G/order_orchestration/order_orchestration_mannual/Build/data/cleaned/cleaned_open_order.xlsx",engine='openpyxl')
df_git_clean = pd.read_excel(r"/home/VECVNET/zzasom/jupyter/01_Developement_work_QA/Chakshu_G/order_orchestration/order_orchestration_mannual/Build/data/cleaned/cleaned_git_type_1.xlsx",engine='openpyxl')
df_clean_logistics = pd.read_excel(r"/home/VECVNET/zzasom/jupyter/01_Developement_work_QA/Chakshu_G/order_orchestration/order_orchestration_mannual/Build/data/cleaned/cleaned_logistics_wide.xlsx",engine='openpyxl')
inventory_master_df = pd.read_excel(r"/home/VECVNET/zzasom/jupyter/01_Developement_work_QA/Chakshu_G/order_orchestration/order_orchestration_mannual/Build/data/cleaned/inventory_master.xlsx",engine='openpyxl')
rlt_df = pd.read_excel(r"/home/VECVNET/zzasom/jupyter/01_Developement_work_QA/Chakshu_G/order_orchestration/order_orchestration_mannual/Build/data/cleaned/cleaned_rlt_master.xlsx",engine='openpyxl')
allowable_qty_df = pd.read_excel(r"/home/VECVNET/zzasom/jupyter/01_Developement_work_QA/Chakshu_G/order_orchestration/order_orchestration_mannual/Build/data/cleaned/cleaned_allowable_max_qty.xlsx",engine='openpyxl')
moq_df = pd.read_excel(r"/home/VECVNET/zzasom/jupyter/01_Developement_work_QA/Chakshu_G/order_orchestration/order_orchestration_mannual/Build/data/cleaned/cleaned_moq_master.xlsx",engine='openpyxl')
norms_df = pd.read_excel(r"/home/VECVNET/zzasom/jupyter/01_Developement_work_QA/Chakshu_G/order_orchestration/order_orchestration_mannual/Build/data/cleaned/cleaned_norms_master.xlsx",engine='openpyxl')
mad_df = pd.read_excel(r"/home/VECVNET/zzasom/jupyter/01_Developement_work_QA/Chakshu_G/order_orchestration/order_orchestration_mannual/Input/customer_plant_material_mad_final_02_11_2026.xlsx",engine='openpyxl')

# %%
import sys
from pathlib import Path

src_dir = Path.cwd() / "src"

if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

print(sys.path[0])

# %%
import scripts.run_unified_order_execution as unified_runner

# %%
open_order_df = (
    open_order_df[
        (
            open_order_df["order_category"]
            .astype(str)
            .str.strip()
            .str.upper()
            .eq("REPLENISHMENT")
        )
        & (
            pd.to_numeric(
                open_order_df["ean_upc"],
                errors="coerce",
            ).isin([16, 17])
        )
    ]
    .assign(
        raw_order_type_sort=lambda df: (
            df["raw_order_type"]
            .astype(str)
            .str.strip()
            .str.upper()
            .map(
                {
                    "ZFMO": 0,
                    "ZMSO": 1,
                }
            )
            .fillna(99)
        ),
        dealer_norms_sort=lambda df: (
            pd.to_numeric(
                df["dealer_norms"],
                errors="coerce",
            )
        ),
    )
    .sort_values(
        by=[
            "ean_upc",
            "raw_order_type_sort",
            "dealer_norms_sort",
        ],
        ascending=[
            True,   # Colour 16 before 17
            True,   # ZFMO before ZMSO
            False,  # Higher dealer norms first
        ],
        na_position="last",
    )
    .drop(
        columns=[
            "raw_order_type_sort",
            "dealer_norms_sort",
        ]
    )
    .reset_index(drop=True)
    .copy()
)

# %%
open_order_df["parent_plant"] = open_order_df["parent_plant"].astype("Int64")
open_order_df["dealer_norms"] = open_order_df["dealer_norms"].astype("Int64")

# %%
from datetime import datetime


decisions_df, candidates_df, movements_df = (
    unified_runner.run_unified_order_execution(
        final_df=open_order_df,
        inventory_master_df=inventory_master_df,
        allowable_qty_df=allowable_qty_df,
        git_df=df_git_clean,
        logistics_df=df_clean_logistics,
        rlt_df=rlt_df,
        mad_df=mad_df,
        moq_df=moq_df,
        norms_df=norms_df,
        output_dir=output_dir,

        # Historical execution date for testing.
        execution_datetime=execution_datetime
    )
)

# %%
import pandas as pd


def print_kpi_summary(
    decisions_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Business KPI summary for daily execution mail.

    Uses unique order line:
        order_id + line_id

    KPI Scope:
        Colour 16
        Colour 17
    """
    

    if decisions_df is None or decisions_df.empty:
        raise ValueError(
            "decisions_df is empty."
        )

    df = decisions_df.copy()

    # -----------------------------------------------------
    # Normalize
    # -----------------------------------------------------
    for column in [
        "order_id",
        "line_id",
        "decision",
    ]:
        df[column] = (
            df[column]
            .astype("string")
            .str.strip()
            .str.upper()
        )

    df["colour_code"] = pd.to_numeric(
        df["colour_code"],
        errors="coerce",
    ).astype("Int64")

    for column in [
        "source_allocated_quantity",
        "source_git_reserved_quantity",
        "remaining_quantity",
        "requested_quantity",
    ]:
        if column not in df.columns:
            df[column] = 0

        df[column] = pd.to_numeric(
            df[column],
            errors="coerce",
        ).fillna(0)

    # -----------------------------------------------------
    # Credit block flag
    # -----------------------------------------------------
    df["credit_blocked"] = (
        df["decision"]
        == "CREDIT_BLOCKED"
    )


    df["is_allocate_decision"] = (
                df["decision"]
                .eq("ALLOCATE")
            )
    
    # -----------------------------------------------------
    # Aggregate to unique line
    # -----------------------------------------------------
    line_df = (
        df.groupby(
            [
                "order_id",
                "line_id",
            ],
            as_index=False,
            dropna=False,

        )
        
        .agg(
            colour_code=(
                "colour_code",
                "first",
            ),
            credit_blocked=(
                "credit_blocked",
                "max",
            ),
            requested_quantity=(
                "requested_quantity",
                "max",
            ),
            physical_qty=(
                "source_allocated_quantity",
                "sum",
            ),
            git_qty=(
                "source_git_reserved_quantity",
                "sum",
            ),
            remaining_quantity=(
                "remaining_quantity",
                "min",
            ),
            allocated=(
                "is_allocate_decision",
                "max",
            ),
        )
    )

    # -----------------------------------------------------
    # Fulfilled quantity
    # -----------------------------------------------------
    line_df["fulfilled_qty"] = (
        line_df["physical_qty"]
        + line_df["git_qty"]
    )

    # line_df["allocation_done"] = (
    #     line_df["fulfilled_qty"]
    #     > 0
    # )

    line_df["allocation_done"] = (
        line_df["allocated"]
    )
    # -----------------------------------------------------
    # Color buckets
    # -----------------------------------------------------
    color16 = (
        line_df["colour_code"]
        == 16
    )

    color17 = (
        line_df["colour_code"]
        == 17
    )

    # -----------------------------------------------------
    # Counts
    # -----------------------------------------------------
    color16_lines = int(
        color16.sum()
    )

    color17_lines = int(
        color17.sum()
    )

    total_lines = (
        color16_lines
        + color17_lines
    )

    credit_block_lines = int(
        (
            line_df["credit_blocked"]
            & (
                color16
                | color17
            )
        ).sum()
    )

    executable_lines = (
        total_lines
        - credit_block_lines
    )

    # -----------------------------------------------------
    # Executable pools
    # -----------------------------------------------------
    color16_exec = (
        color16
        & ~line_df["credit_blocked"]
    )

    color17_exec = (
        color17
        & ~line_df["credit_blocked"]
    )

    color16_exec_count = int(
        color16_exec.sum()
    )

    color17_exec_count = int(
        color17_exec.sum()
    )

    # -----------------------------------------------------
    # Color 16
    # -----------------------------------------------------
    color16_done = int(
        (
            color16_exec
            & line_df["allocation_done"]
        ).sum()
    )

    color16_not_done = (
        color16_exec_count
        - color16_done
    )

    color16_done_pct = (
        color16_done
        / color16_exec_count
        if color16_exec_count
        else 0
    )

    color16_not_done_pct = (
        color16_not_done
        / color16_exec_count
        if color16_exec_count
        else 0
    )

    # -----------------------------------------------------
    # Color 17
    # -----------------------------------------------------
    color17_done = int(
        (
            color17_exec
            & line_df["allocation_done"]
        ).sum()
    )

    color17_not_done = (
        color17_exec_count
        - color17_done
    )

    color17_done_pct = (
        color17_done
        / color17_exec_count
        if color17_exec_count
        else 0
    )

    color17_not_done_pct = (
        color17_not_done
        / color17_exec_count
        if color17_exec_count
        else 0
    )

    # -----------------------------------------------------
    # Total execution
    # -----------------------------------------------------
    total_done = (
        color16_done
        + color17_done
    )

    execution_pct = (
        total_done
        / executable_lines
        if executable_lines
        else 0
    )

    # -----------------------------------------------------
    # First fill rate
    # -----------------------------------------------------
    total_requested_qty = (
        line_df.loc[
            color16 | color17,
            "requested_quantity",
        ]
        .sum()
    )

    total_fulfilled_qty = (
        line_df.loc[
            color16 | color17,
            "fulfilled_qty",
        ]
        .sum()
    )

    first_fill_rate = (
        total_fulfilled_qty
        / total_requested_qty
        if total_requested_qty
        else 0
    )

    # -----------------------------------------------------
    # Build mail table
    # -----------------------------------------------------
    summary = pd.DataFrame(
        [
            {
                "Color 16 Lines":
                    color16_lines,

                "Color 17 Lines":
                    color17_lines,

                "Total Lines":
                    total_lines,

                "Credit Block Lines":
                    credit_block_lines,

                "Net Total Lines for Execution":
                    executable_lines,

                "Color 16 Allocation Done":
                    (
                        f"{color16_done}/"
                        f"{color16_exec_count}"
                        f" - "
                        f"{color16_done_pct:.0%}"
                    ),

                "Color 16 Allocation Not Done":
                    (
                        f"{color16_not_done}/"
                        f"{color16_exec_count}"
                        f" - "
                        f"{color16_not_done_pct:.0%}"
                    ),

                "Color 17 Allocation Done":
                    (
                        f"{color17_done}/"
                        f"{color17_exec_count}"
                        f" - "
                        f"{color17_done_pct:.0%}"
                    ),

                "Color 17 Allocation Not Done":
                    (
                        f"{color17_not_done}/"
                        f"{color17_exec_count}"
                        f" - "
                        f"{color17_not_done_pct:.0%}"
                    ),

                "Net Total Execution %":
                    (
                        f"{total_done}/"
                        f"{executable_lines}"
                        f" - "
                        f"{execution_pct:.0%}"
                    ), 
            }
        ]
    )

    print()
    print("=" * 80)
    print("DAILY KPI SUMMARY")
    print("=" * 80)
    print(
        summary.to_string(
            index=False
        )
    )
    print()

    return summary

#%%
daily_kpi_df = print_kpi_summary(
    decisions_df
)

# %%
import pandas as pd

# decisions_df=pd.read_excel(r"/home/VECVNET/zzasom/jupyter/01_Developement_work_QA/Chakshu_G/order_orchestration/order_orchestration_mannual/Output/13Nov26/unified_execution_decisions.xlsx",engine='openpyxl')

# =========================================================
# 1. PREPARE DECISION DATAFRAME
# =========================================================
sap_df = decisions_df.copy()


# ---------------------------------------------------------
# Validate required columns
# ---------------------------------------------------------
required_columns = [
    "order_id",
    "order_category",
    "colour_code",
    "order_create_datetime",
    "material_code",
    "dealer_code",
    "parent_plant",
    "decision",
    "selected_source",
    "source_allocated_quantity",
    "source_git_reserved_quantity",
    "remaining_quantity",
    "expected_delivery",
]

missing_columns = [
    column
    for column in required_columns
    if column not in sap_df.columns
]

if missing_columns:
    raise ValueError(
        "Decision dataframe is missing required columns: "
        f"{missing_columns}. "
        f"Available columns: {sap_df.columns.tolist()}"
    )


# ---------------------------------------------------------
# Normalize text columns
# ---------------------------------------------------------
for column in [
    "order_id",
    "order_category",
    "decision",
    "material_code",
    "dealer_code",
    "parent_plant",
    "selected_source",
]:
    sap_df[column] = (
        sap_df[column]
        .astype("string")
        .str.strip()
        .str.upper()
    )


# ---------------------------------------------------------
# Remove trailing .0 from code fields
# ---------------------------------------------------------
for column in [
    "material_code",
    "dealer_code",
    "parent_plant",
    "selected_source",
]:
    sap_df[column] = (
        sap_df[column]
        .str.replace(
            r"\.0$",
            "",
            regex=True,
        )
    )


# ---------------------------------------------------------
# Normalize original colour code
# ---------------------------------------------------------
sap_df["colour_code"] = pd.to_numeric(
    sap_df["colour_code"],
    errors="coerce",
).astype("Int64")


# ---------------------------------------------------------
# Normalize quantity columns
# ---------------------------------------------------------
quantity_columns = [
    "source_allocated_quantity",
    "source_git_reserved_quantity",
    "remaining_quantity",
]

for column in quantity_columns:
    sap_df[column] = pd.to_numeric(
        sap_df[column],
        errors="coerce",
    ).fillna(0)


# =========================================================
# 2. VALIDATE ORDER_ID
# =========================================================
# Since line_id is not present, order_id must identify one
# material-dealer-colour-parent combination.
# =========================================================
order_id_validation = (
    sap_df.groupby(
        "order_id",
        dropna=False,
    )
    .agg(
        material_count=(
            "material_code",
            "nunique",
        ),
        dealer_count=(
            "dealer_code",
            "nunique",
        ),
        colour_count=(
            "colour_code",
            "nunique",
        ),
        parent_count=(
            "parent_plant",
            "nunique",
        ),
    )
)

invalid_order_ids = order_id_validation[
    (
        order_id_validation[
            "material_count"
        ] > 1
    )
    | (
        order_id_validation[
            "dealer_count"
        ] > 1
    )
    | (
        order_id_validation[
            "colour_count"
        ] > 1
    )
    | (
        order_id_validation[
            "parent_count"
        ] > 1
    )
]

if not invalid_order_ids.empty:
    raise ValueError(
        "Some order_id values represent multiple order lines. "
        "SAP output cannot safely group these rows by order_id.\n"
        f"{invalid_order_ids.head(20).to_string()}"
    )


# =========================================================
# 3. PREPARE DATE AND TIME
# =========================================================
order_datetime = pd.to_datetime(
    sap_df["order_create_datetime"],
    errors="coerce",
)

sap_df["DATE"] = (
    order_datetime.dt.strftime("%Y%m%d")
)

sap_df["TIME"] = (
    order_datetime.dt.strftime("%H%M%S")
)



#delivery date 
# delivery_date = pd.to_datetime(
#     sap_df["expected_delivery"],
#     errors="coerce",
# )
delivery_date = pd.to_datetime(
    sap_df["expected_delivery"]
        .astype(str)
        .str.replace(
            r"\+.*$",
            "",
            regex=True,
        ),
    errors="coerce",
)

sap_df["expected_delivery"] = (
    delivery_date.dt.strftime("%Y%m%d")
)

 
# =========================================================
# 4. HELPER FUNCTIONS
# =========================================================
def get_allocation_colour_code(
    original_colour,
) -> int | None:
    """
    SAP colour for physical or GIT allocation.

    Original 16 -> SAP 1
    Original 17 -> SAP 2
    """

    if pd.isna(original_colour):
        return None

    colour = int(original_colour)

    if colour == 16:
        return 1

    if colour == 17:
        return 2

    return None


def get_remaining_colour_code(
    original_colour,
    total_allocated_quantity,
) -> int | None:
    """
    SAP colour for remaining quantity.

    Original colour 16:
        No allocation      -> SAP colour 6
        Partial allocation -> SAP colour 7

    Original colour 17:
        No allocation      -> SAP colour 7
        Partial allocation -> SAP colour 8
    """

    if pd.isna(original_colour):
        return None

    colour = int(original_colour)

    allocated_quantity = pd.to_numeric(
        total_allocated_quantity,
        errors="coerce",
    )

    if pd.isna(allocated_quantity):
        allocated_quantity = 0

    partial_allocation_happened = (
        allocated_quantity > 0
    )

    if colour == 16:
        if partial_allocation_happened:
            return 7

        return 6

    if colour == 17:
        if partial_allocation_happened:
            return 8

        return 7

    return None


def clean_code(
    value,
) -> str | None:
    """
    Normalizes plant, dealer, and material codes.
    """

    if pd.isna(value):
        return None

    cleaned_value = (
        str(value)
        .strip()
        .upper()
    )

    if cleaned_value.endswith(".0"):
        cleaned_value = cleaned_value[:-2]

    if cleaned_value in {
        "",
        "NAN",
        "NONE",
        "NULL",
        "<NA>",
        "NAT",
    }:
        return None

    return cleaned_value


def format_sap_quantity(
    value,
):
    """
    Returns an integer for whole-number quantities.
    Otherwise returns the decimal value.
    """

    numeric_value = pd.to_numeric(
        value,
        errors="coerce",
    )

    if pd.isna(numeric_value):
        return 0

    numeric_value = float(
        numeric_value
    )

    if numeric_value.is_integer():
        return int(
            numeric_value
        )

    return numeric_value


# =========================================================
# 5. CREATE PHYSICAL AND GIT ALLOCATION ROWS
# =========================================================
sap_output_rows: list[dict] = []


for _, row in sap_df.iterrows():
    decision = str(
        row["decision"]
    ).strip().upper()

    allocation_colour = (
        get_allocation_colour_code(
            row["colour_code"]
        )
    )

    # Only process supported colours 16 and 17.
    if allocation_colour is None:
        continue

    # -----------------------------------------------------
    # Physical allocation row
    # -----------------------------------------------------
    physical_quantity = pd.to_numeric(
        row["source_allocated_quantity"],
        errors="coerce",
    )

    if (
        pd.notna(physical_quantity)
        and physical_quantity > 0
    ):
        sap_output_rows.append(
            {
                # Internal key. Removed from final SAP output.
                "order_id": row["order_id"],

                "From Location": clean_code(
                    row["selected_source"]
                ),

                "Material Code": clean_code(
                    row["material_code"]
                ),

                "To Location": clean_code(
                    row["dealer_code"]
                ),

                "Quantity": format_sap_quantity(
                    physical_quantity
                ),

                # Original 16 -> 1
                # Original 17 -> 2
                "Colour Code": allocation_colour,

                "Order Type": (
                    row["order_category"]
                ),

                "DATE": row["DATE"],

                "TIME": row["TIME"],

                "GIT Flag": 0,

                "expected_delivery": row["expected_delivery"],

                # Physical allocation appears first.
                "_row_type_order": 1,
            }
        )

    # -----------------------------------------------------
    # GIT reservation row
    # -----------------------------------------------------
    git_quantity = pd.to_numeric(
        row["source_git_reserved_quantity"],
        errors="coerce",
    )

    if (
        decision
        == "DEFERRED_GIT_ALLOCATION"
        and pd.notna(git_quantity)
        and git_quantity > 0
    ):
        sap_output_rows.append(
            {
                # Internal key. Removed from final SAP output.
                "order_id": row["order_id"],

                # GIT allocation is executed through the
                # order's parent plant.
                "From Location": clean_code(
                    row["parent_plant"]
                ),

                "Material Code": clean_code(
                    row["material_code"]
                ),

                "To Location": clean_code(
                    row["dealer_code"]
                ),

                "Quantity": format_sap_quantity(
                    git_quantity
                ),

                # GIT is treated as allocated quantity.
                # Original 16 -> 1
                # Original 17 -> 2
                "Colour Code": allocation_colour,

                "Order Type": (
                    row["order_category"]
                ),

                "DATE": row["DATE"],

                "TIME": row["TIME"],

                "GIT Flag": 1,
                "expected_delivery": row["expected_delivery"],

                # GIT appears after physical allocation.
                "_row_type_order": 2,
            }
        )


# =========================================================
# 6. CREATE ORDER-LEVEL SUMMARY
# =========================================================
# The decision dataframe can contain multiple source rows for
# one order. Aggregate physical and GIT quantities by order_id.
#
# remaining_quantity is repeated on each source row, so use
# min instead of sum.
# =========================================================
sort_columns = [
    "order_id",
]

if "allocation_sequence" in sap_df.columns:
    sort_columns.append(
        "allocation_sequence"
    )


order_level_rows = (
    sap_df.sort_values(
        by=sort_columns,
        na_position="last",
    )
    .groupby(
        "order_id",
        as_index=False,
        dropna=False,
    )
    .agg(
        order_category=(
            "order_category",
            "first",
        ),

        colour_code=(
            "colour_code",
            "first",
        ),

        material_code=(
            "material_code",
            "first",
        ),

        dealer_code=(
            "dealer_code",
            "first",
        ),

        parent_plant=(
            "parent_plant",
            "first",
        ),

        DATE=(
            "DATE",
            "first",
        ),

        TIME=(
            "TIME",
            "first",
        ),

        # Sum all physical-source quantities.
        physical_allocated_quantity=(
            "source_allocated_quantity",
            "sum",
        ),

        # Sum all GIT reservation quantities.
        git_reserved_quantity=(
            "source_git_reserved_quantity",
            "sum",
        ),

        # Repeated on each decision row.
        remaining_quantity=(
            "remaining_quantity",
            "min",
        ),

        expected_delivery=("expected_delivery", "first")
    )
)


# ---------------------------------------------------------
# Calculate total allocated quantity per order
# ---------------------------------------------------------
order_level_rows[
    "total_allocated_quantity"
] = (
    order_level_rows[
        "physical_allocated_quantity"
    ]
    + order_level_rows[
        "git_reserved_quantity"
    ]
)


# =========================================================
# 7. CREATE ONE REMAINING ROW PER ORDER_ID
# =========================================================
for _, row in order_level_rows.iterrows():
    remaining_quantity = pd.to_numeric(
        row["remaining_quantity"],
        errors="coerce",
    )

    if (
        pd.isna(remaining_quantity)
        or remaining_quantity <= 0
    ):
        continue

    remaining_colour = (
        get_remaining_colour_code(
            original_colour=(
                row["colour_code"]
            ),
            total_allocated_quantity=(
                row[
                    "total_allocated_quantity"
                ]
            ),
        )
    )

    if remaining_colour is None:
        continue

    sap_output_rows.append(
        {
            # Internal key. Removed from final SAP output.
            "order_id": row["order_id"],

            # Remaining quantity stays at the parent plant.
            "From Location": clean_code(
                row["parent_plant"]
            ),

            "Material Code": clean_code(
                row["material_code"]
            ),

            "To Location": clean_code(
                row["dealer_code"]
            ),

            "Quantity": format_sap_quantity(
                remaining_quantity
            ),

            # Colour logic:
            #
            # Original 16:
            #   no allocation -> 6
            #   partial       -> 7
            #
            # Original 17:
            #   no allocation -> 7
            #   partial       -> 8
            "Colour Code": remaining_colour,

            "Order Type": (
                row["order_category"]
            ),

            "DATE": row["DATE"],

            "TIME": row["TIME"],

            "GIT Flag": 0,
            "expected_delivery": row["expected_delivery"],

            # Remaining row appears last.
            "_row_type_order": 3,
        }
    )


# =========================================================
# 8. CREATE FINAL SAP OUTPUT
# =========================================================
sap_output_with_keys = pd.DataFrame(
    sap_output_rows
)

final_columns = [
    "From Location",
    "Material Code",
    "To Location",
    "Quantity",
    "Colour Code",
    "Order Type",
    "DATE",
    "TIME",
    "GIT Flag",
    "expected_delivery"
]


if sap_output_with_keys.empty:
    sap_output = pd.DataFrame(
        columns=final_columns
    )

else:
    # Physical rows first, GIT rows second,
    # remaining quantity rows last.
    sap_output_with_keys = (
        sap_output_with_keys.sort_values(
            by=[
                "order_id",
                "_row_type_order",
                "From Location",
            ],
            ascending=[
                True,
                True,
                True,
            ],
            na_position="last",
        )
        .reset_index(drop=True)
    )

    sap_output = (
        sap_output_with_keys[
            final_columns
        ]
        .copy()
    )


# =========================================================
# 9. FINAL DATA-TYPE CLEANUP
# =========================================================
sap_output["Quantity"] = pd.to_numeric(
    sap_output["Quantity"],
    errors="coerce",
).fillna(0)


sap_output["Colour Code"] = pd.to_numeric(
    sap_output["Colour Code"],
    errors="coerce",
).astype("Int64")


sap_output["GIT Flag"] = pd.to_numeric(
    sap_output["GIT Flag"],
    errors="coerce",
).fillna(0).astype("int64")


# Keep DATE and TIME as strings so leading zeros are retained.
sap_output["DATE"] = (
    sap_output["DATE"]
    .astype("string")
)

sap_output["TIME"] = (
    sap_output["TIME"]
    .astype("string")
    .str.zfill(6)
)

sap_output["expected_delivery"] = (
    sap_output["expected_delivery"]
    .astype("string")
)

# =========================================================
# 10. VALIDATE FINAL SAP OUTPUT
# =========================================================
invalid_colour_rows = sap_output[
    sap_output["Colour Code"].isna()
]

if not invalid_colour_rows.empty:
    raise ValueError(
        "SAP output contains invalid colour codes.\n"
        f"{invalid_colour_rows.head(20).to_string(index=False)}"
    )


invalid_quantity_rows = sap_output[
    sap_output["Quantity"] <= 0
]

if not invalid_quantity_rows.empty:
    raise ValueError(
        "SAP output contains zero or negative quantities.\n"
        f"{invalid_quantity_rows.head(20).to_string(index=False)}"
    )


invalid_from_location_rows = sap_output[
    sap_output["From Location"].isna()
    | sap_output[
        "From Location"
    ].astype("string").str.strip().eq("")
]

if not invalid_from_location_rows.empty:
    raise ValueError(
        "SAP output contains blank From Location values.\n"
        f"{invalid_from_location_rows.head(20).to_string(index=False)}"
    )


# =========================================================
# 11. OPTIONAL RECONCILIATION VALIDATION
# =========================================================
# For every order:
#
# physical allocation
# + GIT reservation
# + remaining quantity
# should equal original requested quantity.
# =========================================================
if (
    "original_requested_quantity"
    in sap_df.columns
):
    sap_df[
        "original_requested_quantity"
    ] = pd.to_numeric(
        sap_df[
            "original_requested_quantity"
        ],
        errors="coerce",
    ).fillna(0)

    requested_quantity_by_order = (
        sap_df.groupby(
            "order_id",
            as_index=False,
            dropna=False,
        )
        .agg(
            original_requested_quantity=(
                "original_requested_quantity",
                "max",
            )
        )
    )

    reconciliation_df = (
        order_level_rows.merge(
            requested_quantity_by_order,
            on="order_id",
            how="left",
            validate="one_to_one",
        )
    )

    reconciliation_df[
        "reconciled_quantity"
    ] = (
        reconciliation_df[
            "physical_allocated_quantity"
        ]
        + reconciliation_df[
            "git_reserved_quantity"
        ]
        + reconciliation_df[
            "remaining_quantity"
        ]
    )

    reconciliation_df[
        "quantity_difference"
    ] = (
        reconciliation_df[
            "original_requested_quantity"
        ]
        - reconciliation_df[
            "reconciled_quantity"
        ]
    )

    invalid_reconciliation = (
        reconciliation_df[
            reconciliation_df[
                "quantity_difference"
            ].abs() > 0.000001
        ]
    )

    print(
        "Orders failing quantity reconciliation:",
        len(invalid_reconciliation),
    )

    if not invalid_reconciliation.empty:
        print(
            invalid_reconciliation.head(20).to_string()
        )


# =========================================================
# 12. PREVIEW FINAL OUTPUT
# =========================================================
print()
print(
    "Input decision rows:",
    len(sap_df),
)

print(
    "Unique order IDs:",
    sap_df["order_id"].nunique(),
)

print(
    "SAP output rows:",
    len(sap_output),
)

print()
print("SAP output colour distribution:")

print(
    sap_output[
        "Colour Code"
    ]
    .value_counts(
        dropna=False
    )
    .sort_index()
)

print()
print(
    sap_output.head(20).to_string()
)

# %%
current_dir = os.getcwd()
#current_dir = "/home/VECVNET/zzasom/jupyter/01_Development_work/Black_Forecasting/Deployment/Build/"
cred_path = os.path.join(current_dir, "OO_manual.json")
#cred_path = "/home/VECVNET/zzasom/jupyter/01_Development_work/Black_Forecasting/Deployment/Build/cred.json"

# Load the configuration
with open(cred_path, "r") as config_file:
    config = json.load(config_file)

VF_rationed_path = config.get("VF_rationed", "")

# %%
ration_qty = pd.read_csv(VF_rationed_path)

zfmo_mapping = pd.read_excel(r"/home/VECVNET/zzasom/jupyter/01_Developement_work_QA/Chakshu_G/order_orchestration/order_orchestration_mannual/Build/data/cleaned/cleaned_zfmo_dealer_material.xlsx",engine='openpyxl')

import pandas as pd

rationed_qty_mapped_df = ration_qty.copy()
zfmo_mapping_df = zfmo_mapping.copy()


def normalize_code(series: pd.Series) -> pd.Series:
    return (
        series
        .astype("string")
        .str.strip()
        .str.upper()
        .str.replace(r"\.0$", "", regex=True)
        .str.replace(r"\s+", "", regex=True)
    )


# Normalize rationed quantity matching fields.
rationed_qty_mapped_df["To Location"] = normalize_code(
    rationed_qty_mapped_df["To Location"]
)

rationed_qty_mapped_df["Material Code"] = normalize_code(
    rationed_qty_mapped_df["Material Code"]
)

rationed_qty_mapped_df["Order Type"] = normalize_code(
    rationed_qty_mapped_df["Order Type"]
)

# Normalize ZFMO master matching fields.
zfmo_mapping_df["dealer_code"] = normalize_code(
    zfmo_mapping_df["dealer_code"]
)

zfmo_mapping_df["material_code"] = normalize_code(
    zfmo_mapping_df["material_code"]
)

# Create unique ZFMO dealer-material keys.
zfmo_keys = pd.MultiIndex.from_frame(
    zfmo_mapping_df[
        ["dealer_code", "material_code"]
    ].drop_duplicates()
)

# Find dealer-material matches.
zfmo_match_mask = pd.MultiIndex.from_frame(
    rationed_qty_mapped_df[
        ["To Location", "Material Code"]
    ]
).isin(zfmo_keys)

# Store the final override mask BEFORE changing Order Type.
zfmo_override_mask = (
    zfmo_match_mask
    & rationed_qty_mapped_df["Order Type"].eq("ZMSO")
)

print(
    "Dealer-material matches found:",
    int(zfmo_match_mask.sum()),
)

print(
    "ZMSO rows to change to ZFMO:",
    int(zfmo_override_mask.sum()),
)

# Apply the override.
rationed_qty_mapped_df.loc[
    zfmo_override_mask,
    "Order Type",
] = "ZFMO"

ration_qty = rationed_qty_mapped_df.copy()

print(
    "Rows changed from ZMSO to ZFMO:",
    int(zfmo_override_mask.sum()),
)

# %%
import pandas as pd


# ---------------------------------------------------------
# 1. Create working copies
# ---------------------------------------------------------
generated_sap_df = sap_output.copy()
original_sap_df = ration_qty.copy()


# ---------------------------------------------------------
# 2. Standardize column names
# ---------------------------------------------------------
generated_sap_df.columns = (
    generated_sap_df.columns
    .astype(str)
    .str.strip()
)

original_sap_df.columns = (
    original_sap_df.columns
    .astype(str)
    .str.strip()
)


# ---------------------------------------------------------
# 3. Validate required original SAP columns
# ---------------------------------------------------------
required_sap_columns = [
    "From Location",
    "Material Code",
    "To Location",
    "Quantity",
    "Colour Code",
    "Order Type",
    "DATE",
    "TIME",
]

missing_original_columns = [
    column
    for column in required_sap_columns
    if column not in original_sap_df.columns
]

if missing_original_columns:
    raise ValueError(
        "Original SAP dataframe is missing columns: "
        f"{missing_original_columns}. "
        f"Available columns: "
        f"{original_sap_df.columns.tolist()}"
    )


# ---------------------------------------------------------
# 4. Convert original colour code for filtering
# ---------------------------------------------------------
original_colour_numeric = pd.to_numeric(
    original_sap_df["Colour Code"],
    errors="coerce",
)


# ---------------------------------------------------------
# 5. Select original colour 8, 9, and 10 rows
# ---------------------------------------------------------
original_8_9_10_df = (
    original_sap_df.loc[
        original_colour_numeric.isin(
            [8, 9, 10]
        ),
        required_sap_columns,
    ]
    .copy()
)


# ---------------------------------------------------------
# 6. Add GIT Flag to original rows
# ---------------------------------------------------------
original_8_9_10_df["GIT Flag"] = 0

if "expected_delivery" not in original_8_9_10_df.columns:
    original_8_9_10_df["expected_delivery"] = pd.NA
    
# ---------------------------------------------------------
# 7. Match the generated SAP column order
# ---------------------------------------------------------
final_sap_columns = [
    "From Location",
    "Material Code",
    "To Location",
    "Quantity",
    "Colour Code",
    "Order Type",
    "DATE",
    "TIME",
    "GIT Flag",
    "expected_delivery"
]

# Validate generated SAP columns.
missing_generated_columns = [
    column
    for column in final_sap_columns
    if column not in generated_sap_df.columns
]

if missing_generated_columns:
    raise ValueError(
        "Generated SAP dataframe is missing columns: "
        f"{missing_generated_columns}. "
        f"Available columns: "
        f"{generated_sap_df.columns.tolist()}"
    )

generated_sap_df = generated_sap_df[
    final_sap_columns
].copy()

original_8_9_10_df = original_8_9_10_df[
    final_sap_columns
].copy()


# ---------------------------------------------------------
# 8. Normalize important data types
# ---------------------------------------------------------
for current_df in [
    generated_sap_df,
    original_8_9_10_df,
]:
    current_df["Colour Code"] = pd.to_numeric(
        current_df["Colour Code"],
        errors="coerce",
    ).astype("Int64")

    current_df["Quantity"] = pd.to_numeric(
        current_df["Quantity"],
        errors="coerce",
    )

    current_df["GIT Flag"] = pd.to_numeric(
        current_df["GIT Flag"],
        errors="coerce",
    ).fillna(0).astype("int64")

    # Preserve leading zeros in date and time.
    current_df["DATE"] = (
        current_df["DATE"]
        .astype("string")
        .str.strip()
        .str.replace(
            r"\.0$",
            "",
            regex=True,
        )
        .str.zfill(8)
    )

    current_df["TIME"] = (
        current_df["TIME"]
        .astype("string")
        .str.strip()
        .str.replace(
            r"\.0$",
            "",
            regex=True,
        )
        .str.zfill(6)
    )

    # Clean location and code columns.
    for column in [
        "From Location",
        "Material Code",
        "To Location",
        "Order Type",
    ]:
        current_df[column] = (
            current_df[column]
            .astype("string")
            .str.strip()
            .str.upper()
            .str.replace(
                r"\.0$",
                "",
                regex=True,
            )
        )


# ---------------------------------------------------------
# 9. Append original 8, 9, and 10 rows
# ---------------------------------------------------------
final_sap_output = pd.concat(
    [
        generated_sap_df,
        original_8_9_10_df,
    ],
    ignore_index=True,
    sort=False,
)


# ---------------------------------------------------------
# 10. Keep final column order
# ---------------------------------------------------------
final_sap_output = final_sap_output[
    final_sap_columns
].copy()


# ---------------------------------------------------------
# 11. Print validation summary
# ---------------------------------------------------------
print(
    "Generated SAP rows:",
    len(generated_sap_df),
)

print(
    "Original colour 8, 9, 10 rows appended:",
    len(original_8_9_10_df),
)

print(
    "Final SAP output rows:",
    len(final_sap_output),
)

print()
print("Final colour-code distribution:")

print(
    final_sap_output["Colour Code"]
    .value_counts(
        dropna=False
    )
    .sort_index()
)

print()
print(
    final_sap_output.head(20).to_string()
)
print(final_sap_output.columns.tolist()) 
#%%
# final_sap_output.to_csv(r"C:\Order Orchestration code\order_orchestration\data\outputs_25Nov26\order_orchestration_25112026.csv", index=False)
from pathlib import Path
from datetime import datetime

execution_dt = (
    execution_datetime
    if execution_datetime is not None
    else datetime.now()
)

# Folder name
run_folder_name = execution_dt.strftime("%d%b%y")      # 13Nov26

# File name
file_date = execution_dt.strftime("%d%m%Y")            # 13112026

output_root = Path(output_dir)

output_folder = output_root / run_folder_name

output_folder.mkdir(
    parents=True,
    exist_ok=True,
)

sap_output_file = (
    output_folder
    / f"order_orchestration_{file_date}.csv"
)

final_sap_output.to_csv(
    sap_output_file,
    index=False,
)

print(f"Saved SAP output: {sap_output_file}")
