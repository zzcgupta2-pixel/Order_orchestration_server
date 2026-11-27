from __future__ import annotations

import argparse

from order_orchestration.data.cleaning_pipeline import (
    load_yaml_config,
    run_cleaning_pipeline,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run configurable VECV data-cleaning pipeline."
    )

    parser.add_argument(
        "--config",
        required=True,
        help="Path to data cleaning YAML config.",
    )

    parser.add_argument(
        "--only",
        nargs="*",
        default=None,
        help=(
            "Optional list of cleaning steps to run. "
            "Example: --only open_order logistics inventory_master"
        ),
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    config = load_yaml_config(args.config)

    outputs = run_cleaning_pipeline(
        config=config,
        only_steps=args.only,
    )

    print("\nData cleaning completed successfully.")
    print("Generated outputs:")

    for name, df in outputs.items():
        print(f"  - {name}: {df.shape[0]} rows x {df.shape[1]} columns")


if __name__ == "__main__":
    main()