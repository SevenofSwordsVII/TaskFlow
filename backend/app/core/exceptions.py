"""Standardized API exception classes and handlers."""

from typing import Any

try:
    from fastapi import FastAPI, Request, status
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse
    from starlette.exceptions import HTTPException as StarletteHTTPException
except ImportError:

    class status:  # type: ignore[no-redef]
        HTTP_400_BAD_REQUEST = 400
        HTTP_401_UNAUTHORIZED = 401
        HTTP_403_FORBIDDEN = 403
        HTTP_404_NOT_FOUND = 404
        HTTP_409_CONFLICT = 409
        HTTP_422_UNPROCESSABLE_ENTITY = 422
        HTTP_429_TOO_MANY_REQUESTS = 429
        HTTP_500_INTERNAL_SERVER_ERROR = 500

    FastAPI = Any  # type: ignore[assignment, misc]
    Request = Any  # type: ignore[assignment, misc]
    RequestValidationError = Exception  # type: ignore[assignment, misc]
    JSONResponse = Any  # type: ignore[assignment, misc]
    StarletteHTTPException = Exception  # type: ignore[assignment, misc]


class AppException(Exception):
    """Base application exception with standardized code and status."""

    def __init__(
        self,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        code: str = "INTERNAL_SERVER_ERROR",
        message: str = "An unexpected error occurred.",
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


class BadRequestException(AppException):
    def __init__(
        self,
        code: str = "BAD_REQUEST",
        message: str = "Bad request.",
        details: Any = None,
    ) -> None:
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            code=code,
            message=message,
            details=details,
        )


class UnauthorizedException(AppException):
    def __init__(
        self,
        code: str = "UNAUTHORIZED",
        message: str = "Authentication credentials were not provided or are invalid.",
        details: Any = None,
    ) -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code=code,
            message=message,
            details=details,
        )


class ForbiddenException(AppException):
    def __init__(
        self,
        code: str = "FORBIDDEN",
        message: str = "You do not have permission to perform this action.",
        details: Any = None,
    ) -> None:
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            code=code,
            message=message,
            details=details,
        )


class NotFoundException(AppException):
    def __init__(
        self,
        code: str = "NOT_FOUND",
        message: str = "The requested resource was not found.",
        details: Any = None,
    ) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            code=code,
            message=message,
            details=details,
        )


class ConflictException(AppException):
    def __init__(
        self,
        code: str = "CONFLICT",
        message: str = "Resource state conflict.",
        details: Any = None,
    ) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            code=code,
            message=message,
            details=details,
        )


class UnprocessableEntityException(AppException):
    def __init__(
        self,
        code: str = "UNPROCESSABLE_ENTITY",
        message: str = "The request data could not be processed.",
        details: Any = None,
    ) -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code=code,
            message=message,
            details=details,
        )


class RateLimitException(AppException):
    def __init__(
        self,
        code: str = "RATE_LIMIT_EXCEEDED",
        message: str = "Too many requests. Please try again later.",
        details: Any = None,
    ) -> None:
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            code=code,
            message=message,
            details=details,
        )


class InternalServerErrorException(AppException):
    def __init__(
        self,
        code: str = "INTERNAL_SERVER_ERROR",
        message: str = "An unexpected internal server error occurred.",
        details: Any = None,
    ) -> None:
        super().__init__(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code=code,
            message=message,
            details=details,
        )


def register_exception_handlers(app: FastAPI) -> None:
    """Register custom exception handlers on FastAPI application."""

    @app.exception_handler(AppException)
    async def app_exception_handler(_: Request, exc: AppException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                }
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Input validation failed.",
                    "details": exc.errors(),
                }
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code_mapping = {
            400: "BAD_REQUEST",
            401: "UNAUTHORIZED",
            403: "FORBIDDEN",
            404: "NOT_FOUND",
            405: "METHOD_NOT_ALLOWED",
            409: "CONFLICT",
            422: "UNPROCESSABLE_ENTITY",
            429: "RATE_LIMIT_EXCEEDED",
            500: "INTERNAL_SERVER_ERROR",
        }
        code = code_mapping.get(exc.status_code, "HTTP_ERROR")
        detail = exc.detail if isinstance(exc.detail, str) else "HTTP error"
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": code,
                    "message": detail,
                    "details": None,
                }
            },
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": {
                    "code": "INTERNAL_SERVER_ERROR",
                    "message": "An unexpected server error occurred.",
                    "details": str(exc) if False else None,
                }
            },
        )
