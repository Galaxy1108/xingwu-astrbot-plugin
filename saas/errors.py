"""Unified application errors.

Every error surfaced to the console API must be an :class:`AppError` so the
HTTP layer can serialise it into the envelope documented in ``docs/API.md``.
"""

from __future__ import annotations


class AppError(Exception):
    """Base class for expected, user-facing errors."""

    code = "internal_error"
    status = 500

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status: int | None = None,
        field: str | None = None,
        extra: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if status is not None:
            self.status = status
        self.field = field
        self.extra = extra or {}

    def to_dict(self) -> dict:
        payload = {"code": self.code, "message": self.message, "field": self.field}
        payload.update(self.extra)
        return payload


class ValidationError(AppError):
    code = "validation_error"
    status = 400


class Unauthorized(AppError):
    code = "unauthorized"
    status = 401


class CsrfError(AppError):
    code = "csrf_invalid"
    status = 403


class Forbidden(AppError):
    code = "forbidden"
    status = 403


class NotFound(AppError):
    code = "not_found"
    status = 404


class Conflict(AppError):
    code = "conflict"
    status = 409


class RateLimited(AppError):
    code = "otp_rate_limited"
    status = 429

    def __init__(self, message: str, *, retry_after: int = 60, **kwargs) -> None:
        super().__init__(message, **kwargs)
        self.retry_after = retry_after
        self.extra = {"retry_after": retry_after}


class InternalError(AppError):
    code = "internal_error"
    status = 500
