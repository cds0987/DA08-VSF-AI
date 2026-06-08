from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.auth.login_use_case import LoginSecurityState
from app.domain.entities.user import User
from app.domain.repositories.user_repository import UserRepository
from app.infrastructure.db.models import UserModel


class PostgresUserRepository(UserRepository):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_email(self, email: str) -> User | None:
        result = await self.session.execute(
            select(UserModel).where(UserModel.email == email.lower()),
        )
        return _to_entity(result.scalar_one_or_none())

    async def get_by_id(self, user_id: str) -> User | None:
        result = await self.session.execute(
            select(UserModel).where(UserModel.id == _uuid(user_id)),
        )
        return _to_entity(result.scalar_one_or_none())

    async def create(self, user: User) -> User:
        model = UserModel(
            id=_uuid(user.id),
            email=user.email.lower(),
            hashed_password=user.hashed_password,
            auth_provider=user.auth_provider,
            role=_role_value(user.role),
            account_type=user.account_type,
            is_active=user.is_active,
            department=user.department,
        )
        self.session.add(model)
        await self.session.commit()
        await self.session.refresh(model)
        created = _to_entity(model)
        if created is None:
            raise RuntimeError("failed to create user")
        return created

    async def list_all(
        self,
        is_active: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[User], int]:
        filters = []
        if is_active is not None:
            filters.append(UserModel.is_active == is_active)

        total_result = await self.session.execute(
            select(func.count()).select_from(UserModel).where(*filters),
        )
        result = await self.session.execute(
            select(UserModel)
            .where(*filters)
            .order_by(UserModel.email)
            .limit(limit)
            .offset(offset),
        )
        return [_to_entity_required(row) for row in result.scalars().all()], int(
            total_result.scalar_one(),
        )

    async def set_active(self, user_id: str, is_active: bool) -> User | None:
        result = await self.session.execute(
            select(UserModel).where(UserModel.id == _uuid(user_id)),
        )
        model = result.scalar_one_or_none()
        if model is None:
            return None
        model.is_active = is_active
        await self.session.commit()
        await self.session.refresh(model)
        return _to_entity(model)


class PostgresLoginStateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_login_state(self, user_id: str) -> LoginSecurityState:
        result = await self.session.execute(
            select(UserModel.failed_login_count, UserModel.locked_until).where(
                UserModel.id == _uuid(user_id),
            ),
        )
        row = result.one_or_none()
        if row is None:
            return LoginSecurityState(failed_login_count=0, locked_until=None)
        return LoginSecurityState(
            failed_login_count=row.failed_login_count,
            locked_until=row.locked_until,
        )

    async def register_login_failure(
        self,
        user_id: str,
        failed_login_count: int,
        locked_until: datetime | None,
    ) -> None:
        result = await self.session.execute(
            select(UserModel).where(UserModel.id == _uuid(user_id)),
        )
        model = result.scalar_one_or_none()
        if model is None:
            return
        model.failed_login_count = failed_login_count
        model.locked_until = locked_until
        await self.session.commit()

    async def reset_login_failures(self, user_id: str) -> None:
        result = await self.session.execute(
            select(UserModel).where(UserModel.id == _uuid(user_id)),
        )
        model = result.scalar_one_or_none()
        if model is None:
            return
        model.failed_login_count = 0
        model.locked_until = None
        await self.session.commit()


def _to_entity(model: UserModel | None) -> User | None:
    if model is None:
        return None
    return User(
        id=str(model.id),
        email=model.email,
        role=model.role,
        is_active=model.is_active,
        account_type=model.account_type,
        department=model.department,
        hashed_password=model.hashed_password,
        auth_provider=model.auth_provider,
    )


def _to_entity_required(model: UserModel) -> User:
    entity = _to_entity(model)
    if entity is None:
        raise RuntimeError("expected user row")
    return entity


def _uuid(value: str) -> UUID:
    return UUID(str(value))


def _role_value(role: object) -> str:
    value = getattr(role, "value", None)
    return str(value if value is not None else role)

