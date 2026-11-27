from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

import pandas as pd


@dataclass(frozen=True)
class GitReservationMovement:
    """
    One deferred GIT reservation.

    Reserving GIT does not change current physical inventory.
    """

    git_movement_id: str

    order_id: str
    line_id: str
    order_category: str

    material_code: str
    destination_location: str
    source_location: str
    asn_number: str

    dispatch_datetime: datetime
    expected_arrival_datetime: datetime
    inbound_rlt_days: int
    arrival_days_from_decision: int

    git_quantity_before: Decimal
    reserved_quantity: Decimal
    git_quantity_after: Decimal

    movement_timestamp: datetime
    movement_type: str
    reason_code: str
    remarks: str


@dataclass(frozen=True)
class AvailableGitShipment:
    """
    Current state-aware availability of one ASN.
    """

    material_code: str
    destination_location: str
    source_location: str
    asn_number: str

    dispatch_datetime: datetime
    expected_arrival_datetime: datetime
    inbound_rlt_days: int

    available_quantity: Decimal


class GitStateManager:
    """
    Tracks the remaining quantity of every ASN.

    State key:
        destination_location
        material_code
        source_location
        asn_number

    Only the reserved quantity is removed. Any unreserved balance
    remains available to later orders.
    """

    def __init__(
        self,
        git_df: pd.DataFrame,
    ) -> None:
        self._shipment_data: dict[
            tuple[str, str, str, str],
            AvailableGitShipment,
        ] = {}

        self._available_balance: dict[
            tuple[str, str, str, str],
            Decimal,
        ] = {}

        self._movements: list[
            GitReservationMovement
        ] = []

        self._reservation_keys: set[
            tuple[str, str, str, str, str, str]
        ] = set()

        self._initialize_state(git_df)

    @staticmethod
    def _normalize_code(
        value,
    ) -> str:
        normalized = str(value).strip()

        if normalized.endswith(".0"):
            normalized = normalized[:-2]

        return normalized

    @staticmethod
    def _safe_decimal(
        value,
        default: Decimal = Decimal("0"),
    ) -> Decimal:
        if value is None:
            return default

        try:
            return Decimal(str(value).strip())
        except Exception:
            return default

    @classmethod
    def _make_key(
        cls,
        destination_location: str,
        material_code: str,
        source_location: str,
        asn_number: str,
    ) -> tuple[str, str, str, str]:
        return (
            cls._normalize_code(
                destination_location
            ),
            cls._normalize_code(
                material_code
            ),
            cls._normalize_code(
                source_location
            ),
            cls._normalize_code(
                asn_number
            ),
        )

    def _initialize_state(
        self,
        git_df: pd.DataFrame,
    ) -> None:
        required_columns = [
            "material_code",
            "destination_location",
            "source_location",
            "git_quantity",
            "delivery_status",
            "asn_number",
            "dispatch_datetime",
            "inbound_rlt_days",
            "expected_arrival_datetime",
            "rlt_found",
        ]

        missing_columns = [
            column
            for column in required_columns
            if column not in git_df.columns
        ]

        if missing_columns:
            raise ValueError(
                "Cleaned GIT dataframe is missing columns: "
                f"{missing_columns}"
            )

        working_df = git_df.copy()

        working_df["dispatch_datetime"] = (
            pd.to_datetime(
                working_df["dispatch_datetime"],
                errors="coerce",
            )
        )

        working_df[
            "expected_arrival_datetime"
        ] = pd.to_datetime(
            working_df[
                "expected_arrival_datetime"
            ],
            errors="coerce",
        )

        working_df["git_quantity"] = (
            pd.to_numeric(
                working_df["git_quantity"],
                errors="coerce",
            )
        )

        working_df["inbound_rlt_days"] = (
            pd.to_numeric(
                working_df["inbound_rlt_days"],
                errors="coerce",
            )
        )

        working_df["delivery_status"] = (
            pd.to_numeric(
                working_df["delivery_status"],
                errors="coerce",
            )
        )

        rlt_found_mask = (
            working_df["rlt_found"]
            .astype(str)
            .str.strip()
            .str.upper()
            .isin(["TRUE", "1", "YES"])
        )

        working_df = working_df[
            rlt_found_mask
            & working_df["delivery_status"].isin(
                [1, 2, 3]
            )
            & working_df["git_quantity"].notna()
            & (working_df["git_quantity"] > 0)
            & working_df[
                "dispatch_datetime"
            ].notna()
            & working_df[
                "expected_arrival_datetime"
            ].notna()
            & working_df[
                "inbound_rlt_days"
            ].notna()
        ].copy()

        for _, row in working_df.iterrows():
            key = self._make_key(
                destination_location=(
                    row["destination_location"]
                ),
                material_code=row["material_code"],
                source_location=(
                    row["source_location"]
                ),
                asn_number=row["asn_number"],
            )

            quantity = self._safe_decimal(
                row["git_quantity"]
            )

            if quantity <= Decimal("0"):
                continue

            shipment = AvailableGitShipment(
                material_code=key[1],
                destination_location=key[0],
                source_location=key[2],
                asn_number=key[3],
                dispatch_datetime=(
                    pd.Timestamp(
                        row["dispatch_datetime"]
                    ).to_pydatetime()
                ),
                expected_arrival_datetime=(
                    pd.Timestamp(
                        row[
                            "expected_arrival_datetime"
                        ]
                    ).to_pydatetime()
                ),
                inbound_rlt_days=int(
                    row["inbound_rlt_days"]
                ),
                available_quantity=quantity,
            )

            if key in self._available_balance:
                existing_quantity = (
                    self._available_balance[key]
                )

                self._available_balance[key] = (
                    existing_quantity + quantity
                )

                existing_shipment = (
                    self._shipment_data[key]
                )

                earliest_dispatch = min(
                    existing_shipment
                    .dispatch_datetime,
                    shipment.dispatch_datetime,
                )

                earliest_arrival = min(
                    existing_shipment
                    .expected_arrival_datetime,
                    shipment
                    .expected_arrival_datetime,
                )

                self._shipment_data[key] = (
                    AvailableGitShipment(
                        material_code=key[1],
                        destination_location=key[0],
                        source_location=key[2],
                        asn_number=key[3],
                        dispatch_datetime=(
                            earliest_dispatch
                        ),
                        expected_arrival_datetime=(
                            earliest_arrival
                        ),
                        inbound_rlt_days=(
                            shipment.inbound_rlt_days
                        ),
                        available_quantity=(
                            existing_quantity
                            + quantity
                        ),
                    )
                )

            else:
                self._shipment_data[key] = shipment
                self._available_balance[key] = quantity

    def get_matching_shipments(
        self,
        destination_location: str,
        material_code: str,
    ) -> list:
        """
        Returns current available ASNs for one parent-material.
        """

        destination_key = self._normalize_code(
            destination_location
        )

        material_key = self._normalize_code(
            material_code
        )

        matches: list[
            AvailableGitShipment
        ] = []

        for key, shipment in (
            self._shipment_data.items()
        ):
            if key[0] != destination_key:
                continue

            if key[1] != material_key:
                continue

            available_quantity = (
                self._available_balance.get(
                    key,
                    Decimal("0"),
                )
            )

            if (
                available_quantity
                <= Decimal("0")
            ):
                continue

            matches.append(
                AvailableGitShipment(
                    material_code=(
                        shipment.material_code
                    ),
                    destination_location=(
                        shipment
                        .destination_location
                    ),
                    source_location=(
                        shipment.source_location
                    ),
                    asn_number=(
                        shipment.asn_number
                    ),
                    dispatch_datetime=(
                        shipment.dispatch_datetime
                    ),
                    expected_arrival_datetime=(
                        shipment
                        .expected_arrival_datetime
                    ),
                    inbound_rlt_days=(
                        shipment.inbound_rlt_days
                    ),
                    available_quantity=(
                        available_quantity
                    ),
                )
            )

        return matches

    def reserve(
        self,
        order_id: str,
        line_id: str,
        order_category: str,
        shipment: AvailableGitShipment,
        quantity: Decimal,
        arrival_days_from_decision: int,
        movement_timestamp: datetime,
        reason_code: str,
    ) -> GitReservationMovement:
        """
        Reserves quantity from one ASN.

        Only reserved quantity is removed. Any remaining ASN
        balance may be used for another order.
        """

        quantity = self._safe_decimal(
            quantity
        )

        if quantity <= Decimal("0"):
            raise ValueError(
                "GIT reservation quantity must be positive."
            )

        shipment_key = self._make_key(
            destination_location=(
                shipment.destination_location
            ),
            material_code=(
                shipment.material_code
            ),
            source_location=(
                shipment.source_location
            ),
            asn_number=shipment.asn_number,
        )

        reservation_key = (
            str(order_id).strip(),
            str(line_id).strip(),
            shipment_key[0],
            shipment_key[1],
            shipment_key[2],
            shipment_key[3],
        )

        if (
            reservation_key
            in self._reservation_keys
        ):
            raise ValueError(
                "Duplicate GIT reservation prevented. "
                f"Order={order_id}, "
                f"line={line_id}, "
                f"ASN={shipment.asn_number}."
            )

        quantity_before = (
            self._available_balance.get(
                shipment_key,
                Decimal("0"),
            )
        )

        if quantity > quantity_before:
            raise ValueError(
                "Insufficient GIT balance. "
                f"ASN={shipment.asn_number}, "
                f"available={quantity_before}, "
                f"requested={quantity}."
            )

        quantity_after = (
            quantity_before - quantity
        )

        self._available_balance[
            shipment_key
        ] = quantity_after

        movement = GitReservationMovement(
            git_movement_id=str(uuid4()),
            order_id=str(order_id),
            line_id=str(line_id),
            order_category=(
                str(order_category)
            ),
            material_code=(
                shipment.material_code
            ),
            destination_location=(
                shipment.destination_location
            ),
            source_location=(
                shipment.source_location
            ),
            asn_number=shipment.asn_number,
            dispatch_datetime=(
                shipment.dispatch_datetime
            ),
            expected_arrival_datetime=(
                shipment
                .expected_arrival_datetime
            ),
            inbound_rlt_days=(
                shipment.inbound_rlt_days
            ),
            arrival_days_from_decision=(
                arrival_days_from_decision
            ),
            git_quantity_before=(
                quantity_before
            ),
            reserved_quantity=quantity,
            git_quantity_after=(
                quantity_after
            ),
            movement_timestamp=(
                movement_timestamp
            ),
            movement_type="GIT_RESERVATION",
            reason_code=reason_code,
            remarks=(
                "Replenishment GIT reservation "
                "from earliest ASN arriving "
                "within one day."
            ),
        )

        self._reservation_keys.add(
            reservation_key
        )

        self._movements.append(
            movement
        )

        return movement

    def get_movements(
        self,
    ) -> list:
        return list(self._movements)