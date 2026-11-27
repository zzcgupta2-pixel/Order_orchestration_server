from __future__ import annotations

import json
import sys
from pathlib import Path


# =========================================================
# PROJECT PATHS
# =========================================================

# This file:
# Build/scripts/run_data_cleaning.py
script_path = Path(__file__).resolve()

# Build/scripts
scripts_dir = script_path.parent

# Build
build_dir = scripts_dir.parent

# order_orchestration_mannual
deployment_root = build_dir.parent

# Build/src
src_dir = build_dir / "src"

# Ensure the source package can be imported even if the
# project has not been installed with pip install -e .
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))


from order_orchestration.data.cleaning_pipeline import (
    load_yaml_config,
    run_cleaning_pipeline,
)


# =========================================================
# FIXED CONFIGURATION LOCATIONS
# =========================================================

cleaning_config_path = (
    build_dir
    / "config"
    / "data_cleaning.yaml"
)

path_config_path = (
    deployment_root
    / "Bash"
    / "OO_manual.json"
)


def load_json_config(
    file_path: Path,
) -> dict:
    """Load the JSON file containing physical file paths."""

    if not file_path.is_file():
        raise FileNotFoundError(
            "Path configuration file was not found:\n"
            f"{file_path}"
        )

    with file_path.open(
        "r",
        encoding="utf-8",
    ) as config_file:
        config = json.load(config_file)

    if not isinstance(config, dict):
        raise TypeError(
            "OO_manual.json must contain a JSON object."
        )

    return config


def main() -> None:
    if not cleaning_config_path.is_file():
        raise FileNotFoundError(
            "Data-cleaning YAML configuration was not found:\n"
            f"{cleaning_config_path}"
        )

    print("Data-cleaning configuration:")
    print(cleaning_config_path)

    print("\nFile-path configuration:")
    print(path_config_path)

    cleaning_config = load_yaml_config(
        cleaning_config_path
    )

    path_config = load_json_config(
        path_config_path
    )

    outputs = run_cleaning_pipeline(
        config=cleaning_config,
        path_config=path_config,
    )

    print()
    print("Data cleaning completed successfully.")
    print("Generated outputs:")

    if not outputs:
        print(
            "  No cleaning outputs were generated. "
            "Check the enabled settings in "
            "data_cleaning.yaml."
        )
        return

    for name, dataframe in outputs.items():
        print(
            f"  - {name}: "
            f"{dataframe.shape[0]:,} rows x "
            f"{dataframe.shape[1]:,} columns"
        )


if __name__ == "__main__":
    main()
 