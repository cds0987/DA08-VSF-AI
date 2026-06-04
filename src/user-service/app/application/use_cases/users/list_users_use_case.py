from dataclasses import dataclass

from app.application.exceptions import PermissionDeniedError
from app.domain.entities.user import User
from app.domain.repositories.user_repository import UserRepository


@dataclass(frozen=True)
class UserListResult:
    items: list[User]
    total: int


class ListUsersUseCase:
    def __init__(self, user_repository: UserRepository) -> None:
        self.user_repository = user_repository

    async def execute(
        self,
        actor: User,
        is_active: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> UserListResult:
        if _role_value(actor.role) != "admin":
            raise PermissionDeniedError()
        users, total = await self.user_repository.list_all(
            is_active=is_active,
            limit=limit,
            offset=offset,
        )
        return UserListResult(items=users, total=total)


def _role_value(role: object) -> str:
    value = getattr(role, "value", None)
    return str(value if value is not None else role)
