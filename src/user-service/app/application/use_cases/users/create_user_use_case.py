from __future__ import annotations

from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from app.application.exceptions import ConflictError, PermissionDeniedError
from app.domain.entities.user import User
from app.domain.repositories.user_repository import UserRepository
from app.infrastructure.security.password_hasher import BcryptPasswordHasher


class CreateUserUseCase:
    def __init__(
        self,
        user_repository: UserRepository,
        password_hasher: BcryptPasswordHasher,
        event_emitter: "NatsUserEventEmitter | None" = None,
    ) -> None:
        self.user_repository = user_repository
        self.password_hasher = password_hasher
        self.event_emitter = event_emitter

    async def execute(
        self,
        actor: User,
        email: str,
        password: str,
        role: str,
        account_type: str,
        department: str,
    ) -> User:
        # 1. Check if actor is admin
        if _role_value(actor.role) != "admin":
            raise PermissionDeniedError()

        # 2. Normalize email
        normalized_email = email.strip().lower()

        # 3. Hash password
        hashed_password = self.password_hasher.hash(password)

        # 4. Create User entity (department không lưu vào User — chỉ đưa vào NATS event)
        new_user = User(
            id=str(uuid4()),
            email=normalized_email,
            role=role,
            account_type=account_type,  # type: ignore
            hashed_password=hashed_password,
            is_active=True,
            auth_provider="local",
        )

        # 5. Save to repository with race condition protection
        try:
            created_user = await self.user_repository.create(new_user)
        except IntegrityError as exc:
            if "email" in str(exc).lower() or "unique constraint" in str(exc).lower():
                raise ConflictError(f"User with email {normalized_email} already exists") from exc
            raise exc

        # 6. Emit event — pass department separately so HR Service can set it on the employee record
        if self.event_emitter:
            await self.event_emitter.emit("user.created", created_user, department=department)

        return created_user


def _role_value(role: object) -> str:
    value = getattr(role, "value", None)
    return str(value if value is not None else role)
