# %%
import pandas as pd

# %%
import os
import pandas as pd
import numpy as np
import json

# %%
current_dir = os.getcwd()
#current_dir = "/home/VECVNET/zzasom/jupyter/01_Development_work/Black_Forecasting/Deployment/Build/"
cred_path = os.path.join(current_dir, "OO_manual.json")
#cred_path = "/home/VECVNET/zzasom/jupyter/01_Development_work/Black_Forecasting/Deployment/Build/cred.json"

# Load the configuration
with open(cred_path, "r") as config_file:
    config = json.load(config_file)
 

# %%
 
# zfmo_mapping_df = pd.read_excel(zfmo_path)
# Define the base directory path
dir_path = r"/home/VECVNET/zzasom/jupyter/01_Developement_work_QA/Chakshu_G/order_orchestration/order_orchestration_mannual/Input/Ageing"
out_dir_path=r"/home/VECVNET/zzasom/jupyter/01_Developement_work_QA/Chakshu_G/order_orchestration/order_orchestration_mannual/Input/modified_input_files"
 
# Explicit list of files from your screenshot
file_list = [
    "1161.12.11.2026.xls",
    "1159.12.11.2026.xls",
    "1158.12.11.2026.xls",
    "1157.12.11.2026.xls",
    "1156.12.11.2026.xls",
    "1155.12.11.2026.xls",
    "1153.12.11.2026.xls",
    "1152.12.11.2026.xls",
    "1141.12.11.2026.xls",
    "1110.12.11.2026.xls"
]

# file_list = [
#     "1161.15.10.26.xls",
#     "1159.15.10.26.xls",
#     "1158.15.10.26.xls",
#     "1157.15.10.26.xls",
#     "1156.15.10.26.xls",
#     "1155.15.10.26.xls",
#     "1153.15.10.26.xls",
#     "1152.15.10.26.xls",
#     "1141.15.10.26.xls",
#     "1110.15.10.26.xls"
# ]

df_list = []

print("Starting strict data cleaning and extraction layout alignment...")

# Helper function to handle bad SAP numeric strings (e.g., "1,250.00-", " - ")
def clean_sap_numeric(val):
    val_str = str(val).strip()
    if not val_str or val_str in ['-', '', 'nan', 'NaN']:
        return 0.0
    
    # Remove thousand separators
    val_str = val_str.replace(',', '')
    
    # Handle trailing negative sign (SAP standard)
    if val_str.endswith('-'):
        val_str = '-' + val_str[:-1]
        
    try:
        return float(val_str)
    except ValueError:
        return np.nan

for file_name in file_list:
    full_path = os.path.join(dir_path, file_name)
    
    if os.path.exists(full_path):
        try:
            # Step 1: Open file with universal newlines handling to find header row location
            with open(full_path, 'r', encoding='utf-16', errors='ignore') as f:
                lines = f.readlines()
            
            # Find the true header line index (case-insensitive checking)
            header_idx = 0
            for idx, line in enumerate(lines):
                lower_line = line.lower()
                if 'plant' in lower_line or 'material' in lower_line or 'stoc' in lower_line:
                    header_idx = idx
                    break
            
            # Step 2: Read dataframe using python engine which is safer for broken rows
            df = pd.read_csv(
                full_path, 
                sep='\t', 
                encoding='utf-16', 
                skiprows=header_idx, 
                engine='python', 
                on_bad_lines='skip'
            )
            
            # Step 3: Column headers clean aur standardized mapping karna
            df.columns = df.columns.str.strip()
            
            # Truncated or alternative header variations mapping
            rename_dict = {}
            for col in df.columns:
                col_lower = col.lower()
                if any(x in col_lower for x in ['plant stoc', 'pl stock', 'pl.stock', 'plant stock', 'unrestricted']):
                    rename_dict[col] = 'Plant Stock'
                elif any(x in col_lower for x in ['tot.us.va', 'total value', 'tot value', 'valuated price']):
                    rename_dict[col] = 'Total Value'
                elif any(x in col_lower for x in ['moving pr', 'mvavgprice', 'moving price', 'price']):
                    rename_dict[col] = 'Moving Price'
                elif any(x in col_lower for x in ['material ci descr.', 'descr.', 'description', 'mat. desc.']):
                    rename_dict[col] = 'Description'
                elif 'material code' in col_lower:
                    rename_dict[col] = 'Material'
                    
            if rename_dict:
                df.rename(columns=rename_dict, inplace=True)
            
            # Step 4: Initial drop for blank structures
            df.dropna(how='all', inplace=True)
            
            # Step 5: Clean whitespace characters/newlines values inside cells before validation
            for col in df.columns:
                if df[col].dtype == object:
                    df[col] = df[col].astype(str).str.replace(r'\r|\n', ' ', regex=True).str.strip()

            # Master Row Clean Logic (SAP lines shift aur wrapping fix)
            # Sirf wahi rows bachaenge jinka Plant numeric character structure text match karega
            if 'Plant' in df.columns:
                df = df[df['Plant'].notna()]
                df = df[pd.to_numeric(df['Plant'], errors='coerce').notna()]
            
            if 'Material' in df.columns:
                df = df[df['Material'].notna()]
                df = df[df['Material'].astype(str).str.strip() != '']
            
            # Step 6: Parse numerical values strictly with our Custom SAP Function
            numeric_cols = ['Plant Stock', 'Total Value', 'Moving Price']
            for col in numeric_cols:
                if col in df.columns:
                    df[col] = df[col].apply(clean_sap_numeric)
            
            # Step 7: Back-calculate missing 'Plant Stock' if Total Value and Moving Price are present
            # Formula: Plant Stock = Total Value / Moving Price
            if 'Plant Stock' in df.columns and 'Total Value' in df.columns and 'Moving Price' in df.columns:
                # Fill missing or zeroed stock values only if valid price matrices are found
                mask_nan = (df['Plant Stock'].isna() | (df['Plant Stock'] == 0)) & df['Total Value'].notna() & (df['Moving Price'] > 0)
                df.loc[mask_nan, 'Plant Stock'] = df.loc[mask_nan, 'Total Value'] / df.loc[mask_nan, 'Moving Price']
                
                # Round to 2 decimal places to match standard SAP layout numbers
                df['Plant Stock'] = df['Plant Stock'].round(2)
            
            if len(df) > 0:
                # Format IDs nicely (Removing .0 formatting from raw floats strings)
                for col in ['Plant', 'Material']:
                    if col in df.columns:
                        df[col] = df[col].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                
                df['source_file'] = file_name
                df_list.append(df)
                print(f"Successfully cleaned & aligned: {file_name} ({len(df)} perfect records)")
            else:
                print(f"Warning: No valid lines inside {file_name} post filtering pass.")
                
        except Exception as e:
            print(f"Error handling content mapping inside {file_name}: {str(e)}")
    else:
        print(f"Warning: File not found at {full_path}")

# Merge everything into a master file
if df_list:
    master_df = pd.concat(df_list, ignore_index=True, sort=False)
    
    # Final pass cleaning to remove empty layout columns
    master_df.dropna(how='all', axis=1, inplace=True)
    
    # Save clean dataset to Excel
    output_path = os.path.join(out_dir_path, "master_aging_analysis.xlsx")
    master_df.to_excel(output_path, index=False)
    
    print(f"\nSuccess! Completely clean Master file created with shape: {master_df.shape}")
    print(f"Saved directly to: {output_path}")
else:
    print("\nNo data collected. Please verify your data directory structure or files format.")

# %%
VF_stock = config.get("VF_stock","")
df1 = pd.read_csv(VF_stock)
#df1.head(3)

# %%
df1.head(10)

# %%
import pandas as pd
import numpy as np

# ==========================================================
# 1. PREPARE KEYS
# ==========================================================

