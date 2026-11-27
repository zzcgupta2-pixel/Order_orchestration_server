# %% [markdown]
# vector open order combine

# %%
import pandas as pd 
import os
import json

# %%
current_dir = os.getcwd()
#current_dir = "/home/VECVNET/zzasom/jupyter/01_Development_work/Black_Forecasting/Deployment/Build/"
cred_path = os.path.join(current_dir, "OO_manual.json")
#cred_path = "/home/VECVNET/zzasom/jupyter/01_Development_work/Black_Forecasting/Deployment/Build/cred.json"

# Load the configuration
with open(cred_path, "r") as config_file:
    config = json.load(config_file)

VF_rationed_path = config.get("VF_rationed", "")
VF_openso_path = config.get("VF_openso", "")
credit_block_path = config.get("credit_block", "")
# zfmo_path = config.get("zfmo", "")

# %%
# Read the actual Excel files into pandas DataFrames.
open_order_1 = pd.read_csv(VF_rationed_path)
open_order_2 = pd.read_csv(VF_openso_path)
credit = pd.read_excel(credit_block_path)
# zfmo_mapping_df = pd.read_excel(zfmo_path)
 
# import os
# import sys
# import subprocess
# from pathlib import Path

# build_dir = Path(__file__).resolve().parent
# src_dir = build_dir / "src"

# env = os.environ.copy()
# existing_pythonpath = env.get("PYTHONPATH", "")

# env["PYTHONPATH"] = (
#     str(src_dir)
#     if not existing_pythonpath
#     else str(src_dir) + os.pathsep + existing_pythonpath
# )

# subprocess.run(
#     [
#         sys.executable,
#         str(build_dir / "scripts" / "run_data_cleaning.py"),
#         "--config",
#         str(build_dir / "config" / "data_cleaning.yaml"),
#         "--only",
#         "zfmo_dealer_material",
#     ],
#     cwd=str(build_dir),
#     env=env,
#     check=True,
# )
from pathlib import Path
import sys

build_dir = Path(__file__).resolve().parent
src_dir = build_dir / "src"

if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from order_orchestration.data.cleaning_pipeline import (
    clean_zfmo_dealer_material_master,
)
# %%

zfmo_path = config.get(
    "zfmo_dealer_material",
    ""
)

if not zfmo_path:
    raise ValueError(
        "zfmo_dealer_material path missing in OO_manual.json"
    )

zfmo_section = {
    "column_mapping": {
        "scode": "dealer_code",
        "material_code": "material_code",
    }
}

raw_zfmo_df = pd.read_excel(
    zfmo_path,
    engine="openpyxl",
)

zfmo_mapping = (
    clean_zfmo_dealer_material_master(
        raw_df=raw_zfmo_df,
        section_config=zfmo_section,
    )
)

print(
    "ZFMO rows after cleaning:",
    len(zfmo_mapping)
)

# # %%
# open_order_1  = pd.read_csv(r"C:\Order Orchestration code\order_orchestration\Regular_original_files\16_11_2026\YVF_RATION_QTY.csv")


# # %%
# open_order_2 = pd.read_csv(r"C:\Order Orchestration code\order_orchestration\Regular_original_files\16_11_2026\ECC_OPENSO_20261116.CSV")

# # %%
# credit = pd.read_excel(r"C:\Order Orchestration code\order_orchestration\Regular_original_files\16_11_2026\credit block 16112026.xlsx",engine='openpyxl')

# # %%
# zfmo_mapping = pd.read_excel(r"C:\Order Orchestration code\order_orchestration\data\cleaned\cleaned_zfmo_dealer_material.xlsx",engine='openpyxl')

# %%
# zfmo_mapping.columns

# %%
import pandas as pd

rationed_qty_mapped_df = open_order_1.copy()
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

open_order_1 = rationed_qty_mapped_df.copy()

