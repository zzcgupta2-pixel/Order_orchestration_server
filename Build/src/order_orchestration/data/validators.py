from dataclasses import dataclass
from typing import Iterable, Optional

import pandas as pd


@dataclass(frozen=True)
class ValidationIssue:
    """
    Represents a single data-quality validation issue.

    Each issue captures:
    - table name
    - row index
    - field name
    - issue code
    - issue message
    - severity
    """

    table_name: str
    row_index: Optional[int]
    field_name: Optional[str]
    issue_code: str
    issue_message: str
    severity: str


class ValidationResult:
    """
    Collection of validation issues.

    This object allows validators to collect issues and convert them
    into a pandas DataFrame for reporting.
    """

    def __init__(self) -> None:
        self.issues: list[ValidationIssue] = []

    def add_issue(
        self,
        table_name: str,
        row_index: Optional[int],
        field_name: Optional[str],
        issue_code: str,
        issue_message: str,
        severity: str = "ERROR",
    ) -> None:
        self.issues.append(
            ValidationIssue(
                table_name=table_name,
                row_index=row_index,
                field_name=field_name,
                issue_code=issue_code,
                issue_message=issue_message,
                severity=severity,
            )
        )

    def has_errors(self) -> bool:
        return any(issue.severity == "ERROR" for issue in self.issues)

    def has_warnings(self) -> bool:
        return any(issue.severity == "WARNING" for issue in self.issues)

    def to_dataframe(self) -> pd.DataFrame:
        return pd.DataFrame([issue.__dict__ for issue in self.issues])

    def extend(self, other: "ValidationResult") -> None:
        self.issues.extend(other.issues)


def validate_required_columns(
    df: pd.DataFrame,
    table_name: str,
    required_columns: Iterable[str],
) -> ValidationResult:
    """
    Validates whether all required columns exist in a dataframe.
    """

    result = ValidationResult()

    for column in required_columns:
        if column not in df.columns:
            result.add_issue(
                table_name=table_name,
                row_index=None,
                field_name=column,
                issue_code="MISSING_REQUIRED_COLUMN",
                issue_message=f"Required column '{column}' is missing.",
                severity="ERROR",
            )

    return result


def validate_allowed_values(
    df: pd.DataFrame,
    table_name: str,
    column_name: str,
    allowed_values: set[str],
    issue_code: str,
    issue_message: str,
) -> ValidationResult:
    """
    Validates whether values in a column belong to the configured allowed set.
    """

    result = ValidationResult()

    if column_name not in df.columns:
        result.add_issue(
            table_name=table_name,
            row_index=None,
            field_name=column_name,
            issue_code="MISSING_REQUIRED_COLUMN",
            issue_message=f"Required column '{column_name}' is missing.",
            severity="ERROR",
        )
        return result

    normalized_allowed_values = {str(value).strip().upper() for value in allowed_values}

    invalid_mask = ~df[column_name].astype(str).str.strip().str.upper().isin(
        normalized_allowed_values
    )

    invalid_rows = df[invalid_mask]

    for row_index, row in invalid_rows.iterrows():
        result.add_issue(
            table_name=table_name,
            row_index=int(row_index),
            field_name=column_name,
            issue_code=issue_code,
            issue_message=f"{issue_message}. Found value: {row[column_name]}",
            severity="ERROR",
        )

    return result


def validate_not_missing(
    df: pd.DataFrame,
    table_name: str,
    column_name: str,
    issue_code: str,
    issue_message: str,
    severity: str = "ERROR",
) -> ValidationResult:
    """
    Validates that a column does not contain missing or blank values.
    """

    result = ValidationResult()

    if column_name not in df.columns:
        result.add_issue(
            table_name=table_name,
            row_index=None,
            field_name=column_name,
            issue_code="MISSING_REQUIRED_COLUMN",
            issue_message=f"Required column '{column_name}' is missing.",
            severity="ERROR",
        )
        return result

    missing_mask = (
        df[column_name].isna()
        | df[column_name].astype(str).str.strip().str.lower().isin(["", "nan", "none"])
    )

    for row_index in df[missing_mask].index:
        result.add_issue(
            table_name=table_name,
            row_index=int(row_index),
            field_name=column_name,
            issue_code=issue_code,
            issue_message=issue_message,
            severity=severity,
        )

    return result


def validate_positive_numeric(
    df: pd.DataFrame,
    table_name: str,
    column_name: str,
    issue_code: str,
    issue_message: str,
) -> ValidationResult:
    """
    Validates that a numeric column is greater than zero.
    """

    result = ValidationResult()

    if column_name not in df.columns:
        result.add_issue(
            table_name=table_name,
            row_index=None,
            field_name=column_name,
            issue_code="MISSING_REQUIRED_COLUMN",
            issue_message=f"Required column '{column_name}' is missing.",
            severity="ERROR",
        )
        return result

    numeric_values = pd.to_numeric(df[column_name], errors="coerce")
    invalid_mask = numeric_values.isna() | (numeric_values <= 0)

    for row_index in df[invalid_mask].index:
        result.add_issue(
            table_name=table_name,
            row_index=int(row_index),
            field_name=column_name,
            issue_code=issue_code,
            issue_message=issue_message,
            severity="ERROR",
        )

    return result