plants = [1110, 1159, 1153, 1156, 1157, 1155, 1158, 1161, 1152, 1141]

master_df = master_df.copy()
df1 = df1.copy()

master_df["Plant"] = master_df["Plant"].astype(str)
master_df["Material"] = master_df["Material"].astype(str)

df1["Plant"] = (
    pd.to_numeric(df1["Plant"], errors="coerce")
    .fillna(0)
    .astype(int)
    .astype(str)
)

df1["Material"] = df1["Material"].astype(str)

df1["Un.Stock"] = pd.to_numeric(
    df1["Un.Stock"],
    errors="coerce"
).fillna(0)

# ==========================================================
# 2. SALEABLE STOCK EXCLUDING GE04
# ==========================================================

saleable_stock = (
    df1[
        df1["Plant"].astype(int).isin(plants)
        & (df1["StorageLoc."].astype(str) != "GE04")
    ]
    .groupby(["Plant", "Material"], as_index=False)["Un.Stock"]
    .sum()
    .rename(columns={"Un.Stock": "saleable_stock"})
)

# ==========================================================
# 3. GE04 STOCK
# ==========================================================

ge04_stock = (
    df1[
        df1["Plant"].astype(int).isin(plants)
        & (df1["StorageLoc."].astype(str) == "GE04")
    ]
    .groupby(["Plant", "Material"], as_index=False)["Un.Stock"]
    .sum()
    .rename(columns={"Un.Stock": "ge04_stock"})
)

# ==========================================================
# 4. MERGE STOCKS INTO AGEING FILE
# ==========================================================

ageing_df = master_df.merge(
    saleable_stock,
    on=["Plant", "Material"],
    how="left"
)

ageing_df = ageing_df.merge(
    ge04_stock,
    on=["Plant", "Material"],
    how="left"
)

ageing_df["saleable_stock"] = ageing_df["saleable_stock"].fillna(0)
ageing_df["ge04_stock"] = ageing_df["ge04_stock"].fillna(0)

# ==========================================================
# 5. IDENTIFY AGEING BUCKET COLUMNS
# ==========================================================

bucket_cols = list(master_df.columns)

start_idx = bucket_cols.index("Plant Stock") + 1

# ageing_buckets = bucket_cols[start_idx:]
ageing_buckets = [
    'NOV2026','OCT2026',
    'SEP2026', 'AUG2026', 'JUL2026', 'JUN2026',
    'MAY2026', 'APR2026', 'MAR2026', 'FEB2026',
    'JAN2026', 'DEC2025',    
    '> 1', '> 2', '> 3'
]

latest_bucket = ageing_buckets[0]

print("Ageing buckets:")
print(ageing_buckets)

latest_bucket = ageing_buckets[0]
print("Latest Bucket:", latest_bucket)

# Plant Stock
ageing_df["Plant Stock"] = pd.to_numeric(
    ageing_df["Plant Stock"],
    errors="coerce"
).fillna(0)

# Ageing buckets
for col in ageing_buckets:
    ageing_df[col] = pd.to_numeric(
        ageing_df[col]
        .astype(str)
        .str.replace(",", "", regex=False)
        .str.strip(),
        errors="coerce"
    ).fillna(0)


ageing_df["saleable_stock"] = pd.to_numeric(
    ageing_df["saleable_stock"],
    errors="coerce"
).fillna(0)

ageing_df["ge04_stock"] = pd.to_numeric(
    ageing_df["ge04_stock"],
    errors="coerce"
).fillna(0)

print(ageing_df[ageing_buckets].dtypes)

# ==========================================================
# 6. MATCH AGEING STOCK WITH SALEABLE STOCK
# ==========================================================

