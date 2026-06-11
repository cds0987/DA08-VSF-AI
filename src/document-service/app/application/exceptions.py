class ApplicationError(Exception):
    detail = "Application error"


class ValidationError(ApplicationError):
    detail = "Invalid document input"

    def __init__(self, detail: str | None = None) -> None:
        self.detail = detail or self.detail
        super().__init__(self.detail)


class InvalidTokenError(ApplicationError):
    detail = "Invalid or expired token"


class PermissionDeniedError(ApplicationError):
    detail = "Admin only"


class NotFoundError(ApplicationError):
    detail = "Document not found"


class StorageError(ApplicationError):
    detail = "Storage operation failed"

    def __init__(self, detail: str | None = None) -> None:
        self.detail = detail or self.detail
        super().__init__(self.detail)


class MessagingPublishError(ApplicationError):
    detail = "Document event publish failed"

