# %%
import pandas as pd

# %%
stock=pd.read_excel(r"/home/VECVNET/zzasom/jupyter/01_Developement_work_QA/Chakshu_G/order_orchestration/order_orchestration_mannual/Build/data/cleaned/inventory_master_og.xlsx",engine='openpyxl')
# %%
stock.duplicated().sum()

# %%
stock.head()

# %%
open_order = pd.read_excel(r"/home/VECVNET/zzasom/jupyter/01_Developement_work_QA/Chakshu_G/order_orchestration/order_orchestration_mannual/Input/modified_input_files/input_open_order_mapped.xlsx",engine='openpyxl')

# %%
open_order.columns

# %%
open_order["Plnt"] = open_order["Plnt"].astype(str)

# %%
open_order[
    (open_order["Plnt"] == "1155") &
    (open_order["Material   "] == "IA306245")
]

# %%
open_order.duplicated().sum()

# %%
open_order.head()

# %%
Pending_SO_orders = open_order[
    (open_order["SaTy"].isin(["ZACC", "ZROP"])) |
    (open_order["Customer"].astype(str).str.startswith("1XS")) |
    (open_order["EAN/UPC"].isin([11, 12, 13, 14, 15]))
]

# %%
Pending_SO_orders.head()

# %%
open_order.columns

# %%
alloc_qty = (
    Pending_SO_orders 
    .groupby(["Plnt", "Material   "], as_index=False)["Open Order Qty."]
    .sum()
    .rename(columns={"Open Order Qty.": "pending_so_quantity"})
)

# %%
alloc_qty.head()

# %%
inventory_master = stock

# %%
inventory_master.head()

# %%
inventory_master["location"] = inventory_master["location"].astype(str)
inventory_master["material_code"] = inventory_master["material_code"].astype(str)

alloc_qty["Plnt"] = alloc_qty["Plnt"].astype(str)
alloc_qty["Material   "] = alloc_qty["Material   "].astype(str)

alloc_qty = alloc_qty.rename(
    columns={"pending_so_quantity": "pending_so_quantity_new"}
)

inventory_master = inventory_master.merge(
    alloc_qty,
    left_on=["location", "material_code"],
    right_on=["Plnt", "Material   "],
    how="left"
)

inventory_master["pending_so_quantity"] = (
    inventory_master["pending_so_quantity_new"]
    .fillna(0)
)

inventory_master.drop(
    columns=[
        "Plnt",
        "Material   ",
        "pending_so_quantity_new"
    ],
    inplace=True,
    errors="ignore"
)
# inventory_master = inventory_master.merge(
#     alloc_qty,
#     left_on=["location", "material_code"],
#     right_on=["Plnt", "Material   "],
#     how="left"
# )

# inventory_master["allocated_quantity"] = (
#     inventory_master["allocated_quantity_y"]
#     .fillna(0)
# )

# inventory_master.drop(
#     columns=["Plnt", "Material   ", "allocated_quantity_y"],
#     inplace=True,
#     errors="ignore"
# )

# %%
inventory_master.head()

# %%
inventory_master.shape

# %%
inventory_master.dtypes

# %%
inventory_master['pending_so_quantity'].value_counts()

# %%
inventory_master.duplicated().sum()

# %%
inventory_master.to_excel(r"/home/VECVNET/zzasom/jupyter/01_Developement_work_QA/Chakshu_G/order_orchestration/order_orchestration_mannual/Build/data/cleaned/inventory_master.xlsx",index=False)
