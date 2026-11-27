from datetime import datetime, timezone

import pandas as pd

from order_orchestration.data.validators import (
    validate_master_orders_dataframe,
    validate_required_columns,
)


def test_validate_required_columns_passes_when_columns_exist():
    df = pd.DataFrame(
        {
            "plant": ["1158"],
            "material_code": ["MAT-001"],
        }
    )

    result = validate_required_columns(
        df=df,
        table_name="test_table",
        required_columns=["plant", "material_code"],
    )

    assert result.has_errors() is False
    assert len(result.issues) == 0


def test_validate_required_columns_fails_when_column_missing():
    df = pd.DataFrame(
        {
            "plant": ["1158"],
        }
    )

    result = validate_required_columns(
        df=df,
        table_name="test_table",
        required_columns=["plant", "material_code"],
    )

    assert result.has_errors() is True
    assert len(result.issues) == 1
    assert result.issues[0].issue_code == "MISSING_REQUIRED_COLUMN"


def test_validate_master_orders_dataframe_valid_data():
    df = pd.DataFrame(
        {
            "order_category": ["Replenishment"],
            "priority_rank": [2],
            "plant": ["1158"],
            "material_code": ["MAT-001"],
            "customer_code": ["DEALER-001"],
            "order_create_datetime": [datetime(2026, 7, 24, tzinfo=timezone.utc)],
            "open_order_qty": [10],
            "is_credit_blocked": [0],
            "total_saleable_inventory_qty": [100],
            "git_qty": [0],
            "safety_stock": [20],
        }
    )

    result = validate_master_orders_dataframe(df)

    # One warning is expected because sales_order and sales_order_line are unavailable.
    assert result.has_errors() is False
    assert result.has_warnings() is True


def test_validate_master_orders_dataframe_missing_material():
    df = pd.DataFrame(
        {
            "order_category": ["Replenishment"],
            "priority_rank": [2],
            "plant": ["1158"],
            "material_code": [""],
            "customer_code": ["DEALER-001"],
            "order_create_datetime": [datetime(2026, 7, 24, tzinfo=timezone.utc)],
            "open_order_qty": [10],
            "is_credit_blocked": [0],
            "total_saleable_inventory_qty": [100],
            "git_qty": [0],
            "safety_stock": [20],
        }
    )

    result = validate_master_orders_dataframe(df)

    assert result.has_errors() is True

    issue_codes = {issue.issue_code for issue in result.issues}
    assert "MISSING_MATERIAL_CODE" in issue_codes


def test_validate_master_orders_dataframe_nonpositive_qty():
    df = pd.DataFrame(
        {
            "order_category": ["Replenishment"],
            "priority_rank": [2],
            "plant": ["1158"],
            "material_code": ["MAT-001"],
            "customer_code": ["DEALER-001"],
            "order_create_datetime": [datetime(2026, 7, 24, tzinfo=timezone.utc)],
            "open_order_qty": [0],
            "is_credit_blocked": [0],
            "total_saleable_inventory_qty": [100],
            "git_qty": [0],
            "safety_stock": [20],
        }
    )

    result = validate_master_orders_dataframe(df)

    assert result.has_errors() is True

    issue_codes = {issue.issue_code for issue in result.issues}
    assert "NONPOSITIVE_REQUESTED_QUANTITY" in issue_codes


def test_validate_master_orders_dataframe_negative_inventory():
    df = pd.DataFrame(
        {
            "order_category": ["Replenishment"],
            "priority_rank": [2],
            "plant": ["1158"],
            "material_code": ["MAT-001"],
            "customer_code": ["DEALER-001"],
            "order_create_datetime": [datetime(2026, 7, 24, tzinfo=timezone.utc)],
            "open_order_qty": [10],
            "is_credit_blocked": [0],
            "total_saleable_inventory_qty": [-5],
            "git_qty": [0],
            "safety_stock": [20],
        }
    )

    result = validate_master_orders_dataframe(df)

    assert result.has_errors() is True

    issue_codes = {issue.issue_code for issue in result.issues}
    assert "NEGATIVE_TOTAL_SALEABLE_INVENTORY" in issue_codes


def test_validate_master_orders_dataframe_unsupported_order_category():
    df = pd.DataFrame(
        {
            "order_category": ["Export"],
            "priority_rank": [99],
            "plant": ["1158"],
            "material_code": ["MAT-001"],
            "customer_code": ["DEALER-001"],
            "order_create_datetime": [datetime(2026, 7, 24, tzinfo=timezone.utc)],
            "open_order_qty": [10],
            "is_credit_blocked": [0],
            "total_saleable_inventory_qty": [100],
            "git_qty": [0],
            "safety_stock": [20],
        }
    )

    result = validate_master_orders_dataframe(df)

    assert result.has_errors() is True

    issue_codes = {issue.issue_code for issue in result.issues}
    assert "UNSUPPORTED_ORDER_CATEGORY" in issue_codes