def validate_non_negative_numeric(
    df: pd.DataFrame,
    table_name: str,
    column_name: str,
    issue_code: str,
    issue_message: str,
    severity: str = "ERROR",
) -> ValidationResult:
    """
    Validates that a numeric column is greater than or equal to zero.
    """

    result = ValidationResult()

    if column_name not in df.columns:
        result.add_issue(
            table_name=table_name,
            row_index=None,
            field_name=column_name,
            issue_code="MISSING_REQUIRED_COLUMN",
            issue_message=f"Required column '{column_name}' is missing.",
            severity="ERROR",
        )
        return result

    numeric_values = pd.to_numeric(df[column_name], errors="coerce")
    invalid_mask = numeric_values.isna() | (numeric_values < 0)

    for row_index in df[invalid_mask].index:
        result.add_issue(
            table_name=table_name,
            row_index=int(row_index),
            field_name=column_name,
            issue_code=issue_code,
            issue_message=issue_message,
            severity=severity,
        )

    return result


def validate_duplicate_order_lines(
    df: pd.DataFrame,
    table_name: str = "open_order",
    order_id_column: str = "sales_order",
    line_id_column: str = "sales_order_line",
) -> ValidationResult:
    """
    Validates duplicate order lines if sales order and line columns are available.

    If these columns are not present, a warning is generated instead of an error
    because current cleaned master data may not yet contain these fields.
    """

    result = ValidationResult()

    if order_id_column not in df.columns or line_id_column not in df.columns:
        result.add_issue(
            table_name=table_name,
            row_index=None,
            field_name=f"{order_id_column}, {line_id_column}",
            issue_code="ORDER_LINE_KEY_NOT_AVAILABLE",
            issue_message=(
                "Order-line duplicate validation skipped because sales order "
                "and/or sales order line columns are not available."
            ),
            severity="WARNING",
        )
        return result

    duplicate_mask = df.duplicated(
        subset=[order_id_column, line_id_column],
        keep=False,
    )

    for row_index in df[duplicate_mask].index:
        result.add_issue(
            table_name=table_name,
            row_index=int(row_index),
            field_name=f"{order_id_column}, {line_id_column}",
            issue_code="DUPLICATE_ORDER_LINE",
            issue_message="Duplicate order line found.",
            severity="ERROR",
        )

    return result


def validate_master_orders_dataframe(
    df: pd.DataFrame,
    table_name: str = "open_order_master",
) -> ValidationResult:
    """
    Validates the final open-order master dataframe before orchestration.

    This validation is aligned with the current cleaned master structure.
    """

    result = ValidationResult()

    required_columns = [
        "order_category",
        "priority_rank",
        "plant",
        "material_code",
        "customer_code",
        "order_create_datetime",
        "open_order_qty",
        "is_credit_blocked",
        "total_saleable_inventory_qty",
        "git_qty",
        "safety_stock",
    ]

    result.extend(
        validate_required_columns(
            df=df,
            table_name=table_name,
            required_columns=required_columns,
        )
    )

    if result.has_errors():
        return result

    allowed_order_categories = {"VOR", "REPLENISHMENT", "PUSH"}

    result.extend(
        validate_allowed_values(
            df=df,
            table_name=table_name,
            column_name="order_category",
            allowed_values=allowed_order_categories,
            issue_code="UNSUPPORTED_ORDER_CATEGORY",
            issue_message="Unsupported order category",
        )
    )

    missing_checks = [
        ("order_create_datetime", "MISSING_ORDER_TIMESTAMP", "Order timestamp is required."),
        ("plant", "MISSING_PARENT_RDC", "Plant or parent RDC is required."),
        ("material_code", "MISSING_MATERIAL_CODE", "Material code is required."),
        ("customer_code", "MISSING_CUSTOMER_CODE", "Customer/dealer code is required."),
        ("is_credit_blocked", "MISSING_CREDIT_BLOCK_FLAG", "Credit block flag is required."),
    ]

    for column_name, issue_code, issue_message in missing_checks:
        result.extend(
            validate_not_missing(
                df=df,
                table_name=table_name,
                column_name=column_name,
                issue_code=issue_code,
                issue_message=issue_message,
                severity="ERROR",
            )
        )

    result.extend(
        validate_positive_numeric(
            df=df,
            table_name=table_name,
            column_name="open_order_qty",
            issue_code="NONPOSITIVE_REQUESTED_QUANTITY",
            issue_message="Open order quantity must be greater than zero.",
        )
    )

    non_negative_checks = [
        (
            "total_saleable_inventory_qty",
            "NEGATIVE_TOTAL_SALEABLE_INVENTORY",
            "Total saleable inventory quantity cannot be negative.",
            "ERROR",
        ),
        (
            "git_qty",
            "NEGATIVE_GIT_QUANTITY",
            "GIT quantity cannot be negative.",
            "ERROR",
        ),
        (
            "safety_stock",
            "NEGATIVE_SAFETY_STOCK",
            "Safety stock cannot be negative.",
            "ERROR",
        ),
        (
            "ageing_stock_qty",
            "NEGATIVE_AGEING_STOCK",
            "Ageing stock quantity cannot be negative.",
            "WARNING",
        ),
        (
            "ageing_stock_gt_1yr",
            "NEGATIVE_AGEING_STOCK_GT_1YR",
            "Ageing stock greater than one year cannot be negative.",
            "WARNING",
        ),
        (
            "max_delivery_qty",
            "NEGATIVE_MAX_DELIVERY_QTY",
            "Maximum delivery quantity cannot be negative.",
            "WARNING",
        ),
    ]

    for column_name, issue_code, issue_message, severity in non_negative_checks:
        if column_name in df.columns:
            result.extend(
                validate_non_negative_numeric(
                    df=df,
                    table_name=table_name,
                    column_name=column_name,
                    issue_code=issue_code,
                    issue_message=issue_message,
                    severity=severity,
                )
            )

    result.extend(
        validate_duplicate_order_lines(
            df=df,
            table_name=table_name,
        )
    )

    return result