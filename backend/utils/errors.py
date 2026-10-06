from typing import Any, Dict, Optional
from flask import jsonify, Response


class AppException(Exception):
    """Base application exception for TRINETRA."""
    def __init__(self, message: str, status_code: int = 500, error_code: str = "INTERNAL_SERVER_ERROR", details: Optional[Any] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        self.details = details or {}


class ValidationError(AppException):
    """Raised when incoming user input fails validation constraints."""
    def __init__(self, message: str, details: Optional[Any] = None):
        super().__init__(message, status_code=400, error_code="VALIDATION_ERROR", details=details)


class NotFoundError(AppException):
    """Raised when a requested resource does not exist."""
    def __init__(self, message: str, details: Optional[Any] = None):
        super().__init__(message, status_code=404, error_code="RESOURCE_NOT_FOUND", details=details)


class ConflictError(AppException):
    """Raised when an operation conflicts with existing system state (e.g. duplicate SKU)."""
    def __init__(self, message: str, details: Optional[Any] = None):
        super().__init__(message, status_code=409, error_code="CONFLICT_ERROR", details=details)


class InsufficientDataError(AppException):
    """
    Raised when an ML, forecasting, or risk operation lacks adequate historical observations.
    Never generate fake predictions on sparse data (Spec Section 15 & 42).
    """
    def __init__(self, message: str, observations: int, required_minimum: int, fallback_method: str = "baseline"):
        details = {
            "available_observations": observations,
            "required_minimum": required_minimum,
            "fallback_method": fallback_method
        }
        super().__init__(message, status_code=422, error_code="INSUFFICIENT_DATA", details=details)


class UnauthorizedError(AppException):
    """Raised when authentication credentials are missing or invalid."""
    def __init__(self, message: str = "Authentication required"):
        super().__init__(message, status_code=401, error_code="UNAUTHORIZED")


class ForbiddenError(AppException):
    """Raised when authenticated user lacks permissions for an operation."""
    def __init__(self, message: str = "Access forbidden"):
        super().__init__(message, status_code=403, error_code="FORBIDDEN")


def format_response(
    data: Optional[Any] = None,
    message: Optional[str] = None,
    error: Optional[Dict[str, Any]] = None,
    status_code: int = 200,
    meta: Optional[Dict[str, Any]] = None
) -> tuple[Response, int]:
    """
    Standardized REST API response envelope for TRINETRA.
    Guarantees consistent format across all endpoints:
    {
        "success": bool,
        "message": Optional[str],
        "data": Optional[Any],
        "error": Optional[Dict],
        "meta": Optional[Dict]
    }
    """
    payload = {
        "success": status_code < 400,
        "message": message,
        "data": data,
        "error": error,
        "meta": meta or {}
    }
    return jsonify(payload), status_code
