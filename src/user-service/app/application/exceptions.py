class ApplicationError(Exception):
    detail = "Application error"


class AuthenticationError(ApplicationError):
    detail = "Invalid credentials"


class InactiveUserError(ApplicationError):
    detail = "Inactive user"


class AccountLockedError(ApplicationError):
    detail = "Account locked. Try again later."


class InvalidTokenError(ApplicationError):
    detail = "Invalid or expired token"


class PermissionDeniedError(ApplicationError):
    detail = "Admin only"


class NotFoundError(ApplicationError):
    detail = "Not found"


class ConflictError(ApplicationError):
    detail = "Conflict"

