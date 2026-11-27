class OrderOrchestrationError(Exception):
    """Base exception for order orchestration errors."""


class ConfigurationError(OrderOrchestrationError):
    """Raised when configuration is missing or invalid."""


class DataValidationError(OrderOrchestrationError):
    """Raised when input data fails validation."""


class InventoryStateError(OrderOrchestrationError):
    """Raised when inventory state update is invalid."""


class DuplicateExecutionError(OrderOrchestrationError):
    """Raised when an order line is executed more than once."""


class RuleExecutionError(OrderOrchestrationError):
    """Raised when rule execution fails."""