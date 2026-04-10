"""Shared Synapse error taxonomy for HTTP and MCP adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class SynapseError(Exception):
    """Base typed error for transport-friendly reporting."""

    message: str
    error_type: str = "synapse_error"
    status_code: int = 500
    retryable: bool = False
    dependency: str | None = None
    timeout_seconds: float | None = None

    def __str__(self) -> str:
        return self.message

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "error_type": self.error_type,
            "message": self.message,
            "retryable": self.retryable,
        }
        if self.dependency is not None:
            payload["dependency"] = self.dependency
        if self.timeout_seconds is not None:
            payload["timeout_seconds"] = self.timeout_seconds
        return payload


class SynapseBadRequestError(SynapseError):
    def __init__(self, message: str):
        super().__init__(
            message=message,
            error_type="bad_request",
            status_code=400,
            retryable=False,
        )


class SynapseNotFoundError(SynapseError):
    def __init__(self, message: str):
        super().__init__(
            message=message,
            error_type="not_found",
            status_code=404,
            retryable=False,
        )


class SynapseDependencyError(SynapseError):
    def __init__(
        self,
        message: str,
        *,
        dependency: str,
        retryable: bool = True,
        status_code: int = 424,
        error_type: str = "dependency_unavailable",
    ):
        super().__init__(
            message=message,
            error_type=error_type,
            status_code=status_code,
            retryable=retryable,
            dependency=dependency,
        )


class SynapseTimeoutError(SynapseError):
    def __init__(self, message: str, *, timeout_seconds: float, dependency: str = "reasoning_model"):
        super().__init__(
            message=message,
            error_type="timeout",
            status_code=504,
            retryable=True,
            dependency=dependency,
            timeout_seconds=timeout_seconds,
        )


class SynapseConflictError(SynapseError):
    def __init__(self, message: str):
        super().__init__(
            message=message,
            error_type="conflict",
            status_code=409,
            retryable=False,
        )


class SynapseUnavailableError(SynapseError):
    def __init__(self, message: str, *, dependency: str | None = None):
        super().__init__(
            message=message,
            error_type="service_unavailable",
            status_code=503,
            retryable=True,
            dependency=dependency,
        )