print(
    "Rows changed from ZMSO to ZFMO:",
    int(zfmo_override_mask.sum()),
)

# %%
# rationed_qty_mapped_df.to_csv(
#     r"C:\Order Orchestration code\order_orchestration\data\cleaned\temp_rationed_qty_mapped.csv",
#     index=False,
# )

# %%
open_order_1.head(5)

# %%
open_order_1.columns

# %%
open_order_1.rename(columns = {'From Location':'Plnt','Material Code':"Material   ","To Location":"Customer","Quantity":"Open Order Qty.","Colour Code":"EAN/UPC","Order Type":"SaTy","DATE":"Date      ","TIME":"Time    "}, inplace = True)

# %%
open_order_1.columns

# %%
open_order_2.columns

# %%
open_order_2.rename(columns = {'Customer':'Customer','Order type':'SaTy','Create Date':'Doc. Date ','Creating Time.': 'Time    .1','Material':'Material   ','Order Qty.':'Open Order Qty.','Plant':'Plnt'}, inplace = True)

# %%
open_order_2.columns

# %%
open_order_2 = open_order_2[['Customer','SaTy','Doc. Date ','Time    .1','Material   ','Open Order Qty.','Plnt']]

# %%
open_order_1.columns

# %%
open_order_2.columns

# %%
# Date
open_order_1["Date      "] = pd.to_datetime(
    open_order_1["Date      "].astype(str),
    format="%Y%m%d",
    errors="coerce"
)

# Time
open_order_1["Time    "] = (
    open_order_1["Time    "]
    .astype(str)
    .str.zfill(6)
    .str.replace(r"(\d{2})(\d{2})(\d{2})", r"\1:\2:\3", regex=True)
)

# EAN/UPC: 1-10 -> 11-20
mask = open_order_1["EAN/UPC"].between(1, 10)
open_order_1.loc[mask, "EAN/UPC"] = open_order_1.loc[mask, "EAN/UPC"] + 10

# %%
open_order_1['Doc. Date '] = open_order_1['Date      ']
open_order_1['Time    .1'] = open_order_1['Time    ']

# %%
open_order_1.columns

# %%
open_order_2.columns

# %%
open_order_2.head()

# %%
# Date
open_order_2["Doc. Date "] = pd.to_datetime(
    open_order_2["Doc. Date "].astype(str),
    format="%Y%m%d",
    errors="coerce"
)

# Time
open_order_2["Time    .1"] = (
    open_order_2["Time    .1"]
    .astype(str)
    .str.zfill(6)
    .str.replace(r"(\d{2})(\d{2})(\d{2})", r"\1:\2:\3", regex=True)
)

# %%
open_order_2['EAN/UPC'] = 1
open_order_2['Date      '] = open_order_1['Date      ']
open_order_2['Time    '] = open_order_1['Time    ']

# %%
open_order_2.head(5)

# %%
open_order = pd.concat([open_order_2, open_order_1], ignore_index=True)

# %%
open_order['Cust Type']='DOMESTIC'
open_order['Material Description                    ']='ABCD'
open_order['Name 1                        ']='XYZ'
open_order['CustomerStatus'] = 0

# %%
credit.head()

# %%
credit.columns

# %%
credit = credit[['CP Code']]

# %%
credit.head()

# %%
# Create set of credit block dealers
credit_block_customers = set(
    credit["CP Code"].astype(str).str.strip()
)

# Flag in open order file
open_order["CustomerStatus"] = (
    open_order["Customer"]
    .astype(str)
    .str.strip()
    .isin(credit_block_customers)
    .astype(int)
)

# %%
open_order.head(10)

# %%
open_order.dtypes

# %%
open_order.to_excel(r"/home/VECVNET/zzasom/jupyter/01_Developement_work_QA/Chakshu_G/order_orchestration/order_orchestration_mannual/Input/modified_input_files/input_open_order_mapped.xlsx", index=False)
 


