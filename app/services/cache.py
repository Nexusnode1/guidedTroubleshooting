"""Cache abstraction interface."""

from typing import Any


class PlanCache:
    """Placeholder cache interface for validated troubleshooting plans."""

    def get(self, key: str) -> dict[str, Any] | None:
        """Retrieve a previously validated plan by key."""
        # TODO: Add an in-memory implementation with validation guards.
        raise NotImplementedError("Cache lookup is not implemented.")

    def set(self, key: str, plan: dict[str, Any]) -> None:
        """Store a validated plan by key."""
        # TODO: Validate before caching.
        raise NotImplementedError("Cache storage is not implemented.")
