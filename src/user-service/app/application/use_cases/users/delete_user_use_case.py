from dataclasses import dataclass
from typing import Protocol

from app.application.exceptions import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
)
from app.domain.entities.user import User
from app.domain.repositories.user_repository import UserRepository


@dataclass(frozen=True)
class DeleteUserResult:
    id: str


class AuditLogger(Protocol):
    async def log(
        self,
        action: str,
        actor_id: str,
        actor_role: str,
        resource_type: str | None = None,
        resource_id: str | None = None,
        detail: dict | None = None,
        ip_address: str | None = None,
    ) -> None:
        ...


class UserEventEmitter(Protocol):
    async def emit(self, subject: str, user: User) -> None:
        ...


class DeleteUserUseCase:
    def __init__(
        self,
        user_repository: UserRepository,
        audit_logger: AuditLogger,
        event_emitter: UserEventEmitter | None = None,
    ) -> None:
        self.user_repository = user_repository
        self.audit_logger = audit_logger
        self.event_emitter = event_emitter

    async def execute(
        self,
        actor: User,
        user_id: str,
        ip_address: str | None = None,
    ) -> DeleteUserResult:
        if _role_value(actor.role) != "admin":
            raise PermissionDeniedError()
        if str(actor.id) == str(user_id):
            raise ConflictError("Cannot delete your own account")

        # Lấy entity trước khi xoá để dựng payload event user.deleted.
        user = await self.user_repository.get_by_id(user_id)
        if user is None:
            raise NotFoundError()

        deleted = await self.user_repository.delete(user_id)
        if not deleted:
            raise NotFoundError()

        await self.audit_logger.log(
            action="delete",
            actor_id=actor.id,
            actor_role=_role_value(actor.role),
            resource_type="user",
            resource_id=user_id,
            detail={"email": user.email},
            ip_address=ip_address,
        )
        # Chỉ emit sau khi xoá DB thành công. HR Service consume user.deleted để
        # dọn hồ sơ employee theo user_id (idempotent).
        if self.event_emitter is not None:
            await self.event_emitter.emit("user.deleted", user)
        return DeleteUserResult(id=user_id)


def _role_value(role: object) -> str:
    value = getattr(role, "value", None)
    return str(value if value is not None else role)