for idx in ageing_df.index:

    plant_stock = pd.to_numeric(
        ageing_df.at[idx, "Plant Stock"],
        errors="coerce"
    )

    saleable = ageing_df.at[idx, "saleable_stock"]

    if pd.isna(plant_stock):
        continue

    diff = plant_stock - saleable

    # only when ageing stock > saleable stock
    if diff > 0:

        remaining = diff

        # subtract starting from latest bucket
        for bucket in ageing_buckets:

            bucket_qty = pd.to_numeric(
                ageing_df.at[idx, bucket],
                errors="coerce"
            )

            if pd.isna(bucket_qty):
                bucket_qty = 0

            deduction = min(bucket_qty, remaining)

            ageing_df.at[idx, bucket] = bucket_qty - deduction

            remaining -= deduction

            if remaining <= 0:
                break

        ageing_df.at[idx, "Plant Stock"] = plant_stock - diff

# ==========================================================
# 7. ADD GE04 STOCK BACK TO LATEST BUCKET
# ==========================================================

ageing_df["Plant Stock"] = (
    pd.to_numeric(ageing_df["Plant Stock"], errors="coerce")
    .fillna(0)
)

ageing_df[latest_bucket] = (
    pd.to_numeric(ageing_df[latest_bucket], errors="coerce")
    .fillna(0)
)

ageing_df["Plant Stock"] += ageing_df["ge04_stock"]

ageing_df[latest_bucket] += ageing_df["ge04_stock"]

# ==========================================================
# 8. CLEANUP
# ==========================================================

adjusted_ageing_df = ageing_df.drop(
    columns=["saleable_stock", "ge04_stock"]
)

print(adjusted_ageing_df.head())

# %%
bucket_sum = adjusted_ageing_df[ageing_buckets].sum(axis=1)

check = pd.DataFrame({
    "Plant Stock": adjusted_ageing_df["Plant Stock"],
    "Bucket Sum": bucket_sum
})

check["Diff"] = check["Plant Stock"] - check["Bucket Sum"]

print(check["Diff"].describe())

# %%
# adjusted_ageing_df.to_excel(r"C:\Order Orchestration code\order_orchestration\Regular_original_files\18_09_2026\modified input files\saleable_GE_inventory.xlsx")

# %%
workflow_ageing_df = adjusted_ageing_df.copy()

# Plant
workflow_ageing_df["plant"] = (
    pd.to_numeric(workflow_ageing_df["Plant"], errors="coerce")
    .astype("Int64")
)

# Material code
workflow_ageing_df["material_code"] = (
    workflow_ageing_df["Material"]
    .astype(str)
    .str.strip()
)

# Total ageing stock
workflow_ageing_df["ageing_stock_qty"] = (
    pd.to_numeric(
        workflow_ageing_df["Plant Stock"],
        errors="coerce"
    )
    .fillna(0)
    .round(0)
    .astype(int)
)

# Ageing > 1 year = >1 + >2 + >3
workflow_ageing_df["ageing_stock_gt_1yr"] = (
    pd.to_numeric(workflow_ageing_df["> 1"], errors="coerce").fillna(0)
    + pd.to_numeric(workflow_ageing_df["> 2"], errors="coerce").fillna(0)
    + pd.to_numeric(workflow_ageing_df["> 3"], errors="coerce").fillna(0)
).round(0).astype(int)

# Flag
workflow_ageing_df["is_ageing_stock_available"] = (
    workflow_ageing_df["ageing_stock_gt_1yr"] > 0
).astype(int)

# Final output
workflow_ageing_df = workflow_ageing_df[
    [
        "plant",
        "material_code",
        "ageing_stock_qty",
        "ageing_stock_gt_1yr",
        "is_ageing_stock_available",
    ]
]

print(workflow_ageing_df.head())

# %%
cleaned_files = "/home/VECVNET/zzasom/jupyter/01_Developement_work_QA/Chakshu_G/order_orchestration/order_orchestration_mannual/Build/data/cleaned/"
output_path = os.path.join(cleaned_files, "cleaned_ageing_plant_material_level.xlsx")
workflow_ageing_df.to_excel(output_path, index=False)

# %%


# %%


# %%


# %%


# %%


# %%



