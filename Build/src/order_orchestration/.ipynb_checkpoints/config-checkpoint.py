from __future__ import annotations

from pathlib import Path
from typing import Any
from typing import Union

import yaml

from order_orchestration.exceptions import ConfigurationError


class ConfigLoader:
    """Loads YAML configuration files for the rule engine."""

    def __init__(self, config_dir:  str | Path):
        self.config_dir = Path(config_dir)

    def load_yaml(self, file_name: str) -> dict[str, Any]:
        file_path = self.config_dir / file_name

        if not file_path.exists():
            raise ConfigurationError(f"Configuration file not found: {file_path}")

        with file_path.open("r", encoding="utf-8") as file:
            data = yaml.safe_load(file)

        if data is None:
            raise ConfigurationError(f"Configuration file is empty: {file_path}")

        return data

    def load_business_rules(self) -> dict[str, Any]:
        return self.load_yaml("business_rules.yaml")

    def load_reason_codes(self) -> dict[str, Any]:
        return self.load_yaml("reason_codes.yaml")

    def load_source_priority(self) -> dict[str, Any]:
        return self.load_yaml("source_priority.yaml")

    def load_transport_rules(self) -> dict[str, Any]:
        return self.load_yaml("transport_rules.yaml")

    def load_calendar_rules(self) -> dict[str, Any]:
        return self.load_yaml("calendar_rules.yaml")

    def load_execution_scope(self) -> dict[str, Any]:
        return self.load_yaml("execution_scope.yaml")
