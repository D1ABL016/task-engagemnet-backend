from fastapi import HTTPException, status


class DomainError(HTTPException):
    """Base for errors that map onto a specific HTTP status."""


class NotFoundError(DomainError):
    def __init__(self, detail: str = "Resource not found") -> None:
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


class PermissionDeniedError(DomainError):
    def __init__(self, detail: str = "Not permitted") -> None:
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


class ConflictError(DomainError):
    """Well-formed request that conflicts with the resource's current state."""

    def __init__(self, detail: str = "Conflicts with current state") -> None:
        super().__init__(status_code=status.HTTP_409_CONFLICT, detail=detail)


class AuthenticationError(DomainError):
    def __init__(self, detail: str = "Could not validate credentials") -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )
