"""
Application-wide enumerations.

Defines IntEnum classes for database FK-based lookup values,
ensuring type-safe comparisons in Python code.
"""

from enum import IntEnum


class OrderStatus(IntEnum):
    """Order status codes matching order_status lookup table.

    Values correspond to auto-increment IDs in the order_status table.
    """
    pending = 1
    in_progress = 2
    processing = 3
    completed = 4
    cancelled = 5


class OrderPriority(IntEnum):
    """Order priority codes matching order_priorities lookup table.

    Values correspond to auto-increment IDs in the order_priorities table.
    """
    low = 1
    normal = 2
    high = 3
    urgent = 4
