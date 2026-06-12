from dataclasses import dataclass
from typing import Protocol

from app.application.exceptions import NotFoundError, PermissionDeniedError
from app.domain.entities.user import User
from app.domain.repositories.user_repository import UserRepository


@dataclass(frozen=True)
class SetUserActiveResult:
    id: str
    is_active: bool


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


class SetUserActiveUseCase:
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
        is_active: bool,
        ip_address: str | None = None,
    ) -> SetUserActiveResult:
        if _role_value(actor.role) != "admin":
            raise PermissionDeniedError()

        user = await self.user_repository.set_active(user_id, is_active)
        if user is None:
            raise NotFoundError()

        await self.audit_logger.log(
            action="reactivate" if is_active else "deactivate",
            actor_id=actor.id,
            actor_role=_role_value(actor.role),
            resource_type="user",
            resource_id=user_id,
            detail={"is_active": is_active},
            ip_address=ip_address,
        )
        if self.event_emitter is not None:
            subject = "user.updated" if is_active else "user.deactivated"
            await self.event_emitter.emit(subject, user)
        return SetUserActiveResult(id=user.id, is_active=user.is_active)


def _role_value(role: object) -> str:
    value = getattr(role, "value", None)
    return str(value if value is not None else role)